"""Tests for agent/proposal_engine.py — ProposalEngine detection & queue."""

import json
from pathlib import Path

import pytest

from agent.proposal_engine import ProposalEngine, _WORKFLOW_PATTERNS
from hermes_state import SessionDB


@pytest.fixture()
def db(tmp_path):
    db_path = tmp_path / "test_state.db"
    session_db = SessionDB(db_path=db_path)
    yield session_db
    session_db.close()


@pytest.fixture()
def engine(db, tmp_path):
    return ProposalEngine(db=db, scaffold_dir=tmp_path / "scaffolds")


# =====================================================================
# Pattern detection
# =====================================================================

class TestDetectWorkflowPatterns:
    def test_empty_context(self, engine):
        patterns = engine.detect_workflow_patterns({})
        assert patterns == []

    def test_skill_from_tools(self, engine):
        patterns = engine.detect_workflow_patterns({
            "tool_calls": [
                {"name": "search"},
                {"name": "fetch"},
                {"name": "search"},
            ],
        })
        types = [p["type"] for p in patterns]
        assert "skill_from_tools" in types

    def test_model_routing(self, engine):
        patterns = engine.detect_workflow_patterns({
            "provider_switches": 5,
        })
        types = [p["type"] for p in patterns]
        assert "model_routing" in types

    def test_plugin_integration(self, engine):
        patterns = engine.detect_workflow_patterns({
            "external_api_calls": 7,
        })
        types = [p["type"] for p in patterns]
        assert "plugin_integration" in types

    def test_context_compression(self, engine):
        patterns = engine.detect_workflow_patterns({
            "context_limit_hits": 3,
        })
        types = [p["type"] for p in patterns]
        assert "context_compression" in types

    def test_multiple_patterns(self, engine):
        patterns = engine.detect_workflow_patterns({
            "tool_calls": [{"name": "a"}, {"name": "b"}, {"name": "a"}],
            "provider_switches": 4,
            "external_api_calls": 2,
            "context_limit_hits": 2,
        })
        types = [p["type"] for p in patterns]
        assert "skill_from_tools" in types
        assert "model_routing" in types
        assert "context_compression" in types
        assert "plugin_integration" not in types  # threshold = 5


# =====================================================================
# Queue & dedupe
# =====================================================================

class TestQueueProposal:
    def test_queue_creates_proposal(self, engine):
        pid = engine.queue_proposal("s1", "skill_from_tools", "Test Title")
        assert pid.startswith("prop-")

        prop = engine.db.get_proposal(pid)
        assert prop["session_id"] == "s1"
        assert prop["proposal_type"] == "skill_from_tools"
        assert prop["title"] == "Test Title"
        assert prop["status"] == "pending"

    def test_dedupe_same_type_same_session(self, engine):
        pid1 = engine.queue_proposal("s1", "skill_from_tools", "Title A")
        pid2 = engine.queue_proposal("s1", "skill_from_tools", "Title B")
        assert pid1 == pid2

    def test_no_dedupe_different_sessions(self, engine):
        pid1 = engine.queue_proposal("s1", "skill_from_tools", "Title")
        pid2 = engine.queue_proposal("s2", "skill_from_tools", "Title")
        assert pid1 != pid2

    def test_no_dedupe_different_types(self, engine):
        pid1 = engine.queue_proposal("s1", "skill_from_tools", "T1")
        pid2 = engine.queue_proposal("s1", "plugin_integration", "T2")
        assert pid1 != pid2

    def test_dedupe_with_context_hash(self, engine):
        pid1 = engine.queue_proposal(
            "s1", "skill_from_tools", "T", context_hash="abc", description="d1"
        )
        pid2 = engine.queue_proposal(
            "s1", "skill_from_tools", "T", context_hash="abc", description="d2"
        )
        # When context_hash is provided, dedupe falls back to description comparison
        # Since description differs, it might not dedupe. But our implementation
        # compares description when context_hash is truthy.
        # Wait, looking at the code: if not context_hash or ep.get("description") == description
        # So when context_hash IS provided, it checks description. d1 != d2 so no dedupe.
        assert pid1 != pid2


# =====================================================================
# Ranking
# =====================================================================

class TestRankProposals:
    def test_rank_orders_by_recency(self, engine):
        p1 = engine.queue_proposal("s1", "skill_from_tools", "Older")
        p2 = engine.queue_proposal("s1", "plugin_integration", "Newer")

        ranked = engine.rank_proposals(session_id="s1")
        assert ranked[0]["id"] == p2
        assert ranked[1]["id"] == p1
        assert ranked[0]["rank_score"] > ranked[1]["rank_score"]


# =====================================================================
# Scaffold generation
# =====================================================================

class TestGenerateScaffold:
    def test_generates_file(self, engine):
        path = engine.generate_scaffold("skill_from_tools", {"tools": ["search"]})
        assert Path(path).exists()

        data = json.loads(Path(path).read_text())
        assert data["proposal_type"] == "skill_from_tools"
        assert data["template"]["kind"] == "skill"

    def test_skill_template(self, engine):
        tmpl = engine._scaffold_template("skill_from_tools")
        assert tmpl["kind"] == "skill"
        assert "manifest" in tmpl

    def test_plugin_template(self, engine):
        tmpl = engine._scaffold_template("plugin_integration")
        assert tmpl["kind"] == "plugin"

    def test_unknown_template(self, engine):
        tmpl = engine._scaffold_template("unknown_type")
        assert tmpl["kind"] == "unknown"

    def test_stable_filename(self, engine):
        p1 = engine.generate_scaffold("model_routing", {"a": 1})
        p2 = engine.generate_scaffold("model_routing", {"a": 1})
        assert p1 == p2


# =====================================================================
# Detect + queue integration
# =====================================================================

class TestDetectAndQueue:
    def test_creates_proposals_for_detected_patterns(self, engine):
        ids = engine.detect_and_queue("s1", {
            "tool_calls": [{"name": "x"}, {"name": "y"}, {"name": "x"}],
            "provider_switches": 4,
        })
        assert len(ids) >= 2
        for pid in ids:
            prop = engine.db.get_proposal(pid)
            assert prop is not None
            assert prop["status"] == "pending"
            assert prop["scaffold_path"] is not None

    def test_returns_existing_id_on_dedupe(self, engine):
        ids1 = engine.detect_and_queue("s1", {
            "tool_calls": [{"name": "a"}, {"name": "b"}, {"name": "a"}],
        })
        ids2 = engine.detect_and_queue("s1", {
            "tool_calls": [{"name": "a"}, {"name": "b"}, {"name": "a"}],
        })
        assert ids1[0] == ids2[0]
