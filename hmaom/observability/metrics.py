"""HMAOM Metrics Collection.

Collects counters, gauges, and histograms with Prometheus-compatible
text-format exposition.
"""

from __future__ import annotations

import threading
from typing import Optional


def _format_labels(labels: Optional[dict]) -> str:
    """Return sorted key=value pairs joined by commas."""
    if not labels:
        return ""
    return ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))


def _metric_key(name: str, label_str: str) -> str:
    """Internal storage key from metric name and label string."""
    if label_str:
        return f"{name}:{label_str}"
    return name


def _percentile(values: list[float], p: float) -> float:
    """Compute the p-th percentile using linear interpolation."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    # Use nearest-rank / linear interpolation method
    k = (n - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= n:
        return sorted_vals[-1]
    d = k - f
    return sorted_vals[f] + d * (sorted_vals[c] - sorted_vals[f])


class MetricsCollector:
    """Thread-safe collector for counters, gauges, and histograms."""

    MAX_HISTOGRAM_SAMPLES = 10000

    def __init__(self, prefix: str = "hmaom") -> None:
        self.prefix = prefix
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def counter(self, name: str, value: int = 1, labels: Optional[dict] = None) -> None:
        """Increment a counter by *value*."""
        label_str = _format_labels(labels)
        key = _metric_key(name, label_str)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value

    def gauge(self, name: str, value: float, labels: Optional[dict] = None) -> None:
        """Set a gauge to *value*."""
        label_str = _format_labels(labels)
        key = _metric_key(name, label_str)
        with self._lock:
            self._gauges[key] = value

    def histogram(self, name: str, value: float, labels: Optional[dict] = None) -> None:
        """Record an observation in a histogram."""
        label_str = _format_labels(labels)
        key = _metric_key(name, label_str)
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = []
            self._histograms[key].append(value)
            if len(self._histograms[key]) > self.MAX_HISTOGRAM_SAMPLES:
                # Reservoir sampling: keep every other sample
                self._histograms[key] = self._histograms[key][::2]

    def get_counter(self, name: str, labels: Optional[dict] = None) -> int:
        """Return the current value of a counter."""
        label_str = _format_labels(labels)
        key = _metric_key(name, label_str)
        with self._lock:
            return self._counters.get(key, 0)

    def get_gauge(self, name: str, labels: Optional[dict] = None) -> float:
        """Return the current value of a gauge."""
        label_str = _format_labels(labels)
        key = _metric_key(name, label_str)
        with self._lock:
            return self._gauges.get(key, 0.0)

    def get_histogram(self, name: str, labels: Optional[dict] = None) -> dict:
        """Return histogram statistics."""
        label_str = _format_labels(labels)
        key = _metric_key(name, label_str)
        with self._lock:
            values = self._histograms.get(key, [])
        if not values:
            return {
                "count": 0,
                "sum": 0.0,
                "min": 0.0,
                "max": 0.0,
                "avg": 0.0,
                "p50": 0.0,
                "p95": 0.0,
                "p99": 0.0,
            }
        return {
            "count": len(values),
            "sum": sum(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "p50": _percentile(values, 50),
            "p95": _percentile(values, 95),
            "p99": _percentile(values, 99),
        }

    def prometheus_exposition_format(self) -> str:
        """Render all metrics in Prometheus text format."""
        lines: list[str] = []

        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            histograms = dict(self._histograms)

        # Counters
        for key, value in sorted(counters.items()):
            name, label_str = self._parse_key(key)
            prom_name = f"{self.prefix}_{name}_total"
            lines.append(f"# HELP {prom_name} Total {name}")
            lines.append(f"# TYPE {prom_name} counter")
            if label_str:
                lines.append(f'{prom_name}{{{label_str}}} {value}')
            else:
                lines.append(f"{prom_name} {value}")
            lines.append("")

        # Gauges
        for key, value in sorted(gauges.items()):
            name, label_str = self._parse_key(key)
            prom_name = f"{self.prefix}_{name}"
            lines.append(f"# HELP {prom_name} Current {name}")
            lines.append(f"# TYPE {prom_name} gauge")
            if label_str:
                lines.append(f'{prom_name}{{{label_str}}} {value}')
            else:
                lines.append(f"{prom_name} {value}")
            lines.append("")

        # Histograms — expose as summary with count, sum, and quantiles
        for key, values in sorted(histograms.items()):
            name, label_str = self._parse_key(key)
            prom_name = f"{self.prefix}_{name}"
            count = len(values)
            total = sum(values)

            lines.append(f"# HELP {prom_name} Histogram of {name}")
            lines.append(f"# TYPE {prom_name} summary")

            suffix = f"{{{label_str}}}" if label_str else ""

            lines.append(f"{prom_name}_count{suffix} {count}")
            lines.append(f"{prom_name}_sum{suffix} {total}")

            for q in (0.5, 0.95, 0.99):
                quantile_value = _percentile(values, q * 100)
                q_str = f"{q:g}"
                if label_str:
                    lines.append(
                        f'{prom_name}{{quantile="{q_str}",{label_str}}} {quantile_value}'
                    )
                else:
                    lines.append(
                        f'{prom_name}{{quantile="{q_str}"}} {quantile_value}'
                    )
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _parse_key(key: str) -> tuple[str, str]:
        """Parse an internal storage key into (name, label_str)."""
        if ":" in key:
            name, label_str = key.split(":", 1)
            return name, label_str
        return key, ""

    def reset(self) -> None:
        """Clear all metrics (useful in tests)."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
