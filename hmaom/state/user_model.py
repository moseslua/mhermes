"""HMAOM user model for tracking session-level preferences and routing patterns.

Lightweight SQLite-backed storage with Pydantic validation.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class UserPreference(BaseModel):
    """Session-level user preferences and routing statistics."""

    user_id: str
    preferred_domains: list[str] = Field(default_factory=list)
    domain_success_rates: dict[str, float] = Field(default_factory=dict)
    preferred_output_format: str = "markdown"
    created_at: float = 0.0
    last_active: float = 0.0
    total_interactions: int = 0
    average_confidence: float = 0.0


class UserModel:
    """SQLite-backed user preference and routing pattern tracker.

    Thread-safe for concurrent access via connection-per-call pattern.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            db_path = str(Path.home() / ".hmaom" / "state" / "user_model.sqlite")
        self._db_path = db_path
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id TEXT PRIMARY KEY,
                    preferred_domains TEXT,
                    domain_success_rates TEXT,
                    preferred_output_format TEXT DEFAULT 'markdown',
                    created_at REAL,
                    last_active REAL,
                    total_interactions INTEGER DEFAULT 0,
                    average_confidence REAL DEFAULT 0.0
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_last_active
                ON user_preferences(last_active)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_outcomes (
                    user_id TEXT,
                    domain TEXT,
                    model TEXT,
                    success_count INTEGER DEFAULT 0,
                    total_count INTEGER DEFAULT 0,
                    success_rate REAL DEFAULT 0.0,
                    last_updated REAL,
                    PRIMARY KEY (user_id, domain, model)
                )
                """
            )

            conn.commit()

    def _row_to_preference(self, row: sqlite3.Row) -> UserPreference:
        return UserPreference(
            user_id=row["user_id"],
            preferred_domains=json.loads(row["preferred_domains"]) if row["preferred_domains"] else [],
            domain_success_rates=json.loads(row["domain_success_rates"]) if row["domain_success_rates"] else {},
            preferred_output_format=row["preferred_output_format"] or "markdown",
            created_at=row["created_at"] or 0.0,
            last_active=row["last_active"] or 0.0,
            total_interactions=row["total_interactions"] or 0,
            average_confidence=row["average_confidence"] or 0.0,
        )

    def get_or_create(self, user_id: str) -> UserPreference:
        """Fetch existing user or create a new preference record."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM user_preferences WHERE user_id = ?",
                (user_id,),
            ).fetchone()

            if row is not None:
                return self._row_to_preference(row)

            now = time.time()
            pref = UserPreference(
                user_id=user_id,
                created_at=now,
                last_active=now,
            )
            conn.execute(
                """
                INSERT INTO user_preferences
                (user_id, preferred_domains, domain_success_rates, preferred_output_format,
                 created_at, last_active, total_interactions, average_confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pref.user_id,
                    json.dumps(pref.preferred_domains),
                    json.dumps(pref.domain_success_rates),
                    pref.preferred_output_format,
                    pref.created_at,
                    pref.last_active,
                    pref.total_interactions,
                    pref.average_confidence,
                ),
            )
            conn.commit()
            return pref

    def record_interaction(
        self,
        user_id: str,
        domain: str,
        confidence: float,
        success: bool,
    ) -> None:
        """Record an interaction and update per-domain and aggregate stats."""
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM user_preferences WHERE user_id = ?",
                (user_id,),
            ).fetchone()

            if row is not None:
                pref = self._row_to_preference(row)
            else:
                now = time.time()
                pref = UserPreference(user_id=user_id, created_at=now, last_active=now)
                conn.execute(
                    """
                    INSERT INTO user_preferences
                    (user_id, preferred_domains, domain_success_rates, preferred_output_format,
                     created_at, last_active, total_interactions, average_confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pref.user_id,
                        json.dumps(pref.preferred_domains),
                        json.dumps(pref.domain_success_rates),
                        pref.preferred_output_format,
                        pref.created_at,
                        pref.last_active,
                        pref.total_interactions,
                        pref.average_confidence,
                    ),
                )

            # Update domain list if new
            if domain not in pref.preferred_domains:
                pref.preferred_domains.append(domain)

            # Update domain success rate with exponential moving average (alpha=0.3)
            current_rate = pref.domain_success_rates.get(domain, 0.5)
            alpha = 0.3
            new_rate = current_rate + alpha * ((1.0 if success else 0.0) - current_rate)
            pref.domain_success_rates[domain] = round(new_rate, 4)

            # Update aggregate confidence with rolling average
            total = pref.total_interactions
            pref.average_confidence = (
                (pref.average_confidence * total + confidence) / (total + 1)
                if total > 0
                else confidence
            )
            pref.total_interactions = total + 1
            pref.last_active = time.time()

            conn.execute(
                """
                UPDATE user_preferences SET
                    preferred_domains = ?,
                    domain_success_rates = ?,
                    last_active = ?,
                    total_interactions = ?,
                    average_confidence = ?
                WHERE user_id = ?
                """,
                (
                    json.dumps(pref.preferred_domains),
                    json.dumps(pref.domain_success_rates),
                    pref.last_active,
                    pref.total_interactions,
                    pref.average_confidence,
                    user_id,
                ),
            )
            conn.commit()
    def get_preferred_domains(self, user_id: str, top_n: int = 3) -> list[str]:
        """Return top N domains by success rate."""
        pref = self.get_or_create(user_id)
        if not pref.domain_success_rates:
            return []
        sorted_domains = sorted(
            pref.domain_success_rates.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return [domain for domain, _ in sorted_domains[:top_n]]

    def suggest_routing_mode(self, user_id: str, task_description: str) -> str:
        """Suggest 'single', 'parallel', or 'sequential' based on user history and task."""
        pref = self.get_or_create(user_id)
        desc_lower = task_description.lower()

        # Task keyword heuristics
        parallel_keywords = {"compare", "and", "versus", "vs", "multiple", "all", "both", "aggregate"}
        sequential_keywords = {"then", "after", "first", "next", "finally", "step", "pipeline", "chain"}

        has_parallel = any(kw in desc_lower for kw in parallel_keywords)
        has_sequential = any(kw in desc_lower for kw in sequential_keywords)

        # If user has few interactions, keep it simple
        if pref.total_interactions < 3:
            if has_parallel:
                return "parallel"
            if has_sequential:
                return "sequential"
            return "single"

        # Count successful domains (success rate > 0.5)
        successful_domains = [
            d for d, rate in pref.domain_success_rates.items() if rate > 0.5
        ]

        # Multi-domain user with parallel cues
        if len(successful_domains) >= 2 and has_parallel:
            return "parallel"

        # Multi-domain user with sequential cues
        if len(successful_domains) >= 2 and has_sequential:
            return "sequential"

        # Multi-domain user without strong cues — default to parallel for variety
        if len(successful_domains) >= 2 and pref.total_interactions > 5:
            return "parallel"

        if has_sequential:
            return "sequential"

        return "single"

    def get_all_users(self) -> list[str]:
        """Return all tracked user IDs."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT user_id FROM user_preferences ORDER BY last_active DESC"
            ).fetchall()
            return [row["user_id"] for row in rows]

    def prune_inactive(self, days: int = 30) -> int:
        """Remove users inactive longer than N days. Returns deleted count."""
        cutoff = time.time() - (days * 86400)
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM user_preferences WHERE last_active < ?",
                (cutoff,),
            )
            conn.commit()
            return cursor.rowcount


    def get_model_success_rate(self, user_id: str, domain: str, model: str) -> float:
        """Return the per-domain per-model success rate for a user."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT success_rate FROM model_outcomes WHERE user_id = ? AND domain = ? AND model = ?",
                (user_id, domain, model),
            ).fetchone()
            return float(row["success_rate"]) if row else 0.0

    def record_model_outcome(
        self, user_id: str, domain: str, model: str, success: bool
    ) -> None:
        """Record a model outcome and update its success rate via EMA (alpha=0.3)."""
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT success_count, total_count, success_rate FROM model_outcomes WHERE user_id = ? AND domain = ? AND model = ?",
                (user_id, domain, model),
            ).fetchone()

            alpha = 0.3
            now = time.time()
            if row is not None:
                current_rate = float(row["success_rate"])
                new_rate = current_rate + alpha * ((1.0 if success else 0.0) - current_rate)
                conn.execute(
                    """UPDATE model_outcomes SET
                        success_count = success_count + ?,
                        total_count = total_count + 1,
                        success_rate = ?,
                        last_updated = ?
                    WHERE user_id = ? AND domain = ? AND model = ?""",
                    (1 if success else 0, round(new_rate, 4), now, user_id, domain, model),
                )
            else:
                # EMA starting from 0.5
                initial_rate = 0.5 + alpha * ((1.0 if success else 0.0) - 0.5)
                conn.execute(
                    """INSERT INTO model_outcomes
                        (user_id, domain, model, success_count, total_count, success_rate, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, domain, model, 1 if success else 0, 1, round(initial_rate, 4), now),
                )
            conn.commit()

    def close(self) -> None:
        """No-op — connections are short-lived. Kept for API symmetry."""
        pass
