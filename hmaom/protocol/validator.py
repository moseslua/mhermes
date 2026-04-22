"""HMAOM Schema Validation.

Validates spawn results against JSON Schema output specifications.
Falls back to simple type/shape checking when jsonschema is unavailable.
"""

from __future__ import annotations

from typing import Any, Optional

from hmaom.protocol.schemas import SpawnResult, TaskDescription


try:
    import jsonschema

    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover
    _HAS_JSONSCHEMA = False


def _simple_type_check(value: Any, expected_type: str, path: str = "$") -> list[str]:
    """Basic type checker used as a fallback when jsonschema is absent."""
    errors: list[str] = []
    type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
        "null": type(None),
    }

    if expected_type == "null" and value is None:
        return errors

    py_types = type_map.get(expected_type)
    if py_types is not None and not isinstance(value, py_types):
        errors.append(
            f"{path}: expected {expected_type}, got {type(value).__name__}"
        )
    return errors


def _simple_validate(value: Any, schema: dict, path: str = "$") -> list[str]:
    """Recursive simple schema validation without jsonschema."""
    errors: list[str] = []

    if not isinstance(schema, dict):
        return errors

    # type check
    schema_type = schema.get("type")
    if schema_type is not None:
        if isinstance(schema_type, list):
            if not any(
                len(_simple_type_check(value, t, path)) == 0 for t in schema_type
            ):
                errors.append(
                    f"{path}: expected one of {schema_type}, got {type(value).__name__}"
                )
        else:
            errors.extend(_simple_type_check(value, schema_type, path))

    # required properties
    required = schema.get("required", [])
    if isinstance(value, dict):
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required property '{key}'")

        # properties
        properties = schema.get("properties", {})
        for key, prop_schema in properties.items():
            if key in value:
                errors.extend(
                    _simple_validate(value[key], prop_schema, path=f"{path}.{key}")
                )

        # additionalProperties: false
        if schema.get("additionalProperties") is False:
            allowed = set(properties.keys())
            for key in value:
                if key not in allowed:
                    errors.append(f"{path}: unexpected property '{key}'")

    # items
    if isinstance(value, list):
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for i, item in enumerate(value):
                errors.extend(
                    _simple_validate(item, items_schema, path=f"{path}[{i}]")
                )

    # enum
    enum_vals = schema.get("enum")
    if enum_vals is not None and value not in enum_vals:
        errors.append(f"{path}: expected one of {enum_vals}, got {value!r}")

    return errors


class SchemaValidator:
    """Validates Python values against JSON Schema definitions."""

    def __init__(self) -> None:
        self._draft: Optional[Any] = None
        if _HAS_JSONSCHEMA:
            self._draft = jsonschema.Draft202012Validator

    def validate(self, result: Any, schema: dict) -> tuple[bool, list[str]]:
        """Validate *result* against *schema*.

        Returns (is_valid, error_messages).
        """
        if schema is None or not isinstance(schema, dict):
            return True, []

        if self._draft is not None:
            validator = self._draft(schema)
            raw_errors = list(validator.iter_errors(result))
            if not raw_errors:
                return True, []
            messages = [self._format_error(e) for e in raw_errors]
            return False, messages

        messages = _simple_validate(result, schema)
        return len(messages) == 0, messages

    @staticmethod
    def _format_error(error: Any) -> str:
        """Format a jsonschema.ValidationError into a concise string."""
        path = "/".join(str(p) for p in error.absolute_path) or "$"
        return f"{path}: {error.message}"

    def validate_spawn_result(
        self, result: SpawnResult, task: TaskDescription
    ) -> tuple[bool, list[str]]:
        """Validate a SpawnResult against the task's expected_output_schema."""
        schema = task.expected_output_schema
        if schema is None:
            return True, []
        return self.validate(result.result, schema)
