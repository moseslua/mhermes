"""HMAOM Specialist Pool.

Manages multiple replica instances of the same specialist domain for
horizontal scaling. Supports round-robin, least-loaded, and healthiest
replica selection strategies.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Optional

from hmaom.protocol.schemas import Domain

if TYPE_CHECKING:
    from hmaom.specialists.base import SpecialistHarness


class SpecialistPool:
    """Pool of replica instances for a single specialist domain.

    Thread-safe operations for adding, removing, and selecting replicas
    using various load-balancing strategies.
    """

    def __init__(self, domain: Domain, max_replicas: int = 3) -> None:
        self.domain = domain
        self.max_replicas = max_replicas

        self._replicas: list[SpecialistHarness] = []
        self._health_scores: dict[str, float] = {}
        self._request_counts: dict[str, int] = {}
        self._round_robin_index: int = 0
        self._lock = threading.Lock()

    def add_replica(self, specialist: SpecialistHarness) -> bool:
        """Add a replica to the pool if under ``max_replicas``.

        Returns ``True`` if added, ``False`` if at capacity or duplicate.
        """
        with self._lock:
            if len(self._replicas) >= self.max_replicas:
                return False
            replica_id = specialist.config.name
            if replica_id in self._request_counts:
                return False
            self._replicas.append(specialist)
            self._health_scores[replica_id] = 1.0
            self._request_counts[replica_id] = 0
            return True

    def remove_replica(self, replica_id: str) -> bool:
        """Remove a replica from the pool by its identifier.

        Returns ``True`` if removed, ``False`` if not found.
        """
        with self._lock:
            for i, replica in enumerate(self._replicas):
                if replica.config.name == replica_id:
                    self._replicas.pop(i)
                    self._health_scores.pop(replica_id, None)
                    self._request_counts.pop(replica_id, None)
                    # Adjust round-robin index if needed
                    if self._replicas and self._round_robin_index >= len(self._replicas):
                        self._round_robin_index = 0
                    return True
            return False

    def get_replica(self, strategy: str = "round_robin") -> Optional[SpecialistHarness]:
        """Select a replica using the given strategy.

        Supported strategies:
        - ``round_robin`` — cycles through replicas in order
        - ``least_loaded`` — replica with fewest active requests
        - ``healthiest`` — replica with highest health score
        """
        with self._lock:
            if not self._replicas:
                return None
            if strategy == "round_robin":
                return self._get_replica_round_robin()
            if strategy == "least_loaded":
                return self._get_replica_least_loaded()
            if strategy == "healthiest":
                return self._get_replica_healthiest()
            # Default fallback to round_robin for unknown strategies
            return self._get_replica_round_robin()

    def _get_replica_round_robin(self) -> Optional[SpecialistHarness]:
        """Internal round-robin selection (must hold ``_lock``)."""
        if not self._replicas:
            return None
        replica = self._replicas[self._round_robin_index]
        self._request_counts[replica.config.name] += 1
        self._round_robin_index = (self._round_robin_index + 1) % len(self._replicas)
        return replica

    def get_replica_least_loaded(self) -> Optional[SpecialistHarness]:
        """Return the replica with the lowest request count."""
        with self._lock:
            return self._get_replica_least_loaded()

    def _get_replica_least_loaded(self) -> Optional[SpecialistHarness]:
        """Internal least-loaded selection (must hold ``_lock``)."""
        if not self._replicas:
            return None
        replica = min(
            self._replicas,
            key=lambda r: self._request_counts[r.config.name],
        )
        self._request_counts[replica.config.name] += 1
        return replica

    def get_replica_healthiest(self) -> Optional[SpecialistHarness]:
        """Return the replica with the highest health score."""
        with self._lock:
            return self._get_replica_healthiest()

    def _get_replica_healthiest(self) -> Optional[SpecialistHarness]:
        """Internal healthiest selection (must hold ``_lock``)."""
        if not self._replicas:
            return None
        replica = max(
            self._replicas,
            key=lambda r: self._health_scores.get(r.config.name, 0.0),
        )
        self._request_counts[replica.config.name] += 1
        return replica

    def release_replica(self, replica_id: str) -> None:
        """Decrement the in-flight request count for a replica."""
        with self._lock:
            if replica_id in self._request_counts:
                self._request_counts[replica_id] = max(0, self._request_counts[replica_id] - 1)

    def update_health(self, replica_id: str, score: float) -> None:
        """Update the health score for a replica."""
        with self._lock:
            if replica_id in self._health_scores:
                self._health_scores[replica_id] = score

    def all_replicas(self) -> list[SpecialistHarness]:
        """Return a snapshot of all replicas in the pool."""
        with self._lock:
            return list(self._replicas)

    def replica_count(self) -> int:
        """Return the current number of replicas."""
        with self._lock:
            return len(self._replicas)

    def is_available(self) -> bool:
        """Return ``True`` if at least one replica exists."""
        with self._lock:
            return len(self._replicas) > 0


    def drain_replica(self, replica_id: str, timeout_ms: int = 30000) -> bool:
        """Wait for in-flight requests on a replica to complete.

        Returns ``True`` if the replica drained within the timeout,
        ``False`` otherwise.
        """
        import time
        deadline = time.time() + (timeout_ms / 1000.0)
        while time.time() < deadline:
            with self._lock:
                if replica_id not in self._request_counts:
                    return True
                if self._request_counts[replica_id] == 0:
                    return True
            time.sleep(0.05)
        return False
