"""HMAOM Confidence Calibration.

Platt-scaling calibration of classifier confidence scores per domain.
"""

from __future__ import annotations

import math
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from hmaom.protocol.schemas import Domain


class ConfidenceCalibrator:
    """Calibrate raw classifier confidence scores using Platt scaling.

    Collects (predicted_confidence, actual_success) pairs per domain,
    fits a sigmoid, and returns calibrated probabilities.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = Path(db_path) if db_path else None
        self._bins: dict[str, list[tuple[float, bool]]] = {}
        self._lock = threading.Lock()
        if self._db_path:
            self._init_db()
            self._load_from_db()

    # ── Public API ──────────────────────────────────────────────────────────

    def record(self, domain: Domain, predicted_confidence: float, success: bool) -> None:
        """Store one observation for a domain."""
        key = domain.value if hasattr(domain, "value") else str(domain)
        with self._lock:
            self._bins.setdefault(key, []).append((float(predicted_confidence), bool(success)))
            if self._db_path:
                self._persist_observation(key, predicted_confidence, success)

    def calibrate(self, domain: Domain, raw_confidence: float) -> float:
        """Return a calibrated probability using fitted Platt scaling.

        If insufficient data (fewer than 5 observations) or the sigmoid
        fit is degenerate, returns the raw confidence clipped to [0, 1].
        """
        key = domain.value if hasattr(domain, "value") else str(domain)
        with self._lock:
            data = list(self._bins.get(key, []))
        if len(data) < 5:
            return max(0.0, min(1.0, raw_confidence))

        A, B = self._fit_platt(data)
        calibrated = 1.0 / (1.0 + math.exp(A * float(raw_confidence) + B))
        return float(calibrated)

    def get_calibration_curve(self, domain: Domain) -> list[tuple[float, float]]:
        """Return list of (bin_center, accuracy) for visualization.

        Bins observations into 5 equal-width confidence bins and reports
        empirical accuracy per bin.
        """
        key = domain.value if hasattr(domain, "value") else str(domain)
        with self._lock:
            data = list(self._bins.get(key, []))
        if not data:
            return []

        n_bins = 5
        bin_edges = [i / n_bins for i in range(n_bins + 1)]
        binned: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]

        for pred, actual in data:
            for i in range(n_bins):
                lo, hi = bin_edges[i], bin_edges[i + 1]
                if i == n_bins - 1:
                    if lo <= pred <= hi:
                        binned[i].append((pred, actual))
                        break
                else:
                    if lo <= pred < hi:
                        binned[i].append((pred, actual))
                        break

        curve: list[tuple[float, float]] = []
        for i, bucket in enumerate(binned):
            if bucket:
                center = (bin_edges[i] + bin_edges[i + 1]) / 2
                accuracy = sum(1 for _, a in bucket if a) / len(bucket)
                curve.append((center, accuracy))
        return curve

    # ── Platt scaling internals ─────────────────────────────────────────────

    @staticmethod
    def _fit_platt(data: list[tuple[float, bool]]) -> tuple[float, float]:
        """Fit sigmoid parameters (A, B) via Newton-Raphson.

        Based on Platt 1999 (SVM probabilities). Returns (A, B) for
            p = 1 / (1 + exp(A * x + B))
        """
        N = len(data)
        if N == 0:
            return (0.0, 0.0)

        # Prior counts to avoid degenerate cases
        prior1 = sum(1 for _, y in data if y)
        prior0 = N - prior1
        hi_target = (prior1 + 1.0) / (prior1 + 2.0)
        lo_target = 1.0 / (prior0 + 2.0)

        # Initialize
        A, B = 0.0, math.log((prior0 + 1.0) / (prior1 + 1.0))

        for _ in range(100):
            a = 0.0
            b = 0.0
            c = 0.0
            d = 0.0
            e = 0.0

            for x, y in data:
                t = y * hi_target + (1 - y) * lo_target
                fApB = A * x + B
                if fApB >= 0:
                    p = math.exp(-fApB) / (1.0 + math.exp(-fApB))
                    q = 1.0 / (1.0 + math.exp(-fApB))
                else:
                    p = 1.0 / (1.0 + math.exp(fApB))
                    q = math.exp(fApB) / (1.0 + math.exp(fApB))

                d2 = p * q
                a += x * x * d2
                b += d2
                c += x * d2
                d += (t - p) * x
                e += t - p

            # Newton step
            det = a * b - c * c
            if abs(det) < 1e-10:
                break
            A -= (b * d - c * e) / det
            B -= (a * e - c * d) / det

        return A, B

    # ── SQLite persistence ──────────────────────────────────────────────────

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calibration_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                predicted REAL NOT NULL,
                actual INTEGER NOT NULL,
                created_at REAL DEFAULT (julianday('now'))
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cal_domain ON calibration_observations(domain)"
        )
        conn.commit()
        conn.close()

    def _persist_observation(self, key: str, predicted: float, actual: bool) -> None:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute(
            "INSERT INTO calibration_observations (domain, predicted, actual) VALUES (?, ?, ?)",
            (key, float(predicted), int(actual)),
        )
        conn.commit()
        conn.close()

    def _load_from_db(self) -> None:
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.execute("SELECT domain, predicted, actual FROM calibration_observations")
        for row in cursor:
            domain, pred, actual = row
            self._bins.setdefault(domain, []).append((float(pred), bool(actual)))
        conn.close()
