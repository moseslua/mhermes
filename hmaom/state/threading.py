"""HMAOM Cross-Session Thread Manager.

Tracks persistent conversation threads across sessions, enabling context
injection and intent-based thread recovery.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from hmaom.config import ThreadingConfig
from hmaom.protocol.schemas import TaskDescription


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity between two sets."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _extract_keywords(text: str) -> set[str]:
    """Extract simple keyword tokens from text."""
    # Lowercase, strip punctuation, split on whitespace
    cleaned = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in text)
    return {w for w in cleaned.split() if len(w) > 2}


@dataclass
class ThreadContext:
    """Persistent context for a cross-session thread."""

    thread_id: str
    user_id: str
    created_at: float
    last_active: float
    sessions: list[str] = field(default_factory=list)
    unresolved_tasks: list[dict[str, Any]] = field(default_factory=list)
    preferences: dict[str, Any] = field(default_factory=dict)


class ThreadManager:
    """Manages cross-session threads with intent-based lookup."""

    def __init__(self, config: Optional[ThreadingConfig] = None) -> None:
        self.config = config or ThreadingConfig()
        self._threads: dict[str, ThreadContext] = {}
        self._user_threads: dict[str, list[str]] = {}  # user_id -> thread_ids
        self._lock = threading.Lock()

    def create_thread(self, user_id: str, session_id: str) -> str:
        """Create a new thread for a user and associate the initial session."""
        with self._lock:
            thread_id = str(uuid.uuid4())
            now = time.time()
            ctx = ThreadContext(
                thread_id=thread_id,
                user_id=user_id,
                created_at=now,
                last_active=now,
                sessions=[session_id],
            )
            self._threads[thread_id] = ctx
            self._user_threads.setdefault(user_id, []).append(thread_id)
            return thread_id

    def add_to_thread(
        self,
        thread_id: str,
        session_id: str,
        result: Optional[dict[str, Any]] = None,
    ) -> None:
        """Add a session and optional result to an existing thread."""
        with self._lock:
            ctx = self._threads.get(thread_id)
            if ctx is None:
                raise ValueError(f"Thread {thread_id} not found")

            if session_id not in ctx.sessions:
                ctx.sessions.append(session_id)

            if result is not None:
                ctx.unresolved_tasks.append(result)

            ctx.last_active = time.time()

    def get_thread_context(self, thread_id: str) -> ThreadContext:
        """Retrieve a thread's context."""
        with self._lock:
            ctx = self._threads.get(thread_id)
            if ctx is None:
                raise ValueError(f"Thread {thread_id} not found")
            return ctx

    def find_thread(self, user_id: str, intent_embedding: list[float]) -> str | None:
        """Find an existing thread by user and intent similarity.

        Uses keyword overlap (Jaccard index) as a lightweight similarity proxy.
        The intent_embedding is accepted for API compatibility but ignored;
        thread matching is done via keyword overlap on unresolved task text.
        """
        with self._lock:
            thread_ids = self._user_threads.get(user_id, [])
            if not thread_ids:
                return None

        # Build keyword set from the embedding if it contains string metadata,
        # otherwise fall back to empty set (will match any thread equally)
        query_keywords: set[str] = set()
        if intent_embedding and isinstance(intent_embedding, list):
            for item in intent_embedding:
                if isinstance(item, str):
                    query_keywords |= _extract_keywords(item)

        best_match: str | None = None
        best_score = self.config.similarity_threshold

        with self._lock:
            for tid in thread_ids:
                ctx = self._threads[tid]
                if not ctx.unresolved_tasks:
                    continue
                # Aggregate keywords from all unresolved task text
                thread_keywords: set[str] = set()
                for task in ctx.unresolved_tasks:
                    text = task.get("text") or task.get("description") or task.get("title") or ""
                    if isinstance(text, str):
                        thread_keywords |= _extract_keywords(text)

                score = _jaccard_similarity(query_keywords, thread_keywords)
                if score > best_score:
                    best_score = score
                    best_match = tid

            return best_match

    def inject_context(self, thread_id: str, task: TaskDescription) -> TaskDescription:
        """Prepend thread context (unresolved tasks, preferences) to a task description."""
        with self._lock:
            ctx = self._threads.get(thread_id)
            if ctx is None:
                return task

        parts: list[str] = []
        if ctx.preferences:
            parts.append(f"User preferences: {ctx.preferences}")
        if ctx.unresolved_tasks:
            parts.append("Unresolved thread context:")
            for i, t in enumerate(ctx.unresolved_tasks, 1):
                text = t.get("text") or t.get("description") or t.get("title") or str(t)
                parts.append(f"  {i}. {text}")

        if not parts:
            return task

        parts_str = '\n'.join(parts)
        injected = f"{parts_str}\n\n---\n\n{task.description}"
        return TaskDescription(
            title=task.title,
            description=injected,
            expected_output_schema=task.expected_output_schema,
            priority=task.priority,
            tags=list(task.tags),
        )

    def prune_inactive(self, days: int = 7) -> int:
        """Remove threads inactive for longer than the given number of days.

        Returns the number of threads pruned.
        """
        cutoff = time.time() - (days * 86400)
        with self._lock:
            to_remove: list[str] = []
            for tid, ctx in self._threads.items():
                if ctx.last_active < cutoff:
                    to_remove.append(tid)

            for tid in to_remove:
                ctx = self._threads.pop(tid, None)
                if ctx is not None:
                    user_list = self._user_threads.get(ctx.user_id, [])
                    if tid in user_list:
                        user_list.remove(tid)
                    if not user_list:
                        self._user_threads.pop(ctx.user_id, None)

            return len(to_remove)

    def list_threads_for_user(self, user_id: str) -> list[ThreadContext]:
        """Return all thread contexts for a given user."""
        with self._lock:
            return [self._threads[tid] for tid in self._user_threads.get(user_id, []) if tid in self._threads]

    def thread_count(self) -> int:
        """Return total number of tracked threads."""
        with self._lock:
            return len(self._threads)
