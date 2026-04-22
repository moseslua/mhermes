"""HMAOM Specialist Harness Base.

Domain-isolated execution environment with:
- Deep skill registry (lazy-loaded by area)
- Tool sandbox (domain-relevant tools only)
- Memory space (SQLite per domain)
- Controlled recursive spawning
- Synthesis capability
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from hmaom.prompts.registry import PromptRegistry
from hmaom.config import SpecialistConfig
from hmaom.fault_tolerance.recovery import RecoveryOrchestrator
from hmaom.observability.health import CircuitBreakerRegistry, HealthMonitor
from hmaom.observability.tracing import Tracer
from hmaom.protocol.message_bus import MessageBus
from hmaom.protocol.schemas import (
    AgentAddress,
    AgentMessage,
    AgentResult,
    ContextSlice,
    Domain,
    HealthStatus,
    MessageType,
    RoutingDecision,
    SpawnRequest,
    SpawnResult,
    TaskDescription,
)
from hmaom.protocol.spawn import SpawnProtocol
from hmaom.state.checkpoints import CheckpointManager
from hmaom.state.memory import MemoryManager
from hmaom.state.store import StateStore


class SpecialistHarness(ABC):
    """Base class for all specialist harnesses.

    Each specialist is a standalone execution environment with its own
    skills, tools, memory, and sandbox.
    """

    def __init__(
        self,
        config: SpecialistConfig,
        message_bus: Optional[MessageBus] = None,
        tracer: Optional[Tracer] = None,
        health_monitor: Optional[HealthMonitor] = None,
        circuit_breakers: Optional[CircuitBreakerRegistry] = None,
        prompt_registry: Optional[PromptRegistry] = None,
    ) -> None:
        self.config = config
        self.domain = Domain(config.domain)
        self.message_bus = message_bus
        self.tracer = tracer
        self.health_monitor = health_monitor
        self.circuit_breakers = circuit_breakers
        self.prompt_registry = prompt_registry
        self.config = config
        self.domain = Domain(config.domain)
        self.message_bus = message_bus
        self.tracer = tracer
        self.health_monitor = health_monitor
        self.circuit_breakers = circuit_breakers

        # Isolated subsystems
        self.state_store = StateStore()
        self.checkpoint_manager = CheckpointManager()
        self.memory_manager = MemoryManager()
        self.spawn_protocol = SpawnProtocol()
        self.recovery = RecoveryOrchestrator()

        # Runtime state
        self._active_spawns: dict[str, asyncio.Task] = {}
        self._skills_loaded: dict[str, bool] = {}
        self._tools: list[str] = []
        self._subagent_registry: dict[str, Callable] = {}

        self._setup_subagents()

    @property
    @abstractmethod
    def default_tools(self) -> list[str]:
        """Return the default tool whitelist for this specialist."""
        ...

    @property
    def system_prompt(self) -> str:
        """Return the specialist-specific system prompt.
        Queries the prompt registry when available, otherwise falls back
        to the default system prompt defined by the subclass.
        """
        if self.prompt_registry is not None:
            active = self.prompt_registry.get_active("system", self.domain.value)
            if active is not None:
                return active
        return self._default_system_prompt

    @property
    @abstractmethod
    def _default_system_prompt(self) -> str:
        """Return the fallback system prompt for this specialist."""

    def _setup_subagents(self) -> None:
        """Register default subagent types for this specialist."""
        self._subagent_registry["explore"] = self._subagent_explore
        self._subagent_registry["calculate"] = self._subagent_calculate
        self._subagent_registry["verify"] = self._subagent_verify

    def _agent_address(self, agent_name: str, depth: int = 0) -> AgentAddress:
        return AgentAddress(
            harness=self.config.name,
            agent=agent_name,
            depth=depth,
        )

    # ── Skill Management ──

    def load_skills(self, area: str) -> list[dict[str, Any]]:
        """Lazy-load skills for a specific area.

        In production, this would scan ~/.hmaom/skills/{domain}/{area}/.
        """
        if area in self._skills_loaded:
            return []
        self._skills_loaded[area] = True
        # Placeholder: return empty list; actual skill loading would
        # read SKILL.md files from the filesystem
        return []

    # ── Core Execution ──

    async def execute(
        self,
        request: SpawnRequest,
        model_override_dynamic: Optional[str] = None,
    ) -> SpawnResult:
        """Execute a task within this specialist domain.

        This is the main entry point for specialist execution.
        """
        # Apply dynamic model override if provided
        if model_override_dynamic is not None:
            request = request.model_copy(update={"model_override": model_override_dynamic})

        spawn_id = request.spawn_id
        correlation_id = request.correlation_id
        start_time = time.time()

        # Start trace span
        span = None
        if self.tracer is not None:
            span = self.tracer.start_span(
                correlation_id=correlation_id,
                agent_address=self._agent_address("specialist", request.depth),
                operation=f"execute-{self.config.name}",
            )

        try:
            # Load relevant skills
            for area in self.config.lazy_load_areas:
                if any(term in request.task.description.lower() for term in area.lower().split("-")):
                    self.load_skills(area)

            # Execute the domain-specific handler
            result_data = await self._handle_task(request)

            elapsed_ms = int((time.time() - start_time) * 1000)

            # Record success
            if self.circuit_breakers is not None:
                self.circuit_breakers.record_success(self.config.name)
            if self.health_monitor is not None:
                self.health_monitor.update_status(
                    HealthStatus(
                        agent_address=self._agent_address("specialist"),
                        timestamp=time.time(),
                        status="healthy",
                        active_spawns=len(self._active_spawns),
                        queue_depth=0,
                    )
                )

            if span is not None:
                self.tracer.finish_span(span, status="ok", metadata={"result_type": type(result_data).__name__})

            return SpawnResult(
                spawn_id=spawn_id,
                status="success",
                result=result_data,
                time_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = int((time.time() - start_time) * 1000)

            # Record failure
            if self.circuit_breakers is not None:
                self.circuit_breakers.record_failure(self.config.name)
            if self.health_monitor is not None:
                self.health_monitor.update_status(
                    HealthStatus(
                        agent_address=self._agent_address("specialist"),
                        timestamp=time.time(),
                        status="degraded",
                        active_spawns=len(self._active_spawns),
                        queue_depth=0,
                        last_error=str(exc),
                    )
                )

            if span is not None:
                self.tracer.finish_span(
                    span, status="error", metadata={"error": str(exc)}
                )

            return SpawnResult(
                spawn_id=spawn_id,
                status="failure",
                error=str(exc),
                time_ms=elapsed_ms,
            )

    @abstractmethod
    async def _handle_task(self, request: SpawnRequest) -> Any:
        """Domain-specific task handler. Must be implemented by subclasses."""
        ...

    # ── Subagent Spawning ──

    async def spawn_subagent(
        self,
        parent_request: SpawnRequest,
        subagent_type: str,
        task: TaskDescription,
        context_slice: ContextSlice,
    ) -> SpawnResult:
        """Spawn a subagent within this specialist."""
        # Check spawn permission
        can_spawn, reason = self.spawn_protocol.can_spawn(
            parent_address=self._agent_address(subagent_type, parent_request.depth + 1),
            requested_depth=parent_request.depth + 1,
            correlation_id=parent_request.correlation_id,
        )
        if not can_spawn:
            return SpawnResult(
                spawn_id=f"rejected-{uuid.uuid4().hex[:8]}",
                status="killed",
                error=reason,
            )

        # Create child request
        child_request = self.spawn_protocol.create_child_request(
            parent_request=parent_request,
            task=task,
            context_slice=context_slice,
        )

        # Find handler
        handler = self._subagent_registry.get(subagent_type)
        if handler is None:
            return SpawnResult(
                spawn_id=child_request.spawn_id,
                status="failure",
                error=f"Unknown subagent type: {subagent_type}",
            )

        # Execute via spawn protocol
        result = await self.spawn_protocol.execute_spawn(
            request=child_request,
            handler=handler,
            message_bus=self.message_bus,
        )

        # Consume budget
        self.spawn_protocol.consume_budget(
            correlation_id=parent_request.correlation_id,
            tokens=result.tokens_used,
        )

        return result

    # ── Default Subagent Handlers ──

    async def _subagent_explore(self, request: SpawnRequest) -> Any:
        """Explore subagent: gathers information and maps the problem space."""
        return {
            "agent": "explore",
            "task": request.task.title,
            "findings": f"Explored {self.config.name} domain for: {request.task.description}",
        }

    async def _subagent_calculate(self, request: SpawnRequest) -> Any:
        """Calculate subagent: performs computations and analysis."""
        return {
            "agent": "calculate",
            "task": request.task.title,
            "result": f"Calculated in {self.config.name} domain",
        }

    async def _subagent_verify(self, request: SpawnRequest) -> Any:
        """Verify subagent: validates results and checks for errors."""
        return {
            "agent": "verify",
            "task": request.task.title,
            "verification": "Passed basic checks",
        }

    # ── Synthesis Support ──

    def to_agent_result(self, spawn_result: SpawnResult) -> AgentResult:
        """Convert a SpawnResult to an AgentResult for synthesis."""
        return AgentResult(
            source=self._agent_address(self.config.name),
            result=spawn_result.result,
            confidence=1.0 if spawn_result.status == "success" else 0.0,
            tokens_used=spawn_result.tokens_used,
            time_ms=spawn_result.time_ms,
        )

    # ── Lifecycle ──

    async def start(self) -> None:
        """Start the specialist harness."""
        if self.message_bus is not None:
            self._bus_unsubscribe = self.message_bus.subscribe(
                f"agent:{self.config.name}/*",
                self._on_message,
            )

    async def stop(self) -> None:
        """Stop the specialist harness."""
        if self.message_bus is not None and hasattr(self, "_bus_unsubscribe"):
            self._bus_unsubscribe()
        for task in self._active_spawns.values():
            task.cancel()
        self.state_store.close()
        self.checkpoint_manager = None  # type: ignore[assignment]
        self.memory_manager.close()

    async def _on_message(self, message: AgentMessage) -> None:
        """Handle incoming messages on the bus."""
        if message.type == MessageType.TASK_REQUEST:
            # Spawn request received via bus
            payload = message.payload or {}
            if "spawn_request" in payload:
                request = SpawnRequest(**payload["spawn_request"])
                task = asyncio.create_task(self.execute(request))
                self._active_spawns[request.spawn_id] = task
                task.add_done_callback(lambda t: self._active_spawns.pop(request.spawn_id, None))

    def health(self) -> dict[str, Any]:
        """Return current health information."""
        return {
            "harness": self.config.name,
            "domain": self.config.domain,
            "active_spawns": len(self._active_spawns),
            "skills_loaded": list(self._skills_loaded.keys()),
            "model_override": self.config.model_override,
        }
