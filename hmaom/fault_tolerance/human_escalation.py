"""HMAOM Human Escalation System.

Provides channels and orchestration for escalating failed agent executions
to human operators, collecting structured context, and resuming execution
after human intervention.
"""

from __future__ import annotations

import json
import smtplib
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import MagicMock

from hmaom.config import EscalationConfig
from hmaom.protocol.schemas import Domain, SpawnRequest, SpawnResult, TaskDescription


class EscalationChannel(ABC):
    """Abstract base for human escalation channels."""

    @abstractmethod
    def send(self, context: dict) -> bool:
        """Send escalation context to the channel. Returns True if sent."""

    @abstractmethod
    def await_response(self, timeout: int) -> dict | None:
        """Block until human responds or timeout expires. Returns response dict or None."""


class CLIPauseChannel(EscalationChannel):
    """Console-based escalation: prints context and blocks for stdin input."""

    def __init__(self, input_stream: Any = sys.stdin, output_stream: Any = sys.stdout) -> None:
        self.input_stream = input_stream
        self.output_stream = output_stream

    def send(self, context: dict) -> bool:
        """Print the escalation context to the console."""
        try:
            self.output_stream.write("\n=== HUMAN ESCALATION ===\n")
            self.output_stream.write(json.dumps(context, indent=2, default=str))
            self.output_stream.write("\n========================\n")
            self.output_stream.flush()
            return True
        except Exception:
            return False

    def await_response(self, timeout: int) -> dict | None:
        """Block for stdin input. In test mode, reads from provided input_stream."""
        try:
            self.output_stream.write(
                f"Awaiting human response (timeout: {timeout}s). Enter JSON or 'skip':\n"
            )
            self.output_stream.flush()
            raw = self.input_stream.readline()
            if not raw:
                return None
            text = raw.strip()
            if text.lower() == "skip":
                return None
            return json.loads(text)
        except Exception:
            return None


class SlackChannel(EscalationChannel):
    """Slack webhook-based escalation channel."""

    def __init__(self, webhook_url: str, config: Optional[EscalationConfig] = None) -> None:
        self.webhook_url = webhook_url
        self.config = config or EscalationConfig()
        self._last_response: Optional[dict] = None

    def send(self, context: dict) -> bool:
        """Post escalation context to a Slack webhook."""
        try:
            import urllib.request

            payload = json.dumps(
                {
                    "text": f"HMAOM Escalation: {context.get('correlation_id', 'unknown')}",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"```\n{json.dumps(context, indent=2, default=str)}\n```",
                            },
                        }
                    ],
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.config.channel_timeout_seconds) as resp:
                return resp.status == 200
        except Exception:
            return False

    def await_response(self, timeout: int) -> dict | None:
        """Return the last captured response (simulated in this sync model)."""
        return self._last_response

    def inject_response(self, response: dict) -> None:
        """Inject a test/mock response."""
        self._last_response = response


class EmailChannel(EscalationChannel):
    """SMTP-based escalation channel."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        from_addr: str,
        to_addrs: list[str],
        username: Optional[str] = None,
        password: Optional[str] = None,
        config: Optional[EscalationConfig] = None,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        self.username = username
        self.password = password
        self.config = config or EscalationConfig()
        self._mock_smtp: Optional[MagicMock] = None
        self._last_response: Optional[dict] = None

    def send(self, context: dict) -> bool:
        """Send escalation context via SMTP email."""
        try:
            subject = f"[HMAOM Escalation] {context.get('correlation_id', 'unknown')}"
            body = json.dumps(context, indent=2, default=str)
            msg = f"Subject: {subject}\n\n{body}"

            if self._mock_smtp is not None:
                self._mock_smtp.sendmail(self.from_addr, self.to_addrs, msg)
                return True

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.config.channel_timeout_seconds) as server:
                if self.username and self.password:
                    server.starttls()
                    server.login(self.username, self.password)
                server.sendmail(self.from_addr, self.to_addrs, msg)
            return True
        except Exception:
            return False

    def await_response(self, timeout: int) -> dict | None:
        """Return the last captured response (simulated in this sync model)."""
        return self._last_response

    def set_mock_smtp(self, mock: MagicMock) -> None:
        """Set a mock SMTP object for testing."""
        self._mock_smtp = mock

    def inject_response(self, response: dict) -> None:
        """Inject a test/mock response."""
        self._last_response = response


@dataclass
class EscalationRecord:
    """Record of a human escalation event."""

    correlation_id: str
    channel_type: str
    sent_at: float
    context: dict
    response: Optional[dict] = None
    resolved_at: Optional[float] = None


class HumanEscalation:
    """Orchestrates human escalation for failed agent executions.

    - Packages structured context for the human
    - Sends via an EscalationChannel
    - Awaits and validates the human response
    - Resumes execution by routing the human's decision back into the gateway
    """

    def __init__(self, config: Optional[EscalationConfig] = None) -> None:
        self.config = config or EscalationConfig()
        self._history: list[EscalationRecord] = []

    def package_context(
        self,
        correlation_id: str,
        trace_summary: dict[str, Any],
        failed_attempts: list[SpawnResult],
        request_context: SpawnRequest,
        checkpoint_url: Optional[str] = None,
    ) -> dict:
        """Build a structured dict with all escalation context."""
        return {
            "correlation_id": correlation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_summary": trace_summary,
            "failed_attempts": [
                {
                    "spawn_id": r.spawn_id,
                    "status": r.status,
                    "error": r.error,
                    "tokens_used": r.tokens_used,
                    "time_ms": r.time_ms,
                    "checkpoint_url": r.checkpoint_url,
                }
                for r in failed_attempts
            ],
            "request_context": {
                "spawn_id": request_context.spawn_id,
                "parent_id": request_context.parent_id,
                "depth": request_context.depth,
                "task": request_context.task.model_dump() if request_context.task else None,
                "constraints": request_context.constraints.model_dump() if request_context.constraints else None,
            },
            "checkpoint_url": checkpoint_url,
            "suggested_actions": [
                "retry_same",
                "replan",
                "decompose",
                "abort",
            ],
        }

    def escalate(
        self,
        correlation_id: str,
        trace_summary: dict[str, Any],
        failed_attempts: list[SpawnResult],
        request_context: SpawnRequest,
        channel: EscalationChannel,
        checkpoint_url: Optional[str] = None,
    ) -> dict:
        """Escalate a failed execution to a human via the given channel.

        Returns the human response dict, or a fallback abort decision if no response.
        """
        context = self.package_context(
            correlation_id=correlation_id,
            trace_summary=trace_summary,
            failed_attempts=failed_attempts,
            request_context=request_context,
            checkpoint_url=checkpoint_url,
        )

        sent = channel.send(context)
        record = EscalationRecord(
            correlation_id=correlation_id,
            channel_type=channel.__class__.__name__,
            sent_at=time.time(),
            context=context,
        )

        if not sent:
            record.resolved_at = time.time()
            self._history.append(record)
            return {"action": "abort", "reason": "escalation_channel_failed", "correlation_id": correlation_id}

        response = channel.await_response(timeout=self.config.human_response_timeout_seconds)
        record.response = response
        record.resolved_at = time.time()
        self._history.append(record)

        if response is None:
            return {"action": "abort", "reason": "human_timeout", "correlation_id": correlation_id}

        return response

    def resume_from_human(
        self,
        response: dict,
        router: Any,
    ) -> dict:
        """Resume execution based on a human response dict.

        The response dict should contain an 'action' key:
            - retry_same: retry the original task unchanged
            - replan: rewrite the task description and re-route
            - decompose: break into subtasks and route each
            - abort: return a failure result
        """
        from hmaom.gateway.router import GatewayRouter

        action = response.get("action", "abort")
        correlation_id = response.get("correlation_id", "unknown")

        if action == "retry_same":
            # Return instruction to retry the same task
            return {
                "action": "retry_same",
                "correlation_id": correlation_id,
                "message": "Human approved retry with same parameters",
            }

        if action == "replan":
            # Return instruction to replan the task
            return {
                "action": "replan",
                "correlation_id": correlation_id,
                "new_task_description": response.get("new_task_description"),
                "message": "Human provided a replanned task description",
            }

        if action == "decompose":
            # Return instruction to decompose into subtasks
            return {
                "action": "decompose",
                "correlation_id": correlation_id,
                "subtasks": response.get("subtasks", []),
                "message": "Human requested decomposition into subtasks",
            }

        # Default: abort
        return {
            "action": "abort",
            "correlation_id": correlation_id,
            "reason": response.get("reason", "human_aborted"),
            "message": "Human chose to abort or no valid action provided",
        }

    def get_history(self) -> list[EscalationRecord]:
        """Return all escalation records."""
        return list(self._history)
