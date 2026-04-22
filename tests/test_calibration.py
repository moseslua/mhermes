"""Tests for hmaom.gateway.calibration.ConfidenceCalibrator."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from hmaom.gateway.calibration import ConfidenceCalibrator
from hmaom.protocol.schemas import Domain


class FakeDomain:
    """Simple domain stand-in for tests."""

    def __init__(self, value: str):
        self.value = value


@pytest.fixture
def domain():
    return FakeDomain("code")


class TestRecordAndRetrieve:
    def test_record_single(self, domain):
        cal = ConfidenceCalibrator()
        cal.record(domain, 0.8, True)
        curve = cal.get_calibration_curve(domain)
        assert len(curve) == 1
        assert curve[0][1] == 1.0  # 100 % accuracy

    def test_record_multiple(self, domain):
        cal = ConfidenceCalibrator()
        for i in range(10):
            cal.record(domain, 0.5 + i * 0.05, i % 2 == 0)
        data = cal._bins[domain.value]
        assert len(data) == 10

    def test_different_domains_isolated(self, domain):
        cal = ConfidenceCalibrator()
        d2 = FakeDomain("maths")
        cal.record(domain, 0.9, True)
        cal.record(d2, 0.7, False)
        assert len(cal._bins["code"]) == 1
        assert len(cal._bins["maths"]) == 1


class TestCalibration:
    def test_returns_raw_when_insufficient_data(self, domain):
        cal = ConfidenceCalibrator()
        cal.record(domain, 0.9, True)
        assert cal.calibrate(domain, 0.75) == pytest.approx(0.75)

    def test_calibration_changes_output(self, domain):
        cal = ConfidenceCalibrator()
        # Low confidence + mostly failures → calibration should push down
        for _ in range(20):
            cal.record(domain, 0.3, False)
        for _ in range(5):
            cal.record(domain, 0.3, True)
        raw = 0.3
        calibrated = cal.calibrate(domain, raw)
        assert calibrated != pytest.approx(raw)
        # Should push probability down since mostly failures
        assert calibrated < raw

    def test_calibration_bounded_zero_one(self, domain):
        cal = ConfidenceCalibrator()
        for i in range(50):
            cal.record(domain, 0.5, i % 2 == 0)
        assert 0.0 <= cal.calibrate(domain, 0.5) <= 1.0
        assert 0.0 <= cal.calibrate(domain, -1.0) <= 1.0
        assert 0.0 <= cal.calibrate(domain, 2.0) <= 1.0

    def test_calibration_improves_monotonic(self, domain):
        """If all high-confidence predictions are correct, calibration
        should increase the probability relative to low-confidence ones."""
        cal = ConfidenceCalibrator()
        for _ in range(30):
            cal.record(domain, 0.9, True)
        for _ in range(30):
            cal.record(domain, 0.4, False)
        high = cal.calibrate(domain, 0.9)
        low = cal.calibrate(domain, 0.4)
        assert high > low


class TestCalibrationCurve:
    def test_empty_curve(self, domain):
        cal = ConfidenceCalibrator()
        assert cal.get_calibration_curve(domain) == []

    def test_curve_bins(self, domain):
        cal = ConfidenceCalibrator()
        for i in range(20):
            cal.record(domain, i / 20, i >= 10)
        curve = cal.get_calibration_curve(domain)
        assert len(curve) <= 5
        for center, acc in curve:
            assert 0.0 <= center <= 1.0
            assert 0.0 <= acc <= 1.0

    def test_curve_accuracy(self, domain):
        cal = ConfidenceCalibrator()
        for _ in range(10):
            cal.record(domain, 0.9, True)
        curve = cal.get_calibration_curve(domain)
        # 0.9 falls in the 0.8-1.0 bin (center 0.9)
        bin_acc = next((a for c, a in curve if abs(c - 0.9) < 0.15), None)
        assert bin_acc == 1.0


class TestPersistence:
    def test_persists_and_reloads(self, domain):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "calib.db"
            cal = ConfidenceCalibrator(str(db))
            cal.record(domain, 0.85, True)
            cal.record(domain, 0.55, False)

            cal2 = ConfidenceCalibrator(str(db))
            data = cal2._bins[domain.value]
            assert len(data) == 2
            assert data[0] == (0.85, True)
            assert data[1] == (0.55, False)

    def test_db_schema(self, domain):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "calib.db"
            cal = ConfidenceCalibrator(str(db))
            cal.record(domain, 0.5, True)

            conn = sqlite3.connect(str(db))
            cur = conn.execute("SELECT domain, predicted, actual FROM calibration_observations")
            rows = cur.fetchall()
            conn.close()
            assert len(rows) == 1
            assert rows[0][0] == "code"
            assert rows[0][1] == pytest.approx(0.5)
            assert rows[0][2] == 1
