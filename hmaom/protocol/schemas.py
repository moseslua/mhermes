"""HMAOM Protocol Schemas.

Core Pydantic models for all inter-agent communication, routing decisions,
spawn requests, and state management.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Domain(str, Enum):
    """Recognized specialist domains."""

    FINANCE = "finance"
    MATHS = "maths"
    PHYSICS = "physics"
    CODE = "code"
    RESEARCH = "research"
    REPORTER = "reporter"
    META = "meta"


class TaskType(str, Enum):
    """Classification of task character."""

    ANALYTICAL = "analytical"
    CREATIVE = "creative"
    SYNTHETIC = "synthetic"
    META = "meta"


class RoutingMode(str, Enum):
    """How a task should be distributed across specialists."""

    SINGLE = "single"
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"
    ADAPTIVE = "adaptive"


class MessageType(str, Enum):
    """Types of messages on the inter-agent bus."""

    TASK_REQUEST = "task_request"
    TASK_RESULT = "task_result"
    PARTIAL_RESULT = "partial_result"
    CONTEXT_REQUEST = "context_request"
    CONTEXT_RESPONSE = "context_response"
    ERROR = "error"
    CHECKPOINT = "checkpoint"
    SYNTHESIS_REQUEST = "synthesis_request"
    HEALTH_PING = "health_ping"


class AgentAddress(BaseModel):
    """Hierarchical address of an agent in the mesh."""

    harness: str = Field(description="Gateway or specialist harness name")
    agent: str = Field(description="Agent identifier within the harness")
    depth: int = Field(default=0, description="Depth in the spawn tree")

    def __str__(self) -> str:
        return f"{self.harness}/{self.agent}@{self.depth}"


class RoutingDecision(BaseModel):
    """Output of the intent classifier."""

    primary_domain: Domain
    secondary_domains: list[Domain] = Field(default_factory=list)
    task_type: TaskType = TaskType.ANALYTICAL
    routing_mode: RoutingMode = RoutingMode.SINGLE
    estimated_complexity: int = Field(default=5, ge=1, le=10)
    required_synthesis: bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class TaskDescription(BaseModel):
    """Structured definition of a task to be executed."""

    title: str = Field(description="Short task title")
    description: str = Field(description="Full task description")
    expected_output_schema: Optional[dict[str, Any]] = Field(
        default=None, description="JSONSchema for expected output"
    )
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    tags: list[str] = Field(default_factory=list)


class ContextSlice(BaseModel):
    """Filtered subset of parent context passed to a child agent."""

    source_agent: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    content: str
    memory_keys: list[str] = Field(default_factory=list)
    token_estimate: int = 0


class Evidence(BaseModel):
    """Supporting evidence for an agent result."""

    source: str
    data: Any
    confidence: float = Field(ge=0.0, le=1.0)


class AgentResult(BaseModel):
    """Result produced by a specialist or subagent."""

    source: AgentAddress
    result: Any
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    tokens_used: int = 0
    time_ms: int = 0


class SpawnConstraints(BaseModel):
    """Budget and permission constraints for a spawned subagent."""

    max_depth: int = Field(default=2, ge=0, le=5)
    max_tokens: int = Field(default=50_000, ge=1000)
    max_time_ms: int = Field(default=300_000, ge=1000)
    tools: list[str] = Field(default_factory=list, description="Allowed tool whitelist")


class SpawnRequest(BaseModel):
    """Request to spawn a subagent."""

    # Identity
    spawn_id: str = Field(description="UUID for this spawn")
    parent_id: str = Field(description="Parent agent ID")
    correlation_id: str = Field(description="Traces back to root request")
    depth: int = Field(ge=0, le=5)

    # Context
    task: TaskDescription
    context_slice: ContextSlice
    memory_keys: list[str] = Field(default_factory=list)

    # Constraints
    constraints: SpawnConstraints = Field(default_factory=SpawnConstraints)

    # Return format
    output_schema: Optional[dict[str, Any]] = None
    model_override: Optional[str] = Field(default=None, description="Override model name for this spawn")


class SpawnResult(BaseModel):
    """Result of a spawned subagent execution."""

    spawn_id: str
    status: Literal["success", "failure", "timeout", "killed"]
    result: Any = None
    tokens_used: int = 0
    time_ms: int = 0
    checkpoint_url: Optional[str] = None
    child_spawns: list["SpawnResult"] = Field(default_factory=list)
    error: Optional[str] = None


class SynthesisRequest(BaseModel):
    """Request to synthesize results from multiple specialists."""

    correlation_id: str
    sources: list[AgentResult]
    synthesis_type: Literal["unify", "reconcile", "sequential", "debate"] = "unify"
    output_schema: Optional[dict[str, Any]] = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    max_tokens: int = 20_000
    require_citations: bool = True




class SynthesisResult(BaseModel):

    """Structured result of a synthesis operation."""

    content: str = Field(description="Final synthesized text")

    citations: list[AgentAddress] = Field(default_factory=list, description="Sources cited")

    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    conflicts_resolved: list[dict] = Field(default_factory=list, description="Conflicts found and how they were resolved")

    tokens_used: int = 0

    debate_rounds: list[dict] = Field(default_factory=list, description="Structured debate rounds (debate mode only)")

    uncertainty_note: Optional[str] = Field(default=None, description="Note when all sources conflict")

    

    def model_dump(self, **kwargs):

        data = super().model_dump(**kwargs)

        data["citations"] = [c.model_dump(**kwargs) for c in self.citations]

        return data

    

    @classmethod

    def from_agent_results(

        cls,

        results: list[AgentResult],

        content: str,

        confidence: float = 1.0,

        conflicts_resolved: list[dict] | None = None,

        tokens_used: int = 0,

        debate_rounds: list[dict] | None = None,

        uncertainty_note: str | None = None,

    ) -> "SynthesisResult":

        """Factory to build a SynthesisResult from AgentResults, extracting citations."""

        citations = [r.source for r in results]

        return cls(

            content=content,

            citations=citations,

            confidence=confidence,

            conflicts_resolved=conflicts_resolved or [],

            tokens_used=tokens_used,

            debate_rounds=debate_rounds or [],

            uncertainty_note=uncertainty_note,

        )


class DebateRound(BaseModel):

    """A single round of structured debate between proponent and opponent."""

    round_number: int = Field(description="Debate round index (1-based)")

    proponent_argument: str = Field(description="Argument in favor of the position")

    opponent_argument: str = Field(description="Argument against the position")

    judge_verdict: str = Field(description="Judge's assessment of this round")

    winner: Literal["proponent", "opponent", "tie"] = Field(description="Round winner")

    

    @classmethod

    def from_spawn_results(

        cls,

        round_number: int,

        proponent_result: SpawnResult,

        opponent_result: SpawnResult,

        judge_result: SpawnResult,

    ) -> "DebateRound":

        """Build a DebateRound from the three subagent SpawnResults."""

        proponent_text = str(proponent_result.result) if proponent_result.result else "(no response)"

        opponent_text = str(opponent_result.result) if opponent_result.result else "(no response)"

        judge_text = str(judge_result.result) if judge_result.result else "(no response)"

        

        # Simple heuristic: look for winner indication in judge text

        lower_judge = judge_text.lower()

        if "proponent" in lower_judge and "opponent" not in lower_judge:

            winner = "proponent"

        elif "opponent" in lower_judge and "proponent" not in lower_judge:

            winner = "opponent"

        else:

            winner = "tie"

        

        return cls(

            round_number=round_number,

            proponent_argument=proponent_text,

            opponent_argument=opponent_text,

            judge_verdict=judge_text,

            winner=winner,  # type: ignore[arg-type]

        )

class AgentMessage(BaseModel):
    """Generic message on the inter-agent message bus."""

    message_id: str
    correlation_id: str
    timestamp: float
    sender: AgentAddress
    recipient: AgentAddress | Literal["broadcast", "synthesis"]
    type: MessageType
    payload: Any = None


class StateEntry(BaseModel):
    """Entry in the shared state store."""

    key: str = Field(description="Hierarchical key, e.g. 'finance/risk-model/output'")
    value: Any
    value_schema: Optional[dict[str, Any]] = Field(
        default=None, description="JSONSchema for validation"
    )
    written_by: AgentAddress
    written_at: float
    ttl: Optional[int] = None  # seconds
    access_control: dict[str, list[str]] = Field(
        default_factory=lambda: {"read": ["*"], "write": ["*"]}
    )


class CircuitBreaker(BaseModel):
    """Circuit breaker state for a specialist harness."""

    harness: str
    failures: int = 0
    last_failure: float = 0.0
    state: Literal["closed", "open", "half-open"] = "closed"
    failure_threshold: int = 5
    reset_timeout_ms: int = 30_000
    half_open_max_calls: int = 2
    half_open_calls: int = 0


class Checkpoint(BaseModel):
    """Checkpoint for resumable execution."""

    checkpoint_id: str
    correlation_id: str
    agent_address: AgentAddress
    timestamp: float
    messages: list[dict[str, Any]] = Field(default_factory=list)
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    tokens_used: int = 0


class HealthStatus(BaseModel):
    """Health report from a harness or agent."""

    agent_address: AgentAddress
    timestamp: float
    status: Literal["healthy", "degraded", "unhealthy"]
    active_spawns: int = 0
    queue_depth: int = 0
    last_error: Optional[str] = None



class StreamEvent(BaseModel):
    """An event emitted during streaming response processing."""

    event_type: Literal["routing_decision", "decomposition", "partial_result", "synthesis", "complete", "error"]
    correlation_id: str
    data: dict
    timestamp: float


# Resolve forward references
SpawnResult.model_rebuild()
