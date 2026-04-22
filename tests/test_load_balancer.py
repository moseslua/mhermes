"""Tests for HMAOM Gateway LoadBalancer.

Covers: pool registration, routing strategies, health-aware exclusion,
scaling operations, domain availability, and health summaries.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from hmaom.config import SpecialistConfig
from hmaom.gateway.load_balancer import LoadBalancer
from hmaom.observability.pool import SpecialistPool
from hmaom.protocol.schemas import Domain
from hmaom.specialists.finance import FinanceHarness


# ── Fixtures ──

@pytest.fixture
def load_balancer():
    return LoadBalancer()


@pytest.fixture
def finance_pool():
    return SpecialistPool(domain=Domain.FINANCE, max_replicas=3)


@pytest.fixture
def maths_pool():
    return SpecialistPool(domain=Domain.MATHS, max_replicas=2)


def _make_harness(name: str, domain: str = "finance") -> FinanceHarness:
    config = SpecialistConfig(name=name, domain=domain, description=f"Replica {name}")
    return FinanceHarness(config=config)


# ── Registration & Routing ──

class TestLoadBalancerRegistration:
    def test_register_and_route(self, load_balancer, finance_pool):
        harness = _make_harness("finance-1")
        finance_pool.add_replica(harness)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        result = load_balancer.route(Domain.FINANCE)
        assert result is not None
        assert result.config.name == "finance-1"

    def test_route_unknown_domain_returns_none(self, load_balancer):
        assert load_balancer.route(Domain.CODE) is None

    def test_unregister_pool(self, load_balancer, finance_pool):
        harness = _make_harness("finance-1")
        finance_pool.add_replica(harness)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        load_balancer.unregister_pool(Domain.FINANCE)
        assert load_balancer.route(Domain.FINANCE) is None


# ── Routing Strategies ──

class TestLoadBalancerStrategies:
    def test_round_robin(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        h2 = _make_harness("finance-2")
        finance_pool.add_replica(h1)
        finance_pool.add_replica(h2)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        r1 = load_balancer.route(Domain.FINANCE, strategy="round_robin")
        r2 = load_balancer.route(Domain.FINANCE, strategy="round_robin")
        r3 = load_balancer.route(Domain.FINANCE, strategy="round_robin")

        assert r1 == h1
        assert r2 == h2
        assert r3 == h1

    def test_least_loaded(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        h2 = _make_harness("finance-2")
        h3 = _make_harness("finance-3")

        # Simulate different load levels via active_spawns
        h1._active_spawns = {"a": None, "b": None, "c": None}  # 3
        h2._active_spawns = {"a": None}  # 1
        h3._active_spawns = {"a": None, "b": None}  # 2

        finance_pool.add_replica(h1)
        finance_pool.add_replica(h2)
        finance_pool.add_replica(h3)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)
        result = load_balancer.route(Domain.FINANCE, strategy="least_loaded")
        assert result == h2

    def test_healthiest(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        h2 = _make_harness("finance-2")
        finance_pool.add_replica(h1)
        finance_pool.add_replica(h2)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        finance_pool.update_health("finance-1", 0.3)
        finance_pool.update_health("finance-2", 0.9)

        result = load_balancer.route(Domain.FINANCE, strategy="healthiest")
        assert result == h2

        finance_pool.update_health("finance-1", 1.0)
        result = load_balancer.route(Domain.FINANCE, strategy="healthiest")
        assert result == h1

    def test_random_strategy(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        finance_pool.add_replica(h1)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        result = load_balancer.route(Domain.FINANCE, strategy="random")
        assert result == h1

    def test_unknown_strategy_raises(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        finance_pool.add_replica(h1)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        with pytest.raises(ValueError, match="Unknown strategy"):
            load_balancer.route(Domain.FINANCE, strategy="invalid")


# ── Health-Aware Exclusion ──

class TestLoadBalancerHealthExclusion:
    def test_excludes_unhealthy_replicas(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        h2 = _make_harness("finance-2")
        finance_pool.add_replica(h1)
        finance_pool.add_replica(h2)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        finance_pool.update_health("finance-1", 0.4)  # unhealthy
        finance_pool.update_health("finance-2", 0.9)  # healthy

        for _ in range(10):
            result = load_balancer.route(Domain.FINANCE, strategy="round_robin")
            assert result == h2

    def test_fallback_to_least_bad_when_all_unhealthy(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        h2 = _make_harness("finance-2")
        finance_pool.add_replica(h1)
        finance_pool.add_replica(h2)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        finance_pool.update_health("finance-1", 0.1)
        finance_pool.update_health("finance-2", 0.3)

        # All unhealthy — should fall back to least-bad (highest score = h2)
        result = load_balancer.route(Domain.FINANCE, strategy="healthiest")
        assert result == h2

    def test_empty_pool_returns_none(self, load_balancer, finance_pool):
        load_balancer.register_pool(Domain.FINANCE, finance_pool)
        assert load_balancer.route(Domain.FINANCE) is None


# ── Scaling ──

class TestLoadBalancerScaling:
    def test_scale_up_adds_replica(self, load_balancer, finance_pool):
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        counter = 0
        def factory() -> FinanceHarness:
            nonlocal counter
            counter += 1
            return _make_harness(f"finance-{counter}")

        assert load_balancer.scale_up(Domain.FINANCE, factory) is True
        assert finance_pool.replica_count() == 1
        assert finance_pool.is_available() is True

        assert load_balancer.scale_up(Domain.FINANCE, factory) is True
        assert finance_pool.replica_count() == 2

    def test_scale_up_respects_max_replicas(self, load_balancer, finance_pool):
        finance_pool.max_replicas = 1
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        def factory() -> FinanceHarness:
            return _make_harness("finance-1")

        assert load_balancer.scale_up(Domain.FINANCE, factory) is True
        assert load_balancer.scale_up(Domain.FINANCE, factory) is False
        assert finance_pool.replica_count() == 1

    def test_scale_up_unknown_domain_returns_false(self, load_balancer):
        def factory() -> FinanceHarness:
            return _make_harness("finance-1")

        assert load_balancer.scale_up(Domain.FINANCE, factory) is False

    def test_scale_up_factory_exception_returns_false(self, load_balancer, finance_pool):
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        def factory() -> FinanceHarness:
            raise RuntimeError("boom")

        assert load_balancer.scale_up(Domain.FINANCE, factory) is False

    def test_scale_down_removes_replica(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        h2 = _make_harness("finance-2")
        finance_pool.add_replica(h1)
        finance_pool.add_replica(h2)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        assert load_balancer.scale_down(Domain.FINANCE, "finance-1") is True
        assert finance_pool.replica_count() == 1
        assert h1 not in finance_pool.all_replicas()

    def test_scale_down_unknown_domain_returns_false(self, load_balancer):
        assert load_balancer.scale_down(Domain.FINANCE, "finance-1") is False

    def test_scale_down_unknown_replica_returns_false(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        finance_pool.add_replica(h1)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        assert load_balancer.scale_down(Domain.FINANCE, "unknown") is False


# ── Domain Availability ──

class TestLoadBalancerAvailability:
    def test_get_available_domains(self, load_balancer, finance_pool, maths_pool):
        h1 = _make_harness("finance-1")
        h2 = _make_harness("maths-1", domain="maths")

        finance_pool.add_replica(h1)
        maths_pool.add_replica(h2)

        load_balancer.register_pool(Domain.FINANCE, finance_pool)
        load_balancer.register_pool(Domain.MATHS, maths_pool)

        # Both healthy
        domains = load_balancer.get_available_domains()
        assert Domain.FINANCE in domains
        assert Domain.MATHS in domains

    def test_unhealthy_domain_not_available(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        finance_pool.add_replica(h1)
        finance_pool.update_health("finance-1", 0.3)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        assert load_balancer.get_available_domains() == []

    def test_empty_pool_not_available(self, load_balancer, finance_pool):
        load_balancer.register_pool(Domain.FINANCE, finance_pool)
        assert load_balancer.get_available_domains() == []


# ── Health Summary ──

class TestLoadBalancerHealthSummary:
    def test_health_summary(self, load_balancer, finance_pool, maths_pool):
        h1 = _make_harness("finance-1")
        h2 = _make_harness("finance-2")
        h3 = _make_harness("maths-1", domain="maths")

        finance_pool.add_replica(h1)
        finance_pool.add_replica(h2)
        maths_pool.add_replica(h3)

        finance_pool.update_health("finance-1", 0.8)
        finance_pool.update_health("finance-2", 0.4)

        load_balancer.register_pool(Domain.FINANCE, finance_pool)
        load_balancer.register_pool(Domain.MATHS, maths_pool)

        summary = load_balancer.health_summary()

        assert "finance" in summary
        assert "maths" in summary
        assert summary["finance"]["replicas"] == 2
        assert summary["finance"]["replica_health"]["finance-1"] == 0.8
        assert summary["finance"]["replica_health"]["finance-2"] == 0.4
        assert summary["maths"]["replicas"] == 1
        assert summary["maths"]["replica_health"]["maths-1"] == 1.0

    def test_health_summary_empty_pool(self, load_balancer, finance_pool):
        load_balancer.register_pool(Domain.FINANCE, finance_pool)
        summary = load_balancer.health_summary()
        assert summary == {"finance": {"replicas": 0, "replica_health": {}}}


# ── Thread Safety ──

class TestLoadBalancerThreadSafety:
    def test_concurrent_routing_and_scaling(self, load_balancer, finance_pool):
        h1 = _make_harness("finance-1")
        finance_pool.add_replica(h1)
        load_balancer.register_pool(Domain.FINANCE, finance_pool)

        errors: list[Exception] = []
        results: list[Any] = []

        def worker():
            try:
                for _ in range(50):
                    r = load_balancer.route(Domain.FINANCE, strategy="round_robin")
                    if r is not None:
                        results.append(r.config.name)
                    load_balancer.health_summary()
                    load_balancer.get_available_domains()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 500
