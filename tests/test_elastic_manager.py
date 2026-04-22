"""Tests for HMAOM Elastic Replica Manager.

Covers: scale-up / scale-down decisions, cooldown enforcement,
min/max bounds, drain-before-removal, status reporting, and monitoring.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from hmaom.config import ElasticConfig, SpecialistConfig
from hmaom.gateway.load_balancer import LoadBalancer
from hmaom.observability.elastic import ElasticReplicaManager, ReplicaMetrics
from hmaom.observability.pool import SpecialistPool
from hmaom.protocol.schemas import Domain
from hmaom.specialists.finance import FinanceHarness


# ── Helpers ──

def _make_harness(name: str, domain: str = "finance") -> FinanceHarness:
    config = SpecialistConfig(name=name, domain=domain, description=f"Replica {name}")
    return FinanceHarness(config=config)


def _make_manager(
    load_balancer: LoadBalancer,
    pool_factory: Any,
    **overrides: Any,
) -> ElasticReplicaManager:
    config = ElasticConfig(**overrides)
    return ElasticReplicaManager(
        load_balancer=load_balancer,
        config=config,
        pool_factory=pool_factory,
    )


def _metrics(
    domain: Domain,
    replica_id: str,
    *,
    queue_depth: int = 0,
    p95_latency_ms: float = 100.0,
    in_flight_count: int = 0,
) -> ReplicaMetrics:
    return ReplicaMetrics(
        domain=domain,
        replica_id=replica_id,
        queue_depth=queue_depth,
        p95_latency_ms=p95_latency_ms,
        in_flight_count=in_flight_count,
        last_activity=time.time(),
    )


# ── Fixtures ──

@pytest.fixture
def load_balancer():
    return LoadBalancer()


@pytest.fixture
def finance_pool():
    return SpecialistPool(domain=Domain.FINANCE, max_replicas=10)


# ── Scale Up ──

class TestScaleUp:
    def test_scale_up_on_queue_depth(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        finance_pool.add_replica(h1)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        def factory(domain: Domain) -> FinanceHarness:
            return _make_harness(f"finance-{finance_pool.replica_count() + 1}")

        manager = _make_manager(
            load_balancer, factory,
            enabled=True, min_replicas=1, max_replicas=3,
            scale_up_queue_depth_threshold=5,
            scale_up_latency_ms_threshold=2000,
            scale_up_cooldown_seconds=0.0,
        )
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1", queue_depth=10))

        manager.tick()

        assert finance_pool.replica_count() == 2
        status = manager.get_status()
        assert status["finance"]["desired"] == 2
        assert status["finance"]["actual"] == 2

    def test_scale_up_on_latency_breach(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        finance_pool.add_replica(h1)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        def factory(domain: Domain) -> FinanceHarness:
            return _make_harness(f"finance-{finance_pool.replica_count() + 1}")

        manager = _make_manager(
            load_balancer, factory,
            enabled=True, min_replicas=1, max_replicas=3,
            scale_up_queue_depth_threshold=5,
            scale_up_latency_ms_threshold=2000,
            scale_up_cooldown_seconds=0.0,
        )
        manager.monitor(
            Domain.FINANCE,
            _metrics(Domain.FINANCE, "finance-1", p95_latency_ms=3000),
        )

        manager.tick()

        assert finance_pool.replica_count() == 2

    def test_scale_up_respects_max_replicas(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        finance_pool.add_replica(h1)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        def factory(domain: Domain) -> FinanceHarness:
            return _make_harness(f"finance-{finance_pool.replica_count() + 1}")

        manager = _make_manager(
            load_balancer, factory,
            enabled=True, min_replicas=1, max_replicas=2,
            scale_up_queue_depth_threshold=1,
            scale_up_cooldown_seconds=0.0,
        )
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1", queue_depth=10))
        manager.tick()
        assert finance_pool.replica_count() == 2

        # Try to exceed max
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1", queue_depth=10))
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-2", queue_depth=10))
        manager.tick()
        assert finance_pool.replica_count() == 2  # capped

    def test_scale_up_cooldown_prevents_flapping(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        finance_pool.add_replica(h1)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        def factory(domain: Domain) -> FinanceHarness:
            return _make_harness(f"finance-{finance_pool.replica_count() + 1}")

        manager = _make_manager(
            load_balancer, factory,
            enabled=True, max_replicas=3,
            scale_up_queue_depth_threshold=1,
            scale_up_cooldown_seconds=60.0,
        )
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1", queue_depth=10))
        manager.tick()
        assert finance_pool.replica_count() == 2

        # Immediate second tick should be blocked by cooldown
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1", queue_depth=10))
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-2", queue_depth=10))
        manager.tick()
        assert finance_pool.replica_count() == 2  # still 2


# ── Scale Down ──

class TestScaleDown:
    def test_scale_down_on_idle(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        h2 = _make_harness("finance-2")
        finance_pool.add_replica(h1)
        finance_pool.add_replica(h2)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        def factory(domain: Domain) -> FinanceHarness:
            return _make_harness(f"finance-{finance_pool.replica_count() + 1}")

        manager = _make_manager(
            load_balancer, factory,
            enabled=True, min_replicas=1, max_replicas=3,
            scale_down_idle_ticks=2,
            scale_down_cooldown_seconds=0.0,
            latency_sla_ms=1000,
        )
        # Need 2 consecutive idle ticks
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1", queue_depth=0, p95_latency_ms=100))
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-2", queue_depth=0, p95_latency_ms=100))
        manager.tick()
        assert finance_pool.replica_count() == 2  # not enough idle ticks yet

        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1", queue_depth=0, p95_latency_ms=100))
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-2", queue_depth=0, p95_latency_ms=100))
        manager.tick()
        assert finance_pool.replica_count() == 1

    def test_scale_down_respects_min_replicas(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        finance_pool.add_replica(h1)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        def factory(domain: Domain) -> FinanceHarness:
            return _make_harness(f"finance-{finance_pool.replica_count() + 1}")

        manager = _make_manager(
            load_balancer, factory,
            enabled=True, min_replicas=1, max_replicas=3,
            scale_down_idle_ticks=1,
            scale_down_cooldown_seconds=0.0,
            latency_sla_ms=1000,
        )
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1", queue_depth=0, p95_latency_ms=10))
        manager.tick()
        assert finance_pool.replica_count() == 1  # floor enforced

    def test_scale_down_cooldown_prevents_flapping(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        h2 = _make_harness("finance-2")
        finance_pool.add_replica(h1)
        finance_pool.add_replica(h2)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        def factory(domain: Domain) -> FinanceHarness:
            return _make_harness(f"finance-{finance_pool.replica_count() + 1}")

        manager = _make_manager(
            load_balancer, factory,
            enabled=True, min_replicas=1, max_replicas=3,
            scale_down_idle_ticks=1,
            scale_down_cooldown_seconds=60.0,
            latency_sla_ms=1000,
        )
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1", queue_depth=0, p95_latency_ms=10))
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-2", queue_depth=0, p95_latency_ms=10))
        manager.tick()
        assert finance_pool.replica_count() == 1

        # Add a new replica and try to scale down again immediately
        h3 = _make_harness("finance-3")
        finance_pool.add_replica(h3)
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-3", queue_depth=0, p95_latency_ms=10))
        manager.tick()
        assert finance_pool.replica_count() == 2  # cooldown blocks second scale-down

    def test_scale_down_drains_in_flight_first(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        h2 = _make_harness("finance-2")
        finance_pool.add_replica(h1)
        finance_pool.add_replica(h2)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        # Simulate in-flight request on h2
        finance_pool._request_counts["finance-2"] = 1

        def factory(domain: Domain) -> FinanceHarness:
            return _make_harness(f"finance-{finance_pool.replica_count() + 1}")

        manager = _make_manager(
            load_balancer, factory,
            enabled=True, min_replicas=1, max_replicas=3,
            scale_down_idle_ticks=1,
            scale_down_cooldown_seconds=0.0,
            latency_sla_ms=1000,
        )
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1", queue_depth=0, p95_latency_ms=10, in_flight_count=0))
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-2", queue_depth=0, p95_latency_ms=10, in_flight_count=1))
        manager.tick()
        # h2 has in-flight so it can't be drained; h1 should be removed instead
        assert finance_pool.replica_count() == 1
        # The remaining replica should be the one with in-flight (h2)
        assert finance_pool.all_replicas()[0].config.name == "finance-2"


# ── Monitoring & Status ──

class TestMonitoring:
    def test_monitor_records_metrics(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        finance_pool.add_replica(h1)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        manager = _make_manager(load_balancer, lambda d: _make_harness("x"))
        m = _metrics(Domain.FINANCE, "finance-1", queue_depth=3, p95_latency_ms=500)
        manager.monitor(Domain.FINANCE, m)

        status = manager.get_status()
        assert status["finance"]["desired"] == 1
        assert status["finance"]["actual"] == 1

    def test_status_reports_desired_vs_actual(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        finance_pool.add_replica(h1)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        manager = _make_manager(load_balancer, lambda d: _make_harness("x"))
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1"))

        status = manager.get_status()
        assert "finance" in status
        assert status["finance"]["desired"] == 1
        assert status["finance"]["actual"] == 1

    def test_status_empty_when_no_domains(self, load_balancer):
        manager = _make_manager(load_balancer, lambda d: _make_harness("x"))
        assert manager.get_status() == {}


# ── Background Loop ──

class TestBackgroundLoop:
    def test_start_stop_monitoring(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        finance_pool.add_replica(h1)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        manager = _make_manager(load_balancer, lambda d: _make_harness("x"))
        manager.start_monitoring(interval_seconds=0.1)
        assert manager._monitoring is True
        assert manager._monitor_task is not None

        manager.stop_monitoring()
        assert manager._monitoring is False
        assert manager._monitor_task is None

    @pytest.mark.asyncio
    async def test_monitoring_loop_calls_tick(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        finance_pool.add_replica(h1)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        def factory(domain: Domain) -> FinanceHarness:
            return _make_harness(f"finance-{finance_pool.replica_count() + 1}")

        manager = _make_manager(
            load_balancer, factory,
            enabled=True, max_replicas=2,
            scale_up_queue_depth_threshold=1,
            scale_up_cooldown_seconds=0.0,
        )
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1", queue_depth=10))
        manager.start_monitoring(interval_seconds=0.05)

        await asyncio.sleep(0.15)

        manager.stop_monitoring()
        assert finance_pool.replica_count() == 2


# ── Edge Cases ──

class TestEdgeCases:
    def test_scale_up_unknown_domain_no_crash(self, load_balancer):
        manager = _make_manager(load_balancer, lambda d: _make_harness("x"))
        # No pool registered for finance
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "r1", queue_depth=10))
        manager.tick()  # should not raise
        assert manager.get_status()["finance"]["actual"] == 0

    def test_idle_tick_count_reset_on_load(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        h2 = _make_harness("finance-2")
        finance_pool.add_replica(h1)
        finance_pool.add_replica(h2)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        def factory(domain: Domain) -> FinanceHarness:
            return _make_harness(f"finance-{finance_pool.replica_count() + 1}")

        manager = _make_manager(
            load_balancer, factory,
            enabled=True, min_replicas=1, max_replicas=3,
            scale_down_idle_ticks=3,
            scale_down_cooldown_seconds=0.0,
            latency_sla_ms=1000,
        )
        # One idle tick
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1", queue_depth=0, p95_latency_ms=10))
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-2", queue_depth=0, p95_latency_ms=10))
        manager.tick()
        assert finance_pool.replica_count() == 2

        # Load returns — idle counter should reset
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1", queue_depth=5, p95_latency_ms=10))
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-2", queue_depth=0, p95_latency_ms=10))
        manager.tick()
        assert finance_pool.replica_count() == 2

        # Go idle again — need 3 ticks from scratch
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-1", queue_depth=0, p95_latency_ms=10))
        manager.monitor(Domain.FINANCE, _metrics(Domain.FINANCE, "finance-2", queue_depth=0, p95_latency_ms=10))
        manager.tick()
        assert finance_pool.replica_count() == 2
        manager.tick()
        assert finance_pool.replica_count() == 2
        manager.tick()
        assert finance_pool.replica_count() == 1
