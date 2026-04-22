"""HMAOM A/B Testing Router.

Weighted random routing across classifier variants with outcome tracking.
"""

from __future__ import annotations

import math
import random
import threading
from typing import Optional


class ABTestRouter:
    """Routes traffic across variant configurations and tracks outcomes.

    Thread-safe registration, weighted random selection, and basic
    statistical reporting per variant.
    """

    def __init__(self) -> None:
        self._variants: dict[str, dict] = {}
        self._traffic_split: dict[str, float] = {}
        self._results: dict[str, list[bool]] = {}
        self._lock = threading.Lock()

    # ── Public API ──────────────────────────────────────────────────────────

    def register_variant(self, name: str, classifier_config: dict, traffic_pct: float) -> None:
        """Register a variant with its config and traffic percentage.

        *traffic_pct* should be between 0.0 and 1.0. Percentages across all
        variants need not sum to 1.0 — selection is done proportionally.
        """
        if not 0.0 <= traffic_pct <= 1.0:
            raise ValueError("traffic_pct must be in [0.0, 1.0]")
        with self._lock:
            self._variants[name] = dict(classifier_config)
            self._traffic_split[name] = float(traffic_pct)
            self._results.setdefault(name, [])

    def select_variant(self, seed: Optional[int] = None) -> str:
        """Select a variant using weighted random sampling.

        Returns the selected variant name. Raises *RuntimeError* if no
        variants are registered.
        """
        with self._lock:
            if not self._variants:
                raise RuntimeError("No variants registered")
            names = list(self._variants.keys())
            weights = [self._traffic_split.get(n, 0.0) for n in names]
            total = sum(weights)
            if total == 0.0:
                weights = [1.0 / len(names)] * len(names)
            else:
                weights = [w / total for w in weights]
            return random.Random(seed).choices(names, weights=weights, k=1)[0]

    def record_outcome(self, variant: str, success: bool) -> None:
        """Record a binary outcome for a variant."""
        with self._lock:
            if variant not in self._variants:
                raise KeyError(f"Unknown variant: {variant}")
            self._results.setdefault(variant, []).append(bool(success))

    def get_report(self) -> dict:
        """Return success-rate report per variant.

        Fields per variant: ``n`` (total), ``successes``, ``failures``,
        ``success_rate`` (float), ``p_value`` vs baseline (float or None).
        """
        with self._lock:
            report: dict = {}
            baseline_rate: Optional[float] = None
            baseline_n = 0

            # Determine baseline (first variant by registration order)
            for name in self._variants:
                outcomes = self._results.get(name, [])
                n = len(outcomes)
                successes = sum(1 for o in outcomes if o)
                failures = n - successes
                rate = successes / n if n > 0 else 0.0

                report[name] = {
                    "n": n,
                    "successes": successes,
                    "failures": failures,
                    "success_rate": rate,
                    "p_value": None,
                }

                if baseline_rate is None and n > 0:
                    baseline_rate = rate
                    baseline_n = n

            # Two-proportion z-test for each non-baseline variant
            first = True
            for name in self._variants:
                if first:
                    first = False
                    continue
                outcomes = self._results.get(name, [])
                n = len(outcomes)
                if n == 0 or baseline_n == 0 or baseline_rate is None:
                    continue

                p1 = baseline_rate
                p2 = report[name]["success_rate"]
                pooled = (p1 * baseline_n + p2 * n) / (baseline_n + n)
                if pooled == 0.0 or pooled == 1.0:
                    report[name]["p_value"] = 1.0 if p1 == p2 else 0.0
                    continue
                se = math.sqrt(pooled * (1 - pooled) * (1.0 / baseline_n + 1.0 / n))
                if se == 0.0:
                    report[name]["p_value"] = None
                    continue
                z = abs(p1 - p2) / se
                # Two-tailed p-value from normal approximation
                p_val = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2))))
                report[name]["p_value"] = p_val

            return report

    def list_variants(self) -> list[str]:
        """Return registered variant names."""
        with self._lock:
            return list(self._variants.keys())

    def get_variant_config(self, name: str) -> dict:
        """Return the classifier config for a variant."""
        with self._lock:
            if name not in self._variants:
                raise KeyError(f"Unknown variant: {name}")
            return dict(self._variants[name])
