from __future__ import annotations

from agent.handoff_packets import build_mission_bundle, record_delegate_handoff, record_mission_checkpoint
from agent.mission_state import MissionService
from hermes_state import SessionDB


def _make_service(tmp_path):
    db = SessionDB(db_path=tmp_path / "handoffs.db")
    service = MissionService(db)
    return db, service


def test_record_delegate_handoff_persists_canonical_packet(tmp_path):
    db, service = _make_service(tmp_path)
    try:
        db.create_session(session_id="parent", source="cli")
        db.create_session(session_id="child", source="cli")
        mission_id = service.create_mission(title="Delegation")["id"]
        service.approve_mission(mission_id)
        service.attach_session("parent", mission_id)

        packet = record_delegate_handoff(
            service,
            mission_id,
            goal="Investigate task",
            context="extra context",
            parent_session_id="parent",
            child_session_id="child",
            result={
                "task_index": 0,
                "status": "completed",
                "summary": "Done",
                "api_calls": 2,
                "duration_seconds": 1.5,
                "tool_trace": [{"tool": "read_file"}],
            },
        )

        handoffs = service.list_handoff_packets(mission_id)
        assert packet["id"] == handoffs[0]["id"]
        assert handoffs[0]["goal"] == "Investigate task"
        assert handoffs[0]["metadata"]["tool_trace"] == [{"tool": "read_file"}]
    finally:
        db.close()


def test_record_mission_checkpoint_and_bundle_are_canonical(tmp_path):
    db, service = _make_service(tmp_path)
    try:
        db.create_session(session_id="s1", source="cli")
        mission_id = service.create_mission(title="Checkpoint")["id"]
        service.approve_mission(mission_id)
        service.attach_session("s1", mission_id)

        checkpoint = record_mission_checkpoint(
            service,
            mission_id,
            checkpoint_type="review",
            session_id="s1",
            title="Review ready",
            payload={"gate": "phase-2"},
        )
        bundle = build_mission_bundle(service, mission_id)

        assert checkpoint["checkpoint_type"] == "review"
        assert bundle["mission"]["id"] == mission_id
        assert bundle["checkpoints"][0]["payload"] == {"gate": "phase-2"}
    finally:
        db.close()


def test_handoff_context_is_stored_as_bounded_preview(tmp_path):
    db, service = _make_service(tmp_path)
    try:
        db.create_session(session_id="parent", source="cli")
        mission_id = service.create_mission(title="Preview")["id"]
        service.approve_mission(mission_id)
        service.attach_session("parent", mission_id)

        packet = record_delegate_handoff(
            service,
            mission_id,
            goal="Goal",
            context="first line\nsecond line\nthird line",
            parent_session_id="parent",
            child_session_id=None,
            result={"status": "completed", "summary": "ok"},
        )

        assert packet["context"].startswith("[delegated context preview] first line")
        assert "second line" not in packet["context"]
        assert "+2 more line(s)" in packet["context"]
    finally:
        db.close()