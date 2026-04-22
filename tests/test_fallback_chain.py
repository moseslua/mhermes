"""Tests for hmaom.gateway.fallback_chain.FallbackChain."""

from __future__ import annotations

import pytest

from hmaom.gateway.fallback_chain import FallbackChain


class TestChainProgression:
    def test_next_model_first(self):
        fc = FallbackChain(["model-a", "model-b", "model-c"])
        assert fc.next_model() == "model-a"

    def test_next_model_after(self):
        fc = FallbackChain(["model-a", "model-b", "model-c"])
        assert fc.next_model(after="model-a") == "model-b"
        assert fc.next_model(after="model-b") == "model-c"

    def test_next_model_last_returns_none(self):
        fc = FallbackChain(["model-a", "model-b"])
        assert fc.next_model(after="model-b") is None

    def test_next_model_unknown_returns_none(self):
        fc = FallbackChain(["model-a"])
        assert fc.next_model(after="unknown") is None

    def test_empty_chain(self):
        fc = FallbackChain([])
        assert fc.next_model() is None
        assert fc.next_model(after="x") is None

    def test_chain_property(self):
        fc = FallbackChain(["a", "b"])
        assert fc.chain == ["a", "b"]
        fc.chain.append("c")  # should not mutate internal state
        assert fc.chain == ["a", "b"]


class TestHealthTracking:
    def test_initial_health(self):
        fc = FallbackChain(["a", "b"])
        assert fc.health_snapshot() == {"a": 1.0, "b": 1.0}

    def test_record_success(self):
        fc = FallbackChain(["a"])
        fc.record_success("a")
        assert fc.health_snapshot()["a"] == 1.0  # capped at 1.0

    def test_record_success_boosts_from_low(self):
        fc = FallbackChain(["a"])
        fc.record_failure("a")
        fc.record_failure("a")
        fc.record_success("a")
        assert fc.health_snapshot()["a"] == pytest.approx(0.7)

    def test_record_failure(self):
        fc = FallbackChain(["a"])
        fc.record_failure("a")
        assert fc.health_snapshot()["a"] == 0.8

    def test_record_failure_clamps_at_zero(self):
        fc = FallbackChain(["a"])
        for _ in range(10):
            fc.record_failure("a")
        assert fc.health_snapshot()["a"] == 0.0

    def test_health_for_unknown_model(self):
        fc = FallbackChain(["a"])
        fc.record_success("unknown")
        assert fc.health_snapshot()["unknown"] == 0.6  # 0.5 + 0.1


class TestHealthyModels:
    def test_all_healthy(self):
        fc = FallbackChain(["a", "b", "c"])
        assert fc.get_healthy_models() == ["a", "b", "c"]

    def test_threshold_filters(self):
        fc = FallbackChain(["a", "b", "c"])
        fc.record_failure("b")  # 0.8
        fc.record_failure("b")  # 0.6
        fc.record_failure("b")  # 0.4
        assert fc.get_healthy_models(threshold=0.5) == ["a", "c"]

    def test_threshold_default(self):
        fc = FallbackChain(["a", "b"])
        fc.record_failure("b")  # 0.8 still >= 0.5
        assert fc.get_healthy_models() == ["a", "b"]
        fc.record_failure("b")  # 0.6 still >= 0.5
        assert fc.get_healthy_models() == ["a", "b"]
        fc.record_failure("b")  # 0.4 now below
        assert fc.get_healthy_models() == ["a"]

    def test_order_preserved(self):
        fc = FallbackChain(["c", "a", "b"])
        fc.record_failure("a")
        fc.record_failure("a")
        fc.record_failure("a")  # 0.4
        assert fc.get_healthy_models(threshold=0.5) == ["c", "b"]



class TestFallbackSequence:
    def test_full_sequence(self):
        fc = FallbackChain(["a", "b", "c", "d"])
        assert fc.fallback_sequence("b") == ["b", "c", "d"]

    def test_sequence_from_first(self):
        fc = FallbackChain(["a", "b", "c"])
        assert fc.fallback_sequence("a") == ["a", "b", "c"]

    def test_sequence_from_last(self):
        fc = FallbackChain(["a", "b"])
        assert fc.fallback_sequence("b") == ["b"]

    def test_sequence_unknown_model(self):
        fc = FallbackChain(["a", "b"])
        assert fc.fallback_sequence("z") == []


class TestIntegration:
    def test_typical_fallback_walk(self):
        fc = FallbackChain(["claude-sonnet", "gpt-4", "local-llm"])
        current = "claude-sonnet"
        path = []
        while current:
            path.append(current)
            current = fc.next_model(after=current)
        assert path == ["claude-sonnet", "gpt-4", "local-llm"]

    def test_health_decline_changes_healthy_set(self):
        fc = FallbackChain(["primary", "secondary", "tertiary"])
        fc.record_failure("primary")
        fc.record_failure("primary")
        fc.record_failure("primary")  # 0.4
        healthy = fc.get_healthy_models(threshold=0.5)
        assert healthy == ["secondary", "tertiary"]
        seq = fc.fallback_sequence("primary")
        assert seq == ["primary", "secondary", "tertiary"]
