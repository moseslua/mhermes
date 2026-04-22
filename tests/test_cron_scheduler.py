"""Tests for hmaom.cron.scheduler.CronScheduler."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from hmaom.cron.scheduler import CronScheduler


@pytest.fixture
def mock_router():
    return AsyncMock(return_value={"result": "ok"})


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "cron.sqlite")


@pytest.fixture
def scheduler(mock_router, tmp_db):
    return CronScheduler(router=mock_router, db_path=tmp_db, tick_interval=0.05)


class TestJobLifecycle:
    def test_add_job(self, scheduler):
        job = scheduler.add_job("job-1", "every 10 seconds", "hello")
        assert job["job_id"] == "job-1"
        assert job["schedule_cron"] == "every 10 seconds"
        assert job["user_input"] == "hello"
        assert job["session_id"] is None
        assert job["max_depth"] == 3
        assert job["last_run"] is None
        assert job["next_run"] > time.time()

    def test_add_job_with_session_and_depth(self, scheduler):
        job = scheduler.add_job(
            "job-2", "every 5 minutes", "query", session_id="sess-1", max_depth=2
        )
        assert job["session_id"] == "sess-1"
        assert job["max_depth"] == 2

    def test_add_duplicate_raises(self, scheduler):
        scheduler.add_job("dup", "every 10 seconds", "hello")
        with pytest.raises(ValueError, match="already exists"):
            scheduler.add_job("dup", "every 10 seconds", "hello")

    def test_remove_job(self, scheduler):
        scheduler.add_job("rem", "every 10 seconds", "hello")
        assert scheduler.remove_job("rem") is True
        assert scheduler.remove_job("rem") is False
        assert scheduler.list_jobs() == []

    def test_list_jobs(self, scheduler):
        scheduler.add_job("a", "every 10 seconds", "hello")
        scheduler.add_job("b", "every 20 seconds", "world")
        jobs = scheduler.list_jobs()
        assert len(jobs) == 2
        assert {j["job_id"] for j in jobs} == {"a", "b"}


class TestCronParsing:
    def test_every_seconds(self, scheduler):
        ts = scheduler._compute_next_run("every 30 seconds", time.time())
        assert ts > time.time()
        assert ts <= time.time() + 31

    def test_every_minutes(self, scheduler):
        now = time.time()
        ts = scheduler._compute_next_run("every 5 minutes", now)
        delta = ts - now
        assert 299 <= delta <= 301

    def test_every_hours(self, scheduler):
        now = time.time()
        ts = scheduler._compute_next_run("every 2 hours", now)
        delta = ts - now
        assert 7199 <= delta <= 7201

    def test_daily_at_future(self, scheduler):
        # Pick a time far in the future today
        future = datetime.now() + timedelta(hours=2)
        expr = f"daily at {future.hour:02d}:{future.minute:02d}"
        ts = scheduler._compute_next_run(expr, time.time())
        expected = future.replace(second=0, microsecond=0)
        assert abs(ts - expected.timestamp()) < 1

    def test_daily_at_past_rolls_to_tomorrow(self, scheduler):
        past = datetime.now() - timedelta(hours=2)
        expr = f"daily at {past.hour:02d}:{past.minute:02d}"
        ts = scheduler._compute_next_run(expr, time.time())
        expected = past.replace(second=0, microsecond=0) + timedelta(days=1)
        assert abs(ts - expected.timestamp()) < 1

    def test_invalid_expression_raises(self, scheduler):
        with pytest.raises(ValueError, match="Unsupported"):
            scheduler._compute_next_run("some weird thing")


class TestTickAndRun:
    @pytest.mark.asyncio
    async def test_tick_fires_overdue_job(self, scheduler, mock_router):
        scheduler.add_job("fire", "every 10 seconds", "do it")
        # Force next_run into the past
        scheduler._jobs["fire"]["next_run"] = time.time() - 1
        fired = await scheduler.tick()
        assert len(fired) == 1
        assert fired[0]["job_id"] == "fire"
        mock_router.route.assert_awaited_once_with(user_input="do it", session_id=None)

    @pytest.mark.asyncio
    async def test_tick_does_not_fire_future_job(self, scheduler, mock_router):
        scheduler.add_job("wait", "every 3600 seconds", "do it later")
        fired = await scheduler.tick()
        assert fired == []
        mock_router.route.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_job_updates_last_run_and_next_run(self, scheduler):
        scheduler.add_job("run", "every 10 seconds", "task")
        before = time.time()
        await scheduler.run_job("run")
        after = time.time()
        job = scheduler._jobs["run"]
        assert job["last_run"] is not None
        assert before <= job["last_run"] <= after
        assert job["next_run"] > after

    @pytest.mark.asyncio
    async def test_run_job_not_found_raises(self, scheduler):
        with pytest.raises(ValueError, match="not found"):
            await scheduler.run_job("missing")

    @pytest.mark.asyncio
    async def test_run_job_passes_session_id(self, scheduler, mock_router):
        scheduler.add_job("sess", "every 10 seconds", "hi", session_id="abc")
        await scheduler.run_job("sess")
        mock_router.route.assert_awaited_once_with(user_input="hi", session_id="abc")


class TestPersistence:
    def test_jobs_survive_recreation(self, mock_router, tmp_db):
        s1 = CronScheduler(router=mock_router, db_path=tmp_db, tick_interval=1.0)
        s1.add_job("persist", "every 60 seconds", "keep me")
        s1.remove_job("persist")
        s1.add_job("persist", "every 60 seconds", "keep me")

        s2 = CronScheduler(router=mock_router, db_path=tmp_db, tick_interval=1.0)
        jobs = s2.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["job_id"] == "persist"
        assert jobs[0]["user_input"] == "keep me"

    def test_db_schema_created(self, tmp_db):
        s = CronScheduler(router=AsyncMock(), db_path=tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        assert ("cron_jobs",) in tables


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_stop(self, scheduler, mock_router):
        scheduler.add_job("loop", "every 1 seconds", "ping")
        scheduler._jobs["loop"]["next_run"] = time.time() - 0.1
        scheduler.start()
        assert scheduler._running is True
        await asyncio.sleep(0.15)
        scheduler.stop()
        assert scheduler._running is False
        assert mock_router.route.await_count >= 1

    def test_stop_is_idempotent(self, scheduler):
        scheduler.stop()
        scheduler.stop()
        assert scheduler._running is False

    def test_start_is_idempotent(self, scheduler):
        scheduler.start()
        first_task = scheduler._task
        scheduler.start()
        assert scheduler._task is first_task
        scheduler.stop()
