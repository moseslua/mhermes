#!/usr/bin/env python3
"""
Todo Tool Module - Planning & Task Management

Provides a task list the agent uses to decompose complex tasks, track progress,
and maintain focus across long conversations.

Phase 2 note:
- Unattached sessions keep the historical local TodoStore behavior.
- Attached mission sessions transparently read/write canonical mission task rows
  through ``MissionService``.
- Tool schema and user-visible result shape stay stable.
"""

from __future__ import annotations

import json
from typing import Dict, Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for typing
    from agent.mission_state import MissionService


# Valid status values for todo items
VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}


class TodoStore:
    """Task list store for one agent/session.

    Local mode preserves the original in-memory list semantics. When a
    ``MissionService`` is bound and the current session is attached to a mission,
    reads and writes are delegated to canonical mission state instead.
    """

    def __init__(
        self,
        *,
        session_id: str | None = None,
        mission_service: "MissionService | None" = None,
    ):
        self._items: List[Dict[str, str]] = []
        self._session_id = session_id
        self._mission_service = mission_service
        self._local_loaded = False

    def bind_session(
        self,
        session_id: str | None,
        mission_service: "MissionService | None" = None,
    ) -> None:
        self._session_id = session_id
        if mission_service is not None:
            self._mission_service = mission_service
        self._items = []
        self._local_loaded = False

    def _attached_mission_id(self) -> Optional[str]:
        if not self._mission_service or not self._session_id:
            return None
        return self._mission_service.get_attached_mission_id(self._session_id)

    def _load_local_snapshot_if_needed(self) -> None:
        if self._local_loaded:
            return
        if self._mission_service and self._session_id and not self._attached_mission_id():
            snapshot = self._mission_service.get_session_local_todos(self._session_id)
            self._items = [self._validate(item) for item in self._dedupe_by_id(snapshot)]
        self._local_loaded = True

    def write(self, todos: List[Dict[str, Any]], merge: bool = False) -> List[Dict[str, str]]:
        """Write todos and return the full current list after writing."""
        mission_id = self._attached_mission_id()
        if mission_id and self._mission_service and self._session_id:
            mission_todos = todos
            if merge:
                current_items = self._mission_service.get_todos_for_session(self._session_id)
                merged_by_id = {item["id"]: item.copy() for item in current_items}
                ordered_ids = [item["id"] for item in current_items]
                for t in self._dedupe_by_id(todos):
                    item_id = str(t.get("id", "")).strip()
                    if not item_id:
                        continue
                    if item_id in merged_by_id:
                        merged = merged_by_id[item_id].copy()
                        if "content" in t and t["content"]:
                            merged["content"] = str(t["content"]).strip()
                        if "status" in t and t["status"]:
                            status = str(t["status"]).strip().lower()
                            if status in VALID_STATUSES:
                                merged["status"] = status
                        merged_by_id[item_id] = self._validate(merged)
                    else:
                        merged_by_id[item_id] = self._validate(t)
                        ordered_ids.append(item_id)
                mission_todos = [merged_by_id[item_id] for item_id in ordered_ids if item_id in merged_by_id]
            return self._mission_service.write_todos_for_session(
                self._session_id,
                mission_todos,
                merge=False if merge else merge,
            )

        self._load_local_snapshot_if_needed()
        if not merge:
            self._items = [self._validate(t) for t in self._dedupe_by_id(todos)]
        else:
            existing = {item["id"]: item for item in self._items}
            for t in self._dedupe_by_id(todos):
                item_id = str(t.get("id", "")).strip()
                if not item_id:
                    continue
                if item_id in existing:
                    if "content" in t and t["content"]:
                        existing[item_id]["content"] = str(t["content"]).strip()
                    if "status" in t and t["status"]:
                        status = str(t["status"]).strip().lower()
                        if status in VALID_STATUSES:
                            existing[item_id]["status"] = status
                else:
                    validated = self._validate(t)
                    existing[validated["id"]] = validated
                    self._items.append(validated)
            seen = set()
            rebuilt = []
            for item in self._items:
                current = existing.get(item["id"], item)
                if current["id"] not in seen:
                    rebuilt.append(current)
                    seen.add(current["id"])
            self._items = rebuilt

        if self._mission_service and self._session_id:
            self._mission_service.set_session_local_todos(self._session_id, self._items)
        return self.read()

    def read(self) -> List[Dict[str, str]]:
        """Return a copy of the current list."""
        if self._attached_mission_id() and self._mission_service and self._session_id:
            return [item.copy() for item in self._mission_service.get_todos_for_session(self._session_id)]
        self._load_local_snapshot_if_needed()
        return [item.copy() for item in self._items]

    def has_items(self) -> bool:
        return bool(self.read())

    def format_for_injection(self) -> Optional[str]:
        """Render the active todo list for post-compression injection."""
        items = self.read()
        if not items:
            return None

        markers = {
            "completed": "[x]",
            "in_progress": "[>]",
            "pending": "[ ]",
            "cancelled": "[~]",
        }
        active_items = [
            item for item in items
            if item["status"] in ("pending", "in_progress")
        ]
        if not active_items:
            return None

        lines = ["[Your active task list was preserved across context compression]"]
        for item in active_items:
            marker = markers.get(item["status"], "[?]")
            lines.append(f"- {marker} {item['id']}. {item['content']} ({item['status']})")
        return "\n".join(lines)

    @staticmethod
    def _validate(item: Dict[str, Any]) -> Dict[str, str]:
        item_id = str(item.get("id", "")).strip() or "?"
        content = str(item.get("content", "")).strip() or "(no description)"
        status = str(item.get("status", "pending")).strip().lower()
        if status not in VALID_STATUSES:
            status = "pending"
        return {"id": item_id, "content": content, "status": status}

    @staticmethod
    def _dedupe_by_id(todos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        last_index: Dict[str, int] = {}
        for i, item in enumerate(todos):
            item_id = str(item.get("id", "")).strip() or "?"
            last_index[item_id] = i
        return [todos[i] for i in sorted(last_index.values())]


def todo_tool(
    todos: Optional[List[Dict[str, Any]]] = None,
    merge: bool = False,
    store: Optional[TodoStore] = None,
) -> str:
    """Single entry point for the todo tool."""
    if store is None:
        return tool_error("TodoStore not initialized")

    if todos is not None:
        items = store.write(todos, merge)
    else:
        items = store.read()

    pending = sum(1 for i in items if i["status"] == "pending")
    in_progress = sum(1 for i in items if i["status"] == "in_progress")
    completed = sum(1 for i in items if i["status"] == "completed")
    cancelled = sum(1 for i in items if i["status"] == "cancelled")

    return json.dumps({
        "todos": items,
        "summary": {
            "total": len(items),
            "pending": pending,
            "in_progress": in_progress,
            "completed": completed,
            "cancelled": cancelled,
        },
    }, ensure_ascii=False)



def check_todo_requirements() -> bool:
    """Todo tool has no external requirements -- always available."""
    return True


TODO_SCHEMA = {
    "name": "todo",
    "description": (
        "Manage your task list for the current session. Use for complex tasks "
        "with 3+ steps or when the user provides multiple tasks. "
        "Call with no parameters to read the current list.\n\n"
        "Writing:\n"
        "- Provide 'todos' array to create/update items\n"
        "- merge=false (default): replace the entire list with a fresh plan\n"
        "- merge=true: update existing items by id, add any new ones\n\n"
        "Each item: {id: string, content: string, "
        "status: pending|in_progress|completed|cancelled}\n"
        "List order is priority. Only ONE item in_progress at a time.\n"
        "Mark items completed immediately when done. If something fails, "
        "cancel it and add a revised item.\n\n"
        "Always returns the full current list."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "Task items to write. Omit to read current list.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique item identifier"
                        },
                        "content": {
                            "type": "string",
                            "description": "Task description"
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed", "cancelled"],
                            "description": "Current status"
                        }
                    },
                    "required": ["id", "content", "status"]
                }
            },
            "merge": {
                "type": "boolean",
                "description": (
                    "true: update existing items by id, add new ones. "
                    "false (default): replace the entire list."
                ),
                "default": False
            }
        },
        "required": []
    }
}


# --- Registry ---
from tools.registry import registry, tool_error

registry.register(
    name="todo",
    toolset="todo",
    schema=TODO_SCHEMA,
    handler=lambda args, **kw: todo_tool(
        todos=args.get("todos"),
        merge=args.get("merge", False),
        store=kw.get("store"),
    ),
    check_fn=check_todo_requirements,
    emoji="📋",
)
