from __future__ import annotations

import pytest

from agent.mission_state import MissionService
from hermes_state import SessionDB


@pytest.fixture()
def db(tmp_path):
    db_path = tmp_path / "mission_state.db"
    session_db = SessionDB(db_path=db_path)
    yield session_db
    session_db.close()


@pytest.fixture()
def service(db):
    return MissionService(db)


class TestMissionLifecycle:
    def test_attach_requires_approval(self, service, db):
        db.create_session(session_id="s1", source="cli")
        mission = service.create_mission(title="Mission Alpha", created_by_session_id="s1")

        with pytest.raises(PermissionError):
            service.attach_session("s1", mission["id"])

        approved = service.approve_mission(mission["id"], approved_by_session_id="s1")
        assert approved["status"] == "approved"

        active = service.attach_session("s1", mission["id"])
        assert active["status"] == "active"
        assert service.get_attached_mission_id("s1") == mission["id"]

        detached = service.detach_session("s1")
        assert detached["status"] == "approved"
        assert service.get_attached_mission_id("s1") is None

    def test_create_nodes_and_links(self, service):
        mission = service.create_mission(title="Mission Graph")
        feature = service.create_node(mission_id=mission["id"], node_type="feature", title="Feature A")
        task = service.create_node(
            mission_id=mission["id"],
            node_type="task",
            title="Task A",
            parent_node_id=feature["id"],
            external_id="todo-1",
            status="pending",
        )
        link = service.create_link(
            mission_id=mission["id"],
            source_node_id=feature["id"],
            target_node_id=task["id"],
            link_type="depends_on",
        )

        nodes = service.list_nodes(mission["id"])
        links = service.list_links(mission["id"])
        assert [node["id"] for node in nodes] == [feature["id"], task["id"]]
        assert links == [link]


class TestTodoWriteThrough:
    def test_attached_session_writes_mission_tasks_and_detach_restores_local_snapshot(self, service, db):
        db.create_session(session_id="s1", source="cli")
        local = service.set_session_local_todos(
            "s1",
            [{"id": "local-1", "content": "Local task", "status": "pending"}],
        )
        mission = service.create_mission(title="Mission Todos")
        service.approve_mission(mission["id"])
        service.attach_session("s1", mission["id"])

        mission_todos = service.write_todos_for_session(
            "s1",
            [{"id": "task-1", "content": "Canonical task", "status": "in_progress"}],
        )
        assert mission_todos == [{"id": "task-1", "content": "Canonical task", "status": "in_progress"}]
        assert service.get_session_local_todos("s1") == []
        assert service.get_todos_for_session("s1") == mission_todos

        service.detach_session("s1")
        assert service.get_todos_for_session("s1") == mission_todos

    def test_copy_session_work_context_carries_local_todos_and_attachment(self, service, db):
        db.create_session(session_id="source", source="cli")
        db.create_session(session_id="target", source="cli")
        mission = service.create_mission(title="Copy Context")
        service.approve_mission(mission["id"])
        service.attach_session("source", mission["id"])
        source_todos = service.write_todos_for_session(
            "source",
            [{"id": "t1", "content": "Canonical carry", "status": "pending"}],
        )

        service.copy_session_work_context("source", "target")

        assert service.get_attached_mission_id("target") == mission["id"]
        service.detach_session("target")
        assert service.get_session_local_todos("target") == source_todos



class TestMissionInvariants:
    def test_cross_mission_parent_and_link_rejected(self, service):
        mission_a = service.create_mission(title="Mission A")
        mission_b = service.create_mission(title="Mission B")
        node_a = service.create_node(mission_id=mission_a["id"], node_type="feature", title="A")
        node_b = service.create_node(mission_id=mission_b["id"], node_type="feature", title="B")

        with pytest.raises(ValueError):
            service.create_node(
                mission_id=mission_a["id"],
                node_type="task",
                title="Cross parent",
                parent_node_id=node_b["id"],
            )

        with pytest.raises(ValueError):
            service.create_link(
                mission_id=mission_a["id"],
                source_node_id=node_a["id"],
                target_node_id=node_b["id"],
                link_type="depends_on",
            )

    def test_todo_sync_only_manages_todo_backed_task_nodes(self, service, db):
        db.create_session(session_id="s1", source="cli")
        mission = service.create_mission(title="Mission Todos")
        service.approve_mission(mission["id"])
        service.attach_session("s1", mission["id"])
        generic_task = service.create_node(
            mission_id=mission["id"],
            node_type="task",
            title="Generic task without external id",
            status="pending",
        )

        service.write_todos_for_session(
            "s1",
            [{"id": "todo-1", "content": "Todo-backed task", "status": "pending"}],
            merge=False,
        )

        nodes = service.list_nodes(mission["id"], node_type="task")
        assert any(node["id"] == generic_task["id"] for node in nodes)
        assert service.get_todos_for_session("s1") == [
            {"id": "todo-1", "content": "Todo-backed task", "status": "pending"}
        ]


def test_copy_session_work_context_repairs_previous_target_mission(service, db):
    db.create_session(session_id="source", source="cli")
    db.create_session(session_id="target", source="cli")
    mission_one = service.create_mission(title="Mission One")
    mission_two = service.create_mission(title="Mission Two")
    service.approve_mission(mission_one["id"])
    service.approve_mission(mission_two["id"])
    service.attach_session("source", mission_one["id"])
    service.attach_session("target", mission_two["id"])

    service.copy_session_work_context("source", "target")

    assert service.get_attached_mission_id("target") == mission_one["id"]
    assert service.get_mission(mission_two["id"])["status"] == "approved"