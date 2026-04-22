"""Tests for agent/model_ops.py — ModelOpsService mutation workflow."""

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.model_ops import ModelOpsService, _is_protected_key
from hermes_state import SessionDB


@pytest.fixture()
def db(tmp_path):
    db_path = tmp_path / "test_state.db"
    session_db = SessionDB(db_path=db_path)
    yield session_db
    session_db.close()


@pytest.fixture()
def ops(db):
    return ModelOpsService(db=db)


# =====================================================================
# Protected-key detection
# =====================================================================

class TestProtectedKeys:
    def test_api_key_patterns(self):
        assert _is_protected_key("ANTHROPIC_API_KEY") is True
        assert _is_protected_key("OPENAI_API_KEY") is True
        assert _is_protected_key("OPENROUTER_API_KEY") is True

    def test_base_url_patterns(self):
        assert _is_protected_key("ANTHROPIC_BASE_URL") is True
        assert _is_protected_key("GEMINI_BASE_URL") is True

    def test_model_provider_patterns(self):
        assert _is_protected_key("MODEL") is True
        assert _is_protected_key("PROVIDER") is True
        assert _is_protected_key("DEFAULT_MODEL") is True
        assert _is_protected_key("AUXILIARY_MODEL") is True

    def test_non_protected_keys(self):
        assert _is_protected_key("EDITOR") is False
        assert _is_protected_key("HOME") is False
        assert _is_protected_key("PATH") is False
        assert _is_protected_key("FOO_BAR") is False

    def test_static_method_matches_function(self):
        assert ModelOpsService.is_protected_key("OPENAI_API_KEY") is True
        assert ModelOpsService.is_protected_key("EDITOR") is False


# =====================================================================
# Mutation CRUD
# =====================================================================

class TestMutationCrud:
    def test_create_mutation(self, ops):
        mut_id = ops.create_mutation("s1", "model", "old-model", "new-model")
        assert mut_id.startswith("mut-")

        mut = ops.get_mutation(mut_id)
        assert mut["session_id"] == "s1"
        assert mut["key"] == "model"
        assert mut["old_value"] == "old-model"
        assert mut["new_value"] == "new-model"
        assert mut["status"] == "pending"

    def test_list_mutations_filters(self, ops):
        m1 = ops.create_mutation("s1", "model", "", "m1")
        m2 = ops.create_mutation("s1", "provider", "", "p1")
        m3 = ops.create_mutation("s2", "model", "", "m2")

        all_muts = ops.list_mutations()
        assert len(all_muts) == 3

        s1_muts = ops.list_mutations(session_id="s1")
        assert len(s1_muts) == 2

        pending = ops.list_mutations(status="pending")
        assert len(pending) == 3

    def test_approve_mutation(self, ops):
        mut_id = ops.create_mutation("s1", "model", "old", "new")
        assert ops.approve_mutation(mut_id) is True

        mut = ops.get_mutation(mut_id)
        assert mut["status"] == "approved"
        assert mut["rollback_value"] == "old"

    def test_approve_nonexistent_mutation(self, ops):
        assert ops.approve_mutation("mut-nope") is False

    def test_approve_already_approved_fails(self, ops):
        mut_id = ops.create_mutation("s1", "model", "", "x")
        ops.approve_mutation(mut_id)
        assert ops.approve_mutation(mut_id) is False


# =====================================================================
# Execute + rollback
# =====================================================================

class TestExecuteRollback:
    @patch("hermes_cli.config.save_env_value")
    def test_execute_env_mutation(self, mock_save, ops):
        mut_id = ops.create_mutation("s1", "OPENAI_API_KEY", "old-key", "new-key")
        ops.approve_mutation(mut_id)

        assert ops.execute_mutation(mut_id) is True
        mock_save.assert_called_once_with("OPENAI_API_KEY", "new-key")

        mut = ops.get_mutation(mut_id)
        assert mut["status"] == "executed"

    @patch("hermes_cli.config.set_config_value")
    def test_execute_config_mutation(self, mock_save, ops):
        mut_id = ops.create_mutation("s1", "model", "", "gpt-5")
        ops.approve_mutation(mut_id)

        assert ops.execute_mutation(mut_id) is True
        mock_save.assert_called_once_with("model.default", "gpt-5")

    def test_execute_without_approval_fails(self, ops):
        mut_id = ops.create_mutation("s1", "model", "", "x")
        assert ops.execute_mutation(mut_id) is False

    @patch("hermes_cli.config.save_env_value")
    def test_rollback_env_mutation(self, mock_save, ops):
        mut_id = ops.create_mutation("s1", "OPENAI_API_KEY", "old-key", "new-key")
        ops.approve_mutation(mut_id)
        ops.execute_mutation(mut_id)

        assert ops.rollback_mutation(mut_id) is True
        mock_save.assert_called_with("OPENAI_API_KEY", "old-key")

        mut = ops.get_mutation(mut_id)
        assert mut["status"] == "rolled_back"

    def test_rollback_non_executed_fails(self, ops):
        mut_id = ops.create_mutation("s1", "model", "", "x")
        ops.approve_mutation(mut_id)
        assert ops.rollback_mutation(mut_id) is False


# =====================================================================
# Drift detection
# =====================================================================

class TestDriftDetection:
    @patch("hermes_cli.config.load_env")
    def test_detect_drift_no_history(self, mock_load_env, ops, tmp_path):
        mock_load_env.return_value = {"OPENAI_API_KEY": "direct-key"}
        drift = ops.detect_drift()
        assert len(drift) == 1
        assert drift[0]["key"] == "OPENAI_API_KEY"
        assert drift[0]["current_value"] == "direct-key"
        assert drift[0]["last_mutation_value"] is None

    @patch("hermes_cli.config.load_env")
    def test_detect_drift_with_mutation_match(self, mock_load_env, ops):
        mock_load_env.return_value = {"OPENAI_API_KEY": "mutated-key"}
        mut_id = ops.create_mutation("s1", "OPENAI_API_KEY", "old", "mutated-key")
        ops.approve_mutation(mut_id)
        ops.execute_mutation(mut_id)

        drift = ops.detect_drift()
        assert len(drift) == 0

    @patch("hermes_cli.config.load_env")
    def test_detect_drift_with_mutation_mismatch(self, mock_load_env, ops):
        mock_load_env.return_value = {"OPENAI_API_KEY": "tampered-key"}
        mut_id = ops.create_mutation("s1", "OPENAI_API_KEY", "old", "mutated-key")
        ops.approve_mutation(mut_id)
        ops.execute_mutation(mut_id)

        drift = ops.detect_drift()
        assert len(drift) == 1
        assert drift[0]["last_mutation_value"] == "mutated-key"
        assert drift[0]["current_value"] == "tampered-key"

    @patch("hermes_cli.config.load_env")
    def test_detect_drift_ignores_non_protected(self, mock_load_env, ops):
        mock_load_env.return_value = {"EDITOR": "vim"}
        drift = ops.detect_drift()
        assert len(drift) == 0
