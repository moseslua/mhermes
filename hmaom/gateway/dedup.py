"""Request deduplication tracker."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Optional


class DedupTracker:
    """Deduplicates in-flight requests by (input, session) key.

    Concurrent callers sharing the same dedup key will await the same
    ``asyncio.Future`` and receive the same result.
    """

    def __init__(self) -> None:
        self._in_flight: dict[str, asyncio.Future] = {}

    def dedup_key(self, input_text: str, session_id: str) -> str:
        """Return a stable hash key for the given input and session."""
        payload = f"{session_id}:{input_text}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def get_or_create(self, key: str) -> asyncio.Future:
        """Return an existing Future for *key* or create a new one."""
        if key in self._in_flight:
            return self._in_flight[key]
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._in_flight[key] = future
        return future

    def resolve(self, key: str, result: dict) -> None:
        """Set the result on the Future identified by *key*."""
        future = self._in_flight.get(key)
        if future is not None and not future.done():
            future.set_result(result)

    def cleanup(self, key: str) -> None:
        """Remove *key* from the in-flight map."""
        self._in_flight.pop(key, None)

    def _size(self) -> int:
        """Return the number of in-flight keys (useful for tests)."""
        return len(self._in_flight)
