"""HMAOM Gateway Load Balancer.

Routes requests across specialist pools using health-aware strategies.
Supports horizontal scaling via dynamic replica addition and removal.
"""

from __future__ import annotations

import random
import threading
from typing import Any, Callable, Optional

from hmaom.observability.pool import SpecialistPool
from hmaom.protocol.schemas import Domain
from hmaom.specialists.base import SpecialistHarness


class LoadBalancer:
    """Routes requests across specialist pools using health-aware strategies.

    Thread-safe operations for domain-level routing, scaling, and health
    monitoring across multiple specialist pools.
    """

    def __init__(self) -> None:
        self._pools: dict[Domain, SpecialistPool] = {}
        self._lock = threading.RLock()
        self._round_robin_indices: dict[Domain, int] = {}

    def register_pool(self, domain: Domain, pool: SpecialistPool) -> None:
        """Register a specialist pool for a domain."""
        with self._lock:
            self._pools[domain] = pool
            self._round_robin_indices[domain] = 0

    def unregister_pool(self, domain: Domain) -> None:
        """Unregister the specialist pool for a domain."""
        with self._lock:
            self._pools.pop(domain, None)
            self._round_robin_indices.pop(domain, None)

    def route(
        self, domain: Domain, strategy: str = "round_robin"
    ) -> Optional[SpecialistHarness]:
        """Select a specialist from the pool using the given strategy.

        Health-aware: replicas with health score < 0.5 are excluded unless
        all replicas are unhealthy, in which case the least-bad replica
        (highest score) is returned.

        Supported strategies:
        - ``round_robin`` — cycles through healthy replicas in order
        - ``least_loaded`` — replica with fewest active spawns
        - ``healthiest`` — replica with highest health score
        - ``random`` — randomly selected healthy replica
        """
        with self._lock:
            pool = self._pools.get(domain)
            if pool is None:
                return None

            replicas = pool.all_replicas()
            if not replicas:
                return None

            # Build candidates with health scores
            candidates: list[tuple[SpecialistHarness, float]] = []
            for replica in replicas:
                score = pool._health_scores.get(replica.config.name, 0.0)
                candidates.append((replica, score))

            # Filter to healthy replicas (score >= 0.5)
            healthy = [(r, s) for r, s in candidates if s >= 0.5]

            if healthy:
                targets = healthy
            else:
                # All unhealthy: fall back to least-bad (highest score)
                targets = candidates

            if not targets:
                return None

            if strategy == "round_robin":
                return self._route_round_robin(domain, targets)
            if strategy == "least_loaded":
                return self._route_least_loaded(targets)
            if strategy == "healthiest":
                return self._route_healthiest(targets)
            if strategy == "random":
                return self._route_random(targets)

            raise ValueError(f"Unknown strategy: {strategy}")

    def _route_round_robin(
        self, domain: Domain, targets: list[tuple[SpecialistHarness, float]]
    ) -> SpecialistHarness:
        """Round-robin selection across healthy targets."""
        idx = self._round_robin_indices.get(domain, 0) % len(targets)
        replica = targets[idx][0]
        self._round_robin_indices[domain] = (idx + 1) % len(targets)
        return replica

    @staticmethod
    def _route_least_loaded(
        targets: list[tuple[SpecialistHarness, float]]
    ) -> SpecialistHarness:
        """Select the replica with the lowest active spawn count."""
        def _load(item: tuple[SpecialistHarness, float]) -> int:
            try:
                return item[0].health().get("active_spawns", 0)
            except Exception:
                return 0

        return min(targets, key=_load)[0]

    @staticmethod
    def _route_healthiest(
        targets: list[tuple[SpecialistHarness, float]]
    ) -> SpecialistHarness:
        """Select the replica with the highest health score."""
        return max(targets, key=lambda item: item[1])[0]

    @staticmethod
    def _route_random(
        targets: list[tuple[SpecialistHarness, float]]
    ) -> SpecialistHarness:
        """Select a random replica from the targets."""
        return random.choice(targets)[0]

    def get_available_domains(self) -> list[Domain]:
        """Return domains that have at least one healthy replica."""
        with self._lock:
            result: list[Domain] = []
            for domain, pool in self._pools.items():
                for replica in pool.all_replicas():
                    score = pool._health_scores.get(replica.config.name, 0.0)
                    if score >= 0.5:
                        result.append(domain)
                        break
            return result

    def health_summary(self) -> dict[str, dict[str, Any]]:
        """Return health status per domain and replica."""
        with self._lock:
            summary: dict[str, dict[str, Any]] = {}
            for domain, pool in self._pools.items():
                replica_health: dict[str, float] = {}
                for replica in pool.all_replicas():
                    replica_health[replica.config.name] = pool._health_scores.get(
                        replica.config.name, 0.0
                    )
                summary[domain.value] = {
                    "replicas": pool.replica_count(),
                    "replica_health": replica_health,
                }
            return summary

    def scale_up(
        self, domain: Domain, factory: Callable[[], SpecialistHarness]
    ) -> bool:
        """Add a replica to the pool using *factory* if under ``max_replicas``.

        Returns ``True`` if the replica was added, ``False`` if the pool is
        at capacity, the domain is not registered, or the factory raises.
        """
        with self._lock:
            pool = self._pools.get(domain)
            if pool is None:
                return False
            if pool.replica_count() >= pool.max_replicas:
                return False

        # Factory call is outside the lock to avoid holding the lock during
        # potentially slow or blocking construction.
        try:
            harness = factory()
        except Exception:
            return False

        return pool.add_replica(harness)

    def scale_down(self, domain: Domain, replica_id: str) -> bool:
        """Remove a replica from the pool by its identifier.

        Returns ``True`` if removed, ``False`` if the domain is not registered
        or the replica was not found.
        """
        with self._lock:
            pool = self._pools.get(domain)
            if pool is None:
                return False
            return pool.remove_replica(replica_id)
