"""Tests for the HMAOM dynamic tool registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hmaom.config import ToolRegistryConfig
from hmaom.tools.registry import ToolRegistry


def _dummy_handler(args, **kwargs):
    return {"ok": True}


def _echo_handler(args, **kwargs):
    return args


@pytest.fixture
def tmp_registry(tmp_path):
    """Return a ToolRegistry backed by a temporary SQLite file."""
    db_path = tmp_path / "registry.sqlite"
    config = ToolRegistryConfig(
        tools_dir=str(tmp_path / "tools"),
        db_path=str(db_path),
    )
    reg = ToolRegistry(config=config)
    yield reg
    reg.close()


class TestRegistration:
    def test_register_and_get(self, tmp_registry):
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        tmp_registry.register("add", schema, _dummy_handler, domains=["maths"])

        meta = tmp_registry.get("add")
        assert meta is not None
        assert meta["name"] == "add"
        assert meta["schema"] == schema
        assert meta["domains"] == ["maths"]

    def test_get_nonexistent(self, tmp_registry):
        assert tmp_registry.get("missing") is None

    def test_get_handler(self, tmp_registry):
        tmp_registry.register("h", {}, _dummy_handler)
        assert tmp_registry.get_handler("h") is _dummy_handler
        assert tmp_registry.get_handler("missing") is None

    def test_list_tools_sorted(self, tmp_registry):
        tmp_registry.register("zebra", {}, _dummy_handler)
        tmp_registry.register("alpha", {}, _dummy_handler)
        tmp_registry.register("beta", {}, _dummy_handler)
        assert tmp_registry.list_tools() == ["alpha", "beta", "zebra"]

    def test_unregister(self, tmp_registry):
        tmp_registry.register("t", {}, _dummy_handler)
        assert tmp_registry.get("t") is not None
        tmp_registry.unregister("t")
        assert tmp_registry.get("t") is None
        assert tmp_registry.get_handler("t") is None

    def test_register_overwrite(self, tmp_registry):
        tmp_registry.register("same", {}, _dummy_handler)
        tmp_registry.register("same", {"type": "string"}, _echo_handler, domains=["code"])
        meta = tmp_registry.get("same")
        assert meta["schema"] == {"type": "string"}
        assert meta["domains"] == ["code"]
        assert tmp_registry.get_handler("same") is _echo_handler


class TestDomainFiltering:
    def test_get_for_domain(self, tmp_registry):
        tmp_registry.register("a", {}, _dummy_handler, domains=["finance"])
        tmp_registry.register("b", {}, _dummy_handler, domains=["finance", "maths"])
        tmp_registry.register("c", {}, _dummy_handler, domains=["code"])

        finance = tmp_registry.get_for_domain("finance")
        assert len(finance) == 2
        assert {t["name"] for t in finance} == {"a", "b"}

        maths = tmp_registry.get_for_domain("maths")
        assert len(maths) == 1
        assert maths[0]["name"] == "b"

        code = tmp_registry.get_for_domain("code")
        assert len(code) == 1
        assert code[0]["name"] == "c"

    def test_get_for_domain_empty(self, tmp_registry):
        tmp_registry.register("a", {}, _dummy_handler, domains=["finance"])
        assert tmp_registry.get_for_domain("physics") == []


class TestSchemaValidation:
    def test_valid_schema(self, tmp_registry):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name"],
        }
        valid, errors = tmp_registry.validate_schema(schema)
        assert valid is True
        assert errors == []

    def test_invalid_schema(self, tmp_registry):
        schema = {"type": "object", "properties": {"age": {"type": "not_a_real_type"}}}
        valid, errors = tmp_registry.validate_schema(schema)
        assert valid is False
        assert errors

    def test_non_dict_schema(self, tmp_registry):
        valid, errors = tmp_registry.validate_schema("not a dict")
        assert valid is False
        assert any("dict" in e.lower() for e in errors)

    def test_empty_schema_fallback(self, tmp_registry):
        # When jsonschema is absent the fallback accepts schemas with keywords
        schema = {"type": "object"}
        valid, errors = tmp_registry.validate_schema(schema)
        assert valid is True


class TestReload:
    def test_reload_discovers_tools(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        db_path = tmp_path / "registry.sqlite"

        # Write a dynamic tool file
        tool_file = tools_dir / "my_tool.py"
        tool_file.write_text(
            "def hmaom_register(registry):\n"
            "    registry.register('my_tool', {'type': 'object'}, lambda x: x, domains=['research'])\n"
        )

        config = ToolRegistryConfig(tools_dir=str(tools_dir), db_path=str(db_path))
        reg = ToolRegistry(config=config)
        count = reg.reload()
        assert count == 1

        meta = reg.get("my_tool")
        assert meta is not None
        assert meta["domains"] == ["research"]
        assert meta["source_file"] == str(tool_file)
        reg.close()

    def test_reload_clears_existing(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        db_path = tmp_path / "registry.sqlite"

        config = ToolRegistryConfig(tools_dir=str(tools_dir), db_path=str(db_path))
        reg = ToolRegistry(config=config)
        reg.register("old_tool", {}, _dummy_handler)
        assert reg.get("old_tool") is not None

        count = reg.reload()
        assert count == 0
        assert reg.get("old_tool") is None
        reg.close()

    def test_reload_skips_underscored_files(self, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        db_path = tmp_path / "registry.sqlite"

        underscore_file = tools_dir / "_private.py"
        underscore_file.write_text(
            "def hmaom_register(registry):\n"
            "    registry.register('private', {}, lambda x: x)\n"
        )

        config = ToolRegistryConfig(tools_dir=str(tools_dir), db_path=str(db_path))
        reg = ToolRegistry(config=config)
        count = reg.reload()
        assert count == 0
        assert reg.get("private") is None
        reg.close()

    def test_reload_returns_zero_when_dir_missing(self, tmp_path):
        db_path = tmp_path / "registry.sqlite"
        config = ToolRegistryConfig(tools_dir=str(tmp_path / "nonexistent"), db_path=str(db_path))
        reg = ToolRegistry(config=config)
        assert reg.reload() == 0
        reg.close()


class TestPersistence:
    def test_persists_across_instances(self, tmp_path):
        db_path = tmp_path / "registry.sqlite"
        config = ToolRegistryConfig(tools_dir=str(tmp_path / "tools"), db_path=str(db_path))

        reg1 = ToolRegistry(config=config)
        reg1.register("persisted", {"type": "string"}, _dummy_handler, domains=["meta"])
        reg1.close()

        reg2 = ToolRegistry(config=config)
        meta = reg2.get("persisted")
        assert meta is not None
        assert meta["schema"] == {"type": "string"}
        assert meta["domains"] == ["meta"]
        # Handlers are not persisted
        assert reg2.get_handler("persisted") is None
        reg2.close()

    def test_unregister_removes_from_db(self, tmp_path):
        db_path = tmp_path / "registry.sqlite"
        config = ToolRegistryConfig(tools_dir=str(tmp_path / "tools"), db_path=str(db_path))

        reg1 = ToolRegistry(config=config)
        reg1.register("gone", {}, _dummy_handler)
        reg1.unregister("gone")
        reg1.close()

        reg2 = ToolRegistry(config=config)
        assert reg2.get("gone") is None
        reg2.close()


class TestContextManager:
    def test_context_manager(self, tmp_path):
        db_path = tmp_path / "registry.sqlite"
        config = ToolRegistryConfig(tools_dir=str(tmp_path / "tools"), db_path=str(db_path))
        with ToolRegistry(config=config) as reg:
            reg.register("ctx", {}, _dummy_handler)
            assert reg.get("ctx") is not None
        # After exit, db should be closed
        assert reg._db is None

class TestPathTraversalProtection:
    def test_reload_skips_file_outside_tools_dir(self, tmp_path):
        """Verify that a symlink pointing outside tools_dir is skipped."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        db_path = tmp_path / "registry.sqlite"

        # Create a legitimate tool
        legit = tools_dir / "legit.py"
        legit.write_text(
            "def hmaom_register(registry):\n"
            "    registry.register('legit', {'type': 'object'}, lambda x: x)\n"
        )

        # Create a symlink to a file outside tools_dir (if supported)
        outside = tmp_path / "evil.py"
        outside.write_text(
            "def hmaom_register(registry):\n"
            "    registry.register('evil', {'type': 'object'}, lambda x: x)\n"
        )
        symlink = tools_dir / "evil.py"
        try:
            symlink.symlink_to(outside)
        except OSError:
            pytest.skip("symlink creation not supported on this platform")

        config = ToolRegistryConfig(tools_dir=str(tools_dir), db_path=str(db_path))
        reg = ToolRegistry(config=config)
        count = reg.reload()
        # Only legit should be registered; evil symlink should be skipped
        assert count == 1
        assert reg.get("legit") is not None
        assert reg.get("evil") is None
        reg.close()