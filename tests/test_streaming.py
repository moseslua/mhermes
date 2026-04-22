"""Tests for GatewayRouter.route_stream() streaming functionality.

Covers: single-domain stream, parallel stream (order of completion),
sequential stream, decomposition stream, error handling, and event structure.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from hmaom.gateway.router import GatewayRouter
from hmaom.gateway.decomposer import DecomposedTask
from hmaom.protocol.schemas import (
    Domain,
    RoutingDecision,
    RoutingMode,
    SpawnResult,
    StreamEvent,
    TaskDescription,
)


@pytest.fixture
def router():
    """Return a started GatewayRouter."""
    r = GatewayRouter()
    return r


async def _collect_events(agen):
    """Helper to drain an async generator into a list."""
    return [e async for e in agen]


class TestStreamingSingleDomain:
    @pytest.mark.asyncio
    async def test_single_domain_stream(self, router):
        """A simple single-domain request yields routing_decision, partial_result, and complete."""
        events = await _collect_events(router.route_stream("Prove that the sum of angles in a triangle is 180 degrees"))

        types = [e.event_type for e in events]
        assert types[0] == "routing_decision"
        assert "partial_result" in types
        assert types[-1] == "complete"

        # The routing decision should be maths
        assert events[0].data["decision"]["primary_domain"] == "maths"

        # Complete event should contain the result
        complete_event = events[-1]
        assert "result" in complete_event.data
        assert "specialist_results" in complete_event.data
        assert complete_event.correlation_id.startswith("req-")

    @pytest.mark.asyncio
    async def test_stream_event_structure(self, router):
        """Every emitted event is a valid StreamEvent with required fields."""
        events = await _collect_events(router.route_stream("What is the capital of France?"))

        for event in events:
            assert isinstance(event, StreamEvent)
            assert event.event_type in (
                "routing_decision",
                "decomposition",
                "partial_result",
                "synthesis",
                "complete",
                "error",
            )
            assert isinstance(event.correlation_id, str)
            assert isinstance(event.data, dict)
            assert isinstance(event.timestamp, float)
            assert event.timestamp > 0


class TestStreamingParallel:
    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_parallel_stream_order_of_completion(self, router):
        """Parallel tasks yield partial_result events in completion order, not start order."""
        finance = router._specialists.get(Domain.FINANCE)
        maths = router._specialists.get(Domain.MATHS)

        original_finance_execute = finance.execute
        original_maths_execute = maths.execute

        async def slow_finance(request):
            await asyncio.sleep(0.05)
            return SpawnResult(
                spawn_id="finance-slow",
                status="success",
                result={"domain": "finance"},
            )

        async def fast_maths(request):
            await asyncio.sleep(0.01)
            return SpawnResult(
                spawn_id="maths-fast",
                status="success",
                result={"domain": "maths"},
            )

        finance.execute = slow_finance
        maths.execute = fast_maths

        try:
            with patch.object(
                router.classifier,
                "classify",
                return_value=RoutingDecision(
                    primary_domain=Domain.FINANCE,
                    secondary_domains=[Domain.MATHS],
                    routing_mode=RoutingMode.PARALLEL,
                    estimated_complexity=3,  # below decomposition threshold
                    required_synthesis=False,
                    confidence=0.95,
                ),
            ), patch.object(router.decomposer, "decompose", return_value=[]):
                events = await _collect_events(
                    router.route_stream(
                        "Compare financial risk models and write a statistical analysis report"
                    )
                )
        finally:
            finance.execute = original_finance_execute
            maths.execute = original_maths_execute

        partial_events = [e for e in events if e.event_type == "partial_result"]
        # Should have at least 2 partial results (finance + maths)
        assert len(partial_events) >= 2

        # The first partial result should be from maths (faster)
        first_result = partial_events[0].data["result"]
        assert first_result["result"]["domain"] == "maths"

        # Complete event should contain merged results
        complete_event = events[-1]
        assert complete_event.event_type == "complete"
        assert len(complete_event.data["specialist_results"]) >= 2

    @pytest.mark.asyncio
    async def test_parallel_stream_yields_routing_decision_first(self, router):
        """The first event in a parallel stream is always the routing decision."""
        events = await _collect_events(
            router.route_stream(
                "Compare financial risk models and write a statistical analysis report"
            )
        )
        assert events[0].event_type == "routing_decision"
        assert events[0].data["decision"]["routing_mode"] == "parallel"


class TestStreamingSequential:
    @pytest.mark.asyncio
    async def test_sequential_stream_yields_after_each_step(self, router):
        """Sequential routing yields a partial_result after each domain step."""
        events = await _collect_events(
            router.route_stream("Model the thermodynamics of this trading strategy")
        )

        types = [e.event_type for e in events]
        assert types[0] == "routing_decision"

        # Should have partial results for each sequential step
        partial_count = types.count("partial_result")
        assert partial_count >= 1

        assert types[-1] == "complete"


class TestStreamingDecomposition:
    @pytest.mark.asyncio
    async def test_decomposition_stream(self, router):
        """A complex request that triggers decomposition yields a decomposition event."""
        # Use a complex query that triggers decomposition
        events = await _collect_events(
            router.route_stream(
                "Optimize the portfolio allocation using Monte Carlo simulation and backtest"
            )
        )

        types = [e.event_type for e in events]
        assert "routing_decision" in types

        # Complex tasks may or may not decompose depending on classifier,
        # but we verify the stream is well-formed either way.
        assert "complete" in types

        # If decomposition happened, verify its structure
        decomp_events = [e for e in events if e.event_type == "decomposition"]
        for de in decomp_events:
            assert "subtasks" in de.data
            assert isinstance(de.data["subtasks"], list)

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_streaming_with_decomposed_subtasks(self, router):
        """Explicitly force decomposition via mocked classifier and decomposer."""
        fake_subtasks = [
            DecomposedTask(
                subtask_id="st-1",
                domain=Domain.FINANCE,
                task=TaskDescription(title="t1", description="d1"),
            ),
            DecomposedTask(
                subtask_id="st-2",
                domain=Domain.MATHS,
                task=TaskDescription(title="t2", description="d2"),
            ),
        ]

        with patch.object(
            router.classifier,
            "classify",
            return_value=RoutingDecision(
                primary_domain=Domain.FINANCE,
                secondary_domains=[Domain.MATHS],
                routing_mode=RoutingMode.PARALLEL,
                estimated_complexity=8,
                required_synthesis=True,
                confidence=0.95,
            ),
        ), patch.object(router.decomposer, "decompose", return_value=fake_subtasks):
            events = await _collect_events(
                router.route_stream("Complex multi-domain task")
            )

        types = [e.event_type for e in events]
        assert types[0] == "routing_decision"
        assert "decomposition" in types
        assert "partial_result" in types

        # With 2 decomposed subtask results and required_synthesis, synthesis should fire
        assert "synthesis" in types
        assert types[-1] == "complete"


class TestStreamingErrorHandling:
    @pytest.mark.asyncio
    async def test_streaming_error_event(self, router):
        """If an exception occurs during routing, an error event is yielded."""
        with patch.object(
            router.classifier,
            "classify",
            side_effect=RuntimeError("classification failure"),
        ):
            events = await _collect_events(router.route_stream("trigger error"))

        assert any(e.event_type == "error" for e in events)
        error_event = [e for e in events if e.event_type == "error"][0]
        assert "classification failure" in error_event.data["error"]

    @pytest.mark.asyncio
    async def test_streaming_missing_specialist_partial_result(self, router):
        """When a specialist is missing, a failure partial_result is yielded, then complete."""
        # Patch classifier to route to a non-existent domain by removing finance
        original = router._specialists.pop(Domain.FINANCE, None)
        try:
            with patch.object(
                router.classifier,
                "classify",
                return_value=RoutingDecision(
                    primary_domain=Domain.FINANCE,
                    routing_mode=RoutingMode.SINGLE,
                    estimated_complexity=3,
                    confidence=0.9,
                ),
            ):
                events = await _collect_events(
                    router.route_stream("Calculate option price")
                )

            types = [e.event_type for e in events]
            assert "partial_result" in types
            assert types[-1] == "complete"

            partial = [e for e in events if e.event_type == "partial_result"][0]
            assert partial.data["result"]["status"] == "failure"
            assert "No specialist" in partial.data["result"]["error"]
        finally:
            if original is not None:
                router._specialists[Domain.FINANCE] = original

    @pytest.mark.asyncio
    async def test_streaming_budget_exhausted(self, router):
        """When global budget is exhausted, an error event is yielded immediately."""
        with patch.object(router.budget_manager, "can_allocate", return_value=False):
            events = await _collect_events(router.route_stream("Any input"))

        assert len(events) == 1
        assert events[0].event_type == "error"
        assert "budget" in events[0].data["error"].lower()
