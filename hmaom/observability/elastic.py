"""HMAOM Elastic Replica Manager.

Auto-scales specialist replicas based on queue depth and latency metrics.
Supports cooldown periods to prevent flapping and drains in-flight
requests before removing replicas.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from hmaom.config import ElasticConfig
from hmaom.gateway.load_balancer import LoadBalancer
from hmaom.protocol.schemas import Domain
from hmaom.specialists.base import SpecialistHarness

ReplicaFactory = Callable[[Domain], SpecialistHarness]


@dataclass
class ReplicaMetrics:
    """Snapshot of per-replica operational metrics."""

    domain: Domain
    replica_id: str
    queue_depth: int
    p95_latency_ms: float
    in_flight_count: int
    last_activity: float


class ElasticReplicaManager:
    """Auto-scales specialist replicas based on real-time metrics.

    Thread-safe operations for monitoring, evaluating scale conditions,
    and executing scale-up / scale-down actions via the load balancer.
    """

    def __init__(
        self,
        load_balancer: LoadBalancer,
        config: ElasticConfig,
        pool_factory: ReplicaFactory,
    ) -> None:
        self.load_balancer = load_balancer
        self.scale_config = config
        self.pool_factory = pool_factory

        self._domains: dict[Domain, dict[str, ReplicaMetrics]] = {}
        self._desired_replicas: dict[Domain, int] = {}
        self._actual_replicas: dict[Domain, int] = {}
        self._scale_up_cooldowns: dict[Domain, float] = {}
        self._scale_down_cooldowns: dict[Domain, float] = {}
        self._idle_tick_counts: dict[Domain, int] = {}

        self._lock = threading.Lock()
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None

    def monitor(self, domain: Domain, metrics: ReplicaMetrics) -> None:
        """Record current metrics for a replica."""
        with self._lock:
            if domain not in self._domains:
                self._domains[domain] = {}
                self._idle_tick_counts[domain] = 0
            self._domains[domain][metrics.replica_id] = metrics

    def _should_scale_up(self, domain: Domain) -> bool:
        """Return ``True`` if the domain should scale up.

        Conditions: total queue depth exceeds threshold OR max p95 latency
        exceeds threshold, and the scale-up cooldown has expired.
        """
        with self._lock:
            now = time.time()
            last_scale_up = self._scale_up_cooldowns.get(domain, 0)
            if now - last_scale_up < self.scale_config.scale_up_cooldown_seconds:
                return False

            metrics_map = self._domains.get(domain, {})
            if not metrics_map:
                return False

            desired = self._desired_replicas.get(domain, 0)
            if desired >= self.scale_config.max_replicas:
                return False

            total_queue_depth = sum(m.queue_depth for m in metrics_map.values())
            max_p95 = max(m.p95_latency_ms for m in metrics_map.values())

            if total_queue_depth > self.scale_config.scale_up_queue_depth_threshold:
                return True
            if max_p95 > self.scale_config.scale_up_latency_ms_threshold:
                return True

            return False

    def _should_scale_down(self, domain: Domain) -> bool:
        """Return ``True`` if the domain should scale down.

        Conditions: all replicas report queue_depth == 0 AND p95 latency
        is below 50 % of the SLA for ``scale_down_idle_ticks`` consecutive
        ticks, and the scale-down cooldown has expired.
        """
        with self._lock:
            now = time.time()
            last_scale_down = self._scale_down_cooldowns.get(domain, 0)
            if now - last_scale_down < self.scale_config.scale_down_cooldown_seconds:
                return False

            metrics_map = self._domains.get(domain, {})
            if not metrics_map:
                return False

            desired = self._desired_replicas.get(domain, 0)
            if desired <= self.scale_config.min_replicas:
                return False

            half_sla = self.scale_config.latency_sla_ms * 0.5
            all_idle = all(
                m.queue_depth == 0 and m.p95_latency_ms < half_sla
                for m in metrics_map.values()
            )

            if not all_idle:
                self._idle_tick_counts[domain] = 0
                return False

            self._idle_tick_counts[domain] = self._idle_tick_counts.get(domain, 0) + 1
            return self._idle_tick_counts[domain] >= self.scale_config.scale_down_idle_ticks

    def _scale_up(self, domain: Domain) -> bool:
        """Add a replica to the pool for *domain*."""
        try:
            harness = self.pool_factory(domain)
        except Exception:
            return False

        success = self.load_balancer.scale_up(domain, lambda: harness)
        if success:
            with self._lock:
                self._desired_replicas[domain] = self._desired_replicas.get(domain, 0) + 1
                self._scale_up_cooldowns[domain] = time.time()
        return success

    def _scale_down(self, domain: Domain) -> bool:
        """Remove a replica from the pool for *domain* (drain in-flight first)."""
        pool = self.load_balancer._pools.get(domain)
        if pool is None:
            return False

        replicas = pool.all_replicas()
        if not replicas:
            return False

        metrics_map = self._domains.get(domain, {})

        def _sort_key(replica: SpecialistHarness) -> tuple:
            m = metrics_map.get(replica.config.name)
            if m is None:
                return (999, 999, 0)
            return (m.in_flight_count, m.p95_latency_ms, -m.last_activity)

        # Remove the replica with the lowest load first
        candidates = sorted(replicas, key=_sort_key)

        for replica in candidates:
            replica_id = replica.config.name
            drained = pool.drain_replica(replica_id, timeout_ms=30000)
            if drained:
                success = self.load_balancer.scale_down(domain, replica_id)
                if success:
                    with self._lock:
                        self._desired_replicas[domain] = max(
                            self.scale_config.min_replicas,
                            self._desired_replicas.get(domain, 1) - 1,
                        )
                        self._scale_down_cooldowns[domain] = time.time()
                        self._idle_tick_counts[domain] = 0
                        if domain in self._domains and replica_id in self._domains[domain]:
                            del self._domains[domain][replica_id]
                    return True
        return False

    def tick(self) -> None:
        """Evaluate all known domains and scale as needed."""
        with self._lock:
            domains = list(self._domains.keys())

        for domain in domains:
            pool = self.load_balancer._pools.get(domain)
            actual = pool.replica_count() if pool else 0
            with self._lock:
                self._actual_replicas[domain] = actual
                if domain not in self._desired_replicas:
                    self._desired_replicas[domain] = actual

            if self._should_scale_up(domain):
                self._scale_up(domain)
            elif self._should_scale_down(domain):
                self._scale_down(domain)

    def get_status(self) -> dict:
        """Return desired vs actual replica counts per domain."""
        with self._lock:
            result = {}
            for domain in self._domains:
                pool = self.load_balancer._pools.get(domain)
                actual = pool.replica_count() if pool else 0
                result[domain.value] = {
                    "desired": self._desired_replicas.get(domain, actual),
                    "actual": actual,
                }
            return result

    async def _monitoring_loop(self, interval_seconds: float = 5.0) -> None:
        """Background monitoring loop."""
        while self._monitoring:
            try:
                self.tick()
            except Exception:
                pass
            await asyncio.sleep(interval_seconds)

    def start_monitoring(self, interval_seconds: float = 5.0) -> None:
        """Start the background async monitoring loop."""
        if self._monitoring:
            return
        self._monitoring = True
        self._monitor_task = asyncio.ensure_future(
            self._monitoring_loop(interval_seconds)
        )

    def stop_monitoring(self) -> None:
        """Stop the background monitoring loop."""
        self._monitoring = False
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            self._monitor_task = None
