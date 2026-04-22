"""HMAOM Protocol Layer.

Structured inter-agent communication with JSON Schema validation.
Includes the message bus, spawn protocol, and synthesis protocol.
"""

from hmaom.protocol.schemas import (
    AgentAddress,
    AgentMessage,
    MessageType,
    RoutingDecision,
    RoutingMode,
    TaskType,
    Domain,
    SpawnRequest,
    SpawnResult,
    SynthesisRequest,
    AgentResult,
    ContextSlice,
    TaskDescription,
    Evidence,
    StateEntry,
    CircuitBreaker,
)
from hmaom.protocol.message_bus import MessageBus
from hmaom.protocol.spawn import SpawnProtocol

__all__ = [
    "AgentAddress",
    "AgentMessage",
    "MessageType",
    "RoutingDecision",
    "RoutingMode",
    "TaskType",
    "Domain",
    "SpawnRequest",
    "SpawnResult",
    "SynthesisRequest",
    "AgentResult",
    "ContextSlice",
    "TaskDescription",
    "Evidence",
    "StateEntry",
    "CircuitBreaker",
    "MessageBus",
    "SpawnProtocol",
]


from hmaom.protocol.validator import SchemaValidator

__all__.append("SchemaValidator")