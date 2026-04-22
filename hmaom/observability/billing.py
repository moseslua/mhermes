"""Billing record exporter."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class BillingRecord:
    correlation_id: str
    user_id: str
    domain: str
    tokens_used: int
    cost_usd: float
    elapsed_ms: int


class BillingExporter:
    """In-memory billing record store with summary and export capabilities."""

    MAX_RECORDS = 100000

    def __init__(self) -> None:
        self._records: list[BillingRecord] = []

    def record(
        self,
        correlation_id: str,
        user_id: str,
        domain: str,
        tokens_used: int,
        cost_usd: float,
        elapsed_ms: int,
    ) -> None:
        """Append a billing record."""
        self._records.append(
            BillingRecord(
                correlation_id=correlation_id,
                user_id=user_id,
                domain=domain,
                tokens_used=tokens_used,
                cost_usd=cost_usd,
                elapsed_ms=elapsed_ms,
            )
        )
        if len(self._records) > self.MAX_RECORDS:
            # Remove oldest 10%
            remove_count = self.MAX_RECORDS // 10
            self._records = self._records[remove_count:]

    def get_summary(
        self,
        user_id: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> dict:
        """Aggregate records by optional user_id and/or domain filters."""
        filtered = self._records
        if user_id is not None:
            filtered = [r for r in filtered if r.user_id == user_id]
        if domain is not None:
            filtered = [r for r in filtered if r.domain == domain]

        total_tokens = sum(r.tokens_used for r in filtered)
        total_cost = sum(r.cost_usd for r in filtered)
        total_elapsed = sum(r.elapsed_ms for r in filtered)
        count = len(filtered)

        by_user: dict[str, dict] = {}
        by_domain: dict[str, dict] = {}

        for r in filtered:
            if r.user_id not in by_user:
                by_user[r.user_id] = {
                    "tokens_used": 0,
                    "cost_usd": 0.0,
                    "elapsed_ms": 0,
                    "count": 0,
                }
            bu = by_user[r.user_id]
            bu["tokens_used"] += r.tokens_used
            bu["cost_usd"] += r.cost_usd
            bu["elapsed_ms"] += r.elapsed_ms
            bu["count"] += 1

            if r.domain not in by_domain:
                by_domain[r.domain] = {
                    "tokens_used": 0,
                    "cost_usd": 0.0,
                    "elapsed_ms": 0,
                    "count": 0,
                }
            bd = by_domain[r.domain]
            bd["tokens_used"] += r.tokens_used
            bd["cost_usd"] += r.cost_usd
            bd["elapsed_ms"] += r.elapsed_ms
            bd["count"] += 1

        return {
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "total_elapsed_ms": total_elapsed,
            "count": count,
            "by_user": by_user,
            "by_domain": by_domain,
        }

    def export_csv(self, path: str) -> str:
        """Write records to *path* as CSV. Returns the absolute path."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                ["correlation_id", "user_id", "domain", "tokens_used", "cost_usd", "elapsed_ms"]
            )
            for r in self._records:
                writer.writerow(
                    [r.correlation_id, r.user_id, r.domain, r.tokens_used, r.cost_usd, r.elapsed_ms]
                )
        return str(out.absolute())

    def export_json(self, path: str) -> str:
        """Write records to *path* as JSON. Returns the absolute path."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "correlation_id": r.correlation_id,
                "user_id": r.user_id,
                "domain": r.domain,
                "tokens_used": r.tokens_used,
                "cost_usd": r.cost_usd,
                "elapsed_ms": r.elapsed_ms,
            }
            for r in self._records
        ]
        with out.open("w") as fh:
            json.dump(payload, fh, indent=2)
        return str(out.absolute())
