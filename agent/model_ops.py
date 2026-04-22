"""
ModelOpsService — sole writable authority for model identity.

All mutations to provider, model, base URL, or API key must flow through
this service. It creates an audit trail in the ``model_mutations`` table
and guards against unapproved direct edits.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Set

from hermes_constants import get_hermes_home
from hermes_state import SessionDB

logger = logging.getLogger(__name__)

# Environment variables that affect model identity.
_PROTECTED_ENV_PATTERNS: tuple[str, ...] = (
    r".*_API_KEY$",
    r".*_BASE_URL$",
    r"^MODEL$",
    r"^PROVIDER$",
    r"^DEFAULT_MODEL$",
    r".*_MODEL$",
    r".*_PROVIDER$",
)

_PROTECTED_ENV_KEYS: Set[str] = set()


def _is_protected_key(key: str) -> bool:
    """Return True if *key* is a protected model-identity env var."""
    upper = key.upper()
    for pat in _PROTECTED_ENV_PATTERNS:
        if re.match(pat, upper):
            return True
    return False


class ModelOpsService:
    """
    Single source of truth for mutating model identity.

    Mutations lifecycle:
      pending → approved → executed  (or rolled_back)
    """

    PROTECTED_KEYS = _PROTECTED_ENV_PATTERNS

    def __init__(self, db: SessionDB | None = None):
        self.db = db or SessionDB()

    # ------------------------------------------------------------------
    # Core mutation CRUD
    # ------------------------------------------------------------------

    def create_mutation(
        self,
        session_id: str,
        key: str,
        old_value: str | None,
        new_value: str,
    ) -> str:
        """Create a pending model mutation. Returns mutation_id."""
        mutation_id = f"mut-{uuid.uuid4().hex[:12]}"
        self.db.create_model_mutation(
            mutation_id=mutation_id,
            session_id=session_id,
            key=key,
            old_value=old_value or "",
            new_value=new_value,
            status="pending",
        )
        logger.info("Created mutation %s: %s -> %s", mutation_id, key, new_value)
        return mutation_id

    def get_mutation(self, mutation_id: str) -> Optional[Dict]:
        return self.db.get_model_mutation(mutation_id)

    def list_mutations(
        self,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> List[Dict]:
        return self.db.list_model_mutations(
            session_id=session_id, status=status, limit=limit
        )

    def approve_mutation(self, mutation_id: str) -> bool:
        """Approve a pending mutation."""
        mut = self.db.get_model_mutation(mutation_id)
        if not mut:
            logger.warning("approve_mutation: %s not found", mutation_id)
            return False
        if mut["status"] != "pending":
            logger.warning(
                "approve_mutation: %s is %s, not pending",
                mutation_id,
                mut["status"],
            )
            return False
        self.db.update_model_mutation_status(
            mutation_id, "approved", rollback_value=mut["old_value"]
        )
        logger.info("Approved mutation %s", mutation_id)
        return True

    def execute_mutation(self, mutation_id: str) -> bool:
        """Execute an approved mutation, writing the new value."""
        mut = self.db.get_model_mutation(mutation_id)
        if not mut:
            logger.warning("execute_mutation: %s not found", mutation_id)
            return False
        if mut["status"] != "approved":
            logger.warning(
                "execute_mutation: %s is %s, not approved",
                mutation_id,
                mut["status"],
            )
            return False

        key = mut["key"]
        new_value = mut["new_value"]

        # Persist to config.yaml for model/provider, else .env
        if key in ("model", "provider", "model.default", "model.provider"):
            from hermes_cli.config import set_config_value as save_config_value

            config_key = "model.default" if key == "model" else "model.provider"
            save_config_value(config_key, new_value)
        else:
            from hermes_cli.config import save_env_value

            save_env_value(key, new_value)

        self.db.update_model_mutation_status(mutation_id, "executed")
        logger.info("Executed mutation %s: %s = %s", mutation_id, key, new_value)
        return True

    def rollback_mutation(self, mutation_id: str) -> bool:
        """Rollback an executed mutation to its old value."""
        mut = self.db.get_model_mutation(mutation_id)
        if not mut:
            logger.warning("rollback_mutation: %s not found", mutation_id)
            return False
        if mut["status"] != "executed":
            logger.warning(
                "rollback_mutation: %s is %s, not executed",
                mutation_id,
                mut["status"],
            )
            return False

        key = mut["key"]
        rollback_value = mut["rollback_value"] or ""

        if key in ("model", "provider", "model.default", "model.provider"):
            from hermes_cli.config import set_config_value as save_config_value

            config_key = "model.default" if key == "model" else "model.provider"
            save_config_value(config_key, rollback_value)
        else:
            from hermes_cli.config import save_env_value

            save_env_value(key, rollback_value)

        self.db.update_model_mutation_status(mutation_id, "rolled_back")
        logger.info("Rolled back mutation %s: %s = %s", mutation_id, key, rollback_value)
        return True

    # ------------------------------------------------------------------
    # Drift detection
    # ------------------------------------------------------------------

    def detect_drift(self) -> List[Dict]:
        """
        Scan ``.env`` for protected keys that were modified outside the
        mutation workflow (i.e. no executed mutation covers the current value).
        """
        from hermes_cli.config import load_env

        env_vars = load_env()
        drift_items: List[Dict] = []
        for key, value in env_vars.items():
            if not _is_protected_key(key):
                continue
            # Look for the most recent executed mutation for this key
            mutations = self.db.list_model_mutations(status="executed", limit=1000)
            key_muts = [m for m in mutations if m["key"] == key]
            if not key_muts:
                # No mutation history at all — direct edit
                drift_items.append({
                    "key": key,
                    "current_value": value,
                    "last_mutation_value": None,
                })
                continue
            latest = max(key_muts, key=lambda m: m["updated_at"] or 0)
            if latest["new_value"] != value:
                drift_items.append({
                    "key": key,
                    "current_value": value,
                    "last_mutation_value": latest["new_value"],
                })
        if drift_items:
            logger.warning("Detected %d drifted env var(s)", len(drift_items))
        return drift_items

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_protected_key(key: str) -> bool:
        """Return True if *key* is a protected model-identity env var."""
        return _is_protected_key(key)

    @staticmethod
    def protected_keys() -> Set[str]:
        """Return the set of protected key patterns."""
        return set(_PROTECTED_ENV_PATTERNS)
