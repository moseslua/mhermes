"""Tests for hmaom.hire.triggers module."""

from __future__ import annotations

import time
from typing import Any

import pytest

from hmaom.hire.persistence import HirePersistence
from hmaom.hire.triggers import (
    HireActivationTriggers,
    HireTriggerConfig,
    HireTriggerEvent,
)


@pytest.fixture
def tmp_db_path(tmp_path):
    return str(tmp_path / "hire_test.sqlite")


@pytest.fixture
def persistence(tmp_db_path):
    return HirePersistence(db_path=tmp_db_path)


@pytest.fixture
def default_config():
    return HireTriggerConfig()


class TestHireTriggerConfig:
    def test_default_values(self):
        cfg = HireTriggerConfig()
        assert cfg.min_observations == 5
        assert cfg.time_window_hours == 24
        assert cfg.confidence_threshold == 0.6
        assert cfg.subject_frequency_threshold == 3
        assert cfg.min_unique_users == 1
        assert cfg.require_low_confidence is True
        assert cfg.require_out_of_domain is False
        assert cfg.enabled is True


class TestHireActivationTriggers:
    def test_threshold_crossing(self, persistence, default_config):
        """A subject crossing frequency + observation thresholds fires an event."""
        triggers = HireActivationTriggers(default_config, persistence)
        event = None
        for i in range(5):
            result = {
                "routing_decision": {"confidence": 0.4, "primary_domain": "meta"},
                "status": "failure",
            }
            ev = triggers.record_interaction("help with kubernetes deployment", result)
            if ev is not None:
                event = ev

        assert event is not None
        assert isinstance(event, HireTriggerEvent)
        assert event.subject == "kubernetes"
        assert event.observation_count >= default_config.min_observations

    def test_disabled_config_returns_none(self, persistence):
        """When enabled=False, no events are ever returned."""
        cfg = HireTriggerConfig(enabled=False)
        triggers = HireActivationTriggers(cfg, persistence)
        for i in range(10):
            result = {
                "routing_decision": {"confidence": 0.2},
                "status": "failure",
            }
            ev = triggers.record_interaction("help with kubernetes deployment", result)
            assert ev is None

        assert triggers.check_thresholds() == []
        assert triggers.should_analyze("anything", {"confidence": 0.2}) is False

    def test_pre_filter_allows_low_confidence(self, persistence, default_config):
        """should_analyze returns True for low-confidence interactions."""
        triggers = HireActivationTriggers(default_config, persistence)
        assert triggers.should_analyze(
            "help with kubernetes", {"confidence": 0.4, "primary_domain": "meta"}
        ) is True

    def test_pre_filter_rejects_high_confidence(self, persistence, default_config):
        """should_analyze returns False when confidence is above threshold."""
        triggers = HireActivationTriggers(default_config, persistence)
        assert triggers.should_analyze(
            "help with kubernetes", {"confidence": 0.9, "primary_domain": "code"}
        ) is False

    def test_multi_subject_tracking(self, persistence, default_config):
        """Multiple subjects are tracked independently."""
        triggers = HireActivationTriggers(default_config, persistence)
        for i in range(5):
            triggers.record_interaction(
                "help with kubernetes and terraform",
                {"routing_decision": {"confidence": 0.4}, "status": "failure"},
            )

        events = triggers.check_thresholds()
        subjects = {e.subject for e in events}
        assert "kubernetes" in subjects
        assert "terraform" in subjects

    def test_time_window_filtering(self, persistence):
        """Old observations outside the time window are ignored."""
        cfg = HireTriggerConfig(
            time_window_hours=1,
            min_observations=3,
            subject_frequency_threshold=3,
        )
        triggers = HireActivationTriggers(cfg, persistence)

        # Inject 3 old observations by directly writing to DB
        old_ts = time.time() - 7200  # 2 hours ago
        with persistence._connection() as conn:
            conn.execute(
                """
                INSERT INTO hire_observations
                (timestamp, user_input, routing_decision, specialist_used, result_status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    old_ts,
                    "help with kubernetes",
                    '{"confidence": 0.3}',
                    "unknown",
                    "failure",
                ),
            )
            conn.commit()

        # Fresh observations within window
        for i in range(2):
            triggers.record_interaction(
                "help with kubernetes",
                {"routing_decision": {"confidence": 0.3}, "status": "failure"},
            )

        # Only 2 fresh entries, threshold is 3
        events = triggers.check_thresholds()
        assert all(e.observation_count <= 2 for e in events if e.subject == "kubernetes")

    def test_unique_user_counting(self, persistence):
        """Unique users are counted correctly per subject."""
        cfg = HireTriggerConfig(
            min_observations=3,
            subject_frequency_threshold=3,
            min_unique_users=2,
        )
        triggers = HireActivationTriggers(cfg, persistence)

        # Same user 5 times
        for i in range(5):
            triggers.record_interaction(
                "help with kubernetes",
                {
                    "routing_decision": {"confidence": 0.3},
                    "status": "failure",
                    "user_id": "alice",
                },
            )

        # Not enough unique users
        assert triggers.check_thresholds() == []

        # Second user weighs in
        triggers.record_interaction(
            "help with kubernetes",
            {
                "routing_decision": {"confidence": 0.3},
                "status": "failure",
                "user_id": "bob",
            },
        )

        events = triggers.check_thresholds()
        kubernetes_events = [e for e in events if e.subject == "kubernetes"]
        assert len(kubernetes_events) >= 1
        assert kubernetes_events[0].unique_users >= 2

    def test_no_trigger_below_threshold(self, persistence, default_config):
        """Fewer observations than thresholds should not fire."""
        triggers = HireActivationTriggers(default_config, persistence)
        for i in range(2):
            triggers.record_interaction(
                "help with kubernetes",
                {"routing_decision": {"confidence": 0.3}, "status": "failure"},
            )

        assert triggers.check_thresholds() == []
        # record_interaction also returns None when no threshold crossed
        last = triggers.record_interaction(
            "help with kubernetes",
            {"routing_decision": {"confidence": 0.3}, "status": "failure"},
        )
        # 3rd interaction still below min_observations=5
        assert last is None

    def test_event_structure(self, persistence, default_config):
        """Fired events contain all required fields with correct types."""
        triggers = HireActivationTriggers(default_config, persistence)
        event = None
        for i in range(5):
            ev = triggers.record_interaction(
                "help with kubernetes deployment scaling",
                {"routing_decision": {"confidence": 0.4}, "status": "failure"},
            )
            if ev is not None:
                event = ev

        assert event is not None
        assert isinstance(event.subject, str) and len(event.subject) > 0
        assert isinstance(event.observation_count, int) and event.observation_count >= 1
        assert isinstance(event.confidence_avg, float)
        assert 0.0 <= event.confidence_avg <= 1.0
        assert isinstance(event.unique_users, int) and event.unique_users >= 1
        assert isinstance(event.triggered_at, float) and event.triggered_at <= time.time()
        assert isinstance(event.reason, str) and len(event.reason) > 0

    def test_evaluate_delegates_to_record(self, persistence, default_config):
        """evaluate() delegates to record_interaction and returns events."""
        triggers = HireActivationTriggers(default_config, persistence)
        event = None
        for i in range(5):
            ev = triggers.evaluate(
                "help with kubernetes deployment",
                {"routing_decision": {"confidence": 0.4}, "status": "failure"},
            )
            if ev is not None:
                event = ev

        assert event is not None
        assert event.subject == "kubernetes"

    def test_check_thresholds_rebuilds_from_persistence(self, persistence, default_config):
        """check_thresholds rebuilds stats from DB even without in-memory state."""
        triggers1 = HireActivationTriggers(default_config, persistence)
        for i in range(5):
            triggers1.record_interaction(
                "help with kubernetes",
                {"routing_decision": {"confidence": 0.3}, "status": "failure"},
            )

        # Fresh triggers instance with same DB but empty memory
        triggers2 = HireActivationTriggers(default_config, persistence)
        events = triggers2.check_thresholds()
        subjects = {e.subject for e in events}
        assert "kubernetes" in subjects

    def test_require_out_of_domain(self, persistence):
        """When require_out_of_domain=True, only out-of-domain interactions count."""
        cfg = HireTriggerConfig(
            require_out_of_domain=True,
            require_low_confidence=False,
            min_observations=3,
            subject_frequency_threshold=3,
        )
        triggers = HireActivationTriggers(cfg, persistence)

        # High-confidence success should be filtered by should_analyze
        assert triggers.should_analyze(
            "help with kubernetes",
            {"confidence": 0.9, "primary_domain": "code"},
        ) is False

        # Meta domain counts as out-of-domain
        assert triggers.should_analyze(
            "help with kubernetes",
            {"confidence": 0.9, "primary_domain": "meta"},
        ) is True

        # Record some out-of-domain interactions
        for i in range(3):
            ev = triggers.record_interaction(
                "help with kubernetes",
                {
                    "routing_decision": {"confidence": 0.3, "primary_domain": "meta"},
                    "status": "no_specialists",
                },
            )

        events = triggers.check_thresholds()
        assert any(e.subject == "kubernetes" for e in events)

    def test_record_interaction_logs_to_persistence(self, persistence, default_config):
        """Every recorded interaction is persisted to the database."""
        triggers = HireActivationTriggers(default_config, persistence)
        triggers.record_interaction(
            "help with kubernetes",
            {"routing_decision": {"confidence": 0.3}, "status": "failure"},
        )

        observations = persistence.get_observations()
        assert len(observations) == 1
        assert observations[0].user_input == "help with kubernetes"
