"""HMAOM Prompt Rollout Manager.

A/B testing and gradual promotion/rollback for prompt versions.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from typing import Any, Optional

from hmaom.prompts.registry import PromptRegistry


class PromptRolloutManager:
    """Manages gradual rollouts of prompt versions with A/B testing.

    Uses deterministic traffic splitting and automatic rollback
    when configured.
    """

    def __init__(self, registry: PromptRegistry, auto_rollback: bool = True) -> None:
        self.registry = registry
        self.auto_rollback = auto_rollback
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.registry.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rollouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    new_version_id INTEGER NOT NULL,
                    old_version_id INTEGER NOT NULL,
                    traffic_pct INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    started_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rollouts_name_domain
                ON rollouts(name, domain)
                """
            )
            conn.commit()

    def start_rollout(
        self,
        name: str,
        domain: str,
        new_version_id: int,
        traffic_pct: int = 10,
    ) -> dict[str, Any]:
        """Start a new rollout for a prompt version.

        Captures the currently active version as the old_version_id.
        """
        with self._lock:
            # Find the currently active version
            with sqlite3.connect(self.registry.db_path) as conn:
                row = conn.execute(
                    "SELECT id FROM prompts WHERE name = ? AND domain = ? AND is_active = 1",
                    (name, domain),
                ).fetchone()
                old_version_id = row[0] if row else new_version_id

                # Deactivate any existing rollout for this prompt
                conn.execute(
                    "UPDATE rollouts SET status = 'superseded' "
                    "WHERE name = ? AND domain = ? AND status = 'active'",
                    (name, domain),
                )

                conn.execute(
                    """
                    INSERT INTO rollouts (name, domain, new_version_id, old_version_id, traffic_pct, status, started_at)
                    VALUES (?, ?, ?, ?, ?, 'active', ?)
                    """,
                    (name, domain, new_version_id, old_version_id, traffic_pct, time.time()),
                )
                conn.commit()

            return {
                "name": name,
                "domain": domain,
                "new_version_id": new_version_id,
                "old_version_id": old_version_id,
                "traffic_pct": traffic_pct,
                "status": "active",
            }

    def _get_active_rollout(self, name: str, domain: str) -> Optional[dict[str, Any]]:
        with sqlite3.connect(self.registry.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM rollouts WHERE name = ? AND domain = ? AND status = 'active'",
                (name, domain),
            ).fetchone()
            return dict(row) if row else None

    def get_prompt_for_request(
        self,
        name: str,
        domain: str,
        request_hash: str,
    ) -> Optional[str]:
        """Return prompt content for a request using deterministic traffic split.

        Uses hash(request_hash) % 100 < traffic_pct for consistency.
        """
        with self._lock:
            rollout = self._get_active_rollout(name, domain)
            if rollout is None:
                return self.registry.get_active(name, domain)

            # Deterministic split using stable hash
            hash_int = int(hashlib.md5(str(request_hash).encode()).hexdigest(), 16)
            bucket = hash_int % 100

            if bucket < rollout["traffic_pct"]:
                # Return new version
                version = self.registry.get_version(
                    name, domain, rollout["new_version_id"]
                )
                if version is None:
                    # Fallback if new version missing
                    return self.registry.get_active(name, domain)
                return version.content
            else:
                # Return old/active version
                return self.registry.get_active(name, domain)

    def evaluate_rollout(
        self,
        name: str,
        domain: str,
        new_version_id: int,
        error_rate_threshold: float = 1.2,
    ) -> dict[str, Any]:
        """Compare stats between active (old) and new version.

        If auto_rollback is enabled and the new version is worse,
        automatically calls rollback.
        """
        with self._lock:
            rollout = self._get_active_rollout(name, domain)
            if rollout is None:
                return {"status": "no_active_rollout"}

            # Find version numbers for stats lookup
            with sqlite3.connect(self.registry.db_path) as conn:
                row_new = conn.execute(
                    "SELECT version FROM prompts WHERE id = ?",
                    (new_version_id,),
                ).fetchone()
                row_old = conn.execute(
                    "SELECT version FROM prompts WHERE id = ?",
                    (rollout["old_version_id"],),
                ).fetchone()

            if row_new is None or row_old is None:
                return {"status": "version_not_found"}

            new_version_num = row_new[0]
            old_version_num = row_old[0]

            new_stats = self.registry.get_stats(name, domain, new_version_num)
            old_stats = self.registry.get_stats(name, domain, old_version_num)

            new_error_rate = 1.0 - new_stats["success_rate"] if new_stats["total_outcomes"] > 0 else 0.0
            old_error_rate = 1.0 - old_stats["success_rate"] if old_stats["total_outcomes"] > 0 else 0.0

            result = {
                "status": "evaluated",
                "new_version_id": new_version_id,
                "old_version_id": rollout["old_version_id"],
                "new_stats": new_stats,
                "old_stats": old_stats,
                "new_error_rate": new_error_rate,
                "old_error_rate": old_error_rate,
                "threshold": error_rate_threshold,
                "auto_rollback_triggered": False,
            }

            # Auto-rollback if configured and new version is worse
            if self.auto_rollback and new_stats["total_outcomes"] > 0:
                if old_error_rate == 0.0:
                    # If old version had zero errors, any error from new is worse if > threshold
                    if new_error_rate > 0 and error_rate_threshold < 1.0:
                        pass  # Edge case; handle below with relative comparison
                    elif new_error_rate > 0:
                        self.rollback(name, domain)
                        result["status"] = "rolled_back"
                        result["auto_rollback_triggered"] = True
                        return result
                else:
                    if new_error_rate > old_error_rate * error_rate_threshold:
                        self.rollback(name, domain)
                        result["status"] = "rolled_back"
                        result["auto_rollback_triggered"] = True
                        return result

            return result

    def promote(self, name: str, domain: str, new_version_id: int) -> None:
        """Promote the new version to 100% traffic."""
        with self._lock:
            self.registry.set_active(name, domain, new_version_id)
            with sqlite3.connect(self.registry.db_path) as conn:
                conn.execute(
                    "UPDATE rollouts SET status = 'promoted' "
                    "WHERE name = ? AND domain = ? AND new_version_id = ? AND status = 'active'",
                    (name, domain, new_version_id),
                )
                conn.commit()

    def rollback(self, name: str, domain: str) -> None:
        """Revert to the previous active version."""
        with self._lock:
            with sqlite3.connect(self.registry.db_path) as conn:
                row = conn.execute(
                    "SELECT old_version_id, new_version_id FROM rollouts "
                    "WHERE name = ? AND domain = ? AND status != 'superseded' "
                    "ORDER BY started_at DESC LIMIT 1",
                    (name, domain),
                ).fetchone()
                if row is None:
                    raise ValueError(f"No active rollout for {name}/{domain}")
                old_version_id, new_version_id = row
                self.registry.set_active(name, domain, old_version_id)
                conn.execute(
                    "UPDATE rollouts SET status = 'rolled_back' "
                    "WHERE name = ? AND domain = ? AND new_version_id = ? AND status != 'superseded'",
                    (name, domain, new_version_id),
                )
                conn.commit()

    def can_promote(
        self,
        name: str,
        domain: str,
        new_version_id: int,
        min_samples: int = 100,
        error_rate_threshold: float = 1.2,
    ) -> bool:
        """Check if the new version is statistically better or within threshold."""
        with self._lock:
            rollout = self._get_active_rollout(name, domain)
            if rollout is None:
                return False

            with sqlite3.connect(self.registry.db_path) as conn:
                row_new = conn.execute(
                    "SELECT version FROM prompts WHERE id = ?",
                    (new_version_id,),
                ).fetchone()
                row_old = conn.execute(
                    "SELECT version FROM prompts WHERE id = ?",
                    (rollout["old_version_id"],),
                ).fetchone()

            if row_new is None or row_old is None:
                return False

            new_stats = self.registry.get_stats(name, domain, row_new[0])
            old_stats = self.registry.get_stats(name, domain, row_old[0])

            if new_stats["total_outcomes"] < min_samples:
                return False

            new_error_rate = 1.0 - new_stats["success_rate"]
            old_error_rate = 1.0 - old_stats["success_rate"]

            if old_stats["total_outcomes"] == 0:
                # Old version has no data; allow promotion if new has enough samples
                return True

            return new_error_rate <= old_error_rate * error_rate_threshold
