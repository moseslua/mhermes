"""HMAOM Recovery Orchestrator.

Four-level escalation inspired by Hermes/CAMEL-AI:
    Level 1: RETRY   — Same agent, same task
    Level 2: REPLAN  — Meta-agent rewrites task description
    Level 3: DECOMPOSE — Break into smaller subtasks
    Level 4: ESCALATE — Notify user with partial results
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any, Callable, Optional

from hmaom.config import FaultToleranceConfig
from hmaom.protocol.schemas import (
    AgentAddress,
    AgentMessage,
    AgentResult,
    MessageType,
    SpawnRequest,
    SpawnResult,
    TaskDescription,
)


class EscalationLevel(Enum):
    """Escalation levels for fault recovery."""

    RETRY = 1
    REPLAN = 2
    DECOMPOSE = 3
    ESCALATE = 4


class RecoveryOrchestrator:
    """Orchestrates fault recovery across the agent mesh.

    For each failure, attempts escalating recovery strategies until
    the task succeeds or the user is notified.
    """

    def __init__(self, config: Optional[FaultToleranceConfig] = None) -> None:
        self.config = config or FaultToleranceConfig()
        self._attempt_counts: dict[str, int] = {}  # spawn_id -> attempts
        self._escalation_levels: dict[str, EscalationLevel] = {}

    def classify_failure(self, spawn_result: SpawnResult) -> str:
        """Classify the type of failure from a spawn result."""
        if spawn_result.status == "timeout":
            return "timeout"
        error = (spawn_result.error or "").lower()
        if "tool" in error or "execution" in error:
            return "tool_error"
        if "schema" in error or "validation" in error:
            return "hallucination"
        if "budget" in error or "exhausted" in error:
            return "budget_exhaustion"
        if "depth" in error or "breadth" in error:
            return "spawn_limit"
        return "unknown"

    def next_action(
        self,
        spawn_result: SpawnResult,
        current_request: SpawnRequest,
    ) -> tuple[EscalationLevel, dict[str, Any]]:
        """Determine the next recovery action for a failed spawn.

        Returns (level, params) where params are specific to the level.
        """
        spawn_id = spawn_result.spawn_id
        attempts = self._attempt_counts.get(spawn_id, 0) + 1
        self._attempt_counts[spawn_id] = attempts

        failure_type = self.classify_failure(spawn_result)
        current_level = self._escalation_levels.get(spawn_id, EscalationLevel.RETRY)

        # Level 1: Retry for transient failures
        if current_level <= EscalationLevel.RETRY and attempts <= self.config.retry_max_attempts:
            if failure_type in ("timeout", "tool_error", "unknown"):
                delay = self.config.retry_base_delay_seconds * (2 ** (attempts - 1))
                return EscalationLevel.RETRY, {
                    "delay_seconds": delay,
                    "attempt": attempts,
                    "reason": f"Transient {failure_type}, retrying",
                }

        # Level 2: Replan for persistent or schema failures
        if current_level <= EscalationLevel.REPLAN:
            self._escalation_levels[spawn_id] = EscalationLevel.REPLAN
            return EscalationLevel.REPLAN, {
                "original_task": current_request.task,
                "failure_reason": spawn_result.error,
                "failure_type": failure_type,
                "instruction": "Rewrite the task to avoid the failure. Be more specific.",
            }

        # Level 3: Decompose for complex failures
        if current_level <= EscalationLevel.DECOMPOSE:
            self._escalation_levels[spawn_id] = EscalationLevel.DECOMPOSE
            return EscalationLevel.DECOMPOSE, {
                "original_task": current_request.task,
                "failure_reason": spawn_result.error,
                "instruction": "Break into 2-3 smaller independent subtasks.",
            }

        # Level 4: Escalate to user
        self._escalation_levels[spawn_id] = EscalationLevel.ESCALATE
        return EscalationLevel.ESCALATE, {
            "attempted": attempts,
            "failure_type": failure_type,
            "last_error": spawn_result.error,
            "partial_result": spawn_result.result,
        }

    async def execute_recovery(
        self,
        spawn_result: SpawnResult,
        current_request: SpawnRequest,
        execute_fn: Callable[[SpawnRequest], Any],
        message_bus: Optional[Any] = None,
    ) -> SpawnResult:
        """Execute the appropriate recovery action.

        Args:
            spawn_result: The failed result
            current_request: The original request
            execute_fn: Function to execute a spawn request
            message_bus: Optional message bus for notifications
        """
        level, params = self.next_action(spawn_result, current_request)

        if level == EscalationLevel.RETRY:
            delay = params.get("delay_seconds", 1.0)
            await asyncio.sleep(delay)
            try:
                result_data = await execute_fn(current_request)
                return SpawnResult(
                    spawn_id=spawn_result.spawn_id,
                    status="success",
                    result=result_data,
                    time_ms=spawn_result.time_ms,
                )
            except Exception as exc:
                return SpawnResult(
                    spawn_id=spawn_result.spawn_id,
                    status="failure",
                    error=str(exc),
                    time_ms=spawn_result.time_ms,
                )

        if level == EscalationLevel.REPLAN:
            # Modify the task description with recovery guidance
            original = current_request.task
            replanned = TaskDescription(
                title=f"[REPLANNED] {original.title}",
                description=(
                    f"Original task failed with: {params['failure_reason']}\n\n"
                    f"Original: {original.description}\n\n"
                    f"Recovery instruction: {params['instruction']}"
                ),
                expected_output_schema=original.expected_output_schema,
                priority=original.priority,
                tags=original.tags + ["replanned"],
            )
            new_request = current_request.model_copy(update={"task": replanned})
            try:
                result_data = await execute_fn(new_request)
                return SpawnResult(
                    spawn_id=spawn_result.spawn_id,
                    status="success",
                    result=result_data,
                    time_ms=spawn_result.time_ms,
                )
            except Exception as exc:
                return SpawnResult(
                    spawn_id=spawn_result.spawn_id,
                    status="failure",
                    error=str(exc),
                    time_ms=spawn_result.time_ms,
                )

        if level == EscalationLevel.DECOMPOSE:
            # For now, return a structured error indicating decomposition is needed
            # The caller (specialist) should handle actual decomposition
            return SpawnResult(
                spawn_id=spawn_result.spawn_id,
                status="failure",
                error=(
                    f"DECOMPOSE_REQUIRED: {params['failure_reason']}\n"
                    f"Instruction: {params['instruction']}"
                ),
                result=params,
                time_ms=spawn_result.time_ms,
            )

        # Level 4: Escalate
        if message_bus is not None:
            await message_bus.publish(
                AgentMessage(
                    message_id=f"escalate-{time.time()}",
                    correlation_id=current_request.correlation_id,
                    timestamp=time.time(),
                    sender=AgentAddress(harness="recovery", agent="orchestrator", depth=0),
                    recipient="broadcast",
                    type=MessageType.ERROR,
                    payload=params,
                )
            )

        return SpawnResult(
            spawn_id=spawn_result.spawn_id,
            status="failure",
            error=f"ESCALATED_TO_USER: {params['last_error']}",
            result=params.get("partial_result"),
            time_ms=spawn_result.time_ms,
        )

    def reset(self, spawn_id: str) -> None:
        """Reset escalation state for a spawn."""
        self._attempt_counts.pop(spawn_id, None)
        self._escalation_levels.pop(spawn_id, None)
