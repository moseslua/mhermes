"""Tests for DedupTracker."""

import asyncio

import pytest

from hmaom.gateway.dedup import DedupTracker


class TestDedupTracker:
    def test_dedup_key_deterministic(self):
        tracker = DedupTracker()
        k1 = tracker.dedup_key("input", "session-1")
        k2 = tracker.dedup_key("input", "session-1")
        assert k1 == k2
        assert k1 != tracker.dedup_key("input", "session-2")

    def test_get_or_create_returns_same_future(self):
        tracker = DedupTracker()
        key = tracker.dedup_key("input", "session-1")
        f1 = tracker.get_or_create(key)
        f2 = tracker.get_or_create(key)
        assert f1 is f2
        assert tracker._size() == 1

    def test_resolve_sets_result(self):
        tracker = DedupTracker()
        key = tracker.dedup_key("input", "session-1")
        future = tracker.get_or_create(key)
        tracker.resolve(key, {"result": "ok"})
        assert future.result() == {"result": "ok"}

    def test_cleanup_removes_key(self):
        tracker = DedupTracker()
        key = tracker.dedup_key("input", "session-1")
        tracker.get_or_create(key)
        tracker.cleanup(key)
        assert tracker._size() == 0

    @pytest.mark.asyncio
    async def test_concurrent_dedup_shares_result(self):
        tracker = DedupTracker()
        key = tracker.dedup_key("input", "session-1")

        future = tracker.get_or_create(key)

        async def waiter():
            return await future

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.01)
        tracker.resolve(key, {"result": "shared"})
        result = await task
        assert result == {"result": "shared"}

    @pytest.mark.asyncio
    async def test_different_keys_are_independent(self):
        tracker = DedupTracker()
        key1 = tracker.dedup_key("input-a", "session-1")
        key2 = tracker.dedup_key("input-b", "session-1")

        f1 = tracker.get_or_create(key1)
        f2 = tracker.get_or_create(key2)

        tracker.resolve(key1, {"result": "a"})
        tracker.resolve(key2, {"result": "b"})

        assert f1.result() == {"result": "a"}
        assert f2.result() == {"result": "b"}

    def test_resolve_missing_key_is_noop(self):
        tracker = DedupTracker()
        tracker.resolve("missing-key", {"result": "ok"})
        assert tracker._size() == 0
