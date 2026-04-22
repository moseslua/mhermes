"""HMAOM Replay Engine.

Records routing snapshots and replays them later to detect regressions
in routing decisions or specialist outputs.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import TYPE_CHECKING, Any, Optional

from hmaom.protocol.schemas import RoutingDecision

if TYPE_CHECKING:
    from hmaom.gateway.router import GatewayRouter


class ReplayEngine:
    """SQLite-backed snapshot recorder and regression detector.

    Snapshots capture the user input, routing decision, and final result
    so they can be replayed through a :class:`GatewayRouter` later.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        # Keep a persistent connection for :memory: databases so that the
        # schema survives across individual method calls.
        self._conn: Optional[sqlite3.Connection] = None
        if db_path == ":memory:":
            self._conn = sqlite3.connect(db_path)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                correlation_id TEXT NOT NULL UNIQUE,
                user_input TEXT NOT NULL,
                routing_decision_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_correlation ON snapshots(correlation_id)"
        )
        conn.commit()

    def record(
        self,
        correlation_id: str,
        user_input: str,
        routing_decision: RoutingDecision,
        result: dict[str, Any],
    ) -> None:
        """Persist a snapshot of a completed request."""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO snapshots
            (correlation_id, user_input, routing_decision_json, result_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(correlation_id) DO UPDATE SET
                user_input=excluded.user_input,
                routing_decision_json=excluded.routing_decision_json,
                result_json=excluded.result_json,
                created_at=excluded.created_at
            """,
            (
                correlation_id,
                user_input,
                json.dumps(routing_decision.model_dump(), default=str),
                json.dumps(result, default=str),
                time.time(),
            ),
        )
        conn.commit()

    def _get_snapshot(self, correlation_id: str) -> Optional[dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT user_input, routing_decision_json, result_json FROM snapshots WHERE correlation_id = ?",
            (correlation_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "correlation_id": correlation_id,
            "user_input": row[0],
            "routing_decision": json.loads(row[1]),
            "result": json.loads(row[2]),
        }

    async def replay(
        self, correlation_id: str, router: "GatewayRouter"
    ) -> dict[str, Any]:
        """Re-run the saved input through *router* and compare outputs.

        Returns a dict with ``original``, ``replayed``, ``diff``, and
        ``regression`` keys.
        """
        original = self._get_snapshot(correlation_id)
        if original is None:
            return {
                "correlation_id": correlation_id,
                "error": f"No snapshot found for {correlation_id}",
            }

        replayed = await router.route(original["user_input"])
        diff = self.diff(original, replayed)
        return {
            "correlation_id": correlation_id,
            "original": original,
            "replayed": replayed,
            "diff": diff,
            "regression": bool(diff),
        }

    def diff(
        self, original: dict[str, Any], replayed: dict[str, Any]
    ) -> dict[str, Any]:
        """Compare *original* and *replayed* snapshots.

        Only compares ``routing_decision`` and ``result`` fields.
        Returns an empty dict when they match.
        """
        deltas: dict[str, Any] = {}

        orig_rd = original.get("routing_decision")
        replay_rd = replayed.get("routing_decision")
        if orig_rd != replay_rd:
            deltas["routing_decision"] = {
                "original": orig_rd,
                "replayed": replay_rd,
            }

        orig_res = original.get("result")
        replay_res = replayed.get("result")
        if orig_res != replay_res:
            deltas["result"] = {
                "original": orig_res,
                "replayed": replay_res,
            }

        return deltas

    async def regression_report(
        self, router: "GatewayRouter"
    ) -> list[dict[str, Any]]:
        """Replay every stored snapshot and return those that regressed."""
        regressions: list[dict[str, Any]] = []
        correlation_ids = self._list_correlation_ids()
        for cid in correlation_ids:
            report = await self.replay(cid, router)
            if report.get("regression"):
                regressions.append(report)
        return regressions

    def _list_correlation_ids(self) -> list[str]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT correlation_id FROM snapshots ORDER BY created_at"
        ).fetchall()
        return [r[0] for r in rows]

    def snapshot_count(self) -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()
        return row[0] if row else 0

    def clear(self) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM snapshots")
        conn.commit()
