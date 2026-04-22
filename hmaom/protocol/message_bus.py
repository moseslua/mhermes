"""HMAOM Message Bus.

Structured inter-agent communication using an in-process message bus
with optional SQLite/Redis backend. Supports broadcast, targeted, and
synthesis-directed messaging.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Optional

from hmaom.config import StateConfig
from hmaom.protocol.schemas import AgentAddress, AgentMessage, MessageType


class MessageBus:
    """Structured message bus for inter-agent communication.

    Provides:
    - Pub/sub with topic filtering
    - Persistent message log
    - Broadcast and targeted delivery
    - Synthesis layer integration
    """

    def __init__(self, config: Optional[StateConfig] = None) -> None:
        self.config = config or StateConfig()
        self._subscribers: dict[str, list[Callable[[AgentMessage], Any]]] = {}
        self._lock = asyncio.Lock()
        self._db: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the SQLite message log."""
        if self.config.store_type == "sqlite":
            db_path = Path(self.config.sqlite_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(db_path), check_same_thread=False)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    correlation_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    sender_harness TEXT NOT NULL,
                    sender_agent TEXT NOT NULL,
                    sender_depth INTEGER NOT NULL,
                    recipient TEXT NOT NULL,
                    type TEXT NOT NULL,
                    payload TEXT,
                    created_at REAL DEFAULT (julianday('now'))
                )
            """)
            self._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_correlation ON messages(correlation_id)
            """)
            self._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp)
            """)
            self._db.commit()

    async def publish(self, message: AgentMessage) -> None:
        """Publish a message to all relevant subscribers."""
        async with self._lock:
            # Persist to log
            if self._db is not None:
                self._db.execute(
                    """
                    INSERT OR REPLACE INTO messages
                    (message_id, correlation_id, timestamp, sender_harness, sender_agent,
                     sender_depth, recipient, type, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message.message_id,
                        message.correlation_id,
                        message.timestamp,
                        message.sender.harness,
                        message.sender.agent,
                        message.sender.depth,
                        str(message.recipient),
                        message.type.value,
                        json.dumps(message.payload) if message.payload is not None else None,
                    ),
                )
                self._db.commit()

            # Notify subscribers
            topic = self._topic_for(message)
            callbacks = list(self._subscribers.get(topic, []))
            if message.recipient == "broadcast":
                broadcast_callbacks = self._subscribers.get("broadcast", [])
                for cb in broadcast_callbacks:
                    if cb not in callbacks:
                        callbacks.append(cb)
            elif message.recipient == "synthesis":
                synthesis_callbacks = self._subscribers.get("synthesis", [])
                for cb in synthesis_callbacks:
                    if cb not in callbacks:
                        callbacks.append(cb)
            # Also notify correlation subscribers
            corr_topic = f"corr:{message.correlation_id}"
            if corr_topic != topic:
                corr_callbacks = self._subscribers.get(corr_topic, [])
                for cb in corr_callbacks:
                    if cb not in callbacks:
                        callbacks.append(cb)

        # Invoke callbacks outside the lock
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(message)
                else:
                    callback(message)
            except Exception as exc:
                # Fault isolation: subscriber errors must not break the bus
                print(f"[MessageBus] Subscriber error on {topic}: {exc}")

    def subscribe(
        self,
        topic: str,
        callback: Callable[[AgentMessage], Any],
    ) -> Callable[[], None]:
        """Subscribe to messages on a topic. Returns an unsubscribe function."""
        self._subscribers.setdefault(topic, []).append(callback)

        def unsubscribe() -> None:
            if topic in self._subscribers:
                try:
                    self._subscribers[topic].remove(callback)
                except ValueError:
                    pass

        return unsubscribe

    def subscribe_to_correlation(
        self,
        correlation_id: str,
        callback: Callable[[AgentMessage], Any],
    ) -> Callable[[], None]:
        """Subscribe to all messages for a specific correlation ID."""
        return self.subscribe(f"corr:{correlation_id}", callback)

    async def get_messages_for_correlation(
        self,
        correlation_id: str,
        since: Optional[float] = None,
    ) -> list[AgentMessage]:
        """Retrieve persisted messages for a correlation ID."""
        if self._db is None:
            return []

        cursor = self._db.execute(
            """
            SELECT message_id, correlation_id, timestamp, sender_harness,
                   sender_agent, sender_depth, recipient, type, payload
            FROM messages
            WHERE correlation_id = ? AND timestamp >= COALESCE(?, 0)
            ORDER BY timestamp
            """,
            (correlation_id, since),
        )

        messages: list[AgentMessage] = []
        for row in cursor.fetchall():
            sender = AgentAddress(
                harness=row[3],
                agent=row[4],
                depth=row[5],
            )
            payload = json.loads(row[8]) if row[8] else None
            messages.append(
                AgentMessage(
                    message_id=row[0],
                    correlation_id=row[1],
                    timestamp=row[2],
                    sender=sender,
                    recipient=row[6],  # type: ignore[arg-type]
                    type=MessageType(row[7]),
                    payload=payload,
                )
            )
        return messages

    def _topic_for(self, message: AgentMessage) -> str:
        """Derive a topic key for a message."""
        if isinstance(message.recipient, str):
            if message.recipient in ("broadcast", "synthesis"):
                return message.recipient
            # correlation routing
            return f"corr:{message.correlation_id}"
        # Targeted to a specific agent
        return f"agent:{message.recipient.harness}/{message.recipient.agent}"

    def close(self) -> None:
        """Close the message bus and release resources."""
        if self._db is not None:
            self._db.close()
            self._db = None

    async def health_ping(self, sender: AgentAddress) -> None:
        """Send a health ping message."""
        await self.publish(
            AgentMessage(
                message_id=f"health-{time.time()}-{sender}",
                correlation_id="health",
                timestamp=time.time(),
                sender=sender,
                recipient="broadcast",
                type=MessageType.HEALTH_PING,
                payload={"status": "healthy"},
            )
        )
