"""HMAOM Health Monitoring & Circuit Breakers.

Health pings, circuit breaker pattern, and stuck detection.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from hmaom.config import FaultToleranceConfig, ObservabilityConfig
from hmaom.protocol.schemas import AgentAddress, CircuitBreaker, HealthStatus


class CircuitBreakerRegistry:
    """Registry of circuit breakers for all specialist harnesses.

    When a specialist's circuit is OPEN, tasks are routed to alternative
    specialists or the Reporter harness with a failure note.
    """

    def __init__(self, config: Optional[FaultToleranceConfig] = None) -> None:
        self.config = config or FaultToleranceConfig()
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.RLock()

    def _get_or_create(self, harness: str) -> CircuitBreaker:
        with self._lock:
            if harness not in self._breakers:
                self._breakers[harness] = CircuitBreaker(
                    harness=harness,
                    failure_threshold=self.config.circuit_breaker_failure_threshold,
                    reset_timeout_ms=self.config.circuit_breaker_reset_timeout_ms,
                    half_open_max_calls=self.config.circuit_breaker_half_open_max_calls,
                )
            return self._breakers[harness]

    def record_success(self, harness: str) -> None:
        """Record a successful call to a specialist."""
        with self._lock:
            cb = self._get_or_create(harness)
            if cb.state == "half-open":
                cb.half_open_calls += 1
                if cb.half_open_calls >= cb.half_open_max_calls:
                    cb.state = "closed"
                    cb.failures = 0
                    cb.half_open_calls = 0
            elif cb.state == "closed":
                cb.failures = max(0, cb.failures - 1)

    def record_failure(self, harness: str) -> None:
        """Record a failed call to a specialist."""
        with self._lock:
            cb = self._get_or_create(harness)
            cb.failures += 1
            cb.last_failure = time.time()

            if cb.state == "half-open":
                cb.state = "open"
                cb.half_open_calls = 0
            elif cb.state == "closed" and cb.failures >= cb.failure_threshold:
                cb.state = "open"

    def can_call(self, harness: str) -> bool:
        """Check if calls are allowed to a specialist."""
        with self._lock:
            cb = self._get_or_create(harness)

            if cb.state == "closed":
                return True

            if cb.state == "open":
                elapsed_ms = (time.time() - cb.last_failure) * 1000
                if elapsed_ms >= cb.reset_timeout_ms:
                    cb.state = "half-open"
                    cb.half_open_calls = 0
                    return True
                return False

            if cb.state == "half-open":
                return cb.half_open_calls < cb.half_open_max_calls

            return True

    def get_state(self, harness: str) -> CircuitBreaker:
        """Get the current circuit breaker state for a harness."""
        return self._get_or_create(harness)

    def all_states(self) -> dict[str, CircuitBreaker]:
        """Get all circuit breaker states."""
        return dict(self._breakers)


class HealthMonitor:
    """Monitors health of agents and detects stuck execution.

    - Periodic health pings
    - Stuck detection (no progress for N seconds)
    - Queue depth monitoring
    """

    def __init__(
        self,
        observability_config: Optional[ObservabilityConfig] = None,
    ) -> None:
        self.config = observability_config or ObservabilityConfig()
        self._last_activity: dict[str, float] = {}
        self._statuses: dict[str, HealthStatus] = {}

    def record_activity(self, agent_address: AgentAddress) -> None:
        """Record activity from an agent."""
        key = str(agent_address)
        now = time.time()
        self._last_activity[key] = now
        # Prune entries older than 24 hours
        cutoff = now - 86400
        self._last_activity = {k: v for k, v in self._last_activity.items() if v > cutoff}

    def is_stuck(self, agent_address: AgentAddress) -> tuple[bool, Optional[float]]:
        """Check if an agent appears stuck.

        Returns (is_stuck, seconds_since_last_activity).
        """
        key = str(agent_address)
        last = self._last_activity.get(key)
        if last is None:
            return False, None

        elapsed = time.time() - last
        threshold = self.config.stuck_detector_timeout_seconds
        return elapsed > threshold, elapsed

    def update_status(self, status: HealthStatus) -> None:
        """Update the health status for an agent."""
        key = str(status.agent_address)
        self._statuses[key] = status
        self._last_activity[key] = status.timestamp
        # Prune entries older than 24 hours
        cutoff = status.timestamp - 86400
        self._last_activity = {k: v for k, v in self._last_activity.items() if v > cutoff}
        self._statuses = {k: v for k, v in self._statuses.items() if v.timestamp > cutoff}

    def get_status(self, agent_address: AgentAddress) -> Optional[HealthStatus]:
        """Get the health status for an agent."""
        return self._statuses.get(str(agent_address))

    def get_all_statuses(self) -> list[HealthStatus]:
        """Get all known health statuses."""
        return list(self._statuses.values())

    def stuck_agents(self) -> list[tuple[AgentAddress, float]]:
        """Return all agents that appear stuck with elapsed time."""
        stuck: list[tuple[AgentAddress, float]] = []
        for key, last in self._last_activity.items():
            elapsed = time.time() - last
            if elapsed > self.config.stuck_detector_timeout_seconds:
                # Parse key back to AgentAddress (best effort)
                parts = key.split("/")
                if len(parts) == 2:
                    agent_parts = parts[1].split("@")
                    addr = AgentAddress(
                        harness=parts[0],
                        agent=agent_parts[0],
                        depth=int(agent_parts[1]) if len(agent_parts) > 1 else 0,
                    )
                    stuck.append((addr, elapsed))
        return stuck

    def summary(self) -> dict[str, Any]:
        """Return a health summary."""
        total = len(self._statuses)
        healthy = sum(1 for s in self._statuses.values() if s.status == "healthy")
        degraded = sum(1 for s in self._statuses.values() if s.status == "degraded")
        unhealthy = sum(1 for s in self._statuses.values() if s.status == "unhealthy")
        stuck = self.stuck_agents()

        return {
            "total_agents": total,
            "healthy": healthy,
            "degraded": degraded,
            "unhealthy": unhealthy,
            "stuck_count": len(stuck),
            "stuck_agents": [
                {"harness": str(a.harness), "agent": str(a.agent), "idle_seconds": round(e, 1)}
                for a, e in stuck
            ],
        }
