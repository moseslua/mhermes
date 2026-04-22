"""Distributed gateway components using Redis with graceful fallbacks.

Provides distributed primitives for multi-instance HMAOM deployments:
- DistributedMessageBus: Redis pub/sub with in-process fallback
- DistributedStateStore: Redis-backed key-value with SQLite fallback
- DistributedLock: Redis-based distributed locking
- LeaderElection: Redis-based leader election for singleton ops
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

from hmaom.config import DistributedConfig, StateConfig
from hmaom.protocol.message_bus import MessageBus
from hmaom.protocol.schemas import AgentAddress, AgentMessage, MessageType, StateEntry
from hmaom.state.store import StateStore

try:
    import redis.asyncio as aioredis

    _REDIS_AVAILABLE = True
except Exception:  # pragma: no cover
    aioredis = None  # type: ignore[assignment]
    _REDIS_AVAILABLE = False


class DistributedMessageBus:
    """Redis pub/sub wrapper with same conceptual interface as MessageBus.

    Falls back to an in-process :class:`MessageBus` when Redis is unavailable.
    """

    def __init__(self, config: Optional[DistributedConfig] = None) -> None:
        self.config = config or DistributedConfig()
        self._redis: Optional[Any] = None
        self._pubsub: Optional[Any] = None
        self._fallback_bus: Optional[MessageBus] = None
        self._subscribers: dict[str, list[asyncio.Queue[Any]]] = {}
        self._lock = asyncio.Lock()
        self._listen_task: Optional[asyncio.Task[Any]] = None
        self._connected = False

        if _REDIS_AVAILABLE and self.config.redis_url:
            try:
                self._redis = aioredis.from_url(self.config.redis_url)
                self._pubsub = self._redis.pubsub()
                self._connected = True
            except Exception:
                self._redis = None
                self._pubsub = None

        if not self._connected:
            self._fallback_bus = MessageBus(config=StateConfig())

    async def publish(self, channel: str, message: Any) -> None:
        """Publish a JSON-serialised message to *channel*."""
        if self._redis is not None:
            await self._redis.publish(channel, json.dumps(message))
            return

        # Fallback: bridge into the in-process MessageBus
        # Fallback: bridge into the in-process MessageBus
        msg = AgentMessage(
            message_id=f"dist-{uuid.uuid4().hex}",
            correlation_id=channel,
            timestamp=time.time(),
            sender=AgentAddress(harness="distributed", agent="bus"),
            recipient=AgentAddress(harness="distributed", agent=channel),
            type=MessageType.TASK_REQUEST,
            payload={"channel": channel, "message": message},
        )
        await self._fallback_bus.publish(msg)

    async def subscribe(self, channel: str) -> AsyncGenerator[Any, None]:
        """Yield messages published to *channel* until unsubscribed."""
        queue: asyncio.Queue[Any] = asyncio.Queue()

        async with self._lock:
            self._subscribers.setdefault(channel, []).append(queue)

            if self._pubsub is not None:
                await self._pubsub.subscribe(channel)
                if self._listen_task is None or self._listen_task.done():
                    self._listen_task = asyncio.create_task(self._listen_redis())
            else:
                # Fallback: wrap MessageBus callback -> queue
                def _handler(msg: AgentMessage) -> None:
                    payload = msg.payload or {}
                    if payload.get("channel") == channel:
                        try:
                            queue.put_nowait(payload.get("message"))
                        except Exception:
                            pass

                bus_topic = f"agent:distributed/{channel}"
                unsub = self._fallback_bus.subscribe(bus_topic, _handler)
                queue._unsub = unsub  # type: ignore[attr-defined]

        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield item
                except asyncio.TimeoutError:
                    continue
        finally:
            await self.unsubscribe(channel, queue)

    async def _listen_redis(self) -> None:
        """Background task that drains the Redis pub/sub connection."""
        if self._pubsub is None:
            return
        try:
            async for message in self._pubsub.listen():
                if message.get("type") != "message":
                    continue
                channel = message.get("channel", "")
                if isinstance(channel, bytes):
                    channel = channel.decode()
                data = json.loads(message.get("data", "{}"))
                async with self._lock:
                    queues = list(self._subscribers.get(channel, []))
                for q in queues:
                    try:
                        q.put_nowait(data)
                    except Exception:
                        pass
        except Exception:
            pass  # Fault isolation: listener errors must not break the bus

    async def unsubscribe(self, channel: str, queue: Optional[asyncio.Queue[Any]] = None) -> None:
        """Remove a subscriber (or all subscribers) from *channel*."""
        async with self._lock:
            queues = self._subscribers.get(channel, [])
            if queue is not None and queue in queues:
                queues.remove(queue)
                if hasattr(queue, "_unsub"):
                    queue._unsub()  # type: ignore[attr-defined]
            if queue is None:
                for q in list(queues):
                    if hasattr(q, "_unsub"):
                        q._unsub()  # type: ignore[attr-defined]
                self._subscribers.pop(channel, None)
            elif not queues and self._pubsub is not None:
                await self._pubsub.unsubscribe(channel)

    async def close(self) -> None:
        """Release all resources."""
        if self._listen_task is not None:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._pubsub is not None:
            try:
                await self._pubsub.close()
            except TypeError:
                pass
        if self._redis is not None:
            await self._redis.close()
        if self._fallback_bus is not None:
            self._fallback_bus.close()


class DistributedStateStore:
    """Redis-backed state store with atomic operations.

    Falls back to :class:`StateStore` (SQLite) when Redis is unavailable.
    """

    def __init__(self, config: Optional[DistributedConfig] = None) -> None:
        self.config = config or DistributedConfig()
        self._redis: Optional[Any] = None
        self._fallback_store: Optional[StateStore] = None
        self._connected = False

        if _REDIS_AVAILABLE and self.config.redis_url:
            try:
                self._redis = aioredis.from_url(self.config.redis_url)
                self._connected = True
            except Exception:
                self._redis = None

        if not self._connected:
            fb_path = self.config.fallback_sqlite_path or str(
                _default_state_dir() / "distributed_state.sqlite"
            )
            self._fallback_store = StateStore(config=StateConfig(sqlite_path=fb_path))

    async def get(self, key: str) -> dict[str, Any]:
        """Return the value stored under *key* as a dict, or ``{}``."""
        if self._redis is not None:
            data = await self._redis.get(key)
            if data is None:
                return {}
            if isinstance(data, bytes):
                data = data.decode()
            return json.loads(data)

        entry = self._fallback_store.read(key)
        if entry is None or entry.value is None:
            return {}
        return entry.value if isinstance(entry.value, dict) else {"__value__": entry.value}

    async def set(self, key: str, value: Any) -> None:
        """Store *value* under *key*."""
        if self._redis is not None:
            await self._redis.set(key, json.dumps(value))
            return

        entry = StateEntry(
            key=key,
            value=value if isinstance(value, dict) else {"__value__": value},
            written_by=AgentAddress(harness="distributed", agent="store"),
            written_at=time.time(),
        )
        self._fallback_store.write(entry, force=True)

    async def delete(self, key: str) -> None:
        """Remove *key* from the store."""
        if self._redis is not None:
            await self._redis.delete(key)
            return

        self._fallback_store.delete(
            key, AgentAddress(harness="distributed", agent="store")
        )

    async def increment(self, key: str, amount: int = 1) -> int:
        """Atomically increment the integer stored under *key*."""
        if self._redis is not None:
            return await self._redis.incrby(key, amount)

        current = self._fallback_store.read(key)
        val = 0
        if current is not None and current.value is not None:
            try:
                if isinstance(current.value, dict) and "__value__" in current.value:
                    val = int(current.value["__value__"])
                else:
                    val = int(current.value)
            except (ValueError, TypeError):
                val = 0
        new_val = val + amount
        await self.set(key, {"__value__": new_val})
        return new_val

    async def expire(self, key: str, seconds: int) -> None:
        """Set a TTL on *key*."""
        if self._redis is not None:
            await self._redis.expire(key, seconds)
            return

        current = self._fallback_store.read(key)
        if current is not None:
            current.ttl = seconds
            self._fallback_store.write(current, force=True)

    def close(self) -> None:
        """Release resources."""
        if self._fallback_store is not None:
            self._fallback_store.close()


class DistributedLock:
    """Redis-backed distributed lock (SET NX PX pattern).

    Falls back to local :class:`asyncio.Lock` instances when Redis is unavailable.
    """

    def __init__(self, config: Optional[DistributedConfig] = None) -> None:
        self.config = config or DistributedConfig()
        self._redis: Optional[Any] = None
        self._local_locks: dict[str, asyncio.Lock] = {}
        self._tokens: dict[str, str] = {}

        if _REDIS_AVAILABLE and self.config.redis_url:
            try:
                self._redis = aioredis.from_url(self.config.redis_url)
            except Exception:
                self._redis = None

    async def acquire(self, resource: str, ttl_ms: int = 30000) -> bool:
        """Try to acquire the lock for *resource*. Returns ``True`` on success."""
        token = f"{uuid.uuid4().hex}-{time.time()}"
        if self._redis is not None:
            acquired = await self._redis.set(
                f"lock:{resource}", token, nx=True, px=ttl_ms
            )
            if acquired:
                self._tokens[resource] = token
                return True
            return False

        # Local fallback
        lock = self._local_locks.setdefault(resource, asyncio.Lock())
        if lock.locked():
            return False
        await lock.acquire()
        self._tokens[resource] = token
        return True

    async def release(self, resource: str) -> None:
        """Release the lock for *resource* only if we still hold it."""
        token = self._tokens.pop(resource, None)
        if token is None:
            return

        if self._redis is not None:
            script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            await self._redis.eval(script, 1, f"lock:{resource}", token)
        else:
            lock = self._local_locks.get(resource)
            if lock is not None and lock.locked():
                lock.release()

    def __call__(self, resource: str, ttl_ms: int = 30000):
        """Return an async context manager for the lock on *resource*."""

        @asynccontextmanager
        async def _ctx() -> AsyncGenerator["DistributedLock", None]:
            acquired = await self.acquire(resource, ttl_ms)
            if not acquired:
                raise RuntimeError(f"Could not acquire lock for {resource}")
            try:
                yield self
            finally:
                await self.release(resource)

        return _ctx()


class LeaderElection:
    """Redis-based leader election for singleton operations.

    Falls back to "always leader" when Redis is unavailable.
    """

    def __init__(
        self,
        config: Optional[DistributedConfig] = None,
        instance_id: Optional[str] = None,
    ) -> None:
        self.config = config or DistributedConfig()
        self.instance_id = instance_id or uuid.uuid4().hex
        self._redis: Optional[Any] = None
        self._leader_key = self.config.leader_key or "hmaom:leader"

        if _REDIS_AVAILABLE and self.config.redis_url:
            try:
                self._redis = aioredis.from_url(self.config.redis_url)
            except Exception:
                self._redis = None

    async def is_leader(self) -> bool:
        """Return ``True`` if this instance currently holds the leadership lock."""
        if self._redis is not None:
            val = await self._redis.get(self._leader_key)
            if isinstance(val, bytes):
                val = val.decode()
            return val == self.instance_id
        return True

    async def campaign(self, ttl_ms: int = 30000) -> bool:
        """Attempt to acquire the leadership lock."""
        if self._redis is not None:
            acquired = await self._redis.set(
                self._leader_key, self.instance_id, nx=True, px=ttl_ms
            )
            return bool(acquired)
        return True

    async def resign(self) -> None:
        """Release the leadership lock if we hold it."""
        if self._redis is not None:
            val = await self._redis.get(self._leader_key)
            if isinstance(val, bytes):
                val = val.decode()
            if val == self.instance_id:
                await self._redis.delete(self._leader_key)


def _default_state_dir() -> Any:
    """Return the default HMAOM state directory."""
    from pathlib import Path

    home = Path.home()
    state_dir = home / ".hmaom" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir
