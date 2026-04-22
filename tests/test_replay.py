"""Tests for ReplayEngine."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from hmaom.gateway.router import GatewayRouter
from hmaom.protocol.schemas import Domain, RoutingDecision, RoutingMode
from hmaom.qa.replay import ReplayEngine


class TestReplayEngine:
    @pytest.fixture
    def engine(self):
        return ReplayEngine(":memory:")

    @pytest.fixture
    def mock_router(self):
        router = AsyncMock(spec=GatewayRouter)
        return router

    def test_record_and_retrieve(self, engine):
        decision = RoutingDecision(
            primary_domain=Domain.FINANCE,
            routing_mode=RoutingMode.SINGLE,
            confidence=0.95,
        )
        result = {"answer": 42}
        engine.record("corr-1", "What is the price?", decision, result)

        snapshot = engine._get_snapshot("corr-1")
        assert snapshot is not None
        assert snapshot["user_input"] == "What is the price?"
        assert snapshot["routing_decision"]["primary_domain"] == "finance"
        assert snapshot["result"]["answer"] == 42

    def test_record_overwrite(self, engine):
        decision = RoutingDecision(primary_domain=Domain.FINANCE, routing_mode=RoutingMode.SINGLE)
        engine.record("corr-1", "first", decision, {"a": 1})
        engine.record("corr-1", "second", decision, {"a": 2})

        snapshot = engine._get_snapshot("corr-1")
        assert snapshot["user_input"] == "second"
        assert snapshot["result"]["a"] == 2

    def test_snapshot_count(self, engine):
        decision = RoutingDecision(primary_domain=Domain.FINANCE, routing_mode=RoutingMode.SINGLE)
        engine.record("c1", "q1", decision, {})
        engine.record("c2", "q2", decision, {})
        assert engine.snapshot_count() == 2

    def test_clear(self, engine):
        decision = RoutingDecision(primary_domain=Domain.FINANCE, routing_mode=RoutingMode.SINGLE)
        engine.record("c1", "q1", decision, {})
        engine.clear()
        assert engine.snapshot_count() == 0

    @pytest.mark.asyncio
    async def test_replay_matches(self, engine, mock_router):
        decision = RoutingDecision(
            primary_domain=Domain.FINANCE,
            routing_mode=RoutingMode.SINGLE,
            confidence=0.9,
        )
        engine.record("corr-1", "What is the price?", decision, {"value": 100})

        mock_router.route.return_value = {
            "routing_decision": decision.model_dump(),
            "result": {"value": 100},
        }

        report = await engine.replay("corr-1", mock_router)
        assert report["correlation_id"] == "corr-1"
        assert report["regression"] is False
        assert report["diff"] == {}
        mock_router.route.assert_awaited_once_with("What is the price?")

    @pytest.mark.asyncio
    async def test_replay_detects_regression(self, engine, mock_router):
        decision = RoutingDecision(
            primary_domain=Domain.FINANCE,
            routing_mode=RoutingMode.SINGLE,
            confidence=0.9,
        )
        engine.record("corr-1", "What is the price?", decision, {"value": 100})

        new_decision = RoutingDecision(
            primary_domain=Domain.CODE,
            routing_mode=RoutingMode.SINGLE,
            confidence=0.8,
        )
        mock_router.route.return_value = {
            "routing_decision": new_decision.model_dump(),
            "result": {"value": 200},
        }

        report = await engine.replay("corr-1", mock_router)
        assert report["regression"] is True
        assert "routing_decision" in report["diff"]
        assert "result" in report["diff"]

    @pytest.mark.asyncio
    async def test_replay_missing_snapshot(self, engine, mock_router):
        report = await engine.replay("missing", mock_router)
        assert "error" in report
        assert "No snapshot found" in report["error"]

    def test_diff_empty_when_equal(self, engine):
        a = {"routing_decision": {"x": 1}, "result": {"y": 2}}
        b = {"routing_decision": {"x": 1}, "result": {"y": 2}}
        assert engine.diff(a, b) == {}

    def test_diff_shows_routing_change(self, engine):
        a = {"routing_decision": {"x": 1}, "result": {"y": 2}}
        b = {"routing_decision": {"x": 2}, "result": {"y": 2}}
        d = engine.diff(a, b)
        assert "routing_decision" in d
        assert "result" not in d

    def test_diff_shows_result_change(self, engine):
        a = {"routing_decision": {"x": 1}, "result": {"y": 2}}
        b = {"routing_decision": {"x": 1}, "result": {"y": 3}}
        d = engine.diff(a, b)
        assert "result" in d
        assert "routing_decision" not in d

    @pytest.mark.asyncio
    async def test_regression_report(self, engine, mock_router):
        d1 = RoutingDecision(primary_domain=Domain.FINANCE, routing_mode=RoutingMode.SINGLE)
        d2 = RoutingDecision(primary_domain=Domain.CODE, routing_mode=RoutingMode.SINGLE)

        engine.record("c1", "q1", d1, {"v": 1})
        engine.record("c2", "q2", d2, {"v": 2})

        # Both replay identically -> no regressions
        mock_router.route.side_effect = [
            {"routing_decision": d1.model_dump(), "result": {"v": 1}},
            {"routing_decision": d2.model_dump(), "result": {"v": 2}},
        ]

        report = await engine.regression_report(mock_router)
        assert report == []

    @pytest.mark.asyncio
    async def test_regression_report_with_regression(self, engine, mock_router):
        d1 = RoutingDecision(primary_domain=Domain.FINANCE, routing_mode=RoutingMode.SINGLE)

        engine.record("c1", "q1", d1, {"v": 1})

        d1_changed = RoutingDecision(primary_domain=Domain.CODE, routing_mode=RoutingMode.SINGLE)
        mock_router.route.return_value = {
            "routing_decision": d1_changed.model_dump(),
            "result": {"v": 1},
        }

        report = await engine.regression_report(mock_router)
        assert len(report) == 1
        assert report[0]["correlation_id"] == "c1"
        assert report[0]["regression"] is True
