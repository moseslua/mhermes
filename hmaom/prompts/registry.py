"""HMAOM Prompt Registry.

SQLite-backed versioned prompt storage with per-version performance tracking.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class PromptVersion:
    """A single version of a named prompt."""

    id: int
    name: str
    version: int
    content: str
    domain: str
    created_at: float
    is_active: bool
    metadata_json: Optional[str] = None


class PromptRegistry:
    """SQLite-backed registry for versioned prompts.

    Thread-safe for concurrent reads/writes.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or str(Path.home() / ".hmaom" / "state" / "prompt_registry.sqlite")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prompts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT,
                    UNIQUE(name, domain, version)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prompt_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt_id INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(prompt_id) REFERENCES prompts(id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_prompts_name_domain
                ON prompts(name, domain)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_outcomes_prompt_id
                ON prompt_outcomes(prompt_id)
                """
            )
            conn.commit()

    def register(
        self,
        name: str,
        domain: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> PromptVersion:
        """Register a new prompt version (auto-increment version number)."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT MAX(version) FROM prompts WHERE name = ? AND domain = ?",
                    (name, domain),
                ).fetchone()
                next_version = (row[0] or 0) + 1
                created_at = time.time()
                metadata_json = json.dumps(metadata) if metadata is not None else None
                cursor = conn.execute(
                    """
                    INSERT INTO prompts (name, domain, version, content, created_at, is_active, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (name, domain, next_version, content, created_at, 0, metadata_json),
                )
                conn.commit()
                return PromptVersion(
                    id=cursor.lastrowid,
                    name=name,
                    version=next_version,
                    content=content,
                    domain=domain,
                    created_at=created_at,
                    is_active=False,
                    metadata_json=metadata_json,
                )

    def get_active(self, name: str, domain: str) -> Optional[str]:
        """Return the content of the currently active prompt version."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT content FROM prompts WHERE name = ? AND domain = ? AND is_active = 1",
                    (name, domain),
                ).fetchone()
                return row[0] if row else None

    def set_active(self, name: str, domain: str, version_id: int) -> None:
        """Activate a specific prompt version (deactivates others)."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE prompts SET is_active = 0 WHERE name = ? AND domain = ?",
                    (name, domain),
                )
                conn.execute(
                    "UPDATE prompts SET is_active = 1 WHERE id = ? AND name = ? AND domain = ?",
                    (version_id, name, domain),
                )
                conn.commit()

    def list_versions(self, name: str, domain: str) -> list[dict[str, Any]]:
        """Return all versions with aggregate performance stats."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT
                        p.id,
                        p.name,
                        p.domain,
                        p.version,
                        p.content,
                        p.created_at,
                        p.is_active,
                        p.metadata_json,
                        COUNT(o.id) AS total_outcomes,
                        SUM(CASE WHEN o.success = 1 THEN 1 ELSE 0 END) AS success_count,
                        SUM(o.tokens_used) AS total_tokens,
                        AVG(o.latency_ms) AS avg_latency_ms
                    FROM prompts p
                    LEFT JOIN prompt_outcomes o ON o.prompt_id = p.id
                    WHERE p.name = ? AND p.domain = ?
                    GROUP BY p.id
                    ORDER BY p.version DESC
                    """,
                    (name, domain),
                ).fetchall()
                return [dict(row) for row in rows]

    def get_version(self, name: str, domain: str, version: int) -> Optional[PromptVersion]:
        """Return a specific prompt version."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT id, name, version, content, domain, created_at, is_active, metadata_json "
                    "FROM prompts WHERE name = ? AND domain = ? AND version = ?",
                    (name, domain, version),
                ).fetchone()
                if row is None:
                    return None
                return PromptVersion(
                    id=row[0],
                    name=row[1],
                    version=row[2],
                    content=row[3],
                    domain=row[4],
                    created_at=row[5],
                    is_active=bool(row[6]),
                    metadata_json=row[7],
                )

    def record_outcome(
        self,
        name: str,
        domain: str,
        version: int,
        success: bool,
        tokens_used: int = 0,
        latency_ms: int = 0,
    ) -> None:
        """Record a performance outcome for a prompt version."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT id FROM prompts WHERE name = ? AND domain = ? AND version = ?",
                    (name, domain, version),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Prompt version not found: {name}/{domain} v{version}")
                prompt_id = row[0]
                conn.execute(
                    """
                    INSERT INTO prompt_outcomes (prompt_id, success, tokens_used, latency_ms, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (prompt_id, 1 if success else 0, tokens_used, latency_ms, time.time()),
                )
                conn.commit()

    def get_stats(self, name: str, domain: str, version: int) -> dict[str, Any]:
        """Return aggregate performance stats for a prompt version."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT
                        COUNT(o.id) AS total_outcomes,
                        SUM(CASE WHEN o.success = 1 THEN 1 ELSE 0 END) AS success_count,
                        SUM(o.tokens_used) AS total_tokens,
                        AVG(o.latency_ms) AS avg_latency_ms
                    FROM prompts p
                    LEFT JOIN prompt_outcomes o ON o.prompt_id = p.id
                    WHERE p.name = ? AND p.domain = ? AND p.version = ?
                    """,
                    (name, domain, version),
                ).fetchone()
                if row is None:
                    return {
                        "total_outcomes": 0,
                        "success_count": 0,
                        "success_rate": 0.0,
                        "total_tokens": 0,
                        "avg_latency_ms": 0.0,
                    }
                total = row["total_outcomes"] or 0
                success = row["success_count"] or 0
                return {
                    "total_outcomes": total,
                    "success_count": success,
                    "success_rate": success / total if total > 0 else 0.0,
                    "total_tokens": row["total_tokens"] or 0,
                    "avg_latency_ms": row["avg_latency_ms"] or 0.0,
                }
