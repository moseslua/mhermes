"""Tests for HMAOM integrations: Specialist Hire, MiroAlligator, AgentFlow.

Covers:
- hire/ observer, analyzer, creator, persistence
- integrations/miroalligator debate + collaboration
- integrations/agentflow + providers
- specialists/dynamic harness
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from hmaom.config import SpecialistConfig, StateConfig
from hmaom.gateway.router import GatewayRouter
from hmaom.hire.analyzer import HireAnalyzer, HireSuggestion
from hmaom.hire.creator import HireCreator
from hmaom.hire.observer import HireObserver
from hmaom.hire.persistence import HireDecision, HireObservation, HirePersistence
from hmaom.integrations.miroalligator import (
    CollaborationCoordinator,
    DebateOrchestrator,
    HeavyProjectSubHarness,
)
from hmaom.integrations.providers import (
    list_available_providers,
    resolve_agentflow_credentials,
)
from hmaom.specialists.dynamic import DynamicSpecialistHarness


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
def tmp_hire_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "hire.sqlite")


@pytest.fixture
def hire_persistence(tmp_hire_db):
    p = HirePersistence(db_path=tmp_hire_db)
    yield p
    p._connection().close()


@pytest.fixture
def tmp_specialists_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


# ── Hire Persistence ──

class TestHirePersistence:
    def test_log_and_get_observation(self, hire_persistence):
        rid = hire_persistence.log_observation(
            user_input="test input",
            routing_decision={"primary_domain": "finance"},
            specialist_used="finance",
            result_status="success",
        )
        assert rid > 0

        obs = hire_persistence.get_observations()
        assert len(obs) == 1
        assert obs[0].user_input == "test input"
        assert obs[0].result_status == "success"

    def test_get_observations_since(self, hire_persistence):
        hire_persistence.log_observation("old", {}, "a", "success")
        time.sleep(0.01)
        since = time.time()
        hire_persistence.log_observation("new", {}, "b", "success")

        obs = hire_persistence.get_observations(since=since)
        assert len(obs) == 1
        assert obs[0].user_input == "new"

    def test_log_decision(self, hire_persistence):
        rid = hire_persistence.log_decision(
            specialist_name="crypto",
            domain="crypto",
            reason="High demand",
            config_json='{"name": "crypto"}',
        )
        assert rid > 0

        decisions = hire_persistence.get_decisions()
        assert len(decisions) == 1
        assert decisions[0].specialist_name == "crypto"

        by_domain = hire_persistence.get_decision_by_domain("crypto")
        assert by_domain is not None
        assert by_domain.specialist_name == "crypto"


# ── Hire Observer ──

class TestHireObserver:
    def test_observes_successful_route(self, hire_persistence):
        obs = HireObserver(persistence=hire_persistence)
        result = {
            "routing_decision": {
                "primary_domain": "finance",
                "secondary_domains": [],
                "confidence": 0.95,
            },
            "specialist_results": [{"status": "success"}],
        }
        obs.observe("Calculate option price", result)

        records = hire_persistence.get_observations()
        assert len(records) == 1
        assert records[0].specialist_used == "finance"
        assert records[0].result_status == "success"

    def test_observes_out_of_domain(self, hire_persistence):
        obs = HireObserver(persistence=hire_persistence)
        result = {
            "routing_decision": {"primary_domain": "unknown", "confidence": 0.3},
            "specialist_results": [{"status": "failure", "error": "No specialist available"}],
        }
        obs.observe("Weird request", result)

        records = hire_persistence.get_observations()
        assert records[0].result_status == "out_of_domain"

    def test_observes_partial_failure(self, hire_persistence):
        obs = HireObserver(persistence=hire_persistence)
        result = {
            "routing_decision": {"primary_domain": "finance", "confidence": 0.8},
            "specialist_results": [
                {"status": "success"},
                {"status": "failure", "error": "timeout"},
            ],
        }
        obs.observe("Complex request", result)

        records = hire_persistence.get_observations()
        assert records[0].result_status == "partial"


# ── Hire Analyzer ──

class TestHireAnalyzer:
    def test_no_suggestions_when_no_data(self, hire_persistence):
        analyzer = HireAnalyzer(persistence=hire_persistence, existing_domains={"finance"})
        suggestions = analyzer.analyze()
        assert suggestions == []

    def test_no_suggestions_when_well_covered(self, hire_persistence):
        # Log 15 finance requests with high confidence — should NOT suggest hire
        analyzer = HireAnalyzer(persistence=hire_persistence, existing_domains={"finance"})
        for i in range(15):
            hire_persistence.log_observation(
                user_input="Calculate stock price",
                routing_decision={"primary_domain": "finance", "confidence": 0.95},
                specialist_used="finance",
                result_status="success",
            )
        suggestions = analyzer.analyze()
        assert suggestions == []

    def test_suggests_new_specialist_for_low_confidence_cluster(self, hire_persistence):
        analyzer = HireAnalyzer(
            persistence=hire_persistence,
            existing_domains={"finance", "code", "maths"},
        )
        # Log 12 requests about "crypto blockchain defi" with low confidence
        # Use "failure" status so they are not filtered by _covered_by_existing heuristic
        for i in range(12):
            hire_persistence.log_observation(
                user_input="Analyze crypto blockchain defi protocol",
                routing_decision={"primary_domain": "finance", "confidence": 0.4},
                specialist_used="unknown",
                result_status="failure",
            )
        suggestions = analyzer.analyze()
        assert len(suggestions) >= 1
        # Should suggest a crypto-related specialist
        assert any(
            "crypto" in s.suggested_domain or "blockchain" in s.suggested_domain
            for s in suggestions
        )

    def test_derive_name(self):
        name, domain = HireAnalyzer._derive_name(frozenset(["crypto", "blockchain"]))
        assert "crypto" in domain or "blockchain" in domain

    def test_extract_keywords(self):
        words = HireAnalyzer._extract_keywords("The quick brown fox")
        assert "quick" in words
        assert "fox" in words
        assert "the" not in words

    def test_covered_by_existing(self, hire_persistence):
        analyzer = HireAnalyzer(
            persistence=hire_persistence,
            existing_domains={"finance"},
        )
        # Log observations routed to finance
        for _ in range(12):
            hire_persistence.log_observation(
                user_input="Finance report analysis",
                routing_decision={"primary_domain": "finance", "confidence": 0.4},
                specialist_used="finance",
                result_status="success",
            )
        suggestions = analyzer.analyze()
        # Should be covered by existing finance domain
        assert suggestions == []


# ── Hire Creator ──

class TestHireCreator:
    def test_build_config(self):
        suggestion = HireSuggestion(
            suggested_name="crypto_specialist",
            suggested_domain="crypto",
            keywords=["crypto", "blockchain", "defi"],
            observation_count=12,
            confidence_avg=0.5,
        )
        creator = HireCreator()
        config = creator._build_config(suggestion)
        assert config.name == "crypto_specialist"
        assert config.domain == "crypto"
        assert "crypto" in config.description

    def test_create_specialist_persists(self, hire_persistence, tmp_specialists_dir):
        suggestion = HireSuggestion(
            suggested_name="test_specialist",
            suggested_domain="testing",
            keywords=["test"],
            observation_count=12,
            confidence_avg=0.5,
        )
        creator = HireCreator(
            persistence=hire_persistence,
            specialists_dir=tmp_specialists_dir,
        )
        config = creator.create_specialist(suggestion)
        assert config.name == "test_specialist"

        decisions = hire_persistence.get_decisions()
        assert len(decisions) == 1
        assert decisions[0].specialist_name == "test_specialist"

        harness_path = Path(tmp_specialists_dir) / "testing.py"
        assert harness_path.exists()
        content = harness_path.read_text()
        assert "class TestingHarness" in content

    def test_write_harness_idempotent(self, hire_persistence, tmp_specialists_dir):
        suggestion = HireSuggestion(
            suggested_name="dup_specialist",
            suggested_domain="dup",
            keywords=["dup"],
            observation_count=12,
            confidence_avg=0.5,
        )
        creator = HireCreator(
            persistence=hire_persistence,
            specialists_dir=tmp_specialists_dir,
        )
        creator.create_specialist(suggestion)
        with pytest.raises(FileExistsError):
            creator.create_specialist(suggestion)


# ── Dynamic Specialist Harness ──

class TestDynamicSpecialistHarness:
    @pytest.mark.asyncio
    async def test_default_handle_task(self, tmp_state_config):
        config = SpecialistConfig(name="test", domain="code", description="Test")
        harness = DynamicSpecialistHarness(config=config)

        from hmaom.protocol.schemas import SpawnRequest, TaskDescription, ContextSlice
        request = SpawnRequest(
            spawn_id="s1",
            parent_id="gateway",
            correlation_id="c1",
            depth=1,
            task=TaskDescription(title="test", description="test task"),
            context_slice=ContextSlice(
                source_agent="test", relevance_score=1.0, content="test"
            ),
        )
        result = await harness.execute(request)
        assert result.status == "success"
        assert result.result is not None


# ── MiroAlligator: HeavyProjectSubHarness ──

class TestHeavyProjectSubHarness:
    @pytest.mark.asyncio
    async def test_single_slice_fallback(self, tmp_state_config):
        config = SpecialistConfig(name="heavy", domain="code", description="Heavy")
        harness = HeavyProjectSubHarness(config=config)

        from hmaom.protocol.schemas import SpawnRequest, TaskDescription, ContextSlice
        request = SpawnRequest(
            spawn_id="s1",
            parent_id="gateway",
            correlation_id="c1",
            depth=1,
            task=TaskDescription(title="test", description="Refactor the auth module"),
            context_slice=ContextSlice(
                source_agent="heavy", relevance_score=1.0, content="test"
            ),
        )
        result = await harness.execute(request)
        assert result.status == "success"
        payload = result.result
        assert payload["slices"] == 1
        assert payload["harness"] == "heavy"

    def test_slice_project_with_modules(self):
        config = SpecialistConfig(name="heavy", domain="code", description="Heavy")
        harness = HeavyProjectSubHarness(config=config)
        description = (
            "Refactor codebase\n"
            "MODULE: auth.py\n"
            "Fix login logic\n"
            "MODULE: db.py\n"
            "Fix connection pooling\n"
        )
        slices = harness._slice_project(description)
        assert len(slices) == 2
        assert slices[0]["module"] == "auth.py"
        assert slices[1]["module"] == "db.py"


# ── MiroAlligator: DebateOrchestrator ──

class TestDebateOrchestrator:
    @pytest.mark.asyncio
    async def test_debate_runs_all_rounds(self, tmp_state_config):
        config = SpecialistConfig(name="debate", domain="code", description="Debate")
        harness = DynamicSpecialistHarness(config=config)
        orchestrator = DebateOrchestrator(harness=harness, rounds=2)

        result = await orchestrator.run_debate(
            topic="Best error handling pattern",
            position_a="Use exceptions",
            position_b="Use result types",
        )
        assert result["topic"] == "Best error handling pattern"
        assert result["rounds"] == 2
        assert len(result["transcript"]) == 2
        assert "verdict" in result

    def test_transcript_accumulates(self, tmp_state_config):
        config = SpecialistConfig(name="debate", domain="code", description="Debate")
        harness = DynamicSpecialistHarness(config=config)
        orchestrator = DebateOrchestrator(harness=harness, rounds=2)
        assert orchestrator._transcript == []


# ── MiroAlligator: CollaborationCoordinator ──

class TestCollaborationCoordinator:
    @pytest.mark.asyncio
    async def test_claim_and_release(self):
        coord = CollaborationCoordinator()
        assert await coord.claim_file("agent-1", "src/main.py") is True
        assert await coord.claim_file("agent-2", "src/main.py") is False
        assert await coord.release_file("agent-1", "src/main.py") is True
        assert await coord.release_file("agent-2", "src/main.py") is False
        assert await coord.claim_file("agent-2", "src/main.py") is True

    @pytest.mark.asyncio
    async def test_propose_edit_requires_claim(self):
        coord = CollaborationCoordinator()
        result = await coord.propose_edit("agent-1", "src/main.py", "+line")
        assert result["status"] == "rejected"
        assert result["reason"] == "file_not_claimed"

    @pytest.mark.asyncio
    async def test_propose_edit_accepted(self):
        coord = CollaborationCoordinator()
        await coord.claim_file("agent-1", "src/main.py")
        result = await coord.propose_edit("agent-1", "src/main.py", "+line")
        assert result["status"] == "accepted"
        assert "proposal_id" in result

    @pytest.mark.asyncio
    async def test_detect_conflicts(self):
        coord = CollaborationCoordinator()
        # Agent 1 claims, proposes, then releases so agent 2 can claim too
        await coord.claim_file("agent-1", "src/main.py")
        await coord.propose_edit("agent-1", "src/main.py", "@@ -1,3 +1,4 @@\n+line1")
        await coord.release_file("agent-1", "src/main.py")
        await coord.claim_file("agent-2", "src/main.py")
        await coord.propose_edit("agent-2", "src/main.py", "@@ -1,3 +1,4 @@\n+line2")

        conflicts = coord.detect_conflicts("src/main.py")
        assert len(conflicts) == 1
        assert conflicts[0]["agents"] == ["agent-1", "agent-2"]

    @pytest.mark.asyncio
    async def test_no_conflicts_for_disjoint_edits(self):
        coord = CollaborationCoordinator()
        await coord.claim_file("agent-1", "src/main.py")
        await coord.claim_file("agent-2", "src/main.py")
        # Different hunk headers = no overlap
        await coord.propose_edit("agent-1", "src/main.py", "@@ -10,3 -10,4 @@\n+line1")
        await coord.propose_edit("agent-2", "src/main.py", "@@ -50,3 +50,4 @@\n+line2")

        conflicts = coord.detect_conflicts("src/main.py")
        assert len(conflicts) == 0

    @pytest.mark.asyncio
    async def test_integrate_changes(self):
        coord = CollaborationCoordinator()
        await coord.claim_file("agent-1", "src/main.py")
        await coord.propose_edit("agent-1", "src/main.py", "+line1")

        result = await coord.integrate_changes("src/main.py")
        assert result["status"] == "integrated"
        assert len(result["applied"]) == 1

    @pytest.mark.asyncio
    async def test_integrate_aborts_on_conflict(self):
        coord = CollaborationCoordinator()
        await coord.claim_file("agent-1", "src/main.py")
        await coord.propose_edit("agent-1", "src/main.py", "@@ -1,3 +1,4 @@\n+line1")
        await coord.release_file("agent-1", "src/main.py")
        await coord.claim_file("agent-2", "src/main.py")
        await coord.propose_edit("agent-2", "src/main.py", "@@ -1,3 +1,4 @@\n+line2")

        result = await coord.integrate_changes("src/main.py")
        assert result["status"] == "conflict"
        assert len(result["conflicts"]) == 1

    def test_diff_overlap_heuristic(self):
        # Same hunk header = overlap
        assert CollaborationCoordinator._diffs_overlap(
            "@@ -1,3 +1,4 @@\n+line1",
            "@@ -1,3 +1,4 @@\n+line2",
        ) is True
        # Different hunk headers = no overlap
        assert CollaborationCoordinator._diffs_overlap(
            "@@ -1,3 +1,4 @@\n+line1",
            "@@ -50,3 +50,4 @@\n+line2",
        ) is False


# ── AgentFlow Providers ──

class TestProviderResolution:
    def test_list_available_providers_no_crash(self):
        # Should not crash even if no credentials are configured
        providers = list_available_providers()
        assert isinstance(providers, list)

    def test_resolve_with_env_fallback(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
        creds = resolve_agentflow_credentials("anthropic")
        assert creds["api_key"] == "sk-test-123"
        assert "model" in creds

    def test_resolve_openrouter_uses_openai_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openrouter")
        creds = resolve_agentflow_credentials("openrouter")
        assert creds["api_key"] == "sk-openrouter"

    def test_resolve_unknown_provider_raises(self):
        with pytest.raises(Exception):
            resolve_agentflow_credentials("nonexistent_provider_xyz_12345")

    def test_model_for_provider(self):
        from hmaom.integrations.providers import _model_for_provider
        assert _model_for_provider("anthropic") != ""
        assert _model_for_provider("openrouter") != ""


# ── AgentFlow Bridge ──

class TestAgentFlowBridge:
    def test_graph_builder_api(self):
        from hmaom.integrations.agentflow import HMAOMGraph
        g = HMAOMGraph(name="test-pipeline", provider_id="anthropic")
        g.add_node("plan", node_type="agent", prompt="Plan the work")
        g.add_node("impl", node_type="agent", prompt="Implement")
        g.add_edge("plan", "impl")
        g.fanout("plan", ["impl"])
        g.merge(["plan"], "impl")

        assert g.name == "test-pipeline"
        assert g.provider_id == "anthropic"
        assert len(g._nodes) == 2
        assert len(g._edges) == 3  # add_edge + fanout + merge

    def test_credential_resolver_caches(self, monkeypatch):
        from hmaom.integrations.agentflow import CredentialResolver
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-cache-test")
        resolver = CredentialResolver()
        c1 = resolver.resolve("anthropic")
        c2 = resolver.resolve("anthropic")
        assert c1["api_key"] == "sk-cache-test"
        assert c1 is c2  # same cached object

    def test_inject_env(self, monkeypatch):
        from hmaom.integrations.agentflow import CredentialResolver
        monkeypatch.setenv("GEMINI_API_KEY", "sk-gemini")
        resolver = CredentialResolver()
        resolver.inject_env("gemini")
        assert os.environ.get("GEMINI_API_KEY") == "sk-gemini"

    def test_bridge_create_graph(self):
        from hmaom.integrations.agentflow import AgentFlowBridge
        bridge = AgentFlowBridge()
        g = bridge.create_graph("my-graph", provider_id="anthropic")
        assert g.name == "my-graph"

    def test_node_for_provider(self, monkeypatch):
        from hmaom.integrations.agentflow import AgentFlowBridge
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        bridge = AgentFlowBridge()
        node = bridge.node_for_provider("anthropic", "Refactor auth.py")
        assert node["provider"] == "anthropic"
        assert node["task"] == "Refactor auth.py"
        assert node["api_key"] == "sk-test"


# ── Gateway Router + Hire Observer Integration ──

class TestGatewayRouterHireIntegration:
    @pytest.mark.asyncio
    async def test_routes_without_observer(self):
        router = GatewayRouter()
        await router.start()
        result = await router.route("Compute the integral of x squared from zero to one")
        assert result["routing_decision"]["primary_domain"] == "maths"
        await router.stop()

    @pytest.mark.asyncio
    async def test_routes_with_observer(self, tmp_hire_db):
        from hmaom.hire.observer import HireObserver
        from hmaom.hire.persistence import HirePersistence

        persistence = HirePersistence(db_path=tmp_hire_db)
        observer = HireObserver(persistence=persistence)
        router = GatewayRouter(hire_observer=observer)
        await router.start()

        result = await router.route("Compute the integral of x squared from zero to one")
        assert result["routing_decision"]["primary_domain"] == "maths"

        records = persistence.get_observations()
        assert len(records) == 1
        assert records[0].user_input == "Compute the integral of x squared from zero to one"

        await router.stop()


# ── End-to-end: Hire Suggestion -> Creator ──

class TestHireEndToEnd:
    @pytest.mark.asyncio
    async def test_full_hire_pipeline(self, tmp_hire_db, tmp_specialists_dir):
        persistence = HirePersistence(db_path=tmp_hire_db)

        # Simulate 12 low-confidence crypto requests with failure status
        # to bypass the _covered_by_existing heuristic
        for i in range(12):
            persistence.log_observation(
                user_input=f"Analyze crypto blockchain defi protocol {i}",
                routing_decision=json.dumps({
                    "primary_domain": "finance",
                    "confidence": 0.4,
                }),
                specialist_used="unknown",
                result_status="failure",
            )

        analyzer = HireAnalyzer(
            persistence=persistence,
            existing_domains={"finance", "code", "maths", "physics"},
        )
        suggestions = analyzer.analyze()
        assert len(suggestions) >= 1

        suggestion = suggestions[0]
        creator = HireCreator(
            persistence=persistence,
            specialists_dir=tmp_specialists_dir,
        )
        config = creator.create_specialist(suggestion)
        assert config.name == suggestion.suggested_name
        assert config.domain == suggestion.suggested_domain

        # Verify decision persisted
        decisions = persistence.get_decisions()
        assert any(d.specialist_name == config.name for d in decisions)
