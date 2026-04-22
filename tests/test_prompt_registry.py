"""Tests for PromptRegistry.

Covers: register, get_active, set_active, list_versions, record_outcome,
stats, persistence, and thread safety.
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path

import pytest

from hmaom.prompts.registry import PromptRegistry, PromptVersion


@pytest.fixture
def registry():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "prompts.sqlite")
        reg = PromptRegistry(db_path=db_path)
        yield reg


class TestPromptRegistry:
    def test_register_creates_version(self, registry):
        v = registry.register("system", "code", "You are a coder.")
        assert v.name == "system"
        assert v.domain == "code"
        assert v.version == 1
        assert v.content == "You are a coder."
        assert v.is_active is False

    def test_register_auto_increments_version(self, registry):
        registry.register("system", "code", "v1")
        v2 = registry.register("system", "code", "v2")
        assert v2.version == 2

    def test_get_active_returns_none_when_no_active(self, registry):
        registry.register("system", "code", "content")
        assert registry.get_active("system", "code") is None

    def test_set_active_and_get_active(self, registry):
        v = registry.register("system", "code", "content")
        registry.set_active("system", "code", v.id)
        assert registry.get_active("system", "code") == "content"

    def test_set_active_deactivates_previous(self, registry):
        v1 = registry.register("system", "code", "old")
        v2 = registry.register("system", "code", "new")
        registry.set_active("system", "code", v1.id)
        registry.set_active("system", "code", v2.id)
        assert registry.get_active("system", "code") == "new"

    def test_get_version(self, registry):
        v = registry.register("system", "code", "content", metadata={"key": "val"})
        fetched = registry.get_version("system", "code", v.version)
        assert fetched is not None
        assert fetched.id == v.id
        assert fetched.content == "content"
        assert fetched.metadata_json == '{"key": "val"}'

    def test_get_version_missing(self, registry):
        assert registry.get_version("system", "code", 999) is None

    def test_list_versions_returns_stats(self, registry):
        v1 = registry.register("system", "code", "old")
        v2 = registry.register("system", "code", "new")
        registry.set_active("system", "code", v1.id)
        registry.record_outcome("system", "code", v1.version, success=True, tokens_used=10, latency_ms=100)
        versions = registry.list_versions("system", "code")
        assert len(versions) == 2
        active_versions = [v for v in versions if v["is_active"]]
        assert len(active_versions) == 1
        assert active_versions[0]["version"] == 1
        assert active_versions[0]["success_count"] == 1
        assert active_versions[0]["total_tokens"] == 10

    def test_record_outcome_and_get_stats(self, registry):
        v = registry.register("system", "code", "content")
        registry.record_outcome("system", "code", v.version, success=True, tokens_used=50, latency_ms=200)
        registry.record_outcome("system", "code", v.version, success=False, tokens_used=30, latency_ms=150)
        stats = registry.get_stats("system", "code", v.version)
        assert stats["total_outcomes"] == 2
        assert stats["success_count"] == 1
        assert stats["success_rate"] == 0.5
        assert stats["total_tokens"] == 80
        assert stats["avg_latency_ms"] == 175.0

    def test_record_outcome_missing_version_raises(self, registry):
        with pytest.raises(ValueError, match="Prompt version not found"):
            registry.record_outcome("system", "code", 999, success=True)

    def test_stats_empty(self, registry):
        v = registry.register("system", "code", "content")
        stats = registry.get_stats("system", "code", v.version)
        assert stats["total_outcomes"] == 0
        assert stats["success_rate"] == 0.0

    def test_persistence_across_instances(self, registry):
        v = registry.register("system", "code", "persisted")
        registry.set_active("system", "code", v.id)
        # Create new instance pointing to same DB
        reg2 = PromptRegistry(db_path=registry.db_path)
        assert reg2.get_active("system", "code") == "persisted"

    def test_thread_safety_register(self, registry):
        errors = []

        def worker():
            try:
                for i in range(20):
                    registry.register("system", "code", f"content-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        versions = registry.list_versions("system", "code")
        assert len(versions) == 100

    def test_multiple_names_and_domains(self, registry):
        registry.register("system", "code", "code-system")
        registry.register("system", "finance", "finance-system")
        registry.register("prefix", "code", "code-prefix")
        assert len(registry.list_versions("system", "code")) == 1
        assert len(registry.list_versions("system", "finance")) == 1
        assert len(registry.list_versions("prefix", "code")) == 1
