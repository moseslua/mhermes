"""HMAOM Specialist Hire persistence layer.

SQLite-backed storage for routing observations and hire decisions.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class HireObservation:
    """A single routing observation."""

    id: int = 0
    timestamp: float = 0.0
    user_input: str = ""
    routing_decision: str = ""
    specialist_used: str = ""
    result_status: str = ""


@dataclass
class HireDecision:
    """A recorded hire decision."""

    id: int = 0
    specialist_name: str = ""
    domain: str = ""
    created_at: float = 0.0
    reason: str = ""
    config_json: str = ""


class HirePersistence:
    """SQLite persistence for hire observations and decisions.

    Tables:
    - hire_observations: every routing decision observed
    - hire_decisions: persisted auto-hire outcomes
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            db_path = str(Path.home() / ".hmaom" / "state" / "hire.sqlite")
        self._db_path = db_path
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hire_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    user_input TEXT NOT NULL,
                    routing_decision TEXT NOT NULL,
                    specialist_used TEXT NOT NULL,
                    result_status TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_obs_time
                ON hire_observations(timestamp)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hire_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    specialist_name TEXT NOT NULL UNIQUE,
                    domain TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL,
                    reason TEXT NOT NULL,
                    config_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def log_observation(
        self,
        user_input: str,
        routing_decision: dict[str, Any],
        specialist_used: str,
        result_status: str,
    ) -> int:
        """Log a routing observation. Returns the inserted row id."""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO hire_observations
                (timestamp, user_input, routing_decision, specialist_used, result_status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    user_input,
                    json.dumps(routing_decision),
                    specialist_used,
                    result_status,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def get_observations(
        self,
        since: Optional[float] = None,
        limit: int = 1000,
    ) -> list[HireObservation]:
        """Fetch observations, optionally since a given timestamp."""
        if since is None:
            since = 0.0
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, user_input, routing_decision, specialist_used, result_status
                FROM hire_observations
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (since, limit),
            ).fetchall()
        return [self._row_to_observation(row) for row in rows]

    def get_observation_count(self, since: float) -> int:
        """Count observations since a given timestamp."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM hire_observations WHERE timestamp >= ?",
                (since,),
            ).fetchone()
            return row[0] if row else 0

    def log_decision(
        self,
        specialist_name: str,
        domain: str,
        reason: str,
        config_json: str,
    ) -> int:
        """Persist a hire decision. Returns the inserted row id."""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO hire_decisions
                (specialist_name, domain, created_at, reason, config_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (specialist_name, domain, time.time(), reason, config_json),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def get_decisions(self) -> list[HireDecision]:
        """Fetch all hire decisions."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT id, specialist_name, domain, created_at, reason, config_json
                FROM hire_decisions
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [self._row_to_decision(row) for row in rows]

    def get_decision_by_domain(self, domain: str) -> Optional[HireDecision]:
        """Fetch a hire decision by domain."""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id, specialist_name, domain, created_at, reason, config_json
                FROM hire_decisions
                WHERE domain = ?
                """,
                (domain,),
            ).fetchone()
        return self._row_to_decision(row) if row else None

    @staticmethod
    def _row_to_observation(row: sqlite3.Row) -> HireObservation:
        return HireObservation(
            id=row["id"],
            timestamp=row["timestamp"],
            user_input=row["user_input"],
            routing_decision=row["routing_decision"],
            specialist_used=row["specialist_used"],
            result_status=row["result_status"],
        )

    @staticmethod
    def _row_to_decision(row: sqlite3.Row) -> HireDecision:
        return HireDecision(
            id=row["id"],
            specialist_name=row["specialist_name"],
            domain=row["domain"],
            created_at=row["created_at"],
            reason=row["reason"],
            config_json=row["config_json"],
        )
