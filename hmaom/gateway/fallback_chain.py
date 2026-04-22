"""HMAOM Model Fallback Chain.

Health-aware ordered fallback across model providers.
"""

from __future__ import annotations


class FallbackChain:
    """Ordered model fallback chain with per-model health tracking."""

    def __init__(self, chain: list[str]) -> None:
        self._chain = list(chain)
        self._health: dict[str, float] = {model: 1.0 for model in self._chain}

    @property
    def chain(self) -> list[str]:
        """Return the ordered chain of model names."""
        return list(self._chain)

    def next_model(self, after: str | None = None) -> str | None:
        """Return the next model in the chain after *after*.

        If *after* is None, returns the first model.  If *after* is the
        last model (or not in the chain), returns None.
        """
        if not self._chain:
            return None
        if after is None:
            return self._chain[0]
        try:
            idx = self._chain.index(after)
        except ValueError:
            return None
        if idx + 1 < len(self._chain):
            return self._chain[idx + 1]
        return None

    def record_success(self, model: str) -> None:
        """Boost health for a model that returned a successful response."""
        current = self._health.get(model, 0.5)
        self._health[model] = min(1.0, current + 0.1)

    def record_failure(self, model: str) -> None:
        """Reduce health for a model that returned a failed response."""
        current = self._health.get(model, 0.5)
        self._health[model] = max(0.0, current - 0.2)

    def get_healthy_models(self, threshold: float = 0.5) -> list[str]:
        """Return all models whose health score is >= *threshold*,
        preserving chain order."""
        return [m for m in self._chain if self._health.get(m, 0.0) >= threshold]

    def fallback_sequence(self, starting_model: str) -> list[str]:
        """Return the full ordered fallback path starting from
        *starting_model* (inclusive)."""
        try:
            idx = self._chain.index(starting_model)
        except ValueError:
            return []
        return self._chain[idx:]

    def health_snapshot(self) -> dict[str, float]:
        """Return a copy of the current health scores."""
        return dict(self._health)
