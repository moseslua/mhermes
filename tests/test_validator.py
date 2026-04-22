"""Tests for SchemaValidator."""

from __future__ import annotations

import pytest

from hmaom.protocol.schemas import SpawnResult, TaskDescription
from hmaom.protocol.validator import SchemaValidator, _simple_validate


class TestSchemaValidator:
    def test_valid_simple_schema(self):
        validator = SchemaValidator()
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        valid, errors = validator.validate({"name": "alice"}, schema)
        assert valid is True
        assert errors == []

    def test_invalid_simple_schema(self):
        validator = SchemaValidator()
        schema = {"type": "object", "properties": {"age": {"type": "integer"}}}
        valid, errors = validator.validate({"age": "not an int"}, schema)
        assert valid is False
        assert errors

    def test_nested_schema(self):
        validator = SchemaValidator()
        schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                    },
                    "required": ["name", "email"],
                }
            },
        }
        valid, errors = validator.validate(
            {"user": {"name": "alice", "email": "a@example.com"}}, schema
        )
        assert valid is True
        assert errors == []

    def test_missing_required_field(self):
        validator = SchemaValidator()
        schema = {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        }
        valid, errors = validator.validate({}, schema)
        assert valid is False
        assert any("required" in e.lower() for e in errors)

    def test_type_mismatch_array(self):
        validator = SchemaValidator()
        schema = {"type": "array", "items": {"type": "integer"}}
        valid, errors = validator.validate([1, 2, "three"], schema)
        assert valid is False
        assert any("integer" in e.lower() for e in errors)

    def test_null_schema_returns_valid(self):
        validator = SchemaValidator()
        valid, errors = validator.validate({"anything": 1}, None)
        assert valid is True
        assert errors == []

    def test_validate_spawn_result_with_schema(self):
        validator = SchemaValidator()
        task = TaskDescription(
            title="test",
            description="test",
            expected_output_schema={"type": "object", "properties": {"value": {"type": "number"}}},
        )
        result = SpawnResult(spawn_id="s1", status="success", result={"value": 42})
        valid, errors = validator.validate_spawn_result(result, task)
        assert valid is True
        assert errors == []

    def test_validate_spawn_result_without_schema(self):
        validator = SchemaValidator()
        task = TaskDescription(title="test", description="test")
        result = SpawnResult(spawn_id="s1", status="success", result={"value": 42})
        valid, errors = validator.validate_spawn_result(result, task)
        assert valid is True
        assert errors == []

    def test_validate_spawn_result_failure(self):
        validator = SchemaValidator()
        task = TaskDescription(
            title="test",
            description="test",
            expected_output_schema={"type": "object", "properties": {"value": {"type": "string"}}},
        )
        result = SpawnResult(spawn_id="s1", status="success", result={"value": 42})
        valid, errors = validator.validate_spawn_result(result, task)
        assert valid is False
        assert errors


class TestSimpleValidateFallback:
    def test_simple_object_type(self):
        errors = _simple_validate({"a": 1}, {"type": "object"})
        assert errors == []

    def test_simple_string_type(self):
        errors = _simple_validate(42, {"type": "string"})
        assert errors
        assert "string" in errors[0].lower()

    def test_simple_required(self):
        errors = _simple_validate({}, {"type": "object", "required": ["x"]})
        assert any("required" in e.lower() for e in errors)

    def test_simple_additional_properties_false(self):
        errors = _simple_validate(
            {"a": 1, "b": 2},
            {"type": "object", "properties": {"a": {"type": "integer"}}, "additionalProperties": False},
        )
        assert any("unexpected" in e.lower() for e in errors)

    def test_simple_array_items(self):
        errors = _simple_validate(
            [1, "x"],
            {"type": "array", "items": {"type": "integer"}},
        )
        assert any("integer" in e.lower() for e in errors)

    def test_simple_enum(self):
        errors = _simple_validate("bar", {"type": "string", "enum": ["foo", "baz"]})
        assert any("enum" in e.lower() or "one of" in e.lower() for e in errors)

    def test_simple_null_type(self):
        errors = _simple_validate(None, {"type": "null"})
        assert errors == []
