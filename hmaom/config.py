"""HMAOM Configuration.

Centralized configuration for the gateway, specialists, and protocol parameters.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class GatewayConfig:
    """Gateway Router configuration."""

    # Classifier settings
    slm_model: str = "phi-4"  # Lightweight local model for fast routing
    slm_latency_budget_ms: int = 50
    slm_confidence_threshold: float = 0.85
    fallback_llm_model: str = "claude-sonnet-4"  # Cloud fallback for uncertain routing

    # Routing
    default_routing_mode: str = "single"
    max_parallel_specialists: int = 10

    # Identity
    gateway_name: str = "hmaom-gateway"
    soul_md_path: Optional[str] = None  # Path to gateway SOUL.md


@dataclass
class SpawnConfig:
    """Hierarchical spawn control limits."""

    max_depth: int = 3
    max_depth_hard: int = 5
    max_breadth: int = 10
    max_breadth_hard: int = 50
    max_tokens_per_tree: int = 100_000
    max_tokens_per_tree_hard: int = 500_000
    max_wall_time_ms: int = 300_000  # 5 minutes
    max_wall_time_ms_hard: int = 1_800_000  # 30 minutes
    max_cost_usd: float = 2.0
    max_cost_usd_hard: float = 10.0


@dataclass
class SpecialistConfig:
    """Per-specialist configuration."""

    name: str
    domain: str
    description: str
    model_override: Optional[str] = None
    skill_count_estimate: int = 500
    lazy_load_areas: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    isolation: str = "git-worktree"  # none | git-worktree | fuse-overlay
    max_subagent_depth: int = 2


@dataclass
class StateConfig:
    """Shared state store configuration."""

    store_type: str = "sqlite"  # sqlite | redis
    sqlite_path: str = field(default_factory=lambda: str(_default_state_dir() / "state.sqlite"))
    vector_index_path: str = field(default_factory=lambda: str(_default_state_dir() / "vectors.sqlite"))
    checkpoint_dir: str = field(default_factory=lambda: str(_default_state_dir() / "checkpoints"))
    default_ttl_seconds: Optional[int] = 3600  # 1 hour for temporary state


@dataclass
class ObservabilityConfig:
    """Observability and tracing configuration."""

    enabled: bool = True
    tracing_backend: str = "jsonl"  # jsonl | opentelemetry | none
    trace_log_path: str = field(default_factory=lambda: str(_default_state_dir() / "traces" / "trace.jsonl"))
    metrics_interval_seconds: int = 60
    health_ping_interval_seconds: int = 30
    stuck_detector_timeout_seconds: int = 120


@dataclass
class FaultToleranceConfig:
    """Fault tolerance configuration."""

    retry_max_attempts: int = 3
    retry_base_delay_seconds: float = 1.0
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_reset_timeout_ms: int = 30_000
    circuit_breaker_half_open_max_calls: int = 2
    escalation_levels: int = 4  # retry -> replan -> decompose -> escalate


@dataclass
class BudgetConfig:
    """Global budget management configuration."""

    max_global_tokens: int = 1_000_000
    max_global_cost_usd: float = 50.0
    max_global_time_ms: int = 600_000
    max_concurrent_trees: int = 10


@dataclass
class HireTriggerConfig:
    """Specialist hire activation trigger configuration."""

    enabled: bool = True
    min_observations: int = 5
    time_window_hours: int = 24
    confidence_threshold: float = 0.6
    subject_frequency_threshold: int = 3
    min_unique_users: int = 1
    require_low_confidence: bool = True
    require_out_of_domain: bool = False


@dataclass
class UserModelConfig:
    """User modeling configuration."""

    enabled: bool = True
    db_path: Optional[str] = None
    prune_inactive_days: int = 30


@dataclass
class LoadBalancerConfig:
    """Load balancer and horizontal scaling configuration."""

    enabled: bool = False
    strategy: str = "round_robin"
    max_replicas_per_domain: int = 3
    health_threshold: float = 0.5


@dataclass
class MetricsConfig:
    """Metrics collection configuration."""

    enabled: bool = True
    prefix: str = "hmaom"
    prometheus_port: Optional[int] = None


@dataclass
class EscalationConfig:
    """Human escalation configuration."""

    human_response_timeout_seconds: int = 300
    channel_timeout_seconds: int = 30
    max_history_entries: int = 1000


@dataclass
class ThreadingConfig:
    """Cross-session threading configuration."""

    similarity_threshold: float = 0.2
    max_threads_per_user: int = 100
    default_prune_days: int = 7


@dataclass
class GuardrailConfig:
    """Guardrail and prompt-injection defense configuration."""

    enabled: bool = True
    custom_patterns: list[str] = field(default_factory=list)
    block_threshold: float = 0.0


@dataclass
class ABTestConfig:
    """A/B test routing configuration."""

    enabled: bool = False
    variants: list[dict] = field(default_factory=list)
    default_variant: Optional[str] = None


@dataclass
class PromptRegistryConfig:
    """Prompt registry and rollout configuration."""

    enabled: bool = False
    db_path: Optional[str] = None
    auto_rollback: bool = True
    min_rollout_samples: int = 100


@dataclass
@dataclass
class ToolRegistryConfig:
    """Dynamic tool registry configuration."""

    tools_dir: str = field(default_factory=lambda: str(Path.home() / ".hmaom" / "tools"))
    db_path: str = field(default_factory=lambda: str(_default_state_dir() / "tool_registry.sqlite"))
    auto_reload: bool = False


@dataclass
class MCPConfig:
    """MCP Server configuration."""

    enabled: bool = False
    transport: str = "stdio"  # stdio | sse
    sse_host: str = "127.0.0.1"
    sse_port: int = 8765
    tool_name_prefix: str = "hmaom"


@dataclass
class ElasticConfig:
    """Elastic replica manager configuration."""

    enabled: bool = False
    min_replicas: int = 1
    max_replicas: int = 10
    scale_up_queue_depth_threshold: int = 5
    scale_up_latency_ms_threshold: int = 2000
    scale_down_idle_ticks: int = 3
    scale_up_cooldown_seconds: float = 30.0
    scale_down_cooldown_seconds: float = 60.0
    latency_sla_ms: int = 1000


@dataclass
class CostAwareConfig:
    """Cost-aware model router configuration."""

    enabled: bool = False
    default_models: dict[str, str] = field(default_factory=dict)
    model_catalog: list[dict] = field(default_factory=list)
    cost_threshold_usd: float = 5.0
    latency_sla_ms: dict[str, int] = field(default_factory=lambda: {
        "low": 30000,
        "medium": 15000,
        "high": 10000,
        "critical": 5000,
    })
    success_rate_threshold: float = 0.95


@dataclass
class DistributedConfig:
    """Distributed gateway components configuration."""

    redis_url: Optional[str] = None
    fallback_sqlite_path: Optional[str] = None
    leader_key: Optional[str] = None
    lock_ttl_ms: int = 30000


@dataclass
class HMAOMConfig:
    """Top-level HMAOM configuration."""

    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    spawn: SpawnConfig = field(default_factory=SpawnConfig)
    state: StateConfig = field(default_factory=StateConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    fault_tolerance: FaultToleranceConfig = field(default_factory=FaultToleranceConfig)
    specialists: list[SpecialistConfig] = field(default_factory=list)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    hire_triggers: HireTriggerConfig = field(default_factory=HireTriggerConfig)
    user_model: UserModelConfig = field(default_factory=UserModelConfig)
    load_balancer: LoadBalancerConfig = field(default_factory=LoadBalancerConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    threading: ThreadingConfig = field(default_factory=ThreadingConfig)
    escalation: EscalationConfig = field(default_factory=EscalationConfig)
    guardrails: GuardrailConfig = field(default_factory=GuardrailConfig)
    ab_test: ABTestConfig = field(default_factory=ABTestConfig)
    prompt_registry: PromptRegistryConfig = field(default_factory=PromptRegistryConfig)
    tool_registry: ToolRegistryConfig = field(default_factory=ToolRegistryConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    elastic: ElasticConfig = field(default_factory=ElasticConfig)
    cost_aware: CostAwareConfig = field(default_factory=CostAwareConfig)
    distributed: DistributedConfig = field(default_factory=DistributedConfig)

    @classmethod
    def default(cls) -> HMAOMConfig:
        """Return the default configuration with pre-defined specialists."""
        return cls(
            specialists=[
                SpecialistConfig(
                    name="finance",
                    domain="finance",
                    description="Quant analysis, risk modeling, market data, portfolio optimization",
                    model_override="claude-sonnet-4",
                    skill_count_estimate=800,
                    lazy_load_areas=["risk", "derivatives", "portfolio", "market-data"],
                    max_subagent_depth=2,
                ),
                SpecialistConfig(
                    name="maths",
                    domain="maths",
                    description="Symbolic math, numerical methods, statistics, proof verification",
                    model_override="claude-sonnet-4",
                    skill_count_estimate=600,
                    lazy_load_areas=["calculus", "linear-algebra", "stats", "proofs"],
                    max_subagent_depth=2,
                ),
                SpecialistConfig(
                    name="code",
                    domain="code",
                    description="Software engineering, debugging, architecture, review",
                    model_override="claude-opus-4",
                    skill_count_estimate=1200,
                    lazy_load_areas=["python", "typescript", "rust", "go", "review", "test"],
                    max_subagent_depth=2,
                ),
                SpecialistConfig(
                    name="physics",
                    domain="physics",
                    description="Thermodynamics, mechanics, simulations, unit analysis",
                    model_override="claude-sonnet-4",
                    skill_count_estimate=500,
                    lazy_load_areas=["thermo", "mechanics", "em", "simulation"],
                    max_subagent_depth=2,
                ),
                SpecialistConfig(
                    name="research",
                    domain="research",
                    description="Web search, paper analysis, data collection, synthesis",
                    model_override="claude-sonnet-4",
                    skill_count_estimate=400,
                    lazy_load_areas=["web", "papers", "data"],
                    max_subagent_depth=2,
                ),
                SpecialistConfig(
                    name="reporter",
                    domain="reporter",
                    description="Document generation, formatting, cross-domain synthesis",
                    model_override="claude-sonnet-4",
                    skill_count_estimate=300,
                    lazy_load_areas=[],
                    max_subagent_depth=2,
                ),
            ],
            threading=ThreadingConfig(),
            escalation=EscalationConfig(),
            guardrails=GuardrailConfig(),
            ab_test=ABTestConfig(),
            prompt_registry=PromptRegistryConfig(),
        )


def _default_state_dir() -> Path:
    """Return the default HMAOM state directory."""
    home = Path.home()
    state_dir = home / ".hmaom" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def get_config() -> HMAOMConfig:
    """Load configuration from environment or return defaults."""
    # TODO: Load from YAML/JSON config file if present
    return HMAOMConfig.default()
