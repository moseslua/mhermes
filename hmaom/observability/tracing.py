"""HMAOM Distributed Tracing.

Every request gets a correlation ID that propagates through the entire
tree. Spans are logged with timing, token usage, and status.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from hmaom.config import ObservabilityConfig
from hmaom.protocol.schemas import AgentAddress


class Span:
    """A single span in a distributed trace."""

    def __init__(
        self,
        correlation_id: str,
        span_id: str,
        parent_id: Optional[str],
        agent_address: AgentAddress,
        operation: str,
    ) -> None:
        self.correlation_id = correlation_id
        self.span_id = span_id
        self.parent_id = parent_id
        self.agent_address = agent_address
        self.operation = operation
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.status = "ok"
        self.tokens_used = 0
        self.metadata: dict[str, Any] = {}

    def finish(
        self,
        status: str = "ok",
        tokens_used: int = 0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        self.end_time = time.time()
        self.status = status
        self.tokens_used = tokens_used
        if metadata:
            self.metadata.update(metadata)

    @property
    def duration_ms(self) -> float:
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "harness": self.agent_address.harness,
            "agent": self.agent_address.agent,
            "depth": self.agent_address.depth,
            "operation": self.operation,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "tokens_used": self.tokens_used,
            "metadata": self.metadata,
        }


class Tracer:
    """Distributed tracer for the HMAOM mesh.

    Traces are written as newline-delimited JSON to a log file.
    Each trace is a tree of spans sharing a correlation_id.
    """

    def __init__(self, config: Optional[ObservabilityConfig] = None) -> None:
        self.config = config or ObservabilityConfig()
        self._active_spans: dict[str, Span] = {}
        self._span_counter = 0

        if self.config.enabled:
            trace_path = Path(self.config.trace_log_path)
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = open(str(trace_path), "a", buffering=1)
        else:
            self._log_file = None

    def start_span(
        self,
        correlation_id: str,
        agent_address: AgentAddress,
        operation: str,
        parent_span_id: Optional[str] = None,
    ) -> Span:
        """Start a new span and return it."""
        self._span_counter += 1
        span_id = f"span-{self._span_counter}-{int(time.time() * 1000)}"

        span = Span(
            correlation_id=correlation_id,
            span_id=span_id,
            parent_id=parent_span_id,
            agent_address=agent_address,
            operation=operation,
        )
        self._active_spans[span_id] = span
        return span

    def finish_span(
        self,
        span: Span,
        status: str = "ok",
        tokens_used: int = 0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Finish a span and write it to the trace log."""
        span.finish(status=status, tokens_used=tokens_used, metadata=metadata)
        self._active_spans.pop(span.span_id, None)

        if self._log_file is not None:
            self._log_file.write(json.dumps(span.to_dict()) + "\n")
            self._log_file.flush()

    def get_trace(
        self,
        correlation_id: str,
    ) -> list[dict[str, Any]]:
        """Read all spans for a correlation ID from the trace log."""
        if self._log_file is None:
            return []

        # Need to read from file; close and reopen for reading
        trace_path = Path(self.config.trace_log_path)
        if not trace_path.exists():
            return []

        spans: list[dict[str, Any]] = []
        with open(str(trace_path), "r") as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    if data.get("correlation_id") == correlation_id:
                        spans.append(data)
                except json.JSONDecodeError:
                    continue
        return spans

    def get_active_tree(self, correlation_id: str) -> dict[str, Any]:
        """Get the current active spans for a correlation ID."""
        active = [
            s.to_dict()
            for s in self._active_spans.values()
            if s.correlation_id == correlation_id
        ]
        return {
            "correlation_id": correlation_id,
            "active_spans": active,
            "total_active": len(active),
        }

    def summary(self, correlation_id: str) -> dict[str, Any]:
        """Summarize a trace: total time, tokens, deepest depth."""
        spans = self.get_trace(correlation_id)
        if not spans:
            return {"correlation_id": correlation_id, "found": False}

        durations = [s["duration_ms"] for s in spans if s.get("end_time")]
        tokens = sum(s.get("tokens_used", 0) for s in spans)
        depths = [s.get("depth", 0) for s in spans]
        statuses = [s.get("status", "ok") for s in spans]

        return {
            "correlation_id": correlation_id,
            "found": True,
            "span_count": len(spans),
            "total_duration_ms": sum(durations) if durations else 0,
            "max_duration_ms": max(durations) if durations else 0,
            "total_tokens": tokens,
            "max_depth": max(depths) if depths else 0,
            "all_ok": all(s == "ok" for s in statuses),
            "error_count": sum(1 for s in statuses if s != "ok"),
        }

    def close(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
