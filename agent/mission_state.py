from __future__ import annotations

"""Canonical mission-state service for Hermes.

Phase 2 introduces explicit mission authority on top of ``SessionDB``. Runtime
signal audit rows remain observational; this service owns the durable mission,
node, link, handoff, checkpoint, and session-attachment write paths.
"""

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from hermes_state import SessionDB

MISSION_STATUSES = {"draft", "approved", "active", "paused", "completed", "cancelled"}
MISSION_NODE_TYPES = {"milestone", "feature", "assertion", "task", "checkpoint", "note"}
MISSION_NODE_STATUSES = {
    "pending",
    "ready",
    "in_progress",
    "completed",
    "cancelled",
    "blocked",
}
TODO_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
_DEFAULT_TODO_STATUS = "pending"


class MissionService:
    """High-level mission orchestration service backed by ``SessionDB``."""

    def __init__(self, session_db: SessionDB | None) -> None:
        self._db = session_db

    @property
    def available(self) -> bool:
        return self._db is not None

    def _require_db(self) -> SessionDB:
        if self._db is None:
            raise RuntimeError("Session database not available")
        return self._db

    @staticmethod
    def _now() -> float:
        return time.time()

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    @staticmethod
    def _encode_json(value: Any) -> Optional[str]:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _clean_text(value: Any, *, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} is required")
        return text

    @staticmethod
    def _clean_optional_text(value: Any) -> Optional[str]:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _decode_json(raw: Optional[str]) -> Any:
        return SessionDB._decode_json_column(raw)

    def _row_to_mission(self, row: Any) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "created_by_session_id": row["created_by_session_id"],
            "approved_by_session_id": row["approved_by_session_id"],
            "activated_by_session_id": row["activated_by_session_id"],
            "metadata": self._decode_json(row["metadata_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "approved_at": row["approved_at"],
            "activated_at": row["activated_at"],
        }

    def _row_to_node(self, row: Any) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "mission_id": row["mission_id"],
            "parent_node_id": row["parent_node_id"],
            "external_id": row["external_id"],
            "node_type": row["node_type"],
            "title": row["title"],
            "body": row["body"],
            "status": row["status"],
            "position": row["position"],
            "metadata": self._decode_json(row["metadata_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _row_to_link(self, row: Any) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "mission_id": row["mission_id"],
            "source_node_id": row["source_node_id"],
            "target_node_id": row["target_node_id"],
            "link_type": row["link_type"],
            "metadata": self._decode_json(row["metadata_json"]),
            "created_at": row["created_at"],
        }

    def _row_to_handoff(self, row: Any) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "mission_id": row["mission_id"],
            "from_session_id": row["from_session_id"],
            "to_session_id": row["to_session_id"],
            "child_session_id": row["child_session_id"],
            "goal": row["goal"],
            "context": row["context"],
            "summary": row["summary"],
            "status": row["status"],
            "metadata": self._decode_json(row["metadata_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _row_to_checkpoint(self, row: Any) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "mission_id": row["mission_id"],
            "session_id": row["session_id"],
            "checkpoint_type": row["checkpoint_type"],
            "title": row["title"],
            "payload": self._decode_json(row["payload_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _ensure_session(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        self._require_db().ensure_session(session_id)

    def create_mission(
        self,
        *,
        title: str,
        description: str | None = None,
        created_by_session_id: str | None = None,
        metadata: Dict[str, Any] | None = None,
        mission_id: str | None = None,
    ) -> Dict[str, Any]:
        db = self._require_db()
        mission_title = self._clean_text(title, field="title")
        mission_description = self._clean_optional_text(description)
        mission_id = mission_id or self._new_id("mission")
        now = self._now()
        self._ensure_session(created_by_session_id)

        def _do(conn):
            conn.execute(
                """INSERT INTO missions (
                       id, title, description, status, created_by_session_id,
                       approved_by_session_id, activated_by_session_id, metadata_json,
                       created_at, updated_at, approved_at, activated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mission_id,
                    mission_title,
                    mission_description,
                    "draft",
                    created_by_session_id,
                    None,
                    None,
                    self._encode_json(metadata),
                    now,
                    now,
                    None,
                    None,
                ),
            )

        db._execute_write(_do)
        return self.get_mission(mission_id)

    def get_mission(self, mission_id: str) -> Optional[Dict[str, Any]]:
        db = self._require_db()
        with db._lock:
            row = db._conn.execute("SELECT * FROM missions WHERE id = ?", (mission_id,)).fetchone()
        return self._row_to_mission(row) if row else None

    def list_missions(self, *, status: str | None = None) -> List[Dict[str, Any]]:
        db = self._require_db()
        params: List[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        with db._lock:
            rows = db._conn.execute(
                f"SELECT * FROM missions {where} ORDER BY updated_at DESC, created_at DESC",
                params,
            ).fetchall()
        return [self._row_to_mission(row) for row in rows]

    def approve_mission(
        self,
        mission_id: str,
        *,
        approved_by_session_id: str | None = None,
    ) -> Dict[str, Any]:
        db = self._require_db()
        mission = self.get_mission(mission_id)
        if mission is None:
            raise ValueError(f"Unknown mission: {mission_id}")
        if mission["status"] in {"completed", "cancelled"}:
            raise ValueError("Completed or cancelled missions cannot be approved")
        if mission["status"] in {"approved", "active"}:
            return mission
        self._ensure_session(approved_by_session_id)
        now = self._now()

        def _do(conn):
            conn.execute(
                """UPDATE missions
                   SET status = ?, approved_by_session_id = ?, approved_at = ?, updated_at = ?
                   WHERE id = ?""",
                ("approved", approved_by_session_id, now, now, mission_id),
            )

        db._execute_write(_do)
        return self.get_mission(mission_id)

    def _require_mission(self, mission_id: str) -> Dict[str, Any]:
        mission = self.get_mission(mission_id)
        if mission is None:
            raise ValueError(f"Unknown mission: {mission_id}")
        return mission


    def get_attached_mission_id(self, session_id: str | None) -> Optional[str]:
        if not session_id:
            return None
        db = self._require_db()
        with db._lock:
            row = db._conn.execute(
                "SELECT attached_mission_id FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return row["attached_mission_id"] if row and row["attached_mission_id"] else None

    def get_attached_mission(self, session_id: str | None) -> Optional[Dict[str, Any]]:
        mission_id = self.get_attached_mission_id(session_id)
        return self.get_mission(mission_id) if mission_id else None

    def attach_session(self, session_id: str, mission_id: str) -> Dict[str, Any]:
        db = self._require_db()
        mission = self.get_mission(mission_id)
        if mission is None:
            raise ValueError(f"Unknown mission: {mission_id}")
        if mission["status"] not in {"approved", "active"}:
            raise PermissionError("Mission must be approved before activation")
        self._ensure_session(session_id)
        now = self._now()
        previous_mission_id = self.get_attached_mission_id(session_id)
        local_todos = self.get_session_local_todos(session_id)
        existing_mission_todos = self._list_task_nodes(mission_id)
        if local_todos and existing_mission_todos:
            raise ValueError(
                "Cannot attach a session with local todos to a mission that already has task nodes without an explicit merge"
            )

        def _do(conn):
            conn.execute(
                "UPDATE sessions SET attached_mission_id = ?, local_todo_state = NULL WHERE id = ?",
                (mission_id, session_id),
            )
            conn.execute(
                """UPDATE missions
                   SET status = ?, activated_at = COALESCE(activated_at, ?),
                       activated_by_session_id = COALESCE(activated_by_session_id, ?), updated_at = ?
                   WHERE id = ?""",
                ("active", now, session_id, now, mission_id),
            )
            if previous_mission_id and previous_mission_id != mission_id:
                remaining = conn.execute(
                    "SELECT 1 FROM sessions WHERE attached_mission_id = ? LIMIT 1",
                    (previous_mission_id,),
                ).fetchone()
                if remaining is None:
                    conn.execute(
                        "UPDATE missions SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                        ("approved", now, previous_mission_id, "active"),
                    )
            if local_todos:
                for position, todo in enumerate(self._dedupe_todo_items(local_todos)):
                    conn.execute(
                        """INSERT INTO mission_nodes (
                               id, mission_id, parent_node_id, external_id, node_type,
                               title, body, status, position, metadata_json, created_at, updated_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            self._new_id("node"),
                            mission_id,
                            None,
                            todo["id"],
                            "task",
                            todo["content"],
                            None,
                            todo["status"],
                            position,
                            None,
                            now,
                            now,
                        ),
                    )

        db._execute_write(_do)
        return self.get_mission(mission_id)

    def detach_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        db = self._require_db()
        attached_mission_id = self.get_attached_mission_id(session_id)
        if not attached_mission_id:
            return None
        now = self._now()
        mission_todos = self.get_todos_for_session(session_id)

        def _do(conn):
            conn.execute(
                "UPDATE sessions SET attached_mission_id = NULL, local_todo_state = ? WHERE id = ?",
                (self._encode_json(mission_todos), session_id),
            )
            remaining = conn.execute(
                "SELECT 1 FROM sessions WHERE attached_mission_id = ? LIMIT 1",
                (attached_mission_id,),
            ).fetchone()
            if remaining is None:
                conn.execute(
                    "UPDATE missions SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                    ("approved", now, attached_mission_id, "active"),
                )

        db._execute_write(_do)
        return self.get_mission(attached_mission_id)

    def copy_session_work_context(self, source_session_id: str, target_session_id: str) -> None:
        db = self._require_db()
        self._ensure_session(target_session_id)

        def _do(conn):
            source_row = conn.execute(
                "SELECT attached_mission_id, local_todo_state FROM sessions WHERE id = ?",
                (source_session_id,),
            ).fetchone()
            if source_row is None:
                raise ValueError(f"Unknown source session: {source_session_id}")
            target_row = conn.execute(
                "SELECT attached_mission_id FROM sessions WHERE id = ?",
                (target_session_id,),
            ).fetchone()
            previous_target_mission_id = target_row["attached_mission_id"] if target_row else None
            copied_mission_id = source_row["attached_mission_id"]
            conn.execute(
                "UPDATE sessions SET attached_mission_id = ?, local_todo_state = ? WHERE id = ?",
                (copied_mission_id, source_row["local_todo_state"], target_session_id),
            )
            if copied_mission_id:
                conn.execute(
                    "UPDATE missions SET status = ?, updated_at = ? WHERE id = ? AND status != ?",
                    ("active", self._now(), copied_mission_id, "cancelled"),
                )
                conn.execute(
                    "UPDATE sessions SET attached_mission_id = NULL WHERE id = ?",
                    (source_session_id,),
                )
            if previous_target_mission_id and previous_target_mission_id != copied_mission_id:
                remaining = conn.execute(
                    "SELECT 1 FROM sessions WHERE attached_mission_id = ? LIMIT 1",
                    (previous_target_mission_id,),
                ).fetchone()
                if remaining is None:
                    conn.execute(
                        "UPDATE missions SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                        ("approved", self._now(), previous_target_mission_id, "active"),
                    )

        db._execute_write(_do)

    def clone_session_work_context(self, source_session_id: str, target_session_id: str) -> None:
        db = self._require_db()
        self._ensure_session(target_session_id)

        def _do(conn):
            source_row = conn.execute(
                "SELECT attached_mission_id, local_todo_state FROM sessions WHERE id = ?",
                (source_session_id,),
            ).fetchone()
            if source_row is None:
                raise ValueError(f"Unknown source session: {source_session_id}")
            copied_mission_id = source_row["attached_mission_id"]
            conn.execute(
                "UPDATE sessions SET attached_mission_id = ?, local_todo_state = ? WHERE id = ?",
                (copied_mission_id, source_row["local_todo_state"], target_session_id),
            )
            if copied_mission_id:
                conn.execute(
                    "UPDATE missions SET status = ?, updated_at = ? WHERE id = ? AND status != ?",
                    ("active", self._now(), copied_mission_id, "cancelled"),
                )

        db._execute_write(_do)

    def detach_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        db = self._require_db()
        attached_mission_id = self.get_attached_mission_id(session_id)
        if not attached_mission_id:
            return None
        now = self._now()
        mission_todos = self.get_todos_for_session(session_id)
        existing_local_snapshot = self.get_session_local_todos(session_id)

        def _do(conn):
            replacement_local_state = existing_local_snapshot or mission_todos
            conn.execute(
                "UPDATE sessions SET attached_mission_id = NULL, local_todo_state = ? WHERE id = ?",
                (self._encode_json(replacement_local_state), session_id),
            )
            remaining = conn.execute(
                "SELECT 1 FROM sessions WHERE attached_mission_id = ? LIMIT 1",
                (attached_mission_id,),
            ).fetchone()
            if remaining is None:
                conn.execute(
                    "UPDATE missions SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                    ("approved", now, attached_mission_id, "active"),
                )

        db._execute_write(_do)
        return self.get_mission(attached_mission_id)

    def copy_session_work_context(self, source_session_id: str, target_session_id: str) -> None:
        db = self._require_db()
        self._ensure_session(target_session_id)

        def _do(conn):
            source_row = conn.execute(
                "SELECT attached_mission_id, local_todo_state FROM sessions WHERE id = ?",
                (source_session_id,),
            ).fetchone()
            if source_row is None:
                raise ValueError(f"Unknown source session: {source_session_id}")
            target_row = conn.execute(
                "SELECT attached_mission_id FROM sessions WHERE id = ?",
                (target_session_id,),
            ).fetchone()
            previous_target_mission_id = target_row["attached_mission_id"] if target_row else None
            copied_mission_id = source_row["attached_mission_id"]
            conn.execute(
                "UPDATE sessions SET attached_mission_id = ?, local_todo_state = ? WHERE id = ?",
                (copied_mission_id, source_row["local_todo_state"], target_session_id),
            )
            if copied_mission_id:
                conn.execute(
                    "UPDATE missions SET status = ?, updated_at = ? WHERE id = ? AND status != ?",
                    ("active", self._now(), copied_mission_id, "cancelled"),
                )
                conn.execute(
                    "UPDATE sessions SET attached_mission_id = NULL WHERE id = ?",
                    (source_session_id,),
                )
            if previous_target_mission_id and previous_target_mission_id != copied_mission_id:
                remaining = conn.execute(
                    "SELECT 1 FROM sessions WHERE attached_mission_id = ? LIMIT 1",
                    (previous_target_mission_id,),
                ).fetchone()
                if remaining is None:
                    conn.execute(
                        "UPDATE missions SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                        ("approved", self._now(), previous_target_mission_id, "active"),
                    )

        db._execute_write(_do)

    def get_session_local_todos(self, session_id: str | None) -> List[Dict[str, str]]:
        if not session_id:
            return []
        db = self._require_db()
        with db._lock:
            row = db._conn.execute(
                "SELECT local_todo_state FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        data = self._decode_json(row["local_todo_state"]) if row else None
        if not isinstance(data, list):
            return []
        return [self._normalize_todo_item(item) for item in data]

    def set_session_local_todos(self, session_id: str, todos: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        db = self._require_db()
        self._ensure_session(session_id)
        normalized = [self._normalize_todo_item(item) for item in todos]

        def _do(conn):
            conn.execute(
                "UPDATE sessions SET local_todo_state = ? WHERE id = ?",
                (self._encode_json(normalized), session_id),
            )

        db._execute_write(_do)
        return normalized

    @staticmethod
    def _normalize_todo_item(item: Dict[str, Any]) -> Dict[str, str]:
        item_id = str(item.get("id", "")).strip() or "?"
        content = str(item.get("content", "")).strip() or "(no description)"
        status = str(item.get("status", _DEFAULT_TODO_STATUS)).strip().lower()
        if status not in TODO_STATUSES:
            status = _DEFAULT_TODO_STATUS
        return {"id": item_id, "content": content, "status": status}

    @staticmethod
    def _dedupe_todo_items(todos: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        last_index: Dict[str, int] = {}
        normalized = [MissionService._normalize_todo_item(item) for item in todos]
        for index, item in enumerate(normalized):
            last_index[item["id"]] = index
        return [normalized[index] for index in sorted(last_index.values())]

    def create_node(
        self,
        *,
        mission_id: str,
        node_type: str,
        title: str,
        body: str | None = None,
        status: str = "pending",
        parent_node_id: str | None = None,
        external_id: str | None = None,
        position: int = 0,
        metadata: Dict[str, Any] | None = None,
        node_id: str | None = None,
    ) -> Dict[str, Any]:
        db = self._require_db()
        if node_type not in MISSION_NODE_TYPES:
            raise ValueError(f"Unsupported mission node type: {node_type}")
        if status not in MISSION_NODE_STATUSES and status not in TODO_STATUSES:
            raise ValueError(f"Unsupported mission node status: {status}")
        mission = self._require_mission(mission_id)
        if parent_node_id:
            parent = self.get_node(parent_node_id)
            if parent is None:
                raise ValueError(f"Unknown parent mission node: {parent_node_id}")
            if parent["mission_id"] != mission_id:
                raise ValueError("Parent mission node must belong to the same mission")
        node_id = node_id or self._new_id("node")
        now = self._now()

        def _do(conn):
            conn.execute(
                """INSERT INTO mission_nodes (
                       id, mission_id, parent_node_id, external_id, node_type,
                       title, body, status, position, metadata_json, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    node_id,
                    mission_id,
                    parent_node_id,
                    self._clean_optional_text(external_id),
                    node_type,
                    self._clean_text(title, field="title"),
                    self._clean_optional_text(body),
                    status,
                    int(position),
                    self._encode_json(metadata),
                    now,
                    now,
                ),
            )

        db._execute_write(_do)
        return self.get_node(node_id)

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        db = self._require_db()
        with db._lock:
            row = db._conn.execute("SELECT * FROM mission_nodes WHERE id = ?", (node_id,)).fetchone()
        return self._row_to_node(row) if row else None

    def list_nodes(self, mission_id: str, *, node_type: str | None = None) -> List[Dict[str, Any]]:
        db = self._require_db()
        self._require_mission(mission_id)
        where = "WHERE mission_id = ?"
        params: List[Any] = [mission_id]
        if node_type:
            where += " AND node_type = ?"
            params.append(node_type)
        with db._lock:
            rows = db._conn.execute(
                f"SELECT * FROM mission_nodes {where} ORDER BY position ASC, created_at ASC",
                params,
            ).fetchall()
        return [self._row_to_node(row) for row in rows]

    def update_node(self, node_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        db = self._require_db()
        current = self.get_node(node_id)
        if current is None:
            return None
        allowed = {
            "title": self._clean_optional_text,
            "body": self._clean_optional_text,
            "status": lambda value: value,
            "position": int,
            "metadata": lambda value: value,
            "external_id": self._clean_optional_text,
            "parent_node_id": self._clean_optional_text,
        }
        updates: List[str] = []
        params: List[Any] = []
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "status":
                if value not in MISSION_NODE_STATUSES and value not in TODO_STATUSES:
                    raise ValueError(f"Unsupported mission node status: {value}")
                updates.append("status = ?")
                params.append(value)
            elif key == "metadata":
                updates.append("metadata_json = ?")
                params.append(self._encode_json(value))
            elif key == "parent_node_id":
                parent_node_id = allowed[key](value)
                if parent_node_id:
                    parent = self.get_node(parent_node_id)
                    if parent is None:
                        raise ValueError(f"Unknown parent mission node: {parent_node_id}")
                    if parent["mission_id"] != current["mission_id"]:
                        raise ValueError("Parent mission node must belong to the same mission")
                updates.append("parent_node_id = ?")
                params.append(parent_node_id)
            else:
                updates.append(f"{key} = ?")
                params.append(allowed[key](value))
        if not updates:
            return current
        updates.append("updated_at = ?")
        params.append(self._now())
        params.append(node_id)

        def _do(conn):
            conn.execute(
                f"UPDATE mission_nodes SET {', '.join(updates)} WHERE id = ?",
                params,
            )

        db._execute_write(_do)
        return self.get_node(node_id)

    def delete_node(self, node_id: str) -> None:
        db = self._require_db()

        def _do(conn):
            conn.execute("DELETE FROM mission_nodes WHERE id = ?", (node_id,))

        db._execute_write(_do)

    def create_link(
        self,
        *,
        mission_id: str,
        source_node_id: str,
        target_node_id: str,
        link_type: str,
        metadata: Dict[str, Any] | None = None,
        link_id: str | None = None,
    ) -> Dict[str, Any]:
        self._require_mission(mission_id)
        source = self.get_node(source_node_id)
        if source is None:
            raise ValueError(f"Unknown source mission node: {source_node_id}")
        target = self.get_node(target_node_id)
        if target is None:
            raise ValueError(f"Unknown target mission node: {target_node_id}")
        if source["mission_id"] != mission_id or target["mission_id"] != mission_id:
            raise ValueError("Mission links must connect nodes from the same mission")
        db = self._require_db()
        if not str(link_type or "").strip():
            raise ValueError("link_type is required")
        link_id = link_id or self._new_id("link")
        now = self._now()

        def _do(conn):
            conn.execute(
                """INSERT INTO mission_links (
                       id, mission_id, source_node_id, target_node_id,
                       link_type, metadata_json, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    link_id,
                    mission_id,
                    source_node_id,
                    target_node_id,
                    str(link_type).strip(),
                    self._encode_json(metadata),
                    now,
                ),
            )

        db._execute_write(_do)
        return self.get_link(link_id)

    def get_link(self, link_id: str) -> Optional[Dict[str, Any]]:
        db = self._require_db()
        with db._lock:
            row = db._conn.execute("SELECT * FROM mission_links WHERE id = ?", (link_id,)).fetchone()
        return self._row_to_link(row) if row else None

    def list_links(self, mission_id: str) -> List[Dict[str, Any]]:
        db = self._require_db()
        self._require_mission(mission_id)
        with db._lock:
            rows = db._conn.execute(
                "SELECT * FROM mission_links WHERE mission_id = ? ORDER BY created_at ASC",
                (mission_id,),
            ).fetchall()
        return [self._row_to_link(row) for row in rows]

    def _list_task_nodes(self, mission_id: str) -> List[Dict[str, Any]]:
        return [node for node in self.list_nodes(mission_id, node_type="task") if node.get("external_id")]

    @staticmethod
    def _node_to_todo(node: Dict[str, Any]) -> Dict[str, str]:
        status = node["status"] if node["status"] in TODO_STATUSES else _DEFAULT_TODO_STATUS
        return {
            "id": node.get("external_id") or node["id"],
            "content": node["title"],
            "status": status,
        }

    def get_todos_for_session(self, session_id: str | None) -> List[Dict[str, str]]:
        mission_id = self.get_attached_mission_id(session_id)
        if mission_id:
            return [self._node_to_todo(node) for node in self._list_task_nodes(mission_id)]
        return self.get_session_local_todos(session_id)

    def write_todos_for_session(
        self,
        session_id: str,
        todos: List[Dict[str, Any]],
        *,
        merge: bool = False,
    ) -> List[Dict[str, str]]:
        db = self._require_db()
        mission_id = self.get_attached_mission_id(session_id)
        if not mission_id:
            raise ValueError("Session is not attached to an approved mission")
        normalized = self._dedupe_todo_items(todos)
        now = self._now()

        def _do(conn):
            rows = conn.execute(
                """SELECT id, external_id, title, status, position
                   FROM mission_nodes
                   WHERE mission_id = ? AND node_type = ?
                   ORDER BY position ASC, created_at ASC""",
                (mission_id, "task"),
            ).fetchall()
            existing = {row["external_id"]: row for row in rows if row["external_id"]}
            if merge:
                next_position = max((row["position"] for row in rows), default=-1) + 1
                for todo in normalized:
                    row = existing.get(todo["id"])
                    if row:
                        conn.execute(
                            """UPDATE mission_nodes
                               SET title = ?, status = ?, updated_at = ?
                               WHERE id = ?""",
                            (todo["content"], todo["status"], now, row["id"]),
                        )
                    else:
                        conn.execute(
                            """INSERT INTO mission_nodes (
                                   id, mission_id, parent_node_id, external_id, node_type,
                                   title, body, status, position, metadata_json, created_at, updated_at
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                self._new_id("node"),
                                mission_id,
                                None,
                                todo["id"],
                                "task",
                                todo["content"],
                                None,
                                todo["status"],
                                next_position,
                                None,
                                now,
                                now,
                            ),
                        )
                        next_position += 1
                return

            kept_ids = {todo["id"] for todo in normalized}
            for position, todo in enumerate(normalized):
                row = existing.get(todo["id"])
                if row:
                    conn.execute(
                        """UPDATE mission_nodes
                           SET title = ?, status = ?, position = ?, updated_at = ?
                           WHERE id = ?""",
                        (todo["content"], todo["status"], position, now, row["id"]),
                    )
                else:
                    conn.execute(
                        """INSERT INTO mission_nodes (
                               id, mission_id, parent_node_id, external_id, node_type,
                               title, body, status, position, metadata_json, created_at, updated_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            self._new_id("node"),
                            mission_id,
                            None,
                            todo["id"],
                            "task",
                            todo["content"],
                            None,
                            todo["status"],
                            position,
                            None,
                            now,
                            now,
                        ),
                    )
            stale_node_ids = [
                row["id"]
                for row in rows
                if row["external_id"] and row["external_id"] not in kept_ids
            ]
            if stale_node_ids:
                placeholders = ",".join("?" for _ in stale_node_ids)
                conn.execute(
                    f"DELETE FROM mission_nodes WHERE id IN ({placeholders})",
                    stale_node_ids,
                )

        db._execute_write(_do)
        return self.get_todos_for_session(session_id)

    def record_handoff_packet(
        self,
        *,
        mission_id: str,
        goal: str,
        from_session_id: str | None = None,
        to_session_id: str | None = None,
        child_session_id: str | None = None,
        context: str | None = None,
        summary: str | None = None,
        status: str = "completed",
        metadata: Dict[str, Any] | None = None,
        packet_id: str | None = None,
    ) -> Dict[str, Any]:
        self._require_mission(mission_id)
        db = self._require_db()
        packet_id = packet_id or self._new_id("handoff")
        now = self._now()
        self._ensure_session(from_session_id)
        self._ensure_session(to_session_id)
        self._ensure_session(child_session_id)

        def _do(conn):
            conn.execute(
                """INSERT INTO handoff_packets (
                       id, mission_id, from_session_id, to_session_id, child_session_id,
                       goal, context, summary, status, metadata_json, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    packet_id,
                    mission_id,
                    from_session_id,
                    to_session_id,
                    child_session_id,
                    self._clean_text(goal, field="goal"),
                    self._clean_optional_text(context),
                    self._clean_optional_text(summary),
                    str(status).strip() or "completed",
                    self._encode_json(metadata),
                    now,
                    now,
                ),
            )

        db._execute_write(_do)
        return self.get_handoff_packet(packet_id)

    def get_handoff_packet(self, packet_id: str) -> Optional[Dict[str, Any]]:
        db = self._require_db()
        with db._lock:
            row = db._conn.execute(
                "SELECT * FROM handoff_packets WHERE id = ?",
                (packet_id,),
            ).fetchone()
        return self._row_to_handoff(row) if row else None

    def list_handoff_packets(self, mission_id: str) -> List[Dict[str, Any]]:
        db = self._require_db()
        self._require_mission(mission_id)
        with db._lock:
            rows = db._conn.execute(
                "SELECT * FROM handoff_packets WHERE mission_id = ? ORDER BY created_at ASC",
                (mission_id,),
            ).fetchall()
        return [self._row_to_handoff(row) for row in rows]

    def record_checkpoint(
        self,
        *,
        mission_id: str,
        checkpoint_type: str,
        session_id: str | None = None,
        title: str | None = None,
        payload: Dict[str, Any] | List[Any] | str | None = None,
        checkpoint_id: str | None = None,
    ) -> Dict[str, Any]:
        self._require_mission(mission_id)
        db = self._require_db()
        checkpoint_id = checkpoint_id or self._new_id("checkpoint")
        now = self._now()
        self._ensure_session(session_id)
        def _do(conn):
            conn.execute(
                """INSERT INTO mission_checkpoints (
                       id, mission_id, session_id, checkpoint_type, title,
                       payload_json, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    checkpoint_id,
                    mission_id,
                    session_id,
                    self._clean_text(checkpoint_type, field="checkpoint_type"),
                    self._clean_optional_text(title),
                    self._encode_json(payload),
                    now,
                    now,
                ),
            )

        db._execute_write(_do)
        return self.get_checkpoint(checkpoint_id)

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Dict[str, Any]]:
        db = self._require_db()
        with db._lock:
            row = db._conn.execute(
                "SELECT * FROM mission_checkpoints WHERE id = ?",
                (checkpoint_id,),
            ).fetchone()
        return self._row_to_checkpoint(row) if row else None

    def list_checkpoints(
        self,
        mission_id: str,
        *,
        checkpoint_type: str | None = None,
    ) -> List[Dict[str, Any]]:
        db = self._require_db()
        self._require_mission(mission_id)
        where = "WHERE mission_id = ?"
        params: List[Any] = [mission_id]
        if checkpoint_type:
            where += " AND checkpoint_type = ?"
            params.append(checkpoint_type)
        with db._lock:
            rows = db._conn.execute(
                f"SELECT * FROM mission_checkpoints {where} ORDER BY created_at ASC",
                params,
            ).fetchall()
        return [self._row_to_checkpoint(row) for row in rows]

    def build_bundle(self, mission_id: str) -> Dict[str, Any]:
        mission = self.get_mission(mission_id)
        if mission is None:
            raise ValueError(f"Unknown mission: {mission_id}")
        return {
            "mission": mission,
            "nodes": self.list_nodes(mission_id),
            "links": self.list_links(mission_id),
            "handoffs": self.list_handoff_packets(mission_id),
            "checkpoints": self.list_checkpoints(mission_id),
        }
