"""Tests for the todo tool module."""

import json

from tools.todo_tool import TodoStore, todo_tool


class _FakeMissionService:
    def __init__(self, *, attached: bool = False):
        self.attached = attached
        self.local_todos = []
        self.mission_todos = []
        self.write_calls = []

    def get_attached_mission_id(self, session_id):
        return "mission-1" if self.attached else None

    def get_session_local_todos(self, session_id):
        return [item.copy() for item in self.local_todos]

    def set_session_local_todos(self, session_id, todos):
        self.local_todos = [item.copy() for item in todos]
        return self.get_session_local_todos(session_id)

    def get_todos_for_session(self, session_id):
        return [item.copy() for item in self.mission_todos]

    def write_todos_for_session(self, session_id, todos, *, merge=False):
        self.write_calls.append({"session_id": session_id, "todos": todos, "merge": merge})
        items = [
            {
                "id": str(item.get("id", "")).strip() or "?",
                "content": str(item.get("content", "")).strip() or "(no description)",
                "status": str(item.get("status", "pending")).strip().lower() or "pending",
            }
            for item in todos
        ]
        if not merge:
            self.mission_todos = items
        else:
            existing = {item["id"]: item.copy() for item in self.mission_todos}
            for item in items:
                existing[item["id"]] = item
            ordered_ids = [item["id"] for item in self.mission_todos if item["id"] in existing]
            ordered_ids.extend(item["id"] for item in items if item["id"] not in ordered_ids)
            self.mission_todos = [existing[item_id] for item_id in ordered_ids]
        return self.get_todos_for_session(session_id)


class TestWriteAndRead:
    def test_write_replaces_list(self):
        store = TodoStore()
        items = [
            {"id": "1", "content": "First task", "status": "pending"},
            {"id": "2", "content": "Second task", "status": "in_progress"},
        ]
        result = store.write(items)
        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[1]["status"] == "in_progress"

    def test_read_returns_copy(self):
        store = TodoStore()
        store.write([{"id": "1", "content": "Task", "status": "pending"}])
        items = store.read()
        items[0]["content"] = "MUTATED"
        assert store.read()[0]["content"] == "Task"

    def test_write_deduplicates_duplicate_ids(self):
        store = TodoStore()
        result = store.write([
            {"id": "1", "content": "First version", "status": "pending"},
            {"id": "2", "content": "Other task", "status": "pending"},
            {"id": "1", "content": "Latest version", "status": "in_progress"},
        ])
        assert result == [
            {"id": "2", "content": "Other task", "status": "pending"},
            {"id": "1", "content": "Latest version", "status": "in_progress"},
        ]


class TestHasItems:
    def test_empty_store(self):
        store = TodoStore()
        assert store.has_items() is False

    def test_non_empty_store(self):
        store = TodoStore()
        store.write([{"id": "1", "content": "x", "status": "pending"}])
        assert store.has_items() is True


class TestFormatForInjection:
    def test_empty_returns_none(self):
        store = TodoStore()
        assert store.format_for_injection() is None

    def test_non_empty_has_markers(self):
        store = TodoStore()
        store.write([
            {"id": "1", "content": "Do thing", "status": "completed"},
            {"id": "2", "content": "Next", "status": "pending"},
            {"id": "3", "content": "Working", "status": "in_progress"},
        ])
        text = store.format_for_injection()
        # Completed items are filtered out of injection
        assert "[x]" not in text
        assert "Do thing" not in text
        # Active items are included
        assert "[ ]" in text
        assert "[>]" in text
        assert "Next" in text
        assert "Working" in text
        assert "context compression" in text.lower()


class TestMergeMode:
    def test_update_existing_by_id(self):
        store = TodoStore()
        store.write([
            {"id": "1", "content": "Original", "status": "pending"},
        ])
        store.write(
            [{"id": "1", "status": "completed"}],
            merge=True,
        )
        items = store.read()
        assert len(items) == 1
        assert items[0]["status"] == "completed"
        assert items[0]["content"] == "Original"

    def test_merge_appends_new(self):
        store = TodoStore()
        store.write([{"id": "1", "content": "First", "status": "pending"}])
        store.write(
            [{"id": "2", "content": "Second", "status": "pending"}],
            merge=True,
        )
        items = store.read()
        assert len(items) == 2


class TestTodoToolFunction:
    def test_read_mode(self):
        store = TodoStore()
        store.write([{"id": "1", "content": "Task", "status": "pending"}])
        result = json.loads(todo_tool(store=store))
        assert result["summary"]["total"] == 1
        assert result["summary"]["pending"] == 1

    def test_write_mode(self):
        store = TodoStore()
        result = json.loads(todo_tool(
            todos=[{"id": "1", "content": "New", "status": "in_progress"}],
            store=store,
        ))
        assert result["summary"]["in_progress"] == 1

    def test_no_store_returns_error(self):
        result = json.loads(todo_tool())
        assert "error" in result


class TestMissionAwareTodoStore:
    def test_reads_local_snapshot_from_mission_service_when_unattached(self):
        service = _FakeMissionService(attached=False)
        service.local_todos = [{"id": "1", "content": "Persisted local", "status": "pending"}]
        store = TodoStore(session_id="session-1", mission_service=service)
        assert store.read() == [{"id": "1", "content": "Persisted local", "status": "pending"}]

    def test_reads_attached_mission_tasks_instead_of_local_items(self):
        service = _FakeMissionService(attached=True)
        service.local_todos = [{"id": "1", "content": "Local", "status": "pending"}]
        service.mission_todos = [{"id": "m1", "content": "Mission task", "status": "in_progress"}]
        store = TodoStore(session_id="session-1", mission_service=service)
        assert store.read() == [{"id": "m1", "content": "Mission task", "status": "in_progress"}]

    def test_writes_attached_mission_tasks_through_service(self):
        service = _FakeMissionService(attached=True)
        store = TodoStore(session_id="session-1", mission_service=service)
        items = store.write([{"id": "m1", "content": "Canonical task", "status": "pending"}], merge=False)
        assert service.write_calls == [{
            "session_id": "session-1",
            "todos": [{"id": "m1", "content": "Canonical task", "status": "pending"}],
            "merge": False,
        }]
        assert items == [{"id": "m1", "content": "Canonical task", "status": "pending"}]

    def test_persists_unattached_local_writes_back_to_service_snapshot(self):
        service = _FakeMissionService(attached=False)
        store = TodoStore(session_id="session-1", mission_service=service)
        store.write([{"id": "1", "content": "Local task", "status": "pending"}], merge=False)
        assert service.local_todos == [{"id": "1", "content": "Local task", "status": "pending"}]

    def test_rebinding_to_empty_session_clears_stale_local_items(self):
        service = _FakeMissionService(attached=False)
        first = TodoStore(session_id="session-1", mission_service=service)
        first.write([{"id": "1", "content": "Session one", "status": "pending"}], merge=False)

        second_service = _FakeMissionService(attached=False)
        first.bind_session("session-2", second_service)

        assert first.read() == []

    def test_attached_merge_preserves_existing_content(self):
        service = _FakeMissionService(attached=True)
        service.mission_todos = [{"id": "1", "content": "Original", "status": "pending"}]
        store = TodoStore(session_id="session-1", mission_service=service)

        items = store.write([{"id": "1", "status": "completed"}], merge=True)

        assert items == [{"id": "1", "content": "Original", "status": "completed"}]