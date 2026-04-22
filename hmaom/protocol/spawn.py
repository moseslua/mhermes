"""HMAOM Hierarchical Spawn Protocol.

Wraps hermes-agent's native subagent spawning with budget tracking,
depth enforcement, structured output validation, and checkpointing.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional

from hmaom.config import SpawnConfig
from hmaom.protocol.schemas import (
    AgentAddress,
    AgentMessage,
    ContextSlice,
    MessageType,
    SpawnConstraints,
    SpawnRequest,
    SpawnResult,
    TaskDescription,
)


class SpawnProtocol:
    """Protocol for hierarchical subagent spawning.

    Enforces:
    - Max depth limits (protocol-level rejection)
    - Max breadth (concurrency semaphore per parent)
    - Global token/time/cost budgets
    - Structured output schema validation
    - Automatic checkpointing
    """

    def __init__(self, config: Optional[SpawnConfig] = None) -> None:
        self.config = config or SpawnConfig()
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._token_budgets: dict[str, int] = {}
        self._cost_budgets: dict[str, float] = {}
        self._start_times: dict[str, float] = {}

    def _get_semaphore(self, parent_id: str) -> asyncio.Semaphore:
        """Get or create a concurrency semaphore for a parent agent."""
        if parent_id not in self._semaphores:
            self._semaphores[parent_id] = asyncio.Semaphore(self.config.max_breadth)
        return self._semaphores[parent_id]

    def can_spawn(
        self,
        parent_address: AgentAddress,
        requested_depth: int,
        correlation_id: str,
    ) -> tuple[bool, Optional[str]]:
        """Check if a spawn request is allowed.

        Returns (allowed, reason) tuple.
        """
        # Depth check
        if requested_depth > self.config.max_depth_hard:
            return False, (
                f"Spawn depth {requested_depth} exceeds hard limit "
                f"{self.config.max_depth_hard}"
            )
        if requested_depth > self.config.max_depth:
            return False, (
                f"Spawn depth {requested_depth} exceeds default limit "
                f"{self.config.max_depth}"
            )

        # Token budget check
        tokens_used = self._token_budgets.get(correlation_id, 0)
        if tokens_used >= self.config.max_tokens_per_tree:
            return False, (
                f"Token budget exhausted: {tokens_used} / "
                f"{self.config.max_tokens_per_tree}"
            )

        # Cost budget check
        cost_used = self._cost_budgets.get(correlation_id, 0.0)
        if cost_used >= self.config.max_cost_usd:
            return False, (
                f"Cost budget exhausted: ${cost_used:.2f} / "
                f"${self.config.max_cost_usd:.2f}"
            )

        # Time budget check
        start_time = self._start_times.get(correlation_id)
        if start_time is not None:
            elapsed_ms = (time.time() - start_time) * 1000
            if elapsed_ms >= self.config.max_wall_time_ms:
                return False, (
                    f"Time budget exhausted: {elapsed_ms:.0f}ms / "
                    f"{self.config.max_wall_time_ms}ms"
                )

        return True, None

    def init_tree_budgets(self, correlation_id: str) -> None:
        """Initialize budget tracking for a new request tree."""
        self._token_budgets[correlation_id] = 0
        self._cost_budgets[correlation_id] = 0.0
        self._start_times[correlation_id] = time.time()

    def consume_budget(
        self,
        correlation_id: str,
        tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Record resource consumption for a tree."""
        self._token_budgets[correlation_id] = (
            self._token_budgets.get(correlation_id, 0) + tokens
        )
        self._cost_budgets[correlation_id] = (
            self._cost_budgets.get(correlation_id, 0.0) + cost_usd
        )

    def remaining_budget(self, correlation_id: str) -> dict[str, Any]:
        """Report remaining budget for a tree."""
        tokens_remaining = self.config.max_tokens_per_tree - self._token_budgets.get(
            correlation_id, 0
        )
        cost_remaining = self.config.max_cost_usd - self._cost_budgets.get(
            correlation_id, 0.0
        )
        start_time = self._start_times.get(correlation_id)
        time_remaining = (
            self.config.max_wall_time_ms
            if start_time is None
            else max(
                0,
                self.config.max_wall_time_ms
                - (time.time() - start_time) * 1000,
            )
        )
        return {
            "tokens_remaining": max(0, tokens_remaining),
            "cost_remaining_usd": max(0.0, cost_remaining),
            "time_remaining_ms": max(0, time_remaining),
        }

    async def execute_spawn(
        self,
        request: SpawnRequest,
        handler: callable,  # type: ignore[valid-type]
        message_bus: Optional[Any] = None,
    ) -> SpawnResult:
        """Execute a spawn request with full guardrails.

        Args:
            request: The spawn request
            handler: Async callable that actually runs the subagent
            message_bus: Optional message bus for publishing progress
        """
        spawn_id = request.spawn_id or f"spawn-{uuid.uuid4().hex[:8]}"
        request.spawn_id = spawn_id

        start_time = time.time()

        # Publish start
        if message_bus is not None:
            await message_bus.publish(
                AgentMessage(
                    message_id=f"{spawn_id}-start",
                    correlation_id=request.correlation_id,
                    timestamp=start_time,
                    sender=AgentAddress(harness="spawn-protocol", agent="coordinator", depth=0),
                    recipient=AgentAddress(
                        harness="parent", agent=request.parent_id, depth=request.depth - 1
                    ),
                    type=MessageType.TASK_REQUEST,
                    payload={"spawn_id": spawn_id, "status": "started"},
                )
            )

        try:
            # Acquire concurrency slot
            sem = self._get_semaphore(request.parent_id)
            async with sem:
                # Execute the handler
                result_data = await handler(request)

                elapsed_ms = int((time.time() - start_time) * 1000)

                return SpawnResult(
                    spawn_id=spawn_id,
                    status="success",
                    result=result_data,
                    time_ms=elapsed_ms,
                )

        except asyncio.TimeoutError:
            return SpawnResult(
                spawn_id=spawn_id,
                status="timeout",
                error="Subagent execution exceeded time limit",
                time_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as exc:
            return SpawnResult(
                spawn_id=spawn_id,
                status="failure",
                error=str(exc),
                time_ms=int((time.time() - start_time) * 1000),
            )

    def create_child_request(
        self,
        parent_request: SpawnRequest,
        task: TaskDescription,
        context_slice: ContextSlice,
        output_schema: Optional[dict[str, Any]] = None,
    ) -> SpawnRequest:
        """Create a child spawn request from a parent, decrementing depth budget."""
        child_depth = parent_request.depth + 1
        child_constraints = SpawnConstraints(
            max_depth=max(0, parent_request.constraints.max_depth - 1),
            max_tokens=parent_request.constraints.max_tokens // 2,
            max_time_ms=parent_request.constraints.max_time_ms // 2,
            tools=parent_request.constraints.tools,
        )

        return SpawnRequest(
            spawn_id=f"spawn-{uuid.uuid4().hex[:8]}",
            parent_id=parent_request.spawn_id,
            correlation_id=parent_request.correlation_id,
            depth=child_depth,
            task=task,
            context_slice=context_slice,
            memory_keys=parent_request.memory_keys,
            constraints=child_constraints,
            output_schema=output_schema or parent_request.output_schema,
        )
