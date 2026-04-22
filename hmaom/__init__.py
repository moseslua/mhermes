"""Hierarchical Multi-Agent Orchestration Mesh (HMAOM).

A production-grade, fault-tolerant architecture for hierarchical multi-agent
orchestration built atop hermes-agent. Implements a Mixture-of-Experts (MoE)
routing pattern with domain-isolated specialist sub-harnesses.
"""

__version__ = "0.1.0"

from hmaom.protocol.schemas import (
    AgentAddress,
    AgentMessage,
    RoutingDecision,
    SpawnRequest,
    SpawnResult,
    SynthesisRequest,
    AgentResult,
    ContextSlice,
    StateEntry,
    CircuitBreaker,
)
from hmaom.gateway.router import GatewayRouter
from hmaom.specialists.base import SpecialistHarness

__all__ = [
    "AgentAddress",
    "AgentMessage",
    "RoutingDecision",
    "SpawnRequest",
    "SpawnResult",
    "SynthesisRequest",
    "AgentResult",
    "ContextSlice",
    "StateEntry",
    "CircuitBreaker",
    "GatewayRouter",
    "SpecialistHarness",
]
