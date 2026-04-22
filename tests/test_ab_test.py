"""Tests for hmaom.gateway.ab_test.ABTestRouter."""

import math

import pytest

from hmaom.gateway.ab_test import ABTestRouter


class TestRegisterVariant:
    def test_register_single(self):
        router = ABTestRouter()
        router.register_variant("v1", {"model": "a"}, 0.5)
        assert router.list_variants() == ["v1"]

    def test_register_multiple(self):
        router = ABTestRouter()
        router.register_variant("v1", {"model": "a"}, 0.3)
        router.register_variant("v2", {"model": "b"}, 0.7)
        assert set(router.list_variants()) == {"v1", "v2"}

    def test_register_bad_traffic(self):
        router = ABTestRouter()
        with pytest.raises(ValueError):
            router.register_variant("v1", {}, 1.5)
        with pytest.raises(ValueError):
            router.register_variant("v1", {}, -0.1)

    def test_config_retrieval(self):
        router = ABTestRouter()
        router.register_variant("v1", {"model": "gpt-4"}, 0.5)
        assert router.get_variant_config("v1") == {"model": "gpt-4"}

    def test_unknown_variant_config(self):
        router = ABTestRouter()
        with pytest.raises(KeyError):
            router.get_variant_config("missing")


class TestSelectVariant:
    def test_no_variants_raises(self):
        router = ABTestRouter()
        with pytest.raises(RuntimeError):
            router.select_variant()

    def test_selects_registered(self):
        router = ABTestRouter()
        router.register_variant("v1", {}, 1.0)
        assert router.select_variant(seed=42) == "v1"

    def test_weighted_split(self):
        router = ABTestRouter()
        router.register_variant("v1", {}, 0.8)
        router.register_variant("v2", {}, 0.2)
        counts = {"v1": 0, "v2": 0}
        for i in range(1000):
            v = router.select_variant(seed=i)
            counts[v] += 1
        assert counts["v1"] > counts["v2"]
        assert counts["v1"] + counts["v2"] == 1000

    def test_zero_weights_fallback(self):
        router = ABTestRouter()
        router.register_variant("v1", {}, 0.0)
        router.register_variant("v2", {}, 0.0)
        v = router.select_variant(seed=1)
        assert v in ("v1", "v2")


class TestRecordOutcome:
    def test_records_success(self):
        router = ABTestRouter()
        router.register_variant("v1", {}, 1.0)
        router.record_outcome("v1", True)
        report = router.get_report()
        assert report["v1"]["successes"] == 1
        assert report["v1"]["n"] == 1

    def test_records_failure(self):
        router = ABTestRouter()
        router.register_variant("v1", {}, 1.0)
        router.record_outcome("v1", False)
        report = router.get_report()
        assert report["v1"]["failures"] == 1

    def test_unknown_variant_raises(self):
        router = ABTestRouter()
        with pytest.raises(KeyError):
            router.record_outcome("missing", True)

    def test_multiple_outcomes(self):
        router = ABTestRouter()
        router.register_variant("v1", {}, 1.0)
        for _ in range(5):
            router.record_outcome("v1", True)
        for _ in range(3):
            router.record_outcome("v1", False)
        report = router.get_report()
        assert report["v1"]["successes"] == 5
        assert report["v1"]["failures"] == 3
        assert report["v1"]["success_rate"] == pytest.approx(5 / 8)


class TestGetReport:
    def test_empty_report(self):
        router = ABTestRouter()
        router.register_variant("v1", {}, 1.0)
        report = router.get_report()
        assert report["v1"]["n"] == 0
        assert report["v1"]["success_rate"] == 0.0

    def test_p_value_present(self):
        router = ABTestRouter()
        router.register_variant("v1", {}, 0.5)
        router.register_variant("v2", {}, 0.5)
        for _ in range(50):
            router.record_outcome("v1", True)
            router.record_outcome("v2", False)
        report = router.get_report()
        assert report["v1"]["p_value"] is None  # baseline
        assert report["v2"]["p_value"] is not None
        # v2 is far worse than v1 → small p-value
        assert report["v2"]["p_value"] < 0.05

    def test_p_value_no_difference(self):
        router = ABTestRouter()
        router.register_variant("v1", {}, 0.5)
        router.register_variant("v2", {}, 0.5)
        for _ in range(100):
            router.record_outcome("v1", True)
            router.record_outcome("v2", True)
        report = router.get_report()
        assert report["v2"]["p_value"] > 0.05

    def test_report_structure(self):
        router = ABTestRouter()
        router.register_variant("a", {"m": 1}, 0.5)
        router.register_variant("b", {"m": 2}, 0.5)
        router.record_outcome("a", True)
        router.record_outcome("b", False)
        report = router.get_report()
        for name in ("a", "b"):
            assert "n" in report[name]
            assert "successes" in report[name]
            assert "failures" in report[name]
            assert "success_rate" in report[name]
            assert "p_value" in report[name]
