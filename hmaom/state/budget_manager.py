"""Global budget manager for tracking resources across all active request trees."""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class GlobalBudgetManager:
    """Tracks budgets across ALL active request trees and enforces global limits."""

    def __init__(
        self,
        max_global_tokens: int = 1_000_000,
        max_global_cost_usd: float = 50.0,
        max_global_time_ms: int = 600_000,
        max_concurrent_trees: int = 10,
    ) -> None:
        self._max_global_tokens = max_global_tokens
        self._max_global_cost_usd = max_global_cost_usd
        self._max_global_time_ms = max_global_time_ms
        self._max_concurrent_trees = max_concurrent_trees

        self._lock = threading.Lock()
        self._tree_budgets: dict[str, dict[str, Any]] = {}
        self._global_limits: dict[str, Any] = {
            "max_global_tokens": max_global_tokens,
            "max_global_cost_usd": max_global_cost_usd,
            "max_global_time_ms": max_global_time_ms,
            "max_concurrent_trees": max_concurrent_trees,
        }
        self._active_trees: set[str] = set()

    def register_tree(self, correlation_id: str, limits: dict[str, Any]) -> None:
        """Register a new tree with its budget allocation."""
        with self._lock:
            if correlation_id in self._active_trees:
                return
            self._active_trees.add(correlation_id)
            self._tree_budgets[correlation_id] = {
                "max_tokens": limits.get("tokens", 0),
                "max_cost_usd": limits.get("cost_usd", 0.0),
                "max_time_ms": limits.get("time_ms", 0),
                "tokens_used": 0,
                "cost_usd_used": 0.0,
                "time_ms_used": 0,
                "status": "active",
            }

    def consume(
        self,
        correlation_id: str,
        tokens: int = 0,
        cost_usd: float = 0.0,
        time_ms: int = 0,
    ) -> None:
        """Record consumption for a tree. Warns if tree exceeds its own allocation."""
        with self._lock:
            if correlation_id not in self._tree_budgets:
                return
            tree = self._tree_budgets[correlation_id]
            tree["tokens_used"] += tokens
            tree["cost_usd_used"] += cost_usd
            tree["time_ms_used"] += time_ms

            if tree["max_tokens"] > 0 and tree["tokens_used"] > tree["max_tokens"]:
                logger.warning("Tree %s exceeded token allocation", correlation_id)
            if tree["max_cost_usd"] > 0.0 and tree["cost_usd_used"] > tree["max_cost_usd"]:
                logger.warning("Tree %s exceeded cost allocation", correlation_id)
            if tree["max_time_ms"] > 0 and tree["time_ms_used"] > tree["max_time_ms"]:
                logger.warning("Tree %s exceeded time allocation", correlation_id)

    def can_allocate(self, tokens: int = 0, cost_usd: float = 0.0) -> bool:
        """Check if system has headroom for a new tree."""
        with self._lock:
            if len(self._active_trees) >= self._max_concurrent_trees:
                return False

            total_tokens = sum(t["tokens_used"] for t in self._tree_budgets.values())
            total_cost = sum(t["cost_usd_used"] for t in self._tree_budgets.values())

            if self._max_global_tokens > 0 and total_tokens + tokens > self._max_global_tokens:
                return False
            if self._max_global_cost_usd > 0.0 and total_cost + cost_usd > self._max_global_cost_usd:
                return False

            return True

    def get_tree_status(self, correlation_id: str) -> dict[str, Any]:
        """Return remaining budget for a tree."""
        with self._lock:
            if correlation_id not in self._tree_budgets:
                return {
                    "tokens_remaining": 0,
                    "cost_remaining_usd": 0.0,
                    "time_remaining_ms": 0,
                    "status": "unknown",
                }
            tree = self._tree_budgets[correlation_id]
            return {
                "tokens_remaining": max(0, tree["max_tokens"] - tree["tokens_used"]),
                "cost_remaining_usd": max(0.0, tree["max_cost_usd"] - tree["cost_usd_used"]),
                "time_remaining_ms": max(0, tree["max_time_ms"] - tree["time_ms_used"]),
                "status": tree["status"],
            }

    def get_global_status(self) -> dict[str, Any]:
        """Return total used/remaining across all trees."""
        with self._lock:
            total_tokens = sum(t["tokens_used"] for t in self._tree_budgets.values())
            total_cost = sum(t["cost_usd_used"] for t in self._tree_budgets.values())
            total_time = sum(t["time_ms_used"] for t in self._tree_budgets.values())
            return {
                "total_trees": len(self._active_trees),
                "total_tokens_used": total_tokens,
                "total_cost_used_usd": total_cost,
                "total_time_used_ms": total_time,
                "tokens_remaining": max(0, self._max_global_tokens - total_tokens),
                "cost_remaining_usd": max(0.0, self._max_global_cost_usd - total_cost),
                "time_remaining_ms": max(0, self._max_global_time_ms - total_time),
                "max_concurrent_trees": self._max_concurrent_trees,
            }

    def unregister_tree(self, correlation_id: str) -> None:
        """Cleanup when tree completes."""
        with self._lock:
            self._active_trees.discard(correlation_id)
            self._tree_budgets.pop(correlation_id, None)

    def kill_tree(self, correlation_id: str) -> dict[str, Any]:
        """Mark tree as killed and return final status."""
        with self._lock:
            if correlation_id not in self._tree_budgets:
                return {
                    "tokens_remaining": 0,
                    "cost_remaining_usd": 0.0,
                    "time_remaining_ms": 0,
                    "status": "unknown",
                }
            tree = self._tree_budgets[correlation_id]
            tree["status"] = "killed"
            self._active_trees.discard(correlation_id)
            return {
                "tokens_remaining": max(0, tree["max_tokens"] - tree["tokens_used"]),
                "cost_remaining_usd": max(0.0, tree["max_cost_usd"] - tree["cost_usd_used"]),
                "time_remaining_ms": max(0, tree["max_time_ms"] - tree["time_ms_used"]),
                "status": "killed",
            }
