"""HMAOM Checkpointing & Recovery.

Every subagent execution is checkpointed after each significant event,
enabling resumable execution after failure.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from hmaom.config import StateConfig
from hmaom.protocol.schemas import AgentAddress, Checkpoint



class CheckpointManager:
    """Manages execution checkpoints for resumable agent execution.

    Checkpoint directory layout:
        ~/.hmaom/state/checkpoints/{correlation_id}/
            checkpoint-001.json
            checkpoint-002.json
            ...
    """
    @staticmethod
    def _sanitize_id(cid: str) -> str:
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', cid)
        if len(sanitized) > 128:
            sanitized = sanitized[:128]
        return sanitized

    def __init__(self, config: Optional[StateConfig] = None) -> None:
        self.config = config or StateConfig()
        self.checkpoint_dir = Path(self.config.checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _correlation_dir(self, correlation_id: str) -> Path:
        sanitized = self._sanitize_id(correlation_id)
        return self.checkpoint_dir / sanitized

    def save(
        self,
        checkpoint: Checkpoint,
    ) -> str:
        """Save a checkpoint and return its file path."""
        corr_dir = self._correlation_dir(checkpoint.correlation_id)
        corr_dir.mkdir(parents=True, exist_ok=True)

        # Use timestamp + uuid for atomic, unique filenames
        path = corr_dir / f"checkpoint-{time.time_ns():020d}-{uuid.uuid4().hex[:8]}.json"
        path.write_text(checkpoint.model_dump_json(indent=2))
        return str(path)

    def load_latest(
        self,
        correlation_id: str,
        agent_address: Optional[AgentAddress] = None,
    ) -> Optional[Checkpoint]:
        """Load the most recent checkpoint for a correlation ID."""
        corr_dir = self._correlation_dir(correlation_id)
        if not corr_dir.exists():
            return None

        existing = sorted(corr_dir.glob("checkpoint-*.json"))
        if not existing:
            return None

        for path in reversed(existing):
            data = json.loads(path.read_text())
            cp = Checkpoint(**data)
            if agent_address is None or cp.agent_address == agent_address:
                return cp

        return None

    def load_all(
        self,
        correlation_id: str,
    ) -> list[Checkpoint]:
        """Load all checkpoints for a correlation ID in chronological order."""
        corr_dir = self._correlation_dir(correlation_id)
        if not corr_dir.exists():
            return []

        checkpoints: list[Checkpoint] = []
        for path in sorted(corr_dir.glob("checkpoint-*.json")):
            data = json.loads(path.read_text())
            checkpoints.append(Checkpoint(**data))
        return checkpoints

    def create(
        self,
        correlation_id: str,
        agent_address: AgentAddress,
        messages: list[dict[str, Any]],
        state_snapshot: dict[str, Any],
        tokens_used: int = 0,
    ) -> Checkpoint:
        """Create and save a new checkpoint."""
        checkpoint = Checkpoint(
            checkpoint_id=f"cp-{int(time.time() * 1000)}-{agent_address.agent}",
            correlation_id=correlation_id,
            agent_address=agent_address,
            timestamp=time.time(),
            messages=messages,
            state_snapshot=state_snapshot,
            tokens_used=tokens_used,
        )
        self.save(checkpoint)
        return checkpoint

    def recover_options(
        self,
        correlation_id: str,
        agent_address: AgentAddress,
    ) -> dict[str, Any]:
        """Present recovery options for a failed agent.

        Returns a dict with:
        - has_checkpoint: bool
        - last_checkpoint: Optional[Checkpoint]
        - options: list[str] (resume, retry, decompose, escalate)
        """
        latest = self.load_latest(correlation_id, agent_address)
        options = {
            "has_checkpoint": latest is not None,
            "last_checkpoint": latest,
            "options": ["retry"],
        }
        if latest is not None:
            options["options"].append("resume")
        if agent_address.depth < 2:
            options["options"].append("decompose")
        options["options"].append("escalate")
        return options

    def prune_old(self, max_age_days: int = 7) -> int:
        """Remove checkpoints older than max_age_days. Returns count removed."""
        cutoff = time.time() - (max_age_days * 86400)
        removed = 0
        for corr_dir in self.checkpoint_dir.iterdir():
            if not corr_dir.is_dir():
                continue
            for path in corr_dir.glob("checkpoint-*.json"):
                try:
                    data = json.loads(path.read_text())
                    if data.get("timestamp", 0) < cutoff:
                        path.unlink()
                        removed += 1
                except (json.JSONDecodeError, OSError):
                    continue
            # Remove empty correlation dirs
            try:
                if not any(corr_dir.iterdir()):
                    corr_dir.rmdir()
            except OSError:
                pass
        return removed
