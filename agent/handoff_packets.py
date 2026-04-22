from __future__ import annotations

"""Helpers for mission-linked handoff and checkpoint persistence.

These helpers keep delegation/checkpoint code small while routing all durable
workflow state through ``MissionService``.
"""

from typing import Any, Dict, Optional

from agent.mission_state import MissionService


def _sanitize_handoff_context(context: str | None, *, max_chars: int = 320) -> str | None:
    text = str(context or "").strip()
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    preview = lines[0] if lines else text
    if len(preview) > max_chars:
        preview = preview[:max_chars] + "…"
    extra_lines = max(len(lines) - 1, 0)
    if extra_lines:
        preview += f" (+{extra_lines} more line(s))"
    return f"[delegated context preview] {preview}"


def record_delegate_handoff(
    mission_service: MissionService | None,
    mission_id: str | None,
    *,
    goal: str,
    context: str | None,
    parent_session_id: str | None,
    child_session_id: str | None,
    result: Dict[str, Any] | None,
) -> Optional[Dict[str, Any]]:
    if mission_service is None or not mission_id:
        return None
    payload = result or {}
    return mission_service.record_handoff_packet(
        mission_id=mission_id,
        from_session_id=parent_session_id,
        child_session_id=child_session_id,
        goal=goal,
        context=_sanitize_handoff_context(context),
        summary=payload.get("summary"),
        status=str(payload.get("status") or "completed"),
        metadata={
            "task_index": payload.get("task_index"),
            "api_calls": payload.get("api_calls"),
            "duration_seconds": payload.get("duration_seconds"),
            "exit_reason": payload.get("exit_reason"),
            "tokens": payload.get("tokens"),
            "tool_trace": payload.get("tool_trace"),
            "error": payload.get("error"),
        },
    )


def record_mission_checkpoint(
    mission_service: MissionService | None,
    mission_id: str | None,
    *,
    checkpoint_type: str,
    session_id: str | None,
    title: str | None,
    payload: Dict[str, Any] | list[Any] | str | None,
) -> Optional[Dict[str, Any]]:
    if mission_service is None or not mission_id:
        return None
    return mission_service.record_checkpoint(
        mission_id=mission_id,
        checkpoint_type=checkpoint_type,
        session_id=session_id,
        title=title,
        payload=payload,
    )


def build_mission_bundle(
    mission_service: MissionService | None,
    mission_id: str | None,
) -> Optional[Dict[str, Any]]:
    if mission_service is None or not mission_id:
        return None
    return mission_service.build_bundle(mission_id)
