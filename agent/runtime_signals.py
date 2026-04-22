from __future__ import annotations

"""Typed runtime-signal envelope helpers.

These helpers define the internal runtime-signal contract that later runtime
publishers will emit. Delivery is intentionally at-least-once for durable audit
consumers: retries may replay the same logical event with the same
``idempotency_key``.
"""

from dataclasses import dataclass
import json
import math
import uuid
from typing import Any, Literal, TypeAlias, Callable

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
RuntimeSignalPhase: TypeAlias = Literal[
    "requested",
    "started",
    "completed",
    "failed",
    "blocked",
    "approved",
    "rejected",
    "rolled_back",
    "ended",
]
RuntimeSignalProvenance: TypeAlias = Literal["trusted", "untrusted", "derived", "system"]

_ALLOWED_PHASES = {
    "requested",
    "started",
    "completed",
    "failed",
    "blocked",
    "approved",
    "rejected",
    "rolled_back",
    "ended",
}
_ALLOWED_PROVENANCE = {"trusted", "untrusted", "derived", "system"}
_MAX_PAYLOAD_DEPTH = 6
_MAX_PAYLOAD_ITEMS = 64
_MAX_STRING_CHARS = 2048
MAX_RUNTIME_SIGNAL_PAYLOAD_BYTES = 8_192
_PAYLOAD_PREVIEW_BYTES = 512


@dataclass(frozen=True, slots=True)
class RuntimeSignalRef:
    """Stable reference to the actor or subject attached to a signal."""

    kind: str
    id: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "id": self.id}

    @classmethod
    def from_value(cls, value: "RuntimeSignalRef | dict[str, Any] | None") -> "RuntimeSignalRef | None":
        if value is None or isinstance(value, RuntimeSignalRef):
            return value
        kind = str(value.get("kind") or "")
        ident = str(value.get("id") or "")
        if not kind or not ident:
            raise ValueError("RuntimeSignalRef requires non-empty kind and id")
        return cls(kind=kind, id=ident)


@dataclass(frozen=True, slots=True)
class RuntimeSignal:
    """Serializable runtime-signal envelope for Hermes internal coordination."""

    event_id: str
    idempotency_key: str
    event_type: str
    phase: RuntimeSignalPhase
    occurred_at: float
    publisher: str
    correlation_id: str
    session_id: str | None = None
    mission_id: str | None = None
    sequence_no: int | None = None
    actor: RuntimeSignalRef | None = None
    subject: RuntimeSignalRef | None = None
    provenance: RuntimeSignalProvenance = "system"
    payload: JsonValue | None = None

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("RuntimeSignal.event_id is required")
        if not self.idempotency_key:
            raise ValueError("RuntimeSignal.idempotency_key is required")
        if not self.event_type:
            raise ValueError("RuntimeSignal.event_type is required")
        if not self.publisher:
            raise ValueError("RuntimeSignal.publisher is required")
        if not self.correlation_id:
            raise ValueError("RuntimeSignal.correlation_id is required")
        if self.phase not in _ALLOWED_PHASES:
            raise ValueError(f"Unsupported runtime-signal phase: {self.phase}")
        if self.provenance not in _ALLOWED_PROVENANCE:
            raise ValueError(f"Unsupported runtime-signal provenance: {self.provenance}")
        if self.sequence_no is not None and self.sequence_no < 1:
            raise ValueError("RuntimeSignal.sequence_no must be >= 1 when set")
        object.__setattr__(self, "actor", RuntimeSignalRef.from_value(self.actor))
        object.__setattr__(self, "subject", RuntimeSignalRef.from_value(self.subject))
        object.__setattr__(self, "payload", bound_runtime_signal_payload(self.payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "idempotency_key": self.idempotency_key,
            "event_type": self.event_type,
            "phase": self.phase,
            "occurred_at": self.occurred_at,
            "publisher": self.publisher,
            "session_id": self.session_id,
            "mission_id": self.mission_id,
            "correlation_id": self.correlation_id,
            "sequence_no": self.sequence_no,
            "actor": self.actor.to_dict() if self.actor else None,
            "subject": self.subject.to_dict() if self.subject else None,
            "provenance": self.provenance,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RuntimeSignal":
        return cls(
            event_id=str(value["event_id"]),
            idempotency_key=str(value["idempotency_key"]),
            event_type=str(value["event_type"]),
            phase=value["phase"],
            occurred_at=float(value["occurred_at"]),
            publisher=str(value["publisher"]),
            session_id=value.get("session_id"),
            mission_id=value.get("mission_id"),
            correlation_id=str(value["correlation_id"]),
            sequence_no=value.get("sequence_no"),
            actor=RuntimeSignalRef.from_value(value.get("actor")),
            subject=RuntimeSignalRef.from_value(value.get("subject")),
            provenance=value.get("provenance", "system"),
            payload=value.get("payload"),
        )


def _json_safe_value(value: Any, *, depth: int = 0) -> JsonValue:
    if depth >= _MAX_PAYLOAD_DEPTH:
        return "<depth-limited>"
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str) and len(value) > _MAX_STRING_CHARS:
            return value[:_MAX_STRING_CHARS] + "…"
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return str(value)
    if isinstance(value, bytes):
        preview = value[:128].decode("utf-8", errors="replace")
        suffix = "…" if len(value) > 128 else ""
        return f"<bytes:{len(value)}:{preview}{suffix}>"
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_PAYLOAD_ITEMS:
                result["_truncated_items"] = len(value) - _MAX_PAYLOAD_ITEMS
                break
            result[str(key)] = _json_safe_value(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        result = [_json_safe_value(item, depth=depth + 1) for item in items[:_MAX_PAYLOAD_ITEMS]]
        if len(items) > _MAX_PAYLOAD_ITEMS:
            result.append(f"<truncated:{len(items) - _MAX_PAYLOAD_ITEMS}>")
        return result
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_safe_value(value.to_dict(), depth=depth + 1)
    if hasattr(value, "__dict__"):
        return _json_safe_value(vars(value), depth=depth + 1)
    text = repr(value)
    if len(text) > _MAX_STRING_CHARS:
        text = text[:_MAX_STRING_CHARS] + "…"
    return text


def bound_runtime_signal_payload(payload: Any, *, max_bytes: int = MAX_RUNTIME_SIGNAL_PAYLOAD_BYTES) -> JsonValue | None:
    """Return a JSON-safe payload that fits within the audit payload budget."""

    if payload is None:
        return None

    safe_payload = _json_safe_value(payload)
    encoded = json.dumps(safe_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) <= max_bytes:
        return safe_payload

    preview_text = encoded[: min(_PAYLOAD_PREVIEW_BYTES, max_bytes)].decode("utf-8", errors="replace")
    return {
        "_truncated": True,
        "original_bytes": len(encoded),
        "preview": preview_text,
    }


def make_runtime_signal(
    *,
    event_type: str,
    phase: RuntimeSignalPhase,
    publisher: str,
    session_id: str | None = None,
    mission_id: str | None = None,
    correlation_id: str | None = None,
    sequence_no: int | None = None,
    actor: RuntimeSignalRef | dict[str, Any] | None = None,
    subject: RuntimeSignalRef | dict[str, Any] | None = None,
    provenance: RuntimeSignalProvenance = "system",
    payload: Any = None,
    idempotency_key: str | None = None,
    event_id: str | None = None,
    occurred_at: float | None = None,
) -> RuntimeSignal:
    """Create a runtime-signal envelope with sane defaults for later wiring."""

    envelope_event_id = event_id or str(uuid.uuid4())
    envelope_correlation_id = correlation_id or session_id or envelope_event_id
    return RuntimeSignal(
        event_id=envelope_event_id,
        idempotency_key=idempotency_key or envelope_event_id,
        event_type=event_type,
        phase=phase,
        occurred_at=float(occurred_at) if occurred_at is not None else __import__("time").time(),
        publisher=publisher,
        session_id=session_id,
        mission_id=mission_id,
        correlation_id=envelope_correlation_id,
        sequence_no=sequence_no,
        actor=RuntimeSignalRef.from_value(actor),
        subject=RuntimeSignalRef.from_value(subject),
        provenance=provenance,
        payload=payload,
    )


def requested_signal(**kwargs: Any) -> RuntimeSignal:
    return make_runtime_signal(phase="requested", **kwargs)


def started_signal(**kwargs: Any) -> RuntimeSignal:
    return make_runtime_signal(phase="started", **kwargs)


def completed_signal(**kwargs: Any) -> RuntimeSignal:
    return make_runtime_signal(phase="completed", **kwargs)


def failed_signal(**kwargs: Any) -> RuntimeSignal:
    return make_runtime_signal(phase="failed", **kwargs)

def blocked_signal(**kwargs: Any) -> RuntimeSignal:
    return make_runtime_signal(phase="blocked", **kwargs)


def _log_runtime_signal_issue(logger: Any, level: str, message: str, *args: Any) -> None:
    if logger is None:
        return
    log_fn = getattr(logger, level, None)
    if callable(log_fn):
        log_fn(message, *args)


def persist_runtime_signal(
    signal: RuntimeSignal | dict[str, Any],
    *,
    session_db: Any = None,
    logger: Any = None,
) -> int | None:
    """Best-effort runtime-signal audit persistence."""
    if session_db is None:
        return None
    envelope = signal if isinstance(signal, RuntimeSignal) else RuntimeSignal.from_dict(signal)
    try:
        return int(session_db.append_runtime_signal_audit(envelope))
    except Exception as exc:
        _log_runtime_signal_issue(
            logger,
            "debug",
            "Runtime signal audit persistence failed for %s/%s: %s",
            envelope.event_type,
            envelope.phase,
            exc,
        )
        return None


def emit_runtime_signal(
    signal: RuntimeSignal | dict[str, Any],
    *,
    session_db: Any = None,
    hook_name: str | None = None,
    hook_kwargs: dict[str, Any] | None = None,
    hook_invoker: Callable[[str, dict[str, Any]], Any] | None = None,
    hook_failure_result: Any = None,
    logger: Any = None,
    hook_failure_log_level: str = "warning",
) -> Any:
    """Persist a canonical runtime signal and optionally derive a public hook call."""
    envelope = signal if isinstance(signal, RuntimeSignal) else RuntimeSignal.from_dict(signal)
    persist_runtime_signal(envelope, session_db=session_db, logger=logger)
    if not hook_name:
        return hook_failure_result
    hook_payload = dict(hook_kwargs or {})
    try:
        if hook_invoker is None:
            from hermes_cli.plugins import invoke_hook as _invoke_hook
            return _invoke_hook(hook_name, **hook_payload)
        return hook_invoker(hook_name, hook_payload)
    except Exception as exc:
        _log_runtime_signal_issue(
            logger,
            hook_failure_log_level,
            "%s hook failed: %s",
            hook_name,
            exc,
        )
        return hook_failure_result
