"""Tests for HMAOM core components.

Covers: protocol schemas, intent classification, gateway routing,
specialist execution, message bus, state store, and spawn protocol.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path

import pytest

from hmaom.config import (
    GatewayConfig,
    HMAOMConfig,
    ObservabilityConfig,
    SpecialistConfig,
    SpawnConfig,
    StateConfig,
)
from hmaom.gateway.classifier import IntentClassifier
from hmaom.gateway.decomposer import DecomposedTask, TaskDecomposer
from hmaom.gateway.router import GatewayRouter
from hmaom.observability import MetricsCollector
from hmaom.observability.health import CircuitBreakerRegistry, HealthMonitor
from hmaom.observability.tracing import Tracer
from hmaom.protocol.message_bus import MessageBus
from hmaom.protocol.schemas import (
    AgentAddress,
    AgentMessage,
    ContextSlice,
    Domain,
    HealthStatus,
    MessageType,
    RoutingDecision,
    RoutingMode,
    SpawnRequest,
    SpawnResult,
    StateEntry,
    TaskDescription,
    TaskType,
)
from hmaom.protocol.spawn import SpawnProtocol
from hmaom.specialists.code import CodeHarness
from hmaom.specialists.finance import FinanceHarness
from hmaom.specialists.maths import MathsHarness
from hmaom.state.checkpoints import CheckpointManager
from hmaom.state.memory import MemoryManager
from hmaom.state.store import StateStore
from hmaom.state.budget_manager import GlobalBudgetManager
from hmaom.observability.pool import SpecialistPool


# ── Fixtures ──

@pytest.fixture
def tmp_state_config():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield StateConfig(
            sqlite_path=str(Path(tmpdir) / "state.sqlite"),
            vector_index_path=str(Path(tmpdir) / "vectors.sqlite"),
            checkpoint_dir=str(Path(tmpdir) / "checkpoints"),
        )


@pytest.fixture
def message_bus(tmp_state_config):
    bus = MessageBus(config=tmp_state_config)
    yield bus
    bus.close()


@pytest.fixture
def state_store(tmp_state_config):
    store = StateStore(config=tmp_state_config)
    yield store
    store.close()


@pytest.fixture
def tracer(tmp_state_config):
    trace_path = Path(tmp_state_config.sqlite_path).parent / "trace.jsonl"
    config = ObservabilityConfig(
        enabled=True,
        trace_log_path=str(trace_path),
    )
    t = Tracer(config=config)
    yield t
    t.close()


@pytest.fixture
def finance_harness(tmp_state_config, message_bus):
    config = SpecialistConfig(
        name="finance",
        domain="finance",
        description="Finance specialist",
    )
    harness = FinanceHarness(config=config, message_bus=message_bus)
    yield harness
    # asyncio.run(harness.stop())


def _ctx_slice():
    """Return a default ContextSlice for tests."""
    return ContextSlice(
        source_agent="test",
        relevance_score=1.0,
        content="test context",
    )


# ── Protocol Schemas ──

class TestSchemas:
    def test_routing_decision_defaults(self):
        d = RoutingDecision(
            primary_domain=Domain.FINANCE,
            confidence=0.9,
        )
        assert d.routing_mode == RoutingMode.SINGLE
        assert d.task_type == TaskType.ANALYTICAL
        assert d.estimated_complexity == 5
        assert d.required_synthesis is False

    def test_agent_address_str(self):
        addr = AgentAddress(harness="finance", agent="calc", depth=2)
        assert str(addr) == "finance/calc@2"

    def test_spawn_result_model_dump(self):
        sr = SpawnResult(
            spawn_id="s1",
            status="success",
            result={"value": 42},
            tokens_used=100,
            time_ms=500,
        )
        data = sr.model_dump()
        assert data["spawn_id"] == "s1"
        assert data["status"] == "success"
        assert data["result"]["value"] == 42

    def test_state_entry_access_control(self):
        entry = StateEntry(
            key="finance/output",
            value={"price": 100},
            written_by=AgentAddress(harness="finance", agent="calc"),
            written_at=0.0,
        )
        assert entry.access_control["read"] == ["*"]


# ── Intent Classifier ──

class TestIntentClassifier:
    def test_finance_routing(self):
        clf = IntentClassifier()
        decision = clf.classify("Calculate the Black-Scholes option price for AAPL")
        assert decision.primary_domain == Domain.FINANCE
        assert decision.confidence >= 0.85
        assert decision.routing_mode == RoutingMode.SINGLE

    def test_code_routing(self):
        clf = IntentClassifier()
        decision = clf.classify("Debug this Python function that keeps crashing")
        assert decision.primary_domain == Domain.CODE
        assert decision.confidence >= 0.85

    def test_maths_routing(self):
        clf = IntentClassifier()
        decision = clf.classify("Prove that the sum of angles in a triangle is 180 degrees")
        assert decision.primary_domain == Domain.MATHS
        assert decision.confidence >= 0.85

    def test_parallel_routing(self):
        clf = IntentClassifier()
        decision = clf.classify(
            "Compare financial risk models and write a statistical analysis report"
        )
        # Finance should be primary due to strong keyword matches
        assert decision.routing_mode == RoutingMode.PARALLEL
        assert len(decision.secondary_domains) > 0

    def test_sequential_pattern(self):
        clf = IntentClassifier()
        decision = clf.classify("Model the thermodynamics of this trading strategy")
        assert decision.routing_mode == RoutingMode.SEQUENTIAL
        assert decision.primary_domain == Domain.PHYSICS

    def test_complexity_estimation(self):
        clf = IntentClassifier()
        simple = clf.classify("Hello")
        complex_task = clf.classify(
            "Optimize the portfolio allocation using Monte Carlo simulation and backtest"
        )
        assert simple.estimated_complexity < complex_task.estimated_complexity

    def test_low_confidence_fallback(self):
        clf = IntentClassifier(GatewayConfig(slm_confidence_threshold=0.99))
        decision = clf.classify("Calculate the Black-Scholes option price")
        # With very high threshold, should still route but with lower confidence
        assert decision.primary_domain == Domain.FINANCE


# ── Message Bus ──

class TestMessageBus:
    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self, message_bus):
        received = []

        def handler(msg):
            received.append(msg)

        unsub = message_bus.subscribe("broadcast", handler)
        msg = AgentMessage(
            message_id="m1",
            correlation_id="c1",
            timestamp=0.0,
            sender=AgentAddress(harness="test", agent="a"),
            recipient="broadcast",
            type=MessageType.TASK_REQUEST,
            payload={"data": 1},
        )
        await message_bus.publish(msg)

        assert len(received) == 1
        assert received[0].payload["data"] == 1
        unsub()

    @pytest.mark.asyncio
    async def test_correlation_subscription(self, message_bus):
        received = []

        def handler(msg):
            received.append(msg)

        unsub = message_bus.subscribe_to_correlation("corr-123", handler)
        # Use a targeted recipient so topic_for routes via correlation_id
        msg = AgentMessage(
            message_id="m2",
            correlation_id="corr-123",
            timestamp=0.0,
            sender=AgentAddress(harness="test", agent="a"),
            recipient=AgentAddress(harness="test", agent="b"),
            type=MessageType.TASK_RESULT,
        )
        await message_bus.publish(msg)

        assert len(received) >= 1
        unsub()


# ── Spawn Protocol ──

class TestSpawnProtocol:
    def test_depth_enforcement(self):
        protocol = SpawnProtocol(SpawnConfig(max_depth=3))
        addr = AgentAddress(harness="test", agent="a", depth=0)

        allowed, _ = protocol.can_spawn(addr, 1, "corr-1")
        assert allowed is True

        blocked, reason = protocol.can_spawn(addr, 5, "corr-1")
        assert blocked is False
        # depth=5 exceeds default limit (3), hard limit is also 5 by default
        # So it should hit the default limit first
        assert "exceeds" in reason.lower()

    def test_budget_tracking(self):
        protocol = SpawnProtocol(SpawnConfig(max_tokens_per_tree=1000))
        protocol.init_tree_budgets("corr-1")

        remaining = protocol.remaining_budget("corr-1")
        assert remaining["tokens_remaining"] == 1000

        protocol.consume_budget("corr-1", tokens=500)
        remaining = protocol.remaining_budget("corr-1")
        assert remaining["tokens_remaining"] == 500

        protocol.consume_budget("corr-1", tokens=600)
        remaining = protocol.remaining_budget("corr-1")
        assert remaining["tokens_remaining"] == 0  # clamped at 0

    @pytest.mark.asyncio
    async def test_execute_spawn(self):
        protocol = SpawnProtocol()

        async def dummy_handler(request):
            return {"result": "ok"}

        request = SpawnRequest(
            spawn_id="s1",
            parent_id="p1",
            correlation_id="c1",
            depth=1,
            task=TaskDescription(title="test", description="test task"),
            context_slice=_ctx_slice(),
        )

        result = await protocol.execute_spawn(request, dummy_handler)
        assert result.status == "success"
        assert result.result == {"result": "ok"}

    def test_create_child_request(self):
        protocol = SpawnProtocol(SpawnConfig(max_depth=3))
        parent = SpawnRequest(
            spawn_id="p1",
            parent_id="gateway",
            correlation_id="c1",
            depth=1,
            task=TaskDescription(title="parent", description="parent task"),
            context_slice=_ctx_slice(),
        )

        child = protocol.create_child_request(
            parent,
            TaskDescription(title="child", description="child task"),
            _ctx_slice(),
        )
        assert child.depth == 2
        assert child.constraints.max_depth == 1  # parent default max_depth=2, child gets 2-1=1


# ── State Store ──

class TestStateStore:
    def test_write_and_read(self, state_store):
        entry = StateEntry(
            key="finance/risk/output",
            value={"var": 0.05},
            written_by=AgentAddress(harness="finance", agent="calc"),
            written_at=time.time(),
        )
        assert state_store.write(entry) is True

        read_back = state_store.read("finance/risk/output")
        assert read_back is not None
        assert read_back.value == {"var": 0.05}

    def test_access_control_denial(self, state_store):
        entry = StateEntry(
            key="private/data",
            value={"secret": 123},
            written_by=AgentAddress(harness="finance", agent="calc"),
            written_at=time.time(),
            access_control={"read": ["finance/*"], "write": ["finance/calc"]},
        )
        state_store.write(entry)

        # Another agent should not be able to overwrite
        attacker = StateEntry(
            key="private/data",
            value={"secret": 456},
            written_by=AgentAddress(harness="code", agent="hacker"),
            written_at=time.time(),
        )
        assert state_store.write(attacker) is False

    def test_query_by_prefix(self, state_store):
        for i in range(3):
            entry = StateEntry(
                key=f"finance/output-{i}",
                value={"idx": i},
                written_by=AgentAddress(harness="finance", agent="calc"),
                written_at=time.time(),
            )
            state_store.write(entry)

        results = state_store.query(prefix="finance/")
        assert len(results) == 3

    def test_ttl_expiry(self, state_store):
        entry = StateEntry(
            key="temp/data",
            value={"tmp": 1},
            written_by=AgentAddress(harness="test", agent="a"),
            written_at=time.time(),
            ttl=0,  # expires immediately
        )
        state_store.write(entry)
        read_back = state_store.read("temp/data")
        assert read_back is None  # expired


# ── Checkpoint Manager ──

class TestCheckpointManager:
    def test_save_and_load(self, tmp_state_config):
        mgr = CheckpointManager(config=tmp_state_config)
        cp = mgr.create(
            correlation_id="c1",
            agent_address=AgentAddress(harness="finance", agent="calc"),
            messages=[{"role": "user", "content": "hello"}],
            state_snapshot={"step": 1},
        )
        assert cp.checkpoint_id.startswith("cp-")

        loaded = mgr.load_latest("c1")
        assert loaded is not None
        assert loaded.correlation_id == "c1"
        assert loaded.state_snapshot == {"step": 1}

    def test_load_all_ordered(self, tmp_state_config):
        mgr = CheckpointManager(config=tmp_state_config)
        for i in range(3):
            mgr.create(
                correlation_id="c2",
                agent_address=AgentAddress(harness="finance", agent="calc"),
                messages=[],
                state_snapshot={"step": i},
            )

        all_cps = mgr.load_all("c2")
        assert len(all_cps) == 3
        assert all_cps[0].state_snapshot["step"] == 0
        assert all_cps[2].state_snapshot["step"] == 2

    def test_recover_options(self, tmp_state_config):
        mgr = CheckpointManager(config=tmp_state_config)
        addr = AgentAddress(harness="finance", agent="calc", depth=1)
        mgr.create(
            correlation_id="c3",
            agent_address=addr,
            messages=[],
            state_snapshot={},
        )

        options = mgr.recover_options("c3", addr)
        assert options["has_checkpoint"] is True
        assert "resume" in options["options"]
        assert "retry" in options["options"]
        assert "decompose" in options["options"]
        assert "escalate" in options["options"]


# ── Memory Manager ──

class TestMemoryManager:
    def test_working_memory(self, tmp_state_config):
        mem = MemoryManager(config=tmp_state_config)
        mem.working_set("key1", {"data": 1})
        assert mem.working_get("key1") == {"data": 1}
        mem.working_clear()
        assert mem.working_get("key1") is None
        mem.close()

    def test_context_slice(self, tmp_state_config):
        mem = MemoryManager(config=tmp_state_config)
        mem.working_set("finance-model", {"type": "black-scholes"})
        mem.working_set("code-debug", {"file": "main.py"})

        slice_result = mem.working_slice("finance option pricing")
        assert slice_result.relevance_score > 0
        assert "finance-model" in slice_result.content
        mem.close()

    def test_session_save_load(self, tmp_state_config):
        mem = MemoryManager(config=tmp_state_config)
        path = mem.session_save("sess-1", [{"role": "user", "content": "hi"}])
        loaded = mem.session_load("sess-1")
        assert loaded is not None
        assert loaded["messages"][0]["content"] == "hi"
        mem.close()

    def test_long_term_memory(self, tmp_state_config):
        mem = MemoryManager(config=tmp_state_config)
        mem.long_term_store("fact-1", "Black-Scholes was published in 1973")
        results = mem.long_term_search("Black-Scholes")
        assert len(results) >= 1
        assert any("1973" in r["content"] for r in results)
        mem.close()

    def test_ttl_pruning(self, tmp_state_config):
        mem = MemoryManager(config=tmp_state_config)
        mem.long_term_store("fact-1", "expires immediately", ttl_seconds=0)
        results = mem.long_term_search("expires immediately")
        assert len(results) == 0
        mem.close()


# ── Observability ──

class TestTracer:
    def test_span_lifecycle(self, tmp_state_config):
        trace_path = Path(tmp_state_config.sqlite_path).parent / "trace.jsonl"
        config = ObservabilityConfig(
            enabled=True,
            trace_log_path=str(trace_path),
        )
        tracer = Tracer(config=config)

        span = tracer.start_span(
            correlation_id="c1",
            agent_address=AgentAddress(harness="finance", agent="calc"),
            operation="test-op",
        )
        tracer.finish_span(span, status="ok", tokens_used=100)

        trace = tracer.get_trace("c1")
        assert len(trace) == 1
        assert trace[0]["status"] == "ok"
        assert trace[0]["tokens_used"] == 100
        tracer.close()

    def test_summary(self, tmp_state_config):
        trace_path = Path(tmp_state_config.sqlite_path).parent / "trace.jsonl"
        config = ObservabilityConfig(
            enabled=True,
            trace_log_path=str(trace_path),
        )
        tracer = Tracer(config=config)
        span = tracer.start_span(
            correlation_id="c1",
            agent_address=AgentAddress(harness="finance", agent="calc", depth=1),
            operation="op1",
        )
        tracer.finish_span(span, status="ok", tokens_used=50)

        summary = tracer.summary("c1")
        assert summary["found"] is True
        assert summary["total_tokens"] == 50
        assert summary["max_depth"] == 1
        tracer.close()


class TestCircuitBreaker:
    def test_closed_allows_calls(self):
        cb = CircuitBreakerRegistry()
        assert cb.can_call("finance") is True
        cb.record_success("finance")
        assert cb.can_call("finance") is True

    def test_opens_after_failures(self):
        cb = CircuitBreakerRegistry()
        for _ in range(5):
            cb.record_failure("finance")
        assert cb.can_call("finance") is False
        assert cb.get_state("finance").state == "open"

    def test_half_open_then_closed(self):
        cb = CircuitBreakerRegistry()
        for _ in range(5):
            cb.record_failure("finance")
        assert cb.can_call("finance") is False

        # Simulate time passing for reset
        state = cb.get_state("finance")
        state.last_failure = time.time() - 60  # 60 seconds ago
        assert cb.can_call("finance") is True  # half-open
        assert cb.get_state("finance").state == "half-open"

        cb.record_success("finance")
        cb.record_success("finance")
        assert cb.get_state("finance").state == "closed"


class TestHealthMonitor:
    def test_stuck_detection(self):
        monitor = HealthMonitor()
        addr = AgentAddress(harness="finance", agent="calc")
        monitor.record_activity(addr)

        # Not stuck immediately
        is_stuck, _ = monitor.is_stuck(addr)
        assert is_stuck is False

    def test_status_tracking(self):
        monitor = HealthMonitor()
        addr = AgentAddress(harness="finance", agent="calc")
        status = HealthStatus(
            agent_address=addr,
            timestamp=time.time(),
            status="healthy",
            active_spawns=2,
        )
        monitor.update_status(status)
        assert monitor.get_status(addr).status == "healthy"


# ── Specialist Harnesses ──

class TestSpecialistHarnesses:
    @pytest.mark.asyncio
    async def test_finance_execution(self, tmp_state_config, message_bus):
        config = SpecialistConfig(name="finance", domain="finance", description="Test")
        harness = FinanceHarness(config=config, message_bus=message_bus)

        request = SpawnRequest(
            spawn_id="s1",
            parent_id="gateway",
            correlation_id="c1",
            depth=1,
            task=TaskDescription(
                title="Options pricing",
                description="Calculate Black-Scholes for AAPL",
            ),
            context_slice=_ctx_slice(),
        )

        result = await harness.execute(request)
        assert result.status == "success"
        assert result.result is not None

    @pytest.mark.asyncio
    async def test_code_execution(self, tmp_state_config, message_bus):
        config = SpecialistConfig(name="code", domain="code", description="Test")
        harness = CodeHarness(config=config, message_bus=message_bus)

        request = SpawnRequest(
            spawn_id="s1",
            parent_id="gateway",
            correlation_id="c1",
            depth=1,
            task=TaskDescription(
                title="Debug Python",
                description="Fix the bug in main.py",
            ),
            context_slice=_ctx_slice(),
        )

        result = await harness.execute(request)
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_maths_execution(self, tmp_state_config, message_bus):
        config = SpecialistConfig(name="maths", domain="maths", description="Test")
        harness = MathsHarness(config=config, message_bus=message_bus)

        request = SpawnRequest(
            spawn_id="s1",
            parent_id="gateway",
            correlation_id="c1",
            depth=1,
            task=TaskDescription(
                title="Integral",
                description="Compute the integral of x^2 from 0 to 1",
            ),
            context_slice=_ctx_slice(),
        )

        result = await harness.execute(request)
        assert result.status == "success"


# ── Gateway Router ──

class TestGatewayRouter:
    @pytest.mark.asyncio
    async def test_single_domain_routing(self):
        router = GatewayRouter()
        await router.start()

        result = await router.route("Calculate the Black-Scholes option price for AAPL")
        assert result["routing_decision"]["primary_domain"] == "finance"
        assert result["routing_decision"]["routing_mode"] == "single"
        assert "result" in result
        assert "trace_summary" in result

        await router.stop()

    @pytest.mark.asyncio
    async def test_code_domain_routing(self):
        router = GatewayRouter()
        await router.start()

        result = await router.route("Debug this Python function")
        assert result["routing_decision"]["primary_domain"] == "code"

        await router.stop()

    @pytest.mark.asyncio
    async def test_parallel_routing(self):
        router = GatewayRouter()
        await router.start()

        result = await router.route(
            "Compare financial risk models and write a statistical report"
        )
        # Should involve multiple domains
        assert result["routing_decision"]["routing_mode"] == "parallel"
        assert len(result["specialist_results"]) >= 1

        await router.stop()

    @pytest.mark.asyncio
    async def test_status_endpoint(self):
        router = GatewayRouter()
        await router.start()

        status = await router.status()
        assert "gateway" in status
        assert "specialists" in status
        assert "finance" in status["specialists"]
        assert "code" in status["specialists"]
        assert "maths" in status["specialists"]

        await router.stop()

    @pytest.mark.asyncio
    async def test_budget_tracking(self):
        router = GatewayRouter()
        await router.start()

        result = await router.route("Calculate 2 + 2")
        budget = result["budget_remaining"]
        assert budget["tokens_remaining"] >= 0
        assert budget["cost_remaining_usd"] >= 0

        await router.stop()


# ── Sandbox Manager ──

class TestSandboxManager:
    def test_create_and_destroy(self):
        from hmaom.security.sandbox import SandboxManager
        mgr = SandboxManager()
        path = mgr.create("finance", "calc", isolation="none")
        assert path.exists()
        mgr.destroy(path)
        assert not path.exists()

    def test_list_active(self):
        from hmaom.security.sandbox import SandboxManager
        mgr = SandboxManager()
        path = mgr.create("code", "review", isolation="none")
        active = mgr.list_active()
        assert len(active) == 1
        mgr.destroy_all()
        assert len(mgr.list_active()) == 0




# ── Task Decomposer ──


class TestTaskDecomposer:
    def test_single_mode(self):
        decomposer = TaskDecomposer()
        task = TaskDescription(title="Simple task", description="Calculate the Black-Scholes option price")
        decision = RoutingDecision(primary_domain=Domain.FINANCE, routing_mode=RoutingMode.SINGLE)

        result = decomposer.decompose(task, decision)

        assert len(result) == 1
        assert result[0].domain == Domain.FINANCE
        assert result[0].depends_on == []
        assert result[0].priority == 1

    def test_parallel_mode(self):
        decomposer = TaskDecomposer()
        task = TaskDescription(
            title="Parallel task",
            description="Calculate the option price and debug the Python script.",
        )
        decision = RoutingDecision(primary_domain=Domain.FINANCE, routing_mode=RoutingMode.PARALLEL)

        result = decomposer.decompose(task, decision)

        assert len(result) >= 2
        domains = {st.domain for st in result}
        assert Domain.FINANCE in domains
        assert Domain.CODE in domains
        # Parallel subtasks have no sequential dependencies
        for st in result:
            assert st.priority > 0

    def test_sequential_mode(self):
        decomposer = TaskDecomposer()
        task = TaskDescription(
            title="Sequential task",
            description="First calculate the integral. Then refactor the code.",
        )
        decision = RoutingDecision(primary_domain=Domain.MATHS, routing_mode=RoutingMode.SEQUENTIAL)

        result = decomposer.decompose(task, decision)

        assert len(result) >= 2
        # Each step should depend on the previous
        for i in range(1, len(result)):
            assert result[i].depends_on == [result[i - 1].subtask_id]

    def test_adaptive_mode(self):
        decomposer = TaskDecomposer()
        task = TaskDescription(title="Adaptive task", description="Build a trading strategy")
        decision = RoutingDecision(primary_domain=Domain.FINANCE, routing_mode=RoutingMode.ADAPTIVE)

        result = decomposer.decompose(task, decision)

        assert len(result) == 2
        assert result[0].task.title.startswith("Explore:")
        assert result[1].depends_on == [result[0].subtask_id]
        assert result[0].priority < result[1].priority

    def test_cross_domain_detection(self):
        decomposer = TaskDecomposer()
        task = TaskDescription(
            title="Cross domain",
            description="Research market data and write a financial report.",
        )
        decision = RoutingDecision(primary_domain=Domain.RESEARCH, routing_mode=RoutingMode.SINGLE)

        result = decomposer.decompose(task, decision)

        # Even in SINGLE mode, cross-domain tasks get split
        domains = {st.domain for st in result}
        assert Domain.RESEARCH in domains
        assert Domain.REPORTER in domains

    def test_dependency_detection(self):
        decomposer = TaskDecomposer()
        task = TaskDescription(
            title="With dependencies",
            description="Calculate the integral. Then using the result, plot the graph.",
        )
        decision = RoutingDecision(primary_domain=Domain.MATHS, routing_mode=RoutingMode.PARALLEL)

        result = decomposer.decompose(task, decision)

        # The second subtask should depend on the first due to "using the result"
        assert len(result) >= 2
        # Find the subtask containing "using the result"
        dependent = next(
            (st for st in result if "using the result" in st.task.description.lower()),
            None,
        )
        assert dependent is not None
        assert len(dependent.depends_on) > 0

    def test_unknown_keyword_fallback(self):
        decomposer = TaskDecomposer()
        task = TaskDescription(
            title="Unknown keywords",
            description="Do something with foobar and bazqux.",
        )
        decision = RoutingDecision(primary_domain=Domain.RESEARCH, routing_mode=RoutingMode.SINGLE)

        result = decomposer.decompose(task, decision)

        assert len(result) == 1
        assert result[0].domain == Domain.RESEARCH

    def test_circular_dependency_guard(self):
        decomposer = TaskDecomposer()
        # Manually inject a circular dependency scenario
        st_a = DecomposedTask(
            subtask_id="a",
            domain=Domain.FINANCE,
            task=TaskDescription(title="A", description="Task A"),
            depends_on=["b"],
        )
        st_b = DecomposedTask(
            subtask_id="b",
            domain=Domain.FINANCE,
            task=TaskDescription(title="B", description="Task B"),
            depends_on=["a"],
        )

        with pytest.raises(ValueError, match="Circular dependency"):
            decomposer._validate_no_cycles([st_a, st_b], {"a", "b"}, {"a": 0, "b": 1})

    def test_empty_description(self):
        decomposer = TaskDecomposer()
        task = TaskDescription(title="Empty", description="")
        decision = RoutingDecision(primary_domain=Domain.META, routing_mode=RoutingMode.SINGLE)

        result = decomposer.decompose(task, decision)

        assert len(result) == 1
        assert result[0].task.description == ""
        assert result[0].domain == Domain.META

    def test_long_title_truncation(self):
        decomposer = TaskDecomposer()
        long_title = "x" * 2000
        task = TaskDescription(title=long_title, description="Short desc")
        decision = RoutingDecision(primary_domain=Domain.CODE, routing_mode=RoutingMode.SINGLE)

        result = decomposer.decompose(task, decision)

        assert len(result) == 1
        assert result[0].task.title.endswith("...")
        assert len(result[0].task.title) <= 1000


# ── Global Budget Manager ──

class TestGlobalBudgetManager:
    def test_register_and_consume(self):
        mgr = GlobalBudgetManager()
        mgr.register_tree("c1", {"tokens": 1000, "cost_usd": 10.0, "time_ms": 5000})
        mgr.consume("c1", tokens=300, cost_usd=2.5, time_ms=1000)

        status = mgr.get_tree_status("c1")
        assert status["tokens_remaining"] == 700
        assert status["cost_remaining_usd"] == 7.5
        assert status["time_remaining_ms"] == 4000
        assert status["status"] == "active"

    def test_global_token_limit_enforcement(self):
        mgr = GlobalBudgetManager(max_global_tokens=500, max_concurrent_trees=10)
        mgr.register_tree("c1", {"tokens": 1000})
        mgr.consume("c1", tokens=400)

        # 400 used + 200 requested > 500 max → False
        assert mgr.can_allocate(tokens=200) is False
        # 400 used + 50 requested <= 500 max → True
        assert mgr.can_allocate(tokens=50) is True

    def test_concurrent_tree_limit(self):
        mgr = GlobalBudgetManager(max_concurrent_trees=2)
        mgr.register_tree("c1", {})
        mgr.register_tree("c2", {})

        assert mgr.can_allocate() is False
        assert len(mgr._active_trees) == 2

    def test_kill_tree(self):
        mgr = GlobalBudgetManager()
        mgr.register_tree("c1", {"tokens": 1000, "cost_usd": 10.0})
        mgr.consume("c1", tokens=200, cost_usd=1.0)

        final = mgr.kill_tree("c1")
        assert final["status"] == "killed"
        assert final["tokens_remaining"] == 800
        assert final["cost_remaining_usd"] == 9.0
        assert "c1" not in mgr._active_trees

    def test_get_global_status(self):
        mgr = GlobalBudgetManager(max_global_tokens=1000, max_global_cost_usd=20.0)
        mgr.register_tree("c1", {"tokens": 500, "cost_usd": 10.0})
        mgr.register_tree("c2", {"tokens": 300, "cost_usd": 5.0})
        mgr.consume("c1", tokens=100, cost_usd=2.0)
        mgr.consume("c2", tokens=50, cost_usd=1.0)

        global_status = mgr.get_global_status()
        assert global_status["total_trees"] == 2
        assert global_status["total_tokens_used"] == 150
        assert global_status["total_cost_used_usd"] == 3.0
        assert global_status["tokens_remaining"] == 850
        assert global_status["cost_remaining_usd"] == 17.0

    def test_can_allocate_headroom_check(self):
        mgr = GlobalBudgetManager(max_global_tokens=1000, max_global_cost_usd=100.0)
        assert mgr.can_allocate(tokens=500, cost_usd=30.0) is True
        mgr.register_tree("c1", {})
        mgr.consume("c1", tokens=600, cost_usd=50.0)
        assert mgr.can_allocate(tokens=500, cost_usd=60.0) is False
        assert mgr.can_allocate(tokens=300, cost_usd=40.0) is True

    def test_unregister_cleanup(self):
        mgr = GlobalBudgetManager()
        mgr.register_tree("c1", {"tokens": 1000})
        mgr.consume("c1", tokens=100)
        mgr.unregister_tree("c1")

        assert "c1" not in mgr._active_trees
        assert "c1" not in mgr._tree_budgets
        assert mgr.get_tree_status("c1")["status"] == "unknown"

    def test_thread_safety(self):
        import threading

        mgr = GlobalBudgetManager(max_global_tokens=10_000, max_concurrent_trees=100)
        errors = []

        def worker(tree_id):
            try:
                mgr.register_tree(tree_id, {"tokens": 1000})
                for _ in range(100):
                    mgr.consume(tree_id, tokens=1)
                mgr.get_tree_status(tree_id)
                mgr.get_global_status()
                mgr.unregister_tree(tree_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(mgr._active_trees) == 0
        assert len(mgr._tree_budgets) == 0

    def test_consume_warns_on_tree_overallocation(self, caplog):
        import logging

        mgr = GlobalBudgetManager()
        mgr.register_tree("c1", {"tokens": 100, "cost_usd": 5.0, "time_ms": 1000})
        with caplog.at_level(logging.WARNING):
            mgr.consume("c1", tokens=150, cost_usd=6.0, time_ms=2000)

        assert "exceeded token allocation" in caplog.text
        assert "exceeded cost allocation" in caplog.text
        assert "exceeded time allocation" in caplog.text



class TestSpecialistPool:
    """Tests for SpecialistPool horizontal scaling."""

    @pytest.fixture
    def pool(self):
        return SpecialistPool(domain=Domain.FINANCE, max_replicas=3)

    @pytest.fixture
    def finance_harness_1(self):
        config = SpecialistConfig(name="finance-1", domain="finance", description="Replica 1")
        return FinanceHarness(config=config)

    @pytest.fixture
    def finance_harness_2(self):
        config = SpecialistConfig(name="finance-2", domain="finance", description="Replica 2")
        return FinanceHarness(config=config)

    @pytest.fixture
    def finance_harness_3(self):
        config = SpecialistConfig(name="finance-3", domain="finance", description="Replica 3")
        return FinanceHarness(config=config)

    @pytest.fixture
    def finance_harness_4(self):
        config = SpecialistConfig(name="finance-4", domain="finance", description="Replica 4")
        return FinanceHarness(config=config)

    def test_add_replica(self, pool, finance_harness_1):
        assert pool.add_replica(finance_harness_1) is True
        assert pool.replica_count() == 1
        assert pool.is_available() is True
        assert finance_harness_1 in pool.all_replicas()

    def test_remove_replica(self, pool, finance_harness_1, finance_harness_2):
        pool.add_replica(finance_harness_1)
        pool.add_replica(finance_harness_2)
        assert pool.replica_count() == 2

        assert pool.remove_replica("finance-1") is True
        assert pool.replica_count() == 1
        assert finance_harness_1 not in pool.all_replicas()
        assert finance_harness_2 in pool.all_replicas()

        assert pool.remove_replica("finance-1") is False
        assert pool.remove_replica("unknown") is False

    def test_round_robin(self, pool, finance_harness_1, finance_harness_2):
        pool.add_replica(finance_harness_1)
        pool.add_replica(finance_harness_2)

        r1 = pool.get_replica(strategy="round_robin")
        r2 = pool.get_replica(strategy="round_robin")
        r3 = pool.get_replica(strategy="round_robin")

        assert r1 == finance_harness_1
        assert r2 == finance_harness_2
        assert r3 == finance_harness_1

    def test_least_loaded(self, pool, finance_harness_1, finance_harness_2, finance_harness_3):
        pool.add_replica(finance_harness_1)
        pool.add_replica(finance_harness_2)
        pool.add_replica(finance_harness_3)

        # Simulate some load on harness_1 and harness_2
        pool._request_counts["finance-1"] = 5
        pool._request_counts["finance-2"] = 2
        pool._request_counts["finance-3"] = 0

        r = pool.get_replica_least_loaded()
        assert r == finance_harness_3

        # After selection, harness_3 count should increase
        assert pool._request_counts["finance-3"] == 1

    def test_healthiest(self, pool, finance_harness_1, finance_harness_2):
        pool.add_replica(finance_harness_1)
        pool.add_replica(finance_harness_2)

        pool.update_health("finance-1", 0.5)
        pool.update_health("finance-2", 0.9)

        r = pool.get_replica_healthiest()
        assert r == finance_harness_2

        pool.update_health("finance-1", 1.0)
        r = pool.get_replica_healthiest()
        assert r == finance_harness_1

    def test_max_replicas_limit(self, pool, finance_harness_1, finance_harness_2, finance_harness_3, finance_harness_4):
        assert pool.add_replica(finance_harness_1) is True
        assert pool.add_replica(finance_harness_2) is True
        assert pool.add_replica(finance_harness_3) is True
        assert pool.replica_count() == 3

        assert pool.add_replica(finance_harness_4) is False
        assert pool.replica_count() == 3

    def test_update_health(self, pool, finance_harness_1):
        pool.add_replica(finance_harness_1)
        assert pool._health_scores["finance-1"] == 1.0

        pool.update_health("finance-1", 0.75)
        assert pool._health_scores["finance-1"] == 0.75

        # Unknown replica should be a no-op
        pool.update_health("unknown", 0.5)
        assert "unknown" not in pool._health_scores

    def test_is_available_empty_pool(self, pool):
        assert pool.is_available() is False
        assert pool.replica_count() == 0
        assert pool.get_replica() is None
        assert pool.get_replica_least_loaded() is None
        assert pool.get_replica_healthiest() is None

    def test_thread_safety(self, pool, finance_harness_1, finance_harness_2, finance_harness_3):
        import threading

        pool.add_replica(finance_harness_1)
        pool.add_replica(finance_harness_2)
        pool.add_replica(finance_harness_3)

        errors = []

        def worker():
            try:
                for _ in range(100):
                    pool.get_replica(strategy="round_robin")
                    pool.get_replica_least_loaded()
                    pool.get_replica_healthiest()
                    pool.update_health("finance-1", 0.8)
                    pool.replica_count()
                    pool.is_available()
                    pool.all_replicas()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # 10 threads * 100 iterations * 3 get_replica calls = 3000 requests
        total_requests = sum(pool._request_counts.values())
        assert total_requests == 3000


class TestMetricsCollector:
    def test_counter_increment(self):
        mc = MetricsCollector()
        mc.counter("requests", value=1)
        mc.counter("requests", value=5)
        assert mc.get_counter("requests") == 6

    def test_gauge_set(self):
        mc = MetricsCollector()
        mc.gauge("temperature", 23.5)
        assert mc.get_gauge("temperature") == 23.5
        mc.gauge("temperature", 19.0)
        assert mc.get_gauge("temperature") == 19.0

    def test_histogram_percentiles(self):
        mc = MetricsCollector()
        for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            mc.histogram("latency", v)
        stats = mc.get_histogram("latency")
        assert stats["count"] == 10
        assert stats["min"] == 10
        assert stats["max"] == 100
        assert stats["p50"] == pytest.approx(55.0)
        assert stats["p95"] == pytest.approx(95.5)
        assert stats["p99"] == pytest.approx(99.1)

    def test_labels(self):
        mc = MetricsCollector()
        mc.counter("routing_decisions", value=42, labels={"domain": "finance", "mode": "single"})
        assert mc.get_counter("routing_decisions", labels={"domain": "finance", "mode": "single"}) == 42
        # Different label set is a separate metric
        mc.counter("routing_decisions", value=10, labels={"domain": "code", "mode": "single"})
        assert mc.get_counter("routing_decisions", labels={"domain": "code", "mode": "single"}) == 10
        # Unordered labels should match the same key
        assert mc.get_counter("routing_decisions", labels={"mode": "single", "domain": "finance"}) == 42

    def test_prometheus_format(self):
        mc = MetricsCollector()
        mc.counter("routing_decisions", value=42, labels={"domain": "finance", "mode": "single"})
        mc.gauge("active_agents", 3.0, labels={"domain": "code"})
        output = mc.prometheus_exposition_format()
        assert 'hmaom_routing_decisions_total{domain="finance",mode="single"} 42' in output
        assert 'hmaom_active_agents{domain="code"} 3.0' in output
        assert "# TYPE hmaom_routing_decisions_total counter" in output
        assert "# TYPE hmaom_active_agents gauge" in output

    def test_reset(self):
        mc = MetricsCollector()
        mc.counter("requests", 10)
        mc.gauge("load", 0.8)
        mc.histogram("latency", 0.05)
        mc.reset()
        assert mc.get_counter("requests") == 0
        assert mc.get_gauge("load") == 0.0
        assert mc.get_histogram("latency")["count"] == 0

    def test_multiple_metrics(self):
        mc = MetricsCollector()
        mc.counter("a", 1)
        mc.counter("b", 2)
        mc.gauge("x", 1.5)
        mc.gauge("y", 2.5)
        mc.histogram("h1", 1.0)
        mc.histogram("h2", 2.0)
        assert mc.get_counter("a") == 1
        assert mc.get_counter("b") == 2
        assert mc.get_gauge("x") == 1.5
        assert mc.get_gauge("y") == 2.5
        assert mc.get_histogram("h1")["count"] == 1
        assert mc.get_histogram("h2")["count"] == 1

    def test_histogram_stats_empty(self):
        mc = MetricsCollector()
        stats = mc.get_histogram("never_recorded")
        assert stats == {
            "count": 0,
            "sum": 0.0,
            "min": 0.0,
            "max": 0.0,
            "avg": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
        }

    def test_histogram_prometheus_format(self):
        mc = MetricsCollector()
        mc.histogram("latency", 0.010, labels={"domain": "finance"})
        mc.histogram("latency", 0.020, labels={"domain": "finance"})
        mc.histogram("latency", 0.030, labels={"domain": "finance"})
        output = mc.prometheus_exposition_format()
        assert "# TYPE hmaom_latency summary" in output
        assert 'hmaom_latency_count{domain="finance"} 3' in output
        assert 'hmaom_latency_sum{domain="finance"} 0.06' in output
        assert 'hmaom_latency{quantile="0.5",domain="finance"} 0.02' in output
        # Allow for floating-point representation variance
        assert 'hmaom_latency{quantile="0.95",domain="finance"} 0.02899' in output
        assert 'hmaom_latency{quantile="0.99",domain="finance"} 0.0298' in output

    def test_thread_safety_counter(self):
        import threading

        mc = MetricsCollector()
        errors = []

        def worker():
            try:
                for _ in range(1000):
                    mc.counter("requests", 1)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert mc.get_counter("requests") == 10000

    def test_prefix(self):
        mc = MetricsCollector(prefix="custom")
        mc.counter("requests", 1)
        output = mc.prometheus_exposition_format()
        assert "custom_requests_total" in output
        assert "hmaom_requests_total" not in output
