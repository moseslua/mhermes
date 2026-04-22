"""Cost-aware model router for dynamic model selection.

Dynamically selects models per-request based on task complexity, priority,
budget, and historical performance.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from hmaom.config import CostAwareConfig
from hmaom.protocol.schemas import Domain, TaskDescription
from hmaom.state.budget_manager import GlobalBudgetManager
from hmaom.state.user_model import UserModel


class ModelTier(Enum):
    FAST = "fast"
    STANDARD = "standard"
    THOROUGH = "thorough"


@dataclass
class ModelConfig:
    name: str
    tier: ModelTier
    cost_per_1k_tokens: float
    latency_ms_typical: int
    max_context: int


class CostAwareRouter:
    """Dynamically selects models per-request.

    Selection logic (in priority order):
    1. Budget constraint: downgrade when remaining budget is tight
    2. Priority: upgrade for critical/high, downgrade for low
    3. Complexity: map complexity 1-10 to tier
    4. Historical success: prefer cheaper model if success rate >= threshold
    5. Latency SLA: downgrade if estimated latency exceeds SLA
    """

    def __init__(
        self,
        config: CostAwareConfig,
        budget_manager: Optional[GlobalBudgetManager] = None,
        user_model: Optional[UserModel] = None,
    ) -> None:
        self.config = config
        self.budget_manager = budget_manager
        self.user_model = user_model

        self._models: dict[str, ModelConfig] = {}
        self._default_models: dict[Domain, str] = {}

        for entry in self.config.model_catalog:
            self.register_model(
                name=entry["name"],
                tier=ModelTier(entry["tier"]),
                cost_per_1k_tokens=entry["cost_per_1k_tokens"],
                latency_ms_typical=entry["latency_ms_typical"],
                max_context=entry["max_context"],
            )

        for domain_str, model_name in self.config.default_models.items():
            self._default_models[Domain(domain_str)] = model_name

    def register_model(
        self,
        name: str,
        tier: ModelTier,
        cost_per_1k_tokens: float,
        latency_ms_typical: int,
        max_context: int,
    ) -> None:
        """Register a model in the router catalog."""
        self._models[name] = ModelConfig(
            name=name,
            tier=tier,
            cost_per_1k_tokens=cost_per_1k_tokens,
            latency_ms_typical=latency_ms_typical,
            max_context=max_context,
        )

    def select_model(
        self,
        domain: Domain,
        task: TaskDescription,
        complexity: int,
        session_id: Optional[str] = None,
    ) -> str:
        """Select the best model for a task."""
        if not self.config.enabled:
            default = self._default_models.get(domain)
            return default or next(iter(self._models.keys()), "claude-sonnet-4")

        # Step 3: Base tier from complexity
        if complexity <= 3:
            tier = ModelTier.FAST
        elif complexity <= 7:
            tier = ModelTier.STANDARD
        else:
            tier = ModelTier.THOROUGH

        # Step 2: Adjust for priority
        if task.priority in ("critical", "high"):
            if tier == ModelTier.FAST:
                tier = ModelTier.STANDARD
            elif tier == ModelTier.STANDARD:
                tier = ModelTier.THOROUGH
        elif task.priority == "low":
            if tier == ModelTier.THOROUGH:
                tier = ModelTier.STANDARD
            elif tier == ModelTier.STANDARD:
                tier = ModelTier.FAST

        # Step 1: Budget constraint — downgrade if estimated cost exceeds remaining budget
        remaining_budget = self._get_remaining_budget()
        estimated_cost = self._estimate_cost_for_tier(tier, complexity)
        while estimated_cost > remaining_budget and tier != ModelTier.FAST:
            tier = ModelTier.STANDARD if tier == ModelTier.THOROUGH else ModelTier.FAST
            estimated_cost = self._estimate_cost_for_tier(tier, complexity)

        candidates = [m for m in self._models.values() if m.tier == tier]

        # Step 4: Historical success — if a cheaper model has >= threshold success rate, prefer it
        if session_id is not None and self.user_model is not None:
            cheaper_tiers: list[ModelTier] = []
            if tier == ModelTier.THOROUGH:
                cheaper_tiers = [ModelTier.STANDARD, ModelTier.FAST]
            elif tier == ModelTier.STANDARD:
                cheaper_tiers = [ModelTier.FAST]

            for cheaper_tier in cheaper_tiers:
                cheaper_models = sorted(
                    (m for m in self._models.values() if m.tier == cheaper_tier),
                    key=lambda m: m.cost_per_1k_tokens,
                )
                for m in cheaper_models:
                    try:
                        rate = self.user_model.get_model_success_rate(
                            session_id, domain.value, m.name
                        )
                        if rate >= self.config.success_rate_threshold:
                            return m.name
                    except Exception:
                        pass  # Best-effort

        # Step 5: Latency SLA — if all candidates exceed SLA, try to downgrade
        latency_sla = self.config.latency_sla_ms.get(
            task.priority,
            self.config.latency_sla_ms.get("medium", 30000),
        )
        if candidates:
            all_too_slow = all(c.latency_ms_typical > latency_sla for c in candidates)
            if all_too_slow and tier != ModelTier.FAST:
                next_tier = ModelTier.STANDARD if tier == ModelTier.THOROUGH else ModelTier.FAST
                faster = [
                    m
                    for m in self._models.values()
                    if m.tier == next_tier and m.latency_ms_typical <= latency_sla
                ]
                if faster:
                    return min(faster, key=lambda m: m.cost_per_1k_tokens).name

        if candidates:
            return min(candidates, key=lambda m: m.cost_per_1k_tokens).name

        # Fallbacks
        default = self._default_models.get(domain)
        if default:
            return default
        if self._models:
            return next(iter(self._models.keys()))
        return "claude-sonnet-4"

    def estimate_cost(self, domain: Domain, model: str, complexity: int) -> float:
        """Rough cost estimate for a task."""
        cfg = self._models.get(model)
        if cfg is None:
            return 0.0
        base_tokens = 500
        estimated_tokens = base_tokens * max(1, complexity)
        return (estimated_tokens / 1000) * cfg.cost_per_1k_tokens

    def record_outcome(
        self,
        domain: Domain,
        model: str,
        success: bool,
        tokens_used: int,
        latency_ms: int,
        session_id: Optional[str] = None,
    ) -> None:
        """Feed execution outcome back into the user model."""
        if self.user_model is None:
            return
        try:
            user_id = session_id or domain.value
            self.user_model.record_model_outcome(user_id, domain.value, model, success)
        except Exception:
            pass  # Best-effort

    def get_recommendations(self, domain: Domain) -> list[dict[str, Any]]:
        """Return ranked model suggestions for a domain."""
        models: list[dict[str, Any]] = []
        for name, cfg in self._models.items():
            models.append(
                {
                    "name": name,
                    "tier": cfg.tier.value,
                    "cost_per_1k_tokens": cfg.cost_per_1k_tokens,
                    "latency_ms_typical": cfg.latency_ms_typical,
                    "max_context": cfg.max_context,
                    "estimated_cost_low": self.estimate_cost(domain, name, 1),
                    "estimated_cost_high": self.estimate_cost(domain, name, 10),
                }
            )
        models.sort(key=lambda m: m["cost_per_1k_tokens"])
        return models

    def _get_remaining_budget(self) -> float:
        if self.budget_manager is None:
            return float("inf")
        try:
            status = self.budget_manager.get_global_status()
            return float(status.get("cost_remaining_usd", float("inf")))
        except Exception:
            return float("inf")

    def _estimate_cost_for_tier(self, tier: ModelTier, complexity: int) -> float:
        tier_models = [m for m in self._models.values() if m.tier == tier]
        if not tier_models:
            return float("inf")
        cheapest = min(tier_models, key=lambda m: m.cost_per_1k_tokens)
        return self.estimate_cost(Domain.CODE, cheapest.name, complexity)
