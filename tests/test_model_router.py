"""Tests for hmaom.gateway.model_router.

Covers: complexity-based routing, priority-based routing, budget constraints,
historical success, latency SLA, cost estimation, outcome recording, model
registration, and edge cases.
"""

from __future__ import annotations

import pytest

from hmaom.config import CostAwareConfig
from hmaom.gateway.model_router import CostAwareRouter, ModelConfig, ModelTier
from hmaom.protocol.schemas import Domain, TaskDescription
from hmaom.state.budget_manager import GlobalBudgetManager
from hmaom.state.user_model import UserModel


@pytest.fixture
def cost_aware_config():
    """Provide a default CostAwareConfig with a small model catalog."""
    return CostAwareConfig(
        enabled=True,
        default_models={"code": "gpt-4o", "finance": "claude-sonnet-4"},
        model_catalog=[
            {
                "name": "gpt-3.5",
                "tier": "fast",
                "cost_per_1k_tokens": 0.5,
                "latency_ms_typical": 500,
                "max_context": 4096,
            },
            {
                "name": "claude-sonnet-4",
                "tier": "standard",
                "cost_per_1k_tokens": 3.0,
                "latency_ms_typical": 2000,
                "max_context": 200_000,
            },
            {
                "name": "gpt-4o",
                "tier": "thorough",
                "cost_per_1k_tokens": 10.0,
                "latency_ms_typical": 4000,
                "max_context": 128_000,
            },
        ],
        cost_threshold_usd=5.0,
        latency_sla_ms={"low": 30000, "medium": 15000, "high": 10000, "critical": 5000},
        success_rate_threshold=0.95,
    )


@pytest.fixture
def budget_manager():
    """Provide a GlobalBudgetManager with ample budget."""
    return GlobalBudgetManager(
        max_global_tokens=1_000_000,
        max_global_cost_usd=100.0,
        max_global_time_ms=600_000,
        max_concurrent_trees=10,
    )


@pytest.fixture
def user_model(tmp_path):
    """Provide a UserModel backed by a temporary SQLite file."""
    db_path = str(tmp_path / "user_model.sqlite")
    model = UserModel(db_path=db_path)
    yield model
    model.close()


@pytest.fixture
def router(cost_aware_config, budget_manager, user_model):
    """Provide a fully wired CostAwareRouter."""
    return CostAwareRouter(
        config=cost_aware_config,
        budget_manager=budget_manager,
        user_model=user_model,
    )


class TestComplexityRouting:
    """Complexity maps to tier: low -> fast, mid -> standard, high -> thorough."""

    def test_low_complexity_selects_fast(self, router):
        task = TaskDescription(title="simple", description="add 2+2", priority="medium")
        model = router.select_model(Domain.CODE, task, complexity=2)
        assert model == "gpt-3.5"

    def test_mid_complexity_selects_standard(self, router):
        task = TaskDescription(title="medium", description="refactor a module", priority="medium")
        model = router.select_model(Domain.CODE, task, complexity=5)
        assert model == "claude-sonnet-4"

    def test_high_complexity_selects_thorough(self, router):
        task = TaskDescription(title="hard", description="design a distributed system", priority="medium")
        model = router.select_model(Domain.CODE, task, complexity=9)
        assert model == "gpt-4o"


class TestPriorityRouting:
    """Critical/high upgrades tier; low downgrades tier."""

    def test_critical_upgrades_to_thorough(self, router):
        task = TaskDescription(title="urgent", description="fix prod bug", priority="critical")
        # complexity 5 would normally be standard, but critical upgrades to thorough
        model = router.select_model(Domain.CODE, task, complexity=5)
        assert model == "gpt-4o"

    def test_high_upgrades_to_thorough(self, router):
        task = TaskDescription(title="important", description="security review", priority="high")
        model = router.select_model(Domain.CODE, task, complexity=5)
        assert model == "gpt-4o"

    def test_low_downgrades_to_fast(self, router):
        task = TaskDescription(title="chore", description="format code", priority="low")
        # complexity 5 would normally be standard, but low downgrades to fast
        model = router.select_model(Domain.CODE, task, complexity=5)
        assert model == "gpt-3.5"


class TestBudgetConstraint:
    """When remaining budget is tight, router downgrades tier."""

    def test_budget_downgrade_to_standard(self, cost_aware_config, user_model):
        # Moderate budget: $15 remaining
        bm = GlobalBudgetManager(
            max_global_tokens=1_000_000,
            max_global_cost_usd=15.0,
            max_global_time_ms=600_000,
            max_concurrent_trees=10,
        )
        router = CostAwareRouter(config=cost_aware_config, budget_manager=bm, user_model=user_model)
        task = TaskDescription(title="hard", description="design system", priority="medium")
        # complexity 9 wants thorough (gpt-4o @ ~$45), but budget forces downgrade to standard (~$13.5)
        model = router.select_model(Domain.CODE, task, complexity=9)
        assert model == "claude-sonnet-4"

    def test_budget_downgrade_to_fast(self, cost_aware_config, user_model):
        # Very tight budget: only $0.10 remaining
        bm = GlobalBudgetManager(
            max_global_tokens=1_000_000,
            max_global_cost_usd=0.10,
            max_global_time_ms=600_000,
            max_concurrent_trees=10,
        )
        router = CostAwareRouter(config=cost_aware_config, budget_manager=bm, user_model=user_model)
        task = TaskDescription(title="hard", description="design system", priority="medium")
        model = router.select_model(Domain.CODE, task, complexity=9)
        assert model == "gpt-3.5"

    def test_no_budget_falls_back_to_fast(self, cost_aware_config, user_model):
        # Zero budget manager (no headroom)
        bm = GlobalBudgetManager(
            max_global_tokens=0,
            max_global_cost_usd=0.0,
            max_global_time_ms=0,
            max_concurrent_trees=0,
        )
        router = CostAwareRouter(config=cost_aware_config, budget_manager=bm, user_model=user_model)
        task = TaskDescription(title="anything", description="do something", priority="medium")
        model = router.select_model(Domain.CODE, task, complexity=5)
        assert model == "gpt-3.5"


class TestHistoricalSuccess:
    """If a cheaper model has >= 95% success rate for this domain, prefer it."""

    def test_historical_success_prefers_cheaper(self, router, user_model):
        # Seed 8 successes so EMA exceeds 0.95 threshold
        for _ in range(8):
            user_model.record_model_outcome("alice", "code", "gpt-3.5", success=True)

        task = TaskDescription(title="medium", description="refactor module", priority="medium")
        model = router.select_model(Domain.CODE, task, complexity=5, session_id="alice")
        # complexity 5 -> standard normally, but gpt-3.5 (fast) has high success rate
        assert model == "gpt-3.5"

    def test_no_history_uses_complexity(self, router):
        task = TaskDescription(title="medium", description="refactor module", priority="medium")
        model = router.select_model(Domain.CODE, task, complexity=5, session_id="new_user")
        assert model == "claude-sonnet-4"


class TestLatencySla:
    """If estimated latency > priority SLA, downgrade tier."""

    def test_latency_sla_enforcement(self, cost_aware_config, user_model):
        bm = GlobalBudgetManager(
            max_global_tokens=1_000_000,
            max_global_cost_usd=100.0,
            max_global_time_ms=600_000,
            max_concurrent_trees=10,
        )
        router = CostAwareRouter(config=cost_aware_config, budget_manager=bm, user_model=user_model)
        # critical SLA is 5000ms; thorough model latency is 4000ms (ok)
        # But standard is 2000ms. Let's force a scenario where all models in tier exceed SLA.
        # Register an artificially slow thorough model
        router.register_model(
            name="slow-thorough",
            tier=ModelTier.THOROUGH,
            cost_per_1k_tokens=15.0,
            latency_ms_typical=6000,
            max_context=128_000,
        )
        # Set default to the slow model so it gets selected for thorough tier
        router._default_models[Domain.CODE] = "slow-thorough"
        router._models["gpt-4o"].latency_ms_typical = 6000  # also slow

        task = TaskDescription(title="critical", description="fix outage", priority="critical")
        # complexity 9 -> thorough, but thorough models exceed 5000ms SLA
        # should downgrade to standard (claude-sonnet-4 @ 2000ms)
        model = router.select_model(Domain.CODE, task, complexity=9)
        assert model == "claude-sonnet-4"


class TestCostEstimation:
    """estimate_cost returns reasonable values."""

    def test_estimate_cost_accuracy(self, router):
        # gpt-3.5: 500 tokens * 2 complexity / 1000 * 0.5 = 0.5
        cost = router.estimate_cost(Domain.CODE, "gpt-3.5", complexity=2)
        assert cost == pytest.approx(0.5, abs=0.01)

    def test_estimate_cost_for_thorough(self, router):
        # gpt-4o: 500 tokens * 10 complexity / 1000 * 10.0 = 50.0
        cost = router.estimate_cost(Domain.CODE, "gpt-4o", complexity=10)
        assert cost == pytest.approx(50.0, abs=0.01)

    def test_estimate_cost_unknown_model(self, router):
        cost = router.estimate_cost(Domain.CODE, "nonexistent", complexity=5)
        assert cost == 0.0


class TestOutcomeRecording:
    """record_outcome feeds data back into user_model."""

    def test_record_outcome_updates_user_model(self, router, user_model):
        router.record_outcome(
            domain=Domain.CODE,
            model="gpt-3.5",
            success=True,
            tokens_used=100,
            latency_ms=500,
            session_id="alice",
        )
        rate = user_model.get_model_success_rate("alice", "code", "gpt-3.5")
        assert rate > 0.5  # EMA from 0.5 upward after success

    def test_record_outcome_no_user_model(self, cost_aware_config):
        router = CostAwareRouter(config=cost_aware_config, budget_manager=None, user_model=None)
        # Should not raise
        router.record_outcome(
            domain=Domain.CODE,
            model="gpt-3.5",
            success=True,
            tokens_used=100,
            latency_ms=500,
        )


class TestModelRegistration:
    """Models can be registered dynamically."""

    def test_register_model(self, router):
        router.register_model(
            name="new-model",
            tier=ModelTier.STANDARD,
            cost_per_1k_tokens=2.0,
            latency_ms_typical=1500,
            max_context=8192,
        )
        assert "new-model" in router._models
        cfg = router._models["new-model"]
        assert cfg.tier == ModelTier.STANDARD
        assert cfg.cost_per_1k_tokens == 2.0


class TestEdgeCases:
    """Boundary conditions and fallback behavior."""

    def test_disabled_returns_default(self, cost_aware_config, budget_manager, user_model):
        config = cost_aware_config
        config.enabled = False
        router = CostAwareRouter(config=config, budget_manager=budget_manager, user_model=user_model)
        task = TaskDescription(title="anything", description="do something", priority="medium")
        model = router.select_model(Domain.CODE, task, complexity=9)
        assert model == "gpt-4o"  # default for code

    def test_unknown_domain_fallback(self, router):
        task = TaskDescription(title="unknown", description="do something", priority="medium")
        # Domain.META has no default; should fall back to first registered model
        model = router.select_model(Domain.META, task, complexity=5)
        assert model in router._models

    def test_empty_catalog_fallback(self, budget_manager, user_model):
        config = CostAwareConfig(enabled=True, default_models={}, model_catalog=[])
        router = CostAwareRouter(config=config, budget_manager=budget_manager, user_model=user_model)
        task = TaskDescription(title="empty", description="do something", priority="medium")
        model = router.select_model(Domain.CODE, task, complexity=5)
        assert model == "claude-sonnet-4"  # hardcoded ultimate fallback

    def test_get_recommendations(self, router):
        recs = router.get_recommendations(Domain.CODE)
        assert len(recs) == 3
        # Should be sorted by cost ascending
        costs = [r["cost_per_1k_tokens"] for r in recs]
        assert costs == sorted(costs)
        assert all("estimated_cost_low" in r for r in recs)
        assert all("estimated_cost_high" in r for r in recs)
