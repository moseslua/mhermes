"""
ProposalEngine — approval-gated proposal generation for workflow patterns.

Detects recurring workflow patterns, ranks them, and generates projection-safe
scaffolds for skills and plugins. Proposals are created in ``pending`` status
and must be reviewed before activation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_hermes_home
from hermes_state import SessionDB
from agent.state_projections import _atomic_write

logger = logging.getLogger(__name__)

DEFAULT_SCAFFOLD_DIR = get_hermes_home() / "proposals"
# Patterns we can detect from message history or tool usage
_WORKFLOW_PATTERNS: Dict[str, Dict[str, Any]] = {
    "skill_from_tools": {
        "title": "Extract reusable skill from repeated tool calls",
        "description": "A sequence of tool calls is repeated across sessions; consider bundling into a skill.",
    },
    "plugin_integration": {
        "title": "New plugin integration candidate",
        "description": "Frequent use of an external API suggests a dedicated plugin wrapper.",
    },
    "context_compression": {
        "title": "Context compression pipeline",
        "description": "Sessions are hitting context limits; a compression strategy may help.",
    },
    "model_routing": {
        "title": "Smart model routing rule",
        "description": "Task types correlate strongly with model switches; automate routing.",
    },
}


class ProposalEngine:
    """
    Detect workflow patterns and manage the proposal queue.

    All proposals are generated-only by default (status='pending').
    """

    def __init__(
        self,
        db: SessionDB | None = None,
        scaffold_dir: Path | None = None,
    ):
        self.db = db or SessionDB()
        self.scaffold_dir = scaffold_dir or DEFAULT_SCAFFOLD_DIR
        self.scaffold_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect_workflow_patterns(
        self,
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Inspect *context* and return a list of detected pattern dicts.

        *context* may contain keys like ``tool_calls``, ``messages``,
        ``session_count``, ``provider_switches``, etc.
        """
        detected: List[Dict[str, Any]] = []

        tool_calls = context.get("tool_calls", [])
        if isinstance(tool_calls, list) and len(tool_calls) >= 3:
            # Repeated tool-call sequence heuristic
            names = [tc.get("name") for tc in tool_calls if isinstance(tc, dict)]
            if len(set(names)) < len(names):
                detected.append({
                    "type": "skill_from_tools",
                    "confidence": min(0.5 + 0.1 * len(names), 0.95),
                    "evidence": {"tool_names": names},
                })

        provider_switches = context.get("provider_switches", 0)
        if provider_switches >= 3:
            detected.append({
                "type": "model_routing",
                "confidence": min(0.4 + 0.15 * provider_switches, 0.9),
                "evidence": {"switch_count": provider_switches},
            })

        external_api_calls = context.get("external_api_calls", 0)
        if external_api_calls >= 5:
            detected.append({
                "type": "plugin_integration",
                "confidence": min(0.4 + 0.1 * external_api_calls, 0.9),
                "evidence": {"api_call_count": external_api_calls},
            })

        context_limit_hits = context.get("context_limit_hits", 0)
        if context_limit_hits >= 2:
            detected.append({
                "type": "context_compression",
                "confidence": min(0.5 + 0.15 * context_limit_hits, 0.95),
                "evidence": {"limit_hits": context_limit_hits},
            })

        return detected

    # ------------------------------------------------------------------
    # Queue management (with dedupe + ranking)
    # ------------------------------------------------------------------

    def queue_proposal(
        self,
        session_id: str,
        proposal_type: str,
        title: str,
        description: str = "",
        context_hash: str = "",
        scaffold_path: str = "",
    ) -> str:
        """
        Add a proposal to the queue, deduping against pending proposals
        with the same (session_id, proposal_type, context_hash).
        """
        # Dedupe: if an identical pending proposal exists, skip
        existing = self.db.list_proposals(
            session_id=session_id, status="pending", limit=100
        )
        for ep in existing:
            if ep["proposal_type"] == proposal_type:
                # Simple dedupe by title similarity when no hash provided
                if not context_hash or ep.get("description", "") == description:
                    logger.debug(
                        "Deduped proposal %s (type=%s) for session %s",
                        ep["id"], proposal_type, session_id,
                    )
                    return ep["id"]

        proposal_id = f"prop-{uuid.uuid4().hex[:12]}"
        self.db.create_proposal(
            proposal_id=proposal_id,
            session_id=session_id,
            proposal_type=proposal_type,
            title=title,
            description=description,
            status="pending",
            scaffold_path=scaffold_path or None,
        )
        logger.info("Queued proposal %s (%s)", proposal_id, proposal_type)
        return proposal_id

    def rank_proposals(
        self,
        session_id: str | None = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Return pending proposals ordered by recency.

        In a real system this could score by confidence, business value,
        session frequency, etc. For now we return newest first.
        """
        proposals = self.db.list_proposals(
            session_id=session_id, status="pending", limit=limit
        )
        # Attach a simple rank score (newer = higher)
        for idx, p in enumerate(proposals):
            p["rank_score"] = max(0.0, 1.0 - idx * 0.05)
        return proposals

    # ------------------------------------------------------------------
    # Scaffold generation
    # ------------------------------------------------------------------

    def generate_scaffold(
        self,
        proposal_type: str,
        context: Dict[str, Any],
    ) -> str:
        """
        Create a projection-safe scaffold file for a skill or plugin.

        Returns the path to the generated scaffold file.
        """
        # Build a stable filename from type + sorted context keys
        ctx_json = json.dumps(context, sort_keys=True, default=str)
        digest = hashlib.sha256(ctx_json.encode()).hexdigest()[:16]
        # Sanitize proposal_type to prevent path traversal
        safe_type = re.sub(r"[^a-zA-Z0-9_-]", "_", proposal_type)
        filename = f"{safe_type}_{digest}.json"
        scaffold_path = self.scaffold_dir / filename

        scaffold = {
            "proposal_type": proposal_type,
            "generated_at": time.time(),
            "context": context,
            "template": self._scaffold_template(proposal_type),
        }

        _atomic_write(
            scaffold_path,
            json.dumps(scaffold, indent=2, default=str),
            mode="w",
        )
        logger.info("Generated scaffold: %s", scaffold_path)
        return str(scaffold_path)

    def _scaffold_template(self, proposal_type: str) -> Dict[str, Any]:
        """Return a template dict for the given proposal type."""
        if proposal_type == "skill_from_tools":
            return {
                "kind": "skill",
                "manifest": {
                    "name": "",
                    "version": "0.1.0",
                    "description": "",
                    "tools": [],
                },
                "entrypoint": "scripts/run.py",
            }
        if proposal_type == "plugin_integration":
            return {
                "kind": "plugin",
                "manifest": {
                    "name": "",
                    "version": "0.1.0",
                    "hooks": ["on_startup", "on_message"],
                },
                "entrypoint": "__init__.py",
            }
        if proposal_type == "context_compression":
            return {
                "kind": "pipeline",
                "manifest": {
                    "name": "",
                    "stages": ["summarize", "prune", "rehydrate"],
                },
            }
        if proposal_type == "model_routing":
            return {
                "kind": "rule",
                "manifest": {
                    "name": "",
                    "conditions": [],
                    "target_model": "",
                },
            }
        return {"kind": "unknown", "manifest": {}}

    # ------------------------------------------------------------------
    # Convenience: detect + queue in one pass
    # ------------------------------------------------------------------

    def detect_and_queue(
        self,
        session_id: str,
        context: Dict[str, Any],
    ) -> List[str]:
        """
        Detect patterns in *context* and queue proposals for each.

        Returns the list of proposal IDs created (dedupes may return
        existing IDs).
        """
        patterns = self.detect_workflow_patterns(context)
        ids: List[str] = []
        for pat in patterns:
            ptype = pat["type"]
            meta = _WORKFLOW_PATTERNS.get(ptype, {})
            title = meta.get("title", ptype)
            description = meta.get("description", "")
            scaffold_path = self.generate_scaffold(ptype, context)
            pid = self.queue_proposal(
                session_id=session_id,
                proposal_type=ptype,
                title=title,
                description=description,
                context_hash=json.dumps(pat.get("evidence", {}), sort_keys=True),
                scaffold_path=scaffold_path,
            )
            ids.append(pid)
        return ids
