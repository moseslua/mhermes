"""Dynamic Tool Registry for HMAOM.

Manages runtime tool registration, domain-based filtering, schema validation,
and persists metadata to SQLite.  Handlers are discovered by scanning
``~/.hmaom/tools/*.py`` for modules that define ``hmaom_register(registry)``.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import jsonschema

    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover
    _HAS_JSONSCHEMA = False

from hmaom.config import ToolRegistryConfig


def _default_tools_dir() -> Path:
    """Return the default user tools directory."""
    return Path.home() / ".hmaom" / "tools"


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
        errors.append(f"{path}: expected {expected_type}, got {type(value).__name__}")
    return errors


def _simple_validate(value: Any, schema: dict, path: str = "$") -> list[str]:
    """Recursive simple schema validation without jsonschema."""
    errors: list[str] = []

    if not isinstance(schema, dict):
        return errors

    schema_type = schema.get("type")
    if schema_type is not None:
        if isinstance(schema_type, list):
            if not any(len(_simple_type_check(value, t, path)) == 0 for t in schema_type):
                errors.append(
                    f"{path}: expected one of {schema_type}, got {type(value).__name__}"
                )
        else:
            errors.extend(_simple_type_check(value, schema_type, path))

    required = schema.get("required", [])
    if isinstance(value, dict):
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required property '{key}'")

        properties = schema.get("properties", {})
        for key, prop_schema in properties.items():
            if key in value:
                errors.extend(_simple_validate(value[key], prop_schema, path=f"{path}.{key}"))

        if schema.get("additionalProperties") is False:
            allowed = set(properties.keys())
            for key in value:
                if key not in allowed:
                    errors.append(f"{path}: unexpected property '{key}'")

    if isinstance(value, list):
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for i, item in enumerate(value):
                errors.extend(_simple_validate(item, items_schema, path=f"{path}[{i}]"))

    enum_vals = schema.get("enum")
    if enum_vals is not None and value not in enum_vals:
        errors.append(f"{path}: expected one of {enum_vals}, got {value!r}")

    return errors


class ToolRegistry:
    """Singleton-ish registry for dynamic tool discovery and dispatch.

    * ``_tools`` holds metadata (schema, domains, source_file).
    * ``_handlers`` holds the actual callables.
    * SQLite persists metadata so tool names/domains/schema survive restarts.
    * Handlers must be re-discovered via :py:meth:`reload`.
    """

    def __init__(self, config: Optional[ToolRegistryConfig] = None) -> None:
        self.config = config or ToolRegistryConfig()
        self._tools: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, Callable] = {}
        self._lock = threading.RLock()
        self._db: Optional[sqlite3.Connection] = None
        self._init_db()
        self._load_from_db()

    # ------------------------------------------------------------------
    # Database lifecycle
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        db_path = Path(self.config.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS tool_registry (
                name TEXT PRIMARY KEY,
                schema TEXT NOT NULL,
                domains TEXT NOT NULL,
                source_file TEXT
            )
        """)
        self._db.commit()

    def _load_from_db(self) -> None:
        """Hydrate in-memory metadata from SQLite.

        Handlers are *not* persisted; they remain empty until reload() or
        explicit register() calls populate them.
        """
        if self._db is None:
            return
        cursor = self._db.execute("SELECT name, schema, domains, source_file FROM tool_registry")
        for row in cursor.fetchall():
            name, schema_json, domains_json, source_file = row
            self._tools[name] = {
                "schema": json.loads(schema_json),
                "domains": json.loads(domains_json),
                "source_file": source_file,
            }

    def _persist_tool(self, name: str, schema: dict, domains: list[str], source_file: Optional[str]) -> None:
        if self._db is None:
            return
        self._db.execute(
            """
            INSERT OR REPLACE INTO tool_registry (name, schema, domains, source_file)
            VALUES (?, ?, ?, ?)
            """,
            (name, json.dumps(schema), json.dumps(domains), source_file),
        )
        self._db.commit()

    def _delete_tool_from_db(self, name: str) -> None:
        if self._db is None:
            return
        self._db.execute("DELETE FROM tool_registry WHERE name = ?", (name,))
        self._db.commit()

    def _clear_db(self) -> None:
        if self._db is None:
            return
        self._db.execute("DELETE FROM tool_registry")
        self._db.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        schema: dict,
        handler: Callable,
        domains: Optional[list[str]] = None,
        *,
        _source_file: Optional[str] = None,
    ) -> None:
        """Register a tool.

        Args:
            name: Unique tool identifier.
            schema: JSON Schema describing the tool's input parameters.
            handler: Callable that executes the tool.
            domains: Optional list of domain tags for filtering.
            _source_file: Internal hint used by reload() to track provenance.
        """
        domains = domains or []
        with self._lock:
            self._tools[name] = {
                "schema": schema,
                "domains": domains,
                "source_file": _source_file,
            }
            self._handlers[name] = handler
            self._persist_tool(name, schema, domains, _source_file)

    def get(self, name: str) -> Optional[dict]:
        """Return tool metadata (without the handler)."""
        with self._lock:
            tool = self._tools.get(name)
            if tool is None:
                return None
            return {
                "name": name,
                "schema": tool["schema"],
                "domains": tool["domains"],
                "source_file": tool["source_file"],
            }

    def get_handler(self, name: str) -> Optional[Callable]:
        """Return the handler callable for a tool, or None."""
        with self._lock:
            return self._handlers.get(name)

    def get_for_domain(self, domain: str) -> list[dict]:
        """Return metadata for all tools tagged with *domain*."""
        with self._lock:
            return [
                {
                    "name": name,
                    "schema": tool["schema"],
                    "domains": tool["domains"],
                    "source_file": tool["source_file"],
                }
                for name, tool in self._tools.items()
                if domain in tool["domains"]
            ]

    def list_tools(self) -> list[str]:
        """Return sorted list of registered tool names."""
        with self._lock:
            return sorted(self._tools.keys())

    def unregister(self, name: str) -> None:
        """Remove a tool from the registry and SQLite."""
        with self._lock:
            self._tools.pop(name, None)
            self._handlers.pop(name, None)
            self._delete_tool_from_db(name)

    def reload(self) -> int:
        """Clear the registry and re-scan ``~/.hmaom/tools/``.

        Returns the number of tools discovered and registered.
        """
        tools_dir = Path(self.config.tools_dir).expanduser()
        tools_dir = tools_dir.resolve()
        if not tools_dir.is_absolute():
            raise ValueError(f"tools_dir must be absolute: {tools_dir}")
        if not tools_dir.exists():
            with self._lock:
                self._tools.clear()
                self._handlers.clear()
                self._clear_db()
            return 0

        with self._lock:
            self._tools.clear()
            self._handlers.clear()
            self._clear_db()

            count = 0
            for py_file in sorted(tools_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                file_path = py_file.resolve()
                if not str(file_path).startswith(str(tools_dir)):
                    continue  # Path traversal attempt
                try:
                    module_name = f"_hmaom_dynamic_tool_{py_file.stem}"
                    spec = importlib.util.spec_from_file_location(module_name, py_file)
                    if spec is None or spec.loader is None:
                        continue
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    if hasattr(module, "hmaom_register") and callable(module.hmaom_register):
                        before = len(self._tools)
                        module.hmaom_register(self)
                        after = len(self._tools)
                        # Tag newly registered tools with source_file
                        for name in list(self._tools.keys()):
                            if self._tools[name].get("source_file") is None:
                                self._tools[name]["source_file"] = str(py_file)
                                self._persist_tool(
                                    name,
                                    self._tools[name]["schema"],
                                    self._tools[name]["domains"],
                                    str(py_file),
                                )
                        count += after - before
                except Exception:
                    continue
            return count

    def validate_schema(self, schema: dict) -> tuple[bool, list[str]]:
        """Validate that *schema* is a well-formed JSON Schema.

        Uses ``jsonschema`` when available; otherwise falls back to a
        lightweight structural check.
        """
        if not isinstance(schema, dict):
            return False, ["schema must be a dict"]

        if _HAS_JSONSCHEMA:
            try:
                # Draft202012Validator validates schemas via check_schema
                jsonschema.Draft202012Validator.check_schema(schema)
                return True, []
            except jsonschema.exceptions.SchemaError as exc:
                return False, [str(exc)]

        # Fallback: ensure the schema has at least a recognised root
        if "type" not in schema and "properties" not in schema and "$ref" not in schema:
            return False, ["schema appears to be empty or missing structural keywords"]
        return True, []

    def close(self) -> None:
        """Close the SQLite connection."""
        if self._db is not None:
            self._db.close()
            self._db = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def __del__(self):
        # Best-effort cleanup; callers should use close() explicitly.
        try:
            self.close()
        except Exception:
            pass
