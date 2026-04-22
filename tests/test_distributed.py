"""Tests for distributed gateway components.

Covers: DistributedMessageBus, DistributedStateStore, DistributedLock,
LeaderElection — both Redis-backed and fallback paths.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hmaom.config import DistributedConfig, StateConfig
from hmaom.gateway.distributed import (
    DistributedLock,
    DistributedMessageBus,
    DistributedStateStore,
    LeaderElection,
)


# ── Fixtures ──


@pytest.fixture
def tmp_state_config():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield StateConfig(
            sqlite_path=str(Path(tmpdir) / "state.sqlite"),
            vector_index_path=str(Path(tmpdir) / "vectors.sqlite"),
            checkpoint_dir=str(Path(tmpdir) / "checkpoints"),
        )


@pytest.fixture
def dist_config(tmp_state_config):
    return DistributedConfig(
        redis_url="redis://localhost:6379/0",
        fallback_sqlite_path=tmp_state_config.sqlite_path,
        leader_key="test:leader",
    )


@pytest.fixture
def redis_mock():
    """Return a mock redis.asyncio module."""
    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_pubsub.close = AsyncMock()
    async def _empty_listen():
        return
        yield  # make it an async generator
    mock_pubsub.listen = _empty_listen
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
    return mock_redis, mock_pubsub


# ── DistributedMessageBus ──


class TestDistributedMessageBus:
    @pytest.mark.asyncio
    async def test_fallback_publish_and_subscribe(self):
        """Message bus delivers messages via the in-process fallback."""
        bus = DistributedMessageBus(config=DistributedConfig(redis_url=None))
        received = []

        async def consume():
            async for msg in bus.subscribe("test-channel"):
                received.append(msg)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(consume())
        await asyncio.sleep(0)  # let consumer start before publishing
        await bus.publish("test-channel", {"data": 1})
        await bus.publish("test-channel", {"data": 2})
        await asyncio.wait_for(task, timeout=2.0)

        assert len(received) == 2
        assert received[0]["data"] == 1
        assert received[1]["data"] == 2
        await bus.close()

    @pytest.mark.asyncio
    async def test_redis_publish(self, redis_mock):
        """Publishing delegates to redis.publish when Redis is available."""
        mock_redis, mock_pubsub = redis_mock
        with patch("hmaom.gateway.distributed.aioredis", MagicMock(from_url=MagicMock(return_value=mock_redis))), \
             patch("hmaom.gateway.distributed._REDIS_AVAILABLE", True):
            bus = DistributedMessageBus(config=DistributedConfig(redis_url="redis://localhost"))
            await bus.publish("chan", {"hello": "world"})
            mock_redis.publish.assert_awaited_once()
            args = mock_redis.publish.await_args.args
            assert args[0] == "chan"
            assert '"hello": "world"' in args[1]
            await bus.close()

    @pytest.mark.asyncio
    async def test_redis_subscribe(self, redis_mock):
        """Subscribing delegates to redis pub/sub when Redis is available."""
        mock_redis, mock_pubsub = redis_mock
        with patch("hmaom.gateway.distributed.aioredis", MagicMock(from_url=MagicMock(return_value=mock_redis))), \
             patch("hmaom.gateway.distributed._REDIS_AVAILABLE", True):
            bus = DistributedMessageBus(config=DistributedConfig(redis_url="redis://localhost"))
            sub_gen = bus.subscribe("chan")
            # Pull first item (will timeout since no messages)
            task = asyncio.create_task(sub_gen.__anext__())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            mock_pubsub.subscribe.assert_awaited_once_with("chan")
            await bus.close()

    @pytest.mark.asyncio
    async def test_unsubscribe_cleans_up(self):
        """Unsubscribe removes listeners without errors."""
        bus = DistributedMessageBus(config=DistributedConfig(redis_url=None))
        await bus.unsubscribe("nonexistent")
        await bus.close()


# ── DistributedStateStore ──


class TestDistributedStateStore:
    @pytest.mark.asyncio
    async def test_fallback_get_set_delete(self, tmp_state_config):
        """State store get/set/delete works via SQLite fallback."""
        config = DistributedConfig(
            redis_url=None,
            fallback_sqlite_path=tmp_state_config.sqlite_path,
        )
        store = DistributedStateStore(config=config)

        assert await store.get("missing") == {}

        await store.set("k1", {"a": 1})
        assert await store.get("k1") == {"a": 1}

        await store.delete("k1")
        assert await store.get("k1") == {}

        store.close()

    @pytest.mark.asyncio
    async def test_fallback_increment(self, tmp_state_config):
        """Increment works atomically (as much as SQLite allows) via fallback."""
        config = DistributedConfig(
            redis_url=None,
            fallback_sqlite_path=tmp_state_config.sqlite_path,
        )
        store = DistributedStateStore(config=config)

        val = await store.increment("counter", amount=5)
        assert val == 5

        val = await store.increment("counter", amount=3)
        assert val == 8

        store.close()

    @pytest.mark.asyncio
    async def test_fallback_expire(self, tmp_state_config):
        """Expire sets TTL on fallback entries."""
        config = DistributedConfig(
            redis_url=None,
            fallback_sqlite_path=tmp_state_config.sqlite_path,
        )
        store = DistributedStateStore(config=config)

        await store.set("k2", {"x": 2})
        await store.expire("k2", 60)
        entry = store._fallback_store.read("k2")
        assert entry is not None
        assert entry.ttl == 60

        store.close()

    @pytest.mark.asyncio
    async def test_redis_get_set(self, redis_mock):
        """Get/set delegates to Redis when available."""
        mock_redis, _ = redis_mock
        mock_redis.get = AsyncMock(return_value=b'{"a": 1}')
        with patch("hmaom.gateway.distributed.aioredis", MagicMock(from_url=MagicMock(return_value=mock_redis))), \
             patch("hmaom.gateway.distributed._REDIS_AVAILABLE", True):
            store = DistributedStateStore(config=DistributedConfig(redis_url="redis://localhost"))
            result = await store.get("k")
            assert result == {"a": 1}
            mock_redis.get.assert_awaited_once_with("k")
            store.close()


# ── DistributedLock ──


class TestDistributedLock:
    @pytest.mark.asyncio
    async def test_fallback_acquire_release(self):
        """Local lock acquire/release works when Redis is unavailable."""
        lock = DistributedLock(config=DistributedConfig(redis_url=None))

        assert await lock.acquire("resource-1") is True
        assert await lock.acquire("resource-1") is False  # already locked

        await lock.release("resource-1")
        assert await lock.acquire("resource-1") is True

        await lock.release("resource-1")

    @pytest.mark.asyncio
    async def test_fallback_context_manager(self):
        """Context manager acquires and releases the local lock."""
        lock = DistributedLock(config=DistributedConfig(redis_url=None))

        async with lock("resource-2"):
            assert await lock.acquire("resource-2") is False

        assert await lock.acquire("resource-2") is True
        await lock.release("resource-2")

    @pytest.mark.asyncio
    async def test_redis_acquire_release(self, redis_mock):
        """Lock delegates to Redis SET NX PX when available."""
        mock_redis, _ = redis_mock
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)
        with patch("hmaom.gateway.distributed.aioredis", MagicMock(from_url=MagicMock(return_value=mock_redis))), \
             patch("hmaom.gateway.distributed._REDIS_AVAILABLE", True):
            lock = DistributedLock(config=DistributedConfig(redis_url="redis://localhost"))
            acquired = await lock.acquire("r", ttl_ms=5000)
            assert acquired is True
            mock_redis.set.assert_awaited_once()
            _, kwargs = mock_redis.set.await_args
            assert kwargs.get("nx") is True
            assert kwargs.get("px") == 5000

            await lock.release("r")
            mock_redis.eval.assert_awaited_once()


# ── LeaderElection ──


class TestLeaderElection:
    @pytest.mark.asyncio
    async def test_fallback_always_leader(self):
        """Without Redis, the instance is always the leader."""
        election = LeaderElection(config=DistributedConfig(redis_url=None))

        assert await election.is_leader() is True
        assert await election.campaign() is True
        await election.resign()
        assert await election.is_leader() is True

    @pytest.mark.asyncio
    async def test_redis_campaign_and_resign(self, redis_mock):
        """Campaign/resign use Redis SET NX and conditional DEL."""
        mock_redis, _ = redis_mock
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.delete = AsyncMock()

        with patch("hmaom.gateway.distributed.aioredis", MagicMock(from_url=MagicMock(return_value=mock_redis))), \
             patch("hmaom.gateway.distributed._REDIS_AVAILABLE", True):
            election = LeaderElection(config=DistributedConfig(redis_url="redis://localhost", leader_key="test:leader"))
            assert await election.campaign(ttl_ms=10000) is True
            mock_redis.set.assert_awaited_once()
            _, kwargs = mock_redis.set.await_args
            assert kwargs.get("nx") is True
            assert kwargs.get("px") == 10000

            # Simulate winning the election
            mock_redis.get = AsyncMock(return_value=election.instance_id.encode())
            assert await election.is_leader() is True

            await election.resign()
            mock_redis.delete.assert_awaited_once_with("test:leader")

    @pytest.mark.asyncio
    async def test_redis_not_leader_when_other_instance(self, redis_mock):
        """is_leader returns False when another instance holds the lock."""
        mock_redis, _ = redis_mock
        mock_redis.get = AsyncMock(return_value=b"other-instance")

        with patch("hmaom.gateway.distributed.aioredis", MagicMock(from_url=MagicMock(return_value=mock_redis))), \
             patch("hmaom.gateway.distributed._REDIS_AVAILABLE", True):
            election = LeaderElection(config=DistributedConfig(redis_url="redis://localhost"))
            assert await election.is_leader() is False
