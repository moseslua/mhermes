"""HMAOM Cron Scheduler.

Lightweight periodic scheduler with SQLite persistence.
Supports simple expressions: ``every N seconds/minutes/hours``
and ``daily at HH:MM``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CronScheduler:
    """Schedule and run recurring jobs through the gateway router.

    Jobs are persisted to SQLite so they survive restarts.
    """

    def __init__(
        self,
        router: Any,
        db_path: str | None = None,
        tick_interval: float = 1.0,
    ) -> None:
        self._router = router
        self._tick_interval = tick_interval
        self._jobs: dict[str, dict[str, Any]] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self._lock = threading.Lock()

        if db_path is None:
            db_path = str(Path.home() / ".hmaom" / "state" / "cron.sqlite")
        self._db_path = db_path
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._load_jobs()

    # ── Database ──

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cron_jobs (
                    job_id TEXT PRIMARY KEY,
                    schedule_cron TEXT NOT NULL,
                    user_input TEXT NOT NULL,
                    session_id TEXT,
                    max_depth INTEGER DEFAULT 3,
                    last_run REAL,
                    next_run REAL NOT NULL
                )
                """
            )
            conn.commit()

    def _load_jobs(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM cron_jobs").fetchall()
            for row in rows:
                job = dict(row)
                self._jobs[job["job_id"]] = job

    def _persist_job(self, job: dict[str, Any]) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cron_jobs
                (job_id, schedule_cron, user_input, session_id, max_depth, last_run, next_run)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job["job_id"],
                    job["schedule_cron"],
                    job["user_input"],
                    job.get("session_id"),
                    job.get("max_depth", 3),
                    job.get("last_run"),
                    job["next_run"],
                ),
            )
            conn.commit()

    async def _persist_job_async(self, job: dict[str, Any]) -> None:
        await asyncio.to_thread(self._persist_job, job)

    def _delete_job(self, job_id: str) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM cron_jobs WHERE job_id = ?", (job_id,))
            conn.commit()

    async def _delete_job_async(self, job_id: str) -> None:
        await asyncio.to_thread(self._delete_job, job_id)

    # ── Public API ──

    def add_job(
        self,
        job_id: str,
        cron_expr: str,
        user_input: str,
        session_id: str | None = None,
        max_depth: int = 3,
    ) -> dict[str, Any]:
        """Add a new scheduled job."""
        if job_id in self._jobs:
            raise ValueError(f"Job '{job_id}' already exists")

        next_run = self._compute_next_run(cron_expr)
        job = {
            "job_id": job_id,
            "schedule_cron": cron_expr,
            "user_input": user_input,
            "session_id": session_id,
            "max_depth": max_depth,
            "last_run": None,
            "next_run": next_run,
        }
        self._jobs[job_id] = job
        self._persist_job(job)
        return dict(job)

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job.  Returns True if the job existed."""
        if job_id not in self._jobs:
            return False
        del self._jobs[job_id]
        self._delete_job(job_id)
        return True

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return a snapshot of all registered jobs."""
        return [dict(j) for j in self._jobs.values()]

    def start(self) -> None:
        """Begin the background async tick loop."""
        if self._running:
            return
        self._running = True
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._tick_loop())

    def stop(self) -> None:
        """Stop the background tick loop."""
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None

    async def _tick_loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except Exception as e:
                logger.error(f"Tick failed: {e}", exc_info=True)
            await asyncio.sleep(self._tick_interval)

    async def tick(self) -> list[dict[str, Any]]:
        """Check all jobs and fire any whose next_run <= now.

        Returns the list of jobs that were triggered.
        """
        now = time.time()
        fired: list[dict[str, Any]] = []

        # Snapshot to avoid mutation during iteration
        jobs_snapshot = list(self._jobs.values())
        for job in jobs_snapshot:
            if job["next_run"] <= now:
                await self.run_job(job["job_id"])
                fired.append(dict(job))
        return fired

    async def run_job(self, job_id: str) -> dict[str, Any]:
        """Execute a single job by calling ``router.route()``.

        Updates *last_run* and recomputes *next_run*.
        """
        job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"Job '{job_id}' not found")

        now = time.time()
        job["last_run"] = now

        try:
            result = await self._router.route(
                user_input=job["user_input"],
                session_id=job.get("session_id"),
            )
        except Exception as exc:
            result = {"error": str(exc), "job_id": job_id}

        job["next_run"] = self._compute_next_run(job["schedule_cron"], now)
        await self._persist_job_async(job)
        return result

    # ── Cron parsing ──

    @staticmethod
    def _compute_next_run(cron_expr: str, anchor: float | None = None) -> float:
        """Parse a simple cron expression and return the next Unix timestamp."""
        expr = cron_expr.strip().lower()
        now = datetime.fromtimestamp(anchor if anchor is not None else time.time(), tz=timezone.utc)

        # every N seconds/minutes/hours
        m = re.match(r"every\s+(\d+)\s+(second|seconds|minute|minutes|hour|hours)", expr)
        if m:
            num = int(m.group(1))
            unit = m.group(2)
            if unit.startswith("second"):
                delta = timedelta(seconds=num)
            elif unit.startswith("minute"):
                delta = timedelta(minutes=num)
            else:
                delta = timedelta(hours=num)
            return (now + delta).timestamp()

        # daily at HH:MM
        m = re.match(r"daily\s+at\s+(\d{1,2}):(\d{2})", expr)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2))
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target.timestamp()

        raise ValueError(f"Unsupported cron expression: {cron_expr!r}")
