"""One-way state projections for Hermes.

Projections are **one-way only** — they mirror canonical state to external
formats (Fabric directory, Obsidian vault) but are never read back as input.
All writes use temp-file + atomic rename for crash safety.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_fabric_dir, get_obsidian_vault_dir, get_projection_dir
from hermes_state import SessionDB

logger = logging.getLogger(__name__)

# Event-type prefixes that are relevant to each projection family.
_FABRIC_RELEVANT_PREFIXES = {"session.", "message.", "tool."}
_OBSIDIAN_RELEVANT_PREFIXES = {"session.", "message.", "mission."}
_MISSION_BUNDLE_RELEVANT_PREFIXES = {"mission.", "node.", "link."}

_RELEVANT_PREFIXES: dict[str, frozenset[str]] = {
    "fabric": _FABRIC_RELEVANT_PREFIXES,
    "obsidian": _OBSIDIAN_RELEVANT_PREFIXES,
    "mission_bundle": _MISSION_BUNDLE_RELEVANT_PREFIXES,
}


def _atomic_write(path: Path, content: bytes | str, mode: str = "w") -> None:
    """Write *content* to *path* atomically via a temp file + rename.

    The temp file is created in the same parent directory so the rename
    is guaranteed to be on the same filesystem and therefore atomic.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp.{uuid.uuid4().hex}"
    try:
        if isinstance(content, bytes):
            tmp.write_bytes(content)
        else:
            tmp.write_text(content, encoding="utf-8")
        os.replace(str(tmp), str(path))
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _snapshot_hash(data: Any) -> str:
    """Return a deterministic hash for *data* (used for idempotency checks)."""
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ProjectionService:
    """One-way projection service backed by ``SessionDB``.

    Methods are idempotent and use atomic writes so a crash mid-projection
    never leaves a partially-written file visible to consumers.
    """

    def __init__(self, session_db: SessionDB | None) -> None:
        self._db = session_db

    @property
    def available(self) -> bool:
        return self._db is not None

    def _require_db(self) -> SessionDB:
        if self._db is None:
            raise RuntimeError("Session database not available")
        return self._db

    # -----------------------------------------------------------------------
    # Public projection API
    # -----------------------------------------------------------------------

    def project_fabric(self, session_id: str, output_dir: str | Path | None = None) -> Path:
        """One-way mirror session state into the Fabric directory.

        Returns the path to the written session JSON file.
        """
        db = self._require_db()
        target = Path(output_dir) if output_dir else get_fabric_dir()
        target.mkdir(parents=True, exist_ok=True)

        session = db.get_session(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")

        messages = db.get_messages(session_id)
        payload = {
            "session": session,
            "messages": messages,
            "projected_at": time.time(),
        }
        out_path = target / f"{session_id}.json"
        _atomic_write(out_path, json.dumps(payload, indent=2, ensure_ascii=False))
        logger.debug("project_fabric: %s -> %s", session_id, out_path)
        return out_path

    def project_obsidian(self, session_id: str, vault_path: str | Path | None = None) -> Path:
        """One-way mirror session state into an Obsidian vault as a Markdown note.

        Returns the path to the written Markdown file.
        """
        db = self._require_db()
        vault = Path(vault_path) if vault_path else get_obsidian_vault_dir()
        vault.mkdir(parents=True, exist_ok=True)

        session = db.get_session(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")

        messages = db.get_messages(session_id)
        lines: List[str] = []
        lines.append("---")
        lines.append(f"session_id: {session_id}")
        lines.append(f"source: {session.get('source', 'unknown')}")
        lines.append(f"started_at: {session.get('started_at', '')}")
        lines.append(f"projected_at: {time.time()}")
        lines.append("---")
        lines.append("")
        lines.append(f"# Session {session_id}")
        lines.append("")

        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            lines.append(f"## {role}")
            lines.append("")
            lines.append(str(content))
            lines.append("")

        out_path = vault / f"{session_id}.md"
        _atomic_write(out_path, "\n".join(lines))
        logger.debug("project_obsidian: %s -> %s", session_id, out_path)
        return out_path

    def project_mission_bundle(self, mission_id: str, output_path: str | Path | None = None) -> Path:
        """Export a mission and its graph as a JSON bundle.

        Returns the path to the written bundle file.
        """
        db = self._require_db()
        out = Path(output_path) if output_path else get_projection_dir("mission_bundle") / f"{mission_id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)

        # Import here to avoid circular imports at module load time.
        from agent.mission_state import MissionService

        svc = MissionService(db)
        mission = svc.get_mission(mission_id)
        if mission is None:
            raise ValueError(f"Mission not found: {mission_id}")

        nodes = svc.list_nodes(mission_id)
        links = svc.list_links(mission_id)
        todos = svc.get_todos_for_session(mission_id)

        payload = {
            "mission": mission,
            "nodes": nodes,
            "links": links,
            "todos": todos,
            "projected_at": time.time(),
        }
        _atomic_write(out, json.dumps(payload, indent=2, ensure_ascii=False))
        logger.debug("project_mission_bundle: %s -> %s", mission_id, out)
        return out

    # -----------------------------------------------------------------------
    # Replay / rebuild
    # -----------------------------------------------------------------------

    def incremental_replay(self, projection_type: str) -> None:
        """Replay projection-relevant signals from the last cursor position.

        Fetches ``runtime_signal_audit`` rows after
        ``projection_cursors.last_applied_audit_id`` and dispatches to the
        appropriate projection method.
        """
        db = self._require_db()
        cursor = db.get_projection_cursor(projection_type)
        after_id = cursor["last_applied_audit_id"] if cursor else 0

        prefixes = _RELEVANT_PREFIXES.get(projection_type)
        if prefixes is None:
            raise ValueError(f"Unknown projection_type: {projection_type}")

        # Collect all relevant signals after the cursor.
        all_signals: List[Dict[str, Any]] = []
        for prefix in prefixes:
            batch = db.list_runtime_signal_audit(
                event_type_prefix=prefix,
                after_audit_id=after_id,
                limit=10000,
            )
            all_signals.extend(batch)

        if not all_signals:
            logger.debug("incremental_replay(%s): no new signals", projection_type)
            return

        # Sort globally by audit_id.
        all_signals.sort(key=lambda s: s["audit_id"])

        max_audit_id = all_signals[-1]["audit_id"]
        projected_sessions: set[str] = set()
        projected_missions: set[str] = set()

        for signal in all_signals:
            sid = signal.get("session_id")
            mid = signal.get("mission_id")

            if projection_type in ("fabric", "obsidian") and sid:
                projected_sessions.add(sid)
            elif projection_type == "mission_bundle" and mid:
                projected_missions.add(mid)

        # Apply projections.
        for sid in projected_sessions:
            if projection_type == "fabric":
                self.project_fabric(sid)
            elif projection_type == "obsidian":
                self.project_obsidian(sid)

        for mid in projected_missions:
            if projection_type == "mission_bundle":
                self.project_mission_bundle(mid)

        snapshot = {
            "projection_type": projection_type,
            "max_audit_id": max_audit_id,
            "projected_sessions": sorted(projected_sessions),
            "projected_missions": sorted(projected_missions),
        }
        db.set_projection_cursor(
            projection_type,
            last_applied_audit_id=max_audit_id,
            last_snapshot_hash=_snapshot_hash(snapshot),
        )
        logger.debug(
            "incremental_replay(%s): processed %d signals up to audit_id %d",
            projection_type,
            len(all_signals),
            max_audit_id,
        )

    def rebuild(self, projection_type: str) -> None:
        """Full delete-and-rebuild of *projection_type*.

        Removes the projection output directory, resets the cursor, and
        re-runs a full incremental replay (which, because the cursor is now
        at 0, will process every historical signal).
        """
        db = self._require_db()

        # Determine output directory to wipe.
        if projection_type == "fabric":
            target = get_fabric_dir()
        elif projection_type == "obsidian":
            target = get_obsidian_vault_dir()
        elif projection_type == "mission_bundle":
            target = get_projection_dir("mission_bundle")
        else:
            raise ValueError(f"Unknown projection_type: {projection_type}")

        if target.exists():
            for child in target.iterdir():
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    shutil.rmtree(child)

        db.reset_projection_cursor(projection_type)
        self.incremental_replay(projection_type)
        logger.info("rebuild(%s): full rebuild complete", projection_type)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def get_projection_cursor(self, projection_type: str) -> Optional[Dict[str, Any]]:
        """Return the current cursor for *projection_type*, or None."""
        db = self._require_db()
        return db.get_projection_cursor(projection_type)

    def get_last_projected_path(self, projection_type: str, identifier: str) -> Path:
        """Return the expected on-disk path for a projected artifact.

        This is a convenience helper for tests and monitoring; it does **not**
        read the file.
        """
        if projection_type == "fabric":
            return get_fabric_dir() / f"{identifier}.json"
        elif projection_type == "obsidian":
            return get_obsidian_vault_dir() / f"{identifier}.md"
        elif projection_type == "mission_bundle":
            return get_projection_dir("mission_bundle") / f"{identifier}.json"
        else:
            raise ValueError(f"Unknown projection_type: {projection_type}")
