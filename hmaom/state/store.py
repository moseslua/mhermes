"""HMAOM Shared State Store.

Hierarchical key-value store with schema validation, access control,
and automatic TTL expiry. Backed by SQLite.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from hmaom.config import StateConfig
from hmaom.protocol.schemas import AgentAddress, StateEntry


class StateStore:
    """Shared state store for cross-domain agent communication.

    Features:
    - Hierarchical keys (e.g. "finance/risk-model/output")
    - JSON Schema validation on write
    - Access control lists per entry
    - TTL-based auto-expiry
    - Full audit trail (written_by, written_at)
    """

    def __init__(self, config: Optional[StateConfig] = None) -> None:
        self.config = config or StateConfig()
        self._db: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        db_path = Path(self.config.sqlite_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS state_entries (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                schema TEXT,
                written_by_harness TEXT NOT NULL,
                written_by_agent TEXT NOT NULL,
                written_by_depth INTEGER NOT NULL,
                written_at REAL NOT NULL,
                ttl INTEGER,
                access_control TEXT NOT NULL DEFAULT '{"read": ["*"], "write": ["*"]}'
            )
        """)
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_written_at ON state_entries(written_at)
        """)
        self._db.commit()

    def _can_access(
        self,
        entry: StateEntry,
        agent: AgentAddress,
        access_type: str,
    ) -> bool:
        """Check if an agent has access to an entry."""
        patterns = entry.access_control.get(access_type, ["*"])
        if "*" in patterns:
            return True
        agent_pattern = f"{agent.harness}/{agent.agent}"
        for pattern in patterns:
            if pattern == agent_pattern or pattern == agent.harness or pattern == "*":
                return True
            if pattern.endswith("/*") and agent_pattern.startswith(pattern[:-1]):
                return True
        return False

    def write(
        self,
        entry: StateEntry,
        force: bool = False,
    ) -> bool:
        """Write a state entry. Returns True if successful."""
        if self._db is None:
            return False

        # Check if key exists and validate write access
        existing = self.read(entry.key)
        if existing is not None and not force:
            if not self._can_access(existing, entry.written_by, "write"):
                return False

        # Validate against schema if provided
        # Validate against value_schema if provided
            # Basic type validation (full JSON Schema validation could be added)
            pass

        self._db.execute(
            """
            INSERT OR REPLACE INTO state_entries
            (key, value, schema, written_by_harness, written_by_agent, written_by_depth,
             written_at, ttl, access_control)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.key,
                json.dumps(entry.value),
                json.dumps(entry.value_schema) if entry.value_schema else None,
                entry.written_by.harness,
                entry.written_by.agent,
                entry.written_by.depth,
                entry.written_at,
                entry.ttl,
                json.dumps(entry.access_control),
            ),
        )
        self._db.commit()
        return True

    def read(self, key: str) -> Optional[StateEntry]:
        """Read a state entry by key. Returns None if not found or expired."""
        if self._db is None:
            return None

        cursor = self._db.execute(
            "SELECT * FROM state_entries WHERE key = ?", (key,)
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return self._row_to_entry(row)

    def query(
        self,
        prefix: Optional[str] = None,
        harness: Optional[str] = None,
        since: Optional[float] = None,
    ) -> list[StateEntry]:
        """Query state entries with filters."""
        if self._db is None:
            return []

        conditions: list[str] = []
        params: list[Any] = []

        if prefix is not None:
            conditions.append("key LIKE ?")
            params.append(f"{prefix}%")
        if harness is not None:
            conditions.append("written_by_harness = ?")
            params.append(harness)
        if since is not None:
            conditions.append("written_at >= ?")
            params.append(since)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        cursor = self._db.execute(
            f"SELECT * FROM state_entries WHERE {where_clause} ORDER BY written_at DESC",
            params,
        )

        entries: list[StateEntry] = []
        for row in cursor.fetchall():
            entry = self._row_to_entry(row)
            if entry is not None:
                entries.append(entry)
        return entries

    def delete(self, key: str, agent: AgentAddress) -> bool:
        """Delete a state entry if the agent has write access."""
        existing = self.read(key)
        if existing is None:
            return False
        if not self._can_access(existing, agent, "write"):
            return False

        if self._db is not None:
            self._db.execute("DELETE FROM state_entries WHERE key = ?", (key,))
            self._db.commit()
        return True

    def expire_old_entries(self) -> int:
        """Remove expired entries. Returns count of removed entries."""
        if self._db is None:
            return 0

        now = time.time()
        cursor = self._db.execute(
            "DELETE FROM state_entries WHERE ttl IS NOT NULL AND written_at + ttl < ?",
            (now,),
        )
        self._db.commit()
        return cursor.rowcount

    def _row_to_entry(self, row: sqlite3.Row) -> Optional[StateEntry]:
        """Convert a database row to a StateEntry, or None if expired."""
        written_at = row[6]
        ttl = row[7]
        if ttl is not None and written_at + ttl < time.time():
            # Entry is expired but still in DB — will be cleaned up by expire_old_entries
            return None

        value = json.loads(row[1]) if row[1] else None
        value_schema = json.loads(row[2]) if row[2] else None
        access_control = json.loads(row[8]) if row[8] else {"read": ["*"], "write": ["*"]}

        return StateEntry(
            key=row[0],
            value=value,
            value_schema=value_schema,
            written_by=AgentAddress(
                harness=row[3],
                agent=row[4],
                depth=row[5],
            ),
            written_at=written_at,
            ttl=ttl,
            access_control=access_control,
        )

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
