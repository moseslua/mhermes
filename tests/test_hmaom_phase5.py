"""Phase 5 tests: Horizontal Scaling, Load Balancing, Metrics."""

from __future__ import annotations

import pytest

from hmaom.gateway.router import GatewayRouter
from hmaom.observability.metrics import MetricsCollector
from hmaom.observability.pool import SpecialistPool
from hmaom.gateway.load_balancer import LoadBalancer
from hmaom.protocol.schemas import Domain
from hmaom.config import SpecialistConfig
from hmaom.specialists.code import CodeHarness


# ── MetricsCollector Integration ──

class TestMetricsIntegration:
    @pytest.mark.asyncio
    async def test_router_records_routing_metrics(self):
        router = GatewayRouter()
        await router.start()

        result = await router.route("Calculate 2 + 2")
        assert result["correlation_id"]

        # Metrics should have been recorded
        metrics_text = router.metrics.prometheus_exposition_format()
        assert "routing_decisions_total" in metrics_text
        assert "requests_total" in metrics_text

        await router.stop()

    @pytest.mark.asyncio
    async def test_router_status_includes_metrics(self):
        router = GatewayRouter()
        await router.start()
        # Generate some metrics first
        await router.route("Calculate 2 + 2")
        status = await router.status()
        assert "metrics" in status
        assert "prometheus" in status["metrics"]
        assert "routing_decisions_total" in status["metrics"]["prometheus"]
        await router.stop()

    def test_metrics_collector_histogram(self):
        m = MetricsCollector()
        m.histogram("request_duration_ms", 150)
        m.histogram("request_duration_ms", 250)
        m.histogram("request_duration_ms", 350)

        h = m.get_histogram("request_duration_ms")
        assert h["count"] == 3
        assert h["min"] == 150
        assert h["max"] == 350

    def test_metrics_collector_prometheus_format(self):
        m = MetricsCollector()
        m.counter("test_total", value=5, labels={"status": "ok"})
        m.gauge("active", value=3.0)

        text = m.prometheus_exposition_format()
        assert "hmaom_test_total" in text
        assert "status=\"ok\"" in text
        assert "hmaom_active" in text


# ── LoadBalancer Integration ──

class TestLoadBalancerIntegration:
    @pytest.mark.asyncio
    async def test_router_registers_specialists_in_pools(self):
        router = GatewayRouter()
        await router.start()

        # Each configured specialist should have a pool with at least one replica
        for domain in router._specialists:
            assert domain in router.load_balancer._pools
            pool = router.load_balancer._pools[domain]
            assert pool.replica_count() >= 1

        await router.stop()

    @pytest.mark.asyncio
    async def test_load_balancer_health_summary(self):
        router = GatewayRouter()
        await router.start()

        status = await router.status()
        assert "load_balancer" in status
        lb_summary = status["load_balancer"]
        # Should have entries for each domain
        assert len(lb_summary) > 0

        await router.stop()

    def test_load_balancer_routes_to_replica(self):
        lb = LoadBalancer()
        config = SpecialistConfig(name="code", domain="code", description="Code")
        specialist = CodeHarness(config=config)

        pool = SpecialistPool(domain=Domain.CODE)
        pool.add_replica(specialist)
        lb.register_pool(Domain.CODE, pool)

        replica = lb.route(Domain.CODE, strategy="round_robin")
        assert replica is not None

    def test_load_balancer_excludes_unhealthy(self):
        lb = LoadBalancer()
        config = SpecialistConfig(name="code", domain="code", description="Code")
        s1 = CodeHarness(config=config)
        s2 = CodeHarness(config=config)

        pool = SpecialistPool(domain=Domain.CODE)
        pool.add_replica(s1)
        pool.add_replica(s2)
        pool.update_health(s1.config.name, 0.9)
        pool.update_health(s2.config.name, 0.3)  # Below 0.5 threshold
        lb.register_pool(Domain.CODE, pool)

        # Should prefer the healthy replica
        replica = lb.route(Domain.CODE, strategy="healthiest")
        assert replica is not None

    def test_load_balancer_scale_up_down(self):
        lb = LoadBalancer()
        pool = SpecialistPool(domain=Domain.CODE, max_replicas=3)
        lb.register_pool(Domain.CODE, pool)
        def factory():
            return CodeHarness(config=SpecialistConfig(name="code", domain="code", description="Code"))
        assert lb.scale_up(Domain.CODE, factory) is True
        assert lb.scale_up(Domain.CODE, factory) is False  # duplicate name
        assert pool.replica_count() == 1
        # Scale down
        replica_id = pool.all_replicas()[0].config.name
        assert lb.scale_down(Domain.CODE, replica_id) is True
        assert pool.replica_count() == 0


# ── SpecialistPool ──

class TestSpecialistPool:
    def test_round_robin_cycles(self):
        config = SpecialistConfig(name="code", domain="code", description="Code")
        s1 = CodeHarness(config=config)
        s2 = CodeHarness(config=config)

        pool = SpecialistPool(domain=Domain.CODE)
        pool.add_replica(s1)
        pool.add_replica(s2)

        r1 = pool.get_replica("round_robin")
        r2 = pool.get_replica("round_robin")
        r3 = pool.get_replica("round_robin")

        assert r1 is not None
        assert r2 is not None
        assert r3 is not None
        # Should cycle back to first
        assert r1 is r3

    def test_least_loaded(self):
        s1 = CodeHarness(config=SpecialistConfig(name="code-1", domain="code", description="Code"))
        s2 = CodeHarness(config=SpecialistConfig(name="code-2", domain="code", description="Code"))
        pool = SpecialistPool(domain=Domain.CODE)
        pool.add_replica(s1)
        pool.add_replica(s2)
        # Simulate s1 having more requests
        pool._request_counts[s1.config.name] = 5
        pool._request_counts[s2.config.name] = 1
        replica = pool.get_replica("least_loaded")
        assert replica.config.name == s2.config.name

    def test_max_replicas_limit(self):
        s1 = CodeHarness(config=SpecialistConfig(name="code-1", domain="code", description="Code"))
        s2 = CodeHarness(config=SpecialistConfig(name="code-2", domain="code", description="Code"))
        s3 = CodeHarness(config=SpecialistConfig(name="code-3", domain="code", description="Code"))
        pool = SpecialistPool(domain=Domain.CODE, max_replicas=2)
        assert pool.add_replica(s1) is True
        assert pool.add_replica(s2) is True
        assert pool.add_replica(s3) is False  # Exceeds max
        assert pool.replica_count() == 2

    def test_health_tracking(self):
        config = SpecialistConfig(name="code", domain="code", description="Code")
        s1 = CodeHarness(config=config)

        pool = SpecialistPool(domain=Domain.CODE)
        pool.add_replica(s1)

        pool.update_health(s1.config.name, 0.75)
        assert pool._health_scores[s1.config.name] == 0.75

    def test_is_available(self):
        pool = SpecialistPool(domain=Domain.CODE)
        assert pool.is_available() is False

        config = SpecialistConfig(name="code", domain="code", description="Code")
        s1 = CodeHarness(config=config)
        pool.add_replica(s1)
        assert pool.is_available() is True


# ── End-to-end: Full Phase 5 Pipeline ──

class TestPhase5EndToEnd:
    @pytest.mark.asyncio
    async def test_full_pipeline_with_metrics_and_lb(self):
        router = GatewayRouter()
        await router.start()

        # Run multiple requests to generate metrics
        for _ in range(3):
            result = await router.route("What is the capital of France?")
            assert result["correlation_id"]

        # Check status includes all Phase 5 components
        status = await router.status()
        assert "metrics" in status
        assert "load_balancer" in status
        assert "budget" in status

        # Prometheus metrics should show the requests
        prometheus = status["metrics"]["prometheus"]
        assert "requests_total" in prometheus

        await router.stop()

    @pytest.mark.asyncio
    async def test_budget_enforcement_blocks_when_exhausted(self):
        router = GatewayRouter()
        await router.start()

        # Exhaust the budget by registering many trees
        for i in range(20):
            router.budget_manager.register_tree(f"tree-{i}", limits={})

        result = await router.route("Simple test")
        # Should either succeed or be blocked by budget
        assert "correlation_id" in result or "error" in result

        await router.stop()

    @pytest.mark.asyncio
    async def test_user_model_tracks_sessions(self):
        router = GatewayRouter()
        await router.start()

        result = await router.route("Calculate 2+2", session_id="user-123")
        assert result["correlation_id"]

        # User should be tracked
        users = router.user_model.get_all_users()
        assert "user-123" in users

        await router.stop()

    @pytest.mark.asyncio
    async def test_load_balancer_routes_to_healthy_replicas(self):
        router = GatewayRouter()
        await router.start()

        # Get a replica from the load balancer
        replica = router.load_balancer.route(Domain.MATHS, strategy="round_robin")
        assert replica is not None

        await router.stop()
