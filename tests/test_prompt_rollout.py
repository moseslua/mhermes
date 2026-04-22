"""Tests for PromptRolloutManager.

Covers: rollout start, traffic split determinism, evaluate, promote,
rollback, can_promote thresholds, and auto-rollback.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hmaom.prompts.registry import PromptRegistry
from hmaom.prompts.rollout import PromptRolloutManager


@pytest.fixture
def manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "prompts.sqlite")
        registry = PromptRegistry(db_path=db_path)
        rollout = PromptRolloutManager(registry=registry, auto_rollback=True)
        yield {"registry": registry, "rollout": rollout}


class TestPromptRolloutManager:
    def test_start_rollout_captures_old_version(self, manager):
        reg = manager["registry"]
        rollout = manager["rollout"]
        v1 = reg.register("system", "code", "old prompt")
        reg.set_active("system", "code", v1.id)
        v2 = reg.register("system", "code", "new prompt")
        info = rollout.start_rollout("system", "code", v2.id, traffic_pct=10)
        assert info["old_version_id"] == v1.id
        assert info["new_version_id"] == v2.id
        assert info["traffic_pct"] == 10
        assert info["status"] == "active"

    def test_traffic_split_determinism(self, manager):
        reg = manager["registry"]
        rollout = manager["rollout"]
        v1 = reg.register("system", "code", "old")
        reg.set_active("system", "code", v1.id)
        v2 = reg.register("system", "code", "new")
        rollout.start_rollout("system", "code", v2.id, traffic_pct=50)

        # Same request_hash should always yield same result
        results = {rollout.get_prompt_for_request("system", "code", "req-abc") for _ in range(10)}
        assert len(results) == 1

    def test_traffic_split_distribution(self, manager):
        reg = manager["registry"]
        rollout = manager["rollout"]
        v1 = reg.register("system", "code", "old")
        reg.set_active("system", "code", v1.id)
        v2 = reg.register("system", "code", "new")
        rollout.start_rollout("system", "code", v2.id, traffic_pct=10)

        new_count = 0
        for i in range(1000):
            prompt = rollout.get_prompt_for_request("system", "code", f"req-{i}")
            if prompt == "new":
                new_count += 1
        # Should be approximately 10%; allow generous margin
        assert 50 <= new_count <= 150

    def test_no_rollout_returns_active(self, manager):
        reg = manager["registry"]
        rollout = manager["rollout"]
        v1 = reg.register("system", "code", "active prompt")
        reg.set_active("system", "code", v1.id)
        assert rollout.get_prompt_for_request("system", "code", "req-1") == "active prompt"

    def test_promote(self, manager):
        reg = manager["registry"]
        rollout = manager["rollout"]
        v1 = reg.register("system", "code", "old")
        reg.set_active("system", "code", v1.id)
        v2 = reg.register("system", "code", "new")
        rollout.start_rollout("system", "code", v2.id, traffic_pct=10)
        rollout.promote("system", "code", v2.id)
        assert reg.get_active("system", "code") == "new"

    def test_rollback(self, manager):
        reg = manager["registry"]
        rollout = manager["rollout"]
        v1 = reg.register("system", "code", "old")
        reg.set_active("system", "code", v1.id)
        v2 = reg.register("system", "code", "new")
        rollout.start_rollout("system", "code", v2.id, traffic_pct=10)
        rollout.promote("system", "code", v2.id)
        rollout.rollback("system", "code")
        assert reg.get_active("system", "code") == "old"

    def test_rollback_no_active_rollout_raises(self, manager):
        rollout = manager["rollout"]
        with pytest.raises(ValueError, match="No active rollout"):
            rollout.rollback("system", "code")

    def test_can_promote_min_samples(self, manager):
        reg = manager["registry"]
        rollout = manager["rollout"]
        v1 = reg.register("system", "code", "old")
        reg.set_active("system", "code", v1.id)
        v2 = reg.register("system", "code", "new")
        rollout.start_rollout("system", "code", v2.id, traffic_pct=10)

        # Not enough samples
        assert rollout.can_promote("system", "code", v2.id, min_samples=100) is False

        # Record enough samples
        for _ in range(100):
            reg.record_outcome("system", "code", v2.version, success=True, tokens_used=1, latency_ms=1)
        assert rollout.can_promote("system", "code", v2.id, min_samples=100) is True

    def test_can_promote_error_rate_threshold(self, manager):
        reg = manager["registry"]
        rollout = manager["rollout"]
        v1 = reg.register("system", "code", "old")
        reg.set_active("system", "code", v1.id)
        v2 = reg.register("system", "code", "new")
        rollout.start_rollout("system", "code", v2.id, traffic_pct=10)

        # Old version: 10% error rate (90/100 success)
        for _ in range(90):
            reg.record_outcome("system", "code", v1.version, success=True, tokens_used=1, latency_ms=1)
        for _ in range(10):
            reg.record_outcome("system", "code", v1.version, success=False, tokens_used=1, latency_ms=1)

        # New version: 20% error rate (80/100 success) — 2x worse, exceeds 1.2 threshold
        for _ in range(80):
            reg.record_outcome("system", "code", v2.version, success=True, tokens_used=1, latency_ms=1)
        for _ in range(20):
            reg.record_outcome("system", "code", v2.version, success=False, tokens_used=1, latency_ms=1)

        assert rollout.can_promote("system", "code", v2.id, min_samples=100, error_rate_threshold=1.2) is False

        # With a 3.0 threshold it should pass
        assert rollout.can_promote("system", "code", v2.id, min_samples=100, error_rate_threshold=3.0) is True

    def test_auto_rollback_on_high_error_rate(self, manager):
        reg = manager["registry"]
        rollout = manager["rollout"]
        v1 = reg.register("system", "code", "old")
        reg.set_active("system", "code", v1.id)
        v2 = reg.register("system", "code", "new")
        rollout.start_rollout("system", "code", v2.id, traffic_pct=10)

        # Old version perfect
        for _ in range(50):
            reg.record_outcome("system", "code", v1.version, success=True, tokens_used=1, latency_ms=1)

        # New version terrible
        for _ in range(50):
            reg.record_outcome("system", "code", v2.version, success=False, tokens_used=1, latency_ms=1)

        result = rollout.evaluate_rollout("system", "code", v2.id, error_rate_threshold=1.2)
        assert result["status"] == "rolled_back"
        assert result["auto_rollback_triggered"] is True
        assert reg.get_active("system", "code") == "old"

    def test_evaluate_rollout_no_active_rollout(self, manager):
        rollout = manager["rollout"]
        result = rollout.evaluate_rollout("system", "code", 1)
        assert result["status"] == "no_active_rollout"
