"""AgentFlow integration: wrap AgentFlow's Graph DSL with Hermes credentials.

Because AgentFlow may not be installed in every environment, the import is
performed lazily at runtime.  If AgentFlow is absent the wrapper classes raise
:exc:`ImportError` with an informative message.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from hmaom.integrations.providers import (
    list_available_providers,
    resolve_agentflow_credentials,
)

logger = logging.getLogger(__name__)

_AGENTFLOW_GRAPH_CLS: Any = None
_AGENTFLOW_AVAILABLE: bool | None = None


def _agentflow_graph_cls() -> Any:
    """Lazy importer for AgentFlow's Graph class."""
    global _AGENTFLOW_GRAPH_CLS, _AGENTFLOW_AVAILABLE
    if _AGENTFLOW_AVAILABLE is not None:
        return _AGENTFLOW_GRAPH_CLS

    try:
        # Try the most likely import paths
        try:
            from agentflow.graph import Graph as _Graph  # type: ignore[import-untyped]
        except Exception:
            from agentflow import Graph as _Graph  # type: ignore[import-untyped]
        _AGENTFLOW_GRAPH_CLS = _Graph
        _AGENTFLOW_AVAILABLE = True
        logger.debug("AgentFlow Graph imported successfully")
    except Exception as exc:
        logger.debug("AgentFlow import failed: %s", exc)
        _AGENTFLOW_AVAILABLE = False
        _AGENTFLOW_GRAPH_CLS = None
    return _AGENTFLOW_GRAPH_CLS


class CredentialResolver:
    """Maps Hermes provider names to AgentFlow-compatible credentials.

    Credentials are cached per-process so that multiple graphs/nodes do not
    trigger redundant file-system reads.
    """

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}

    def resolve(self, provider_id: str) -> dict[str, Any]:
        """Return ``{"api_key": ..., "base_url": ..., "model": ...}`` for *provider_id*."""
        if provider_id not in self._cache:
            self._cache[provider_id] = resolve_agentflow_credentials(provider_id)
        return self._cache[provider_id]

    def inject_env(self, provider_id: str) -> None:
        """Inject credentials into environment variables for child processes."""
        creds = self.resolve(provider_id)
        prefix = provider_id.upper().replace("-", "_")
        if creds.get("api_key"):
            os.environ[f"{prefix}_API_KEY"] = creds["api_key"]
        if creds.get("base_url"):
            os.environ[f"{prefix}_BASE_URL"] = creds["base_url"]

    def available_providers(self) -> list[str]:
        """Shorthand for :func:`list_available_providers`."""
        return list_available_providers()


class HMAOMGraph:
    """Wrapper around AgentFlow's ``Graph`` that resolves LLM providers via Hermes.

    Supports fan-out / merge patterns and stores node/edge metadata until
    :meth:`build` is called, at which point the underlying AgentFlow Graph is
    materialised.
    """

    def __init__(
        self,
        name: str,
        provider_id: str | None = None,
        model: str | None = None,
        credential_resolver: CredentialResolver | None = None,
    ) -> None:
        self.name = name
        self.provider_id = provider_id or "anthropic"
        self.model = model
        self.resolver = credential_resolver or CredentialResolver()
        self._creds = self.resolver.resolve(self.provider_id)
        self._nodes: list[dict[str, Any]] = []
        self._edges: list[tuple[str, str]] = []
        self._graph_instance: Any = None

    # ── Builder API ──────────────────────────────────────────────────────────

    def add_node(self, node_id: str, node_type: str = "agent", **kwargs: Any) -> HMAOMGraph:
        """Add a node to the graph blueprint."""
        self._nodes.append({"id": node_id, "type": node_type, **kwargs})
        return self

    def add_edge(self, from_node: str, to_node: str) -> HMAOMGraph:
        """Add a directed edge between two nodes."""
        self._edges.append((from_node, to_node))
        return self

    def fanout(self, from_node: str, to_nodes: list[str]) -> HMAOMGraph:
        """Fan out from *from_node* to multiple targets in parallel."""
        for tn in to_nodes:
            self.add_edge(from_node, tn)
        return self

    def merge(self, from_nodes: list[str], to_node: str) -> HMAOMGraph:
        """Merge multiple source nodes into *to_node*."""
        for fn in from_nodes:
            self.add_edge(fn, to_node)
        return self

    # ── Materialisation ──────────────────────────────────────────────────────

    def build(self) -> Any:
        """Build and return the underlying AgentFlow Graph instance."""
        graph_cls = _agentflow_graph_cls()
        if graph_cls is None:
            raise ImportError(
                "AgentFlow is not installed. "
                "Install it (e.g. `pip install agentflow`) to use HMAOMGraph."
            )

        self._graph_instance = graph_cls(name=self.name)
        for node in self._nodes:
            self._graph_instance.add_node(**node)
        for from_node, to_node in self._edges:
            self._graph_instance.add_edge(from_node, to_node)
        return self._graph_instance

    def run(self, **kwargs: Any) -> Any:
        """Build (if necessary) and execute the graph."""
        if self._graph_instance is None:
            self.build()
        return self._graph_instance.run(**kwargs)


class AgentFlowBridge:
    """Adapter that translates Hermes configuration into AgentFlow node descriptors.

    The bridge is stateless apart from an optional shared
    :class:`CredentialResolver`.
    """

    def __init__(self, credential_resolver: CredentialResolver | None = None) -> None:
        self.resolver = credential_resolver or CredentialResolver()

    def create_graph(
        self,
        name: str,
        provider_id: str | None = None,
        model: str | None = None,
    ) -> HMAOMGraph:
        """Create an :class:`HMAOMGraph` with Hermes-resolved credentials."""
        return HMAOMGraph(
            name=name,
            provider_id=provider_id,
            model=model,
            credential_resolver=self.resolver,
        )

    def node_for_provider(
        self,
        provider_id: str,
        task: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return an AgentFlow node descriptor pre-filled with Hermes credentials.

        Example::

            bridge = AgentFlowBridge()
            node = bridge.node_for_provider("anthropic", "Refactor auth.py")
        """
        creds = self.resolver.resolve(provider_id)
        return {
            "provider": provider_id,
            "model": kwargs.pop("model", None) or creds.get("model") or provider_id,
            "api_key": creds.get("api_key"),
            "base_url": creds.get("base_url"),
            "task": task,
            **kwargs,
        }
