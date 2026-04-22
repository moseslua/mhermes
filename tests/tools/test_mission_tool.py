from __future__ import annotations

import json

import pytest

from agent.mission_state import MissionService
from hermes_state import SessionDB
from tools.mission_tool import mission_tool


@pytest.fixture()
def db(tmp_path):
    db_path = tmp_path / "mission_tool.db"
    session_db = SessionDB(db_path=db_path)
    yield session_db
    session_db.close()


@pytest.fixture()
def service(db):
    return MissionService(db)


class TestMissionTool:
    def test_create_approve_attach_and_get(self, db, service):
        db.create_session(session_id="s1", source="cli")

        created = json.loads(mission_tool(action="create", title="Mission Tool", session_id="s1", service=service, db=db))
        mission_id = created["mission"]["id"]
        assert created["mission"]["status"] == "draft"

        approved = json.loads(mission_tool(action="approve", mission_id=mission_id, session_id="s1", service=service, db=db))
        assert approved["mission"]["status"] == "approved"

        attached = json.loads(mission_tool(action="attach", mission_id=mission_id, session_id="s1", service=service, db=db))
        assert attached["mission"]["status"] == "active"

        current = json.loads(mission_tool(action="get", session_id="s1", service=service, db=db))
        assert current["mission"]["id"] == mission_id

    def test_todos_and_checkpoint_use_attached_session(self, db, service):
        db.create_session(session_id="s1", source="cli")
        mission_id = service.create_mission(title="Mission Todos")["id"]
        service.approve_mission(mission_id)
        service.attach_session("s1", mission_id)

        todo_result = json.loads(
            mission_tool(
                action="todos",
                session_id="s1",
                todos=[{"id": "1", "content": "Task", "status": "pending"}],
                service=service,
                db=db,
            )
        )
        assert todo_result["todos"] == [{"id": "1", "content": "Task", "status": "pending"}]

        checkpoint = json.loads(
            mission_tool(
                action="checkpoint",
                session_id="s1",
                checkpoint_type="review",
                title="Checkpoint",
                payload={"ok": True},
                service=service,
                db=db,
            )
        )
        assert checkpoint["checkpoint"]["checkpoint_type"] == "review"

        bundle = json.loads(mission_tool(action="bundle", session_id="s1", service=service, db=db))
        assert bundle["bundle"]["mission"]["id"] == mission_id
        assert bundle["bundle"]["checkpoints"][0]["title"] == "Checkpoint"

    def test_attach_rejects_unapproved_mission(self, db, service):
        db.create_session(session_id="s1", source="cli")
        mission_id = service.create_mission(title="Needs approval")["id"]

        result = json.loads(mission_tool(action="attach", mission_id=mission_id, session_id="s1", service=service, db=db))
        assert "error" in result
        assert "approved" in result["error"].lower()



class TestMissionToolRegistryHandler:
    def test_registered_handler_honors_session_id_override(self, db):
        from tools.registry import registry
        service = MissionService(db)
        db.create_session(session_id="caller", source="cli")
        db.create_session(session_id="override", source="cli")
        mission_id = service.create_mission(title="Override Target")["id"]
        service.approve_mission(mission_id)

        result = json.loads(
            registry.dispatch(
                "mission",
                {"action": "attach", "mission_id": mission_id, "session_id": "override"},
                session_id="caller",
                mission_service=service,
                db=db,
            )
        )

        assert result["mission"]["status"] == "active"
        assert service.get_attached_mission_id("override") == mission_id
        assert service.get_attached_mission_id("caller") is None

    def test_unknown_mission_returns_consistent_error(self, db, service):
        result = json.loads(mission_tool(action="get", mission_id="missing", service=service, db=db))
        assert result["error"] == "Unknown mission: missing"

    def test_detach_without_attached_mission_returns_error(self, db, service):
        db.create_session(session_id="s1", source="cli")
        result = json.loads(mission_tool(action="detach", session_id="s1", service=service, db=db))
        assert result["error"] == "No attached mission for session: s1"

    def test_update_missing_node_returns_error(self, db, service):
        result = json.loads(mission_tool(action="update_node", node_id="missing", service=service, db=db))
        assert result["error"] == "Unknown mission node: missing"

    def test_handoff_action_persists_packet(self, db, service):
        db.create_session(session_id="s1", source="cli")
        mission_id = service.create_mission(title="Handoff")["id"]
        service.approve_mission(mission_id)
        result = json.loads(
            mission_tool(
                action="handoff",
                mission_id=mission_id,
                session_id="s1",
                goal="Investigate mission state",
                title="handoff summary",
                description="context line one\ncontext line two",
                service=service,
                db=db,
            )
        )
        assert result["handoff"]["goal"] == "Investigate mission state"
        assert result["handoff"]["summary"] == "handoff summary"