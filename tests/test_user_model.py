"""Tests for hmaom.state.user_model.

Covers: create/get, record interaction, preferred domains, suggest routing,
prune inactive, multiple users, success rate tracking, average confidence update.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from hmaom.state.user_model import UserModel, UserPreference


@pytest.fixture
def user_model(tmp_path):
    """Provide a UserModel backed by a temporary SQLite file."""
    db_path = str(tmp_path / "user_model.sqlite")
    model = UserModel(db_path=db_path)
    yield model
    model.close()


class TestUserModel:
    # 1. create / get
    def test_get_or_create_returns_user(self, user_model):
        pref = user_model.get_or_create("alice")
        assert isinstance(pref, UserPreference)
        assert pref.user_id == "alice"
        assert pref.total_interactions == 0
        assert pref.preferred_domains == []

    def test_get_or_create_is_idempotent(self, user_model):
        pref1 = user_model.get_or_create("alice")
        pref2 = user_model.get_or_create("alice")
        assert pref1.user_id == pref2.user_id
        assert pref1.created_at == pytest.approx(pref2.created_at, abs=0.01)

    # 2. record interaction
    def test_record_interaction_updates_totals(self, user_model):
        user_model.record_interaction("alice", "finance", 0.85, success=True)
        pref = user_model.get_or_create("alice")
        assert pref.total_interactions == 1
        assert pref.average_confidence == pytest.approx(0.85, abs=0.001)
        assert "finance" in pref.preferred_domains

    # 3. preferred domains
    def test_get_preferred_domains_sorted_by_success_rate(self, user_model):
        # Seed alice with three domains
        user_model.record_interaction("alice", "code", 0.8, success=True)
        user_model.record_interaction("alice", "code", 0.8, success=True)
        user_model.record_interaction("alice", "code", 0.8, success=True)

        user_model.record_interaction("alice", "finance", 0.8, success=False)
        user_model.record_interaction("alice", "finance", 0.8, success=False)
        user_model.record_interaction("alice", "finance", 0.8, success=True)

        user_model.record_interaction("alice", "maths", 0.8, success=True)
        user_model.record_interaction("alice", "maths", 0.8, success=False)

        tops = user_model.get_preferred_domains("alice", top_n=2)
        assert len(tops) == 2
        # code should be highest (mostly successes)
        assert tops[0] == "code"

    # 4. suggest routing
    def test_suggest_routing_single_for_new_user(self, user_model):
        mode = user_model.suggest_routing_mode("alice", "simple task")
        assert mode == "single"

    def test_suggest_routing_parallel_from_history_and_keywords(self, user_model):
        # Build multi-domain history
        for _ in range(4):
            user_model.record_interaction("bob", "finance", 0.9, success=True)
        for _ in range(4):
            user_model.record_interaction("bob", "code", 0.9, success=True)

        mode = user_model.suggest_routing_mode("bob", "compare finance and code models")
        assert mode == "parallel"

    def test_suggest_routing_sequential_from_keywords(self, user_model):
        mode = user_model.suggest_routing_mode("alice", "first do this then do that")
        assert mode == "sequential"

    # 5. prune inactive
    def test_prune_inactive_removes_old_users(self, user_model):
        user_model.get_or_create("old_user")
        # Manually back-date last_active
        with user_model._connection() as conn:
            conn.execute(
                "UPDATE user_preferences SET last_active = ? WHERE user_id = ?",
                (time.time() - 40 * 86400, "old_user"),
            )
            conn.commit()

        user_model.get_or_create("new_user")

        deleted = user_model.prune_inactive(days=30)
        assert deleted == 1
        remaining = user_model.get_all_users()
        assert "old_user" not in remaining
        assert "new_user" in remaining

    # 6. multiple users
    def test_get_all_users_returns_multiple(self, user_model):
        user_model.get_or_create("u1")
        user_model.get_or_create("u2")
        user_model.get_or_create("u3")
        users = user_model.get_all_users()
        assert set(users) == {"u1", "u2", "u3"}

    # 7. success rate tracking
    def test_success_rate_ema_updates(self, user_model):
        user_model.record_interaction("alice", "code", 0.8, success=True)
        pref = user_model.get_or_create("alice")
        # EMA with alpha=0.3 starting from 0.5: 0.5 + 0.3*(1.0-0.5) = 0.65
        assert pref.domain_success_rates["code"] == pytest.approx(0.65, abs=0.01)

        user_model.record_interaction("alice", "code", 0.8, success=False)
        pref = user_model.get_or_create("alice")
        # 0.65 + 0.3*(0.0-0.65) = 0.455
        assert pref.domain_success_rates["code"] == pytest.approx(0.455, abs=0.01)

    # 8. average confidence update
    def test_average_confidence_rolling(self, user_model):
        user_model.record_interaction("alice", "maths", 0.5, success=True)
        pref = user_model.get_or_create("alice")
        assert pref.average_confidence == pytest.approx(0.5, abs=0.001)

        user_model.record_interaction("alice", "maths", 1.0, success=True)
        pref = user_model.get_or_create("alice")
        assert pref.average_confidence == pytest.approx(0.75, abs=0.001)

        user_model.record_interaction("alice", "maths", 0.0, success=True)
        pref = user_model.get_or_create("alice")
        assert pref.average_confidence == pytest.approx(0.5, abs=0.001)

    def test_preferred_output_format_default(self, user_model):
        pref = user_model.get_or_create("alice")
        assert pref.preferred_output_format == "markdown"
