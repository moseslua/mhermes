"""Tests for one-way state projections.

Invariant: projections are **write-only** — no test reads a projection back
into canonical state.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from agent.mission_state import MissionService
from agent.runtime_signals import completed_signal, requested_signal
from agent.state_projections import ProjectionService, _atomic_write, _snapshot_hash
from hermes_constants import get_fabric_dir, get_obsidian_vault_dir, get_projection_dir
from hermes_state import SessionDB


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    db_path = tmp_path / ".hermes" / "state.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    session_db = SessionDB(db_path=db_path)
    yield session_db
    session_db.close()


@pytest.fixture()
def service(db):
    return ProjectionService(db)


@pytest.fixture()
def mission_service(db):
    return MissionService(db)


class TestAtomicWrite:
    """Atomic temp-file + rename must never leave partial output visible."""

    def test_atomic_write_creates_target(self, tmp_path):
        target = tmp_path / "out.json"
        _atomic_write(target, '{"ok": true}')
        assert target.read_text() == '{"ok": true}'
        # No temp debris
        assert list(tmp_path.glob(".*.tmp.*")) == []

    def test_atomic_write_bytes_mode(self, tmp_path):
        target = tmp_path / "out.bin"
        _atomic_write(target, b"\x00\x01\x02", mode="wb")
        assert target.read_bytes() == b"\x00\x01\x02"

    def test_atomic_write_does_not_leave_partial_on_crash(self, tmp_path, monkeypatch):
        target = tmp_path / "out.json"
        calls = []

        original_replace = os.replace

        def _boom(*args, **kwargs):
            calls.append("replace")
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", _boom)

        with pytest.raises(OSError):
            _atomic_write(target, '{"ok": true}')

        # Target must not exist (or must be previous version — here there is none)
        assert not target.exists()
        # Temp file must be cleaned up
        assert list(tmp_path.glob(".*.tmp.*")) == []

    def test_atomic_write_concurrent_stress(self, tmp_path):
        target = tmp_path / "counter.json"
        errors = []

        def _worker(value: int):
            try:
                _atomic_write(target, json.dumps({"value": value}))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # File must contain valid JSON with some value
        data = json.loads(target.read_text())
        assert isinstance(data["value"], int)


class TestProjectionFabric:
    def test_project_fabric_creates_session_json(self, service, db, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
        db.create_session("s1", "cli")
        db.append_message("s1", "user", "hello")
        db.append_message("s1", "assistant", "hi")

        out = service.project_fabric("s1")
        assert out == get_fabric_dir() / "s1.json"

        payload = json.loads(out.read_text())
        assert payload["session"]["id"] == "s1"
        assert len(payload["messages"]) == 2
        assert "projected_at" in payload

    def test_project_fabric_to_custom_dir(self, service, db, tmp_path):
        custom = tmp_path / "my-fabric"
        db.create_session("s1", "cli")
        out = service.project_fabric("s1", output_dir=custom)
        assert out == custom / "s1.json"
        assert out.exists()

    def test_project_fabric_raises_on_missing_session(self, service):
        with pytest.raises(ValueError, match="Session not found"):
            service.project_fabric("nosuch")


class TestProjectionObsidian:
    def test_project_obsidian_creates_markdown(self, service, db, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
        db.create_session("s1", "cli")
        db.append_message("s1", "user", "hello world")

        out = service.project_obsidian("s1")
        assert out == get_obsidian_vault_dir() / "s1.md"

        text = out.read_text()
        assert "---" in text
        assert "session_id: s1" in text
        assert "# Session s1" in text
        assert "hello world" in text

    def test_project_obsidian_to_custom_vault(self, service, db, tmp_path):
        vault = tmp_path / "vault"
        db.create_session("s1", "cli")
        out = service.project_obsidian("s1", vault_path=vault)
        assert out == vault / "s1.md"
        assert out.exists()


class TestProjectionMissionBundle:
    def test_project_mission_bundle(self, service, db, mission_service, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
        db.create_session("s1", "cli")
        mission = mission_service.create_mission(title="Test Mission", created_by_session_id="s1")
        mission_service.approve_mission(mission["id"])

        out = service.project_mission_bundle(mission["id"])
        assert out == get_projection_dir("mission_bundle") / f"{mission['id']}.json"

        payload = json.loads(out.read_text())
        assert payload["mission"]["title"] == "Test Mission"
        assert payload["nodes"] == []
        assert payload["links"] == []
        assert "projected_at" in payload

    def test_project_mission_bundle_raises_on_missing(self, service):
        with pytest.raises(ValueError, match="Mission not found"):
            service.project_mission_bundle("nosuch")


class TestIncrementalReplay:
    def test_replay_processes_new_signals_and_advances_cursor(self, service, db, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
        db.create_session("s1", "cli")

        # Seed some runtime signals
        sig1 = requested_signal(
            event_type="session.start",
            publisher="test",
            session_id="s1",
            correlation_id="c1",
            sequence_no=1,
            provenance="system",
            payload={"foo": 1},
        )
        sig2 = completed_signal(
            event_type="session.start",
            publisher="test",
            session_id="s1",
            correlation_id="c1",
            sequence_no=2,
            provenance="system",
            payload={"foo": 2},
        )
        aid1 = db.append_runtime_signal_audit(sig1)
        aid2 = db.append_runtime_signal_audit(sig2)

        # First replay
        service.incremental_replay("fabric")

        out = get_fabric_dir() / "s1.json"
        assert out.exists()
        cursor = service.get_projection_cursor("fabric")
        assert cursor is not None
        assert cursor["last_applied_audit_id"] == max(aid1, aid2)
        assert cursor["last_snapshot_hash"] is not None

        # Add another signal
        sig3 = completed_signal(
            event_type="message.add",
            publisher="test",
            session_id="s1",
            correlation_id="c2",
            sequence_no=3,
            provenance="system",
            payload={"foo": 3},
        )
        aid3 = db.append_runtime_signal_audit(sig3)

        # Second replay — should pick up only the new signal
        service.incremental_replay("fabric")
        cursor2 = service.get_projection_cursor("fabric")
        assert cursor2["last_applied_audit_id"] == aid3
        # Hash should have changed because more signals were projected
        assert cursor2["last_snapshot_hash"] != cursor["last_snapshot_hash"]

    def test_replay_is_idempotent_when_no_new_signals(self, service, db, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
        db.create_session("s1", "cli")
        sig = requested_signal(
            event_type="session.start",
            publisher="test",
            session_id="s1",
            correlation_id="c1",
            sequence_no=1,
            provenance="system",
        )
        db.append_runtime_signal_audit(sig)

        service.incremental_replay("fabric")
        cursor1 = service.get_projection_cursor("fabric")

        # Run again with no new signals
        service.incremental_replay("fabric")
        cursor2 = service.get_projection_cursor("fabric")

        # Cursor should not regress
        assert cursor2["last_applied_audit_id"] == cursor1["last_applied_audit_id"]

    def test_replay_dispatches_mission_bundle(self, service, db, mission_service, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
        db.create_session("s1", "cli")
        mission = mission_service.create_mission(title="M", created_by_session_id="s1")
        mission_service.approve_mission(mission["id"])

        sig = requested_signal(
            event_type="mission.create",
            publisher="test",
            session_id="s1",
            mission_id=mission["id"],
            correlation_id="c1",
            sequence_no=1,
            provenance="system",
        )
        db.append_runtime_signal_audit(sig)

        service.incremental_replay("mission_bundle")
        out = get_projection_dir("mission_bundle") / f"{mission['id']}.json"
        assert out.exists()


class TestRebuild:
    def test_rebuild_deletes_and_reconstructs(self, service, db, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
        db.create_session("s1", "cli")
        db.append_message("s1", "user", "hello")
        db.append_runtime_signal_audit(
            requested_signal(
                event_type="session.start",
                publisher="test",
                session_id="s1",
                correlation_id="c1",
                sequence_no=1,
                provenance="system",
            )
        )

        service.incremental_replay("fabric")
        first = json.loads((get_fabric_dir() / "s1.json").read_text())

        # Corrupt the projection (simulate external tampering)
        (get_fabric_dir() / "s1.json").write_text("corrupted")
        # Add an extra junk file
        (get_fabric_dir() / "junk.txt").write_text("junk")

        # Rebuild should wipe and recreate
        service.rebuild("fabric")
        second = json.loads((get_fabric_dir() / "s1.json").read_text())
        assert not (get_fabric_dir() / "junk.txt").exists()
        assert second["session"]["id"] == first["session"]["id"]
        assert second["messages"] == first["messages"]

    def test_rebuild_is_idempotent(self, service, db, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
        db.create_session("s1", "cli")
        db.append_runtime_signal_audit(
            requested_signal(
                event_type="session.start",
                publisher="test",
                session_id="s1",
                correlation_id="c1",
                sequence_no=1,
                provenance="system",
            )
        )

        service.rebuild("fabric")
        first_data = json.loads((get_fabric_dir() / "s1.json").read_text())
        first_data.pop("projected_at", None)
        first_hash = _snapshot_hash(first_data)
        cursor1 = service.get_projection_cursor("fabric")

        service.rebuild("fabric")
        second_data = json.loads((get_fabric_dir() / "s1.json").read_text())
        second_data.pop("projected_at", None)
        second_hash = _snapshot_hash(second_data)
        cursor2 = service.get_projection_cursor("fabric")

        assert first_hash == second_hash
        assert cursor1["last_applied_audit_id"] == cursor2["last_applied_audit_id"]

    def test_rebuild_unknown_type_raises(self, service):
        with pytest.raises(ValueError, match="Unknown projection_type"):
            service.rebuild("unknown_type")


class TestProjectionHelpers:
    def test_available_requires_db(self):
        svc = ProjectionService(None)
        assert not svc.available
        with pytest.raises(RuntimeError, match="Session database not available"):
            svc.project_fabric("s1")

    def test_get_last_projected_path(self, service):
        assert service.get_last_projected_path("fabric", "s1") == get_fabric_dir() / "s1.json"
        assert service.get_last_projected_path("obsidian", "s1") == get_obsidian_vault_dir() / "s1.md"
        assert service.get_last_projected_path("mission_bundle", "m1") == get_projection_dir("mission_bundle") / "m1.json"

    def test_get_last_projected_path_unknown_raises(self, service):
        with pytest.raises(ValueError, match="Unknown projection_type"):
            service.get_last_projected_path("nosuch", "x")
