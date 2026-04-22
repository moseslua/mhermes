"""Tests for BillingExporter."""

import csv
import json
import tempfile
from pathlib import Path

import pytest

from hmaom.observability.billing import BillingExporter


class TestBillingExporter:
    def test_record(self):
        exporter = BillingExporter()
        exporter.record("cid-1", "alice", "code", 100, 0.05, 250)
        assert len(exporter._records) == 1
        assert exporter._records[0].user_id == "alice"

    def test_get_summary_all(self):
        exporter = BillingExporter()
        exporter.record("cid-1", "alice", "code", 100, 0.05, 250)
        exporter.record("cid-2", "bob", "maths", 200, 0.10, 500)

        summary = exporter.get_summary()
        assert summary["count"] == 2
        assert summary["total_tokens"] == 300
        assert summary["total_cost_usd"] == pytest.approx(0.15)
        assert summary["total_elapsed_ms"] == 750

    def test_get_summary_by_user(self):
        exporter = BillingExporter()
        exporter.record("cid-1", "alice", "code", 100, 0.05, 250)
        exporter.record("cid-2", "alice", "maths", 200, 0.10, 500)
        exporter.record("cid-3", "bob", "code", 150, 0.075, 300)

        summary = exporter.get_summary(user_id="alice")
        assert summary["count"] == 2
        assert summary["total_tokens"] == 300
        assert summary["by_user"]["alice"]["count"] == 2
        assert "bob" not in summary["by_user"]

    def test_get_summary_by_domain(self):
        exporter = BillingExporter()
        exporter.record("cid-1", "alice", "code", 100, 0.05, 250)
        exporter.record("cid-2", "bob", "code", 150, 0.075, 300)
        exporter.record("cid-3", "alice", "maths", 200, 0.10, 500)

        summary = exporter.get_summary(domain="code")
        assert summary["count"] == 2
        assert summary["by_domain"]["code"]["count"] == 2
        assert "maths" not in summary["by_domain"]

    def test_get_summary_by_user_and_domain(self):
        exporter = BillingExporter()
        exporter.record("cid-1", "alice", "code", 100, 0.05, 250)
        exporter.record("cid-2", "alice", "maths", 200, 0.10, 500)

        summary = exporter.get_summary(user_id="alice", domain="code")
        assert summary["count"] == 1
        assert summary["total_tokens"] == 100

    def test_export_csv(self):
        exporter = BillingExporter()
        exporter.record("cid-1", "alice", "code", 100, 0.05, 250)
        exporter.record("cid-2", "bob", "maths", 200, 0.10, 500)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "billing.csv"
            result_path = exporter.export_csv(str(path))
            assert Path(result_path).exists()

            with open(result_path, newline="") as fh:
                reader = list(csv.reader(fh))
                assert reader[0] == [
                    "correlation_id",
                    "user_id",
                    "domain",
                    "tokens_used",
                    "cost_usd",
                    "elapsed_ms",
                ]
                assert len(reader) == 3

    def test_export_json(self):
        exporter = BillingExporter()
        exporter.record("cid-1", "alice", "code", 100, 0.05, 250)
        exporter.record("cid-2", "bob", "maths", 200, 0.10, 500)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "billing.json"
            result_path = exporter.export_json(str(path))
            assert Path(result_path).exists()

            with open(result_path) as fh:
                data = json.load(fh)
                assert len(data) == 2
                assert data[0]["user_id"] == "alice"
                assert data[1]["domain"] == "maths"

    def test_empty_summary(self):
        exporter = BillingExporter()
        summary = exporter.get_summary()
        assert summary["count"] == 0
        assert summary["total_tokens"] == 0
        assert summary["total_cost_usd"] == 0.0

    def test_empty_export_csv(self):
        exporter = BillingExporter()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "billing.csv"
            result_path = exporter.export_csv(str(path))
            with open(result_path, newline="") as fh:
                reader = list(csv.reader(fh))
                assert len(reader) == 1  # header only
