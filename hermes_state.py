#!/usr/bin/env python3
"""
SQLite State Store for Hermes Agent.

Provides persistent session storage with FTS5 full-text search, replacing
the per-session JSONL file approach. Stores session metadata, full message
history, and model configuration for CLI and gateway sessions.

Key design decisions:
- WAL mode for concurrent readers + one writer (gateway multi-platform)
- FTS5 virtual table for fast text search across all session messages
- Compression-triggered session splitting via parent_session_id chains
- Batch runner and RL trajectories are NOT stored here (separate systems)
- Session source tagging ('cli', 'telegram', 'discord', etc.) for filtering
"""

import json
import logging
import random
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar
from agent.runtime_signals import RuntimeSignal
from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_DB_PATH = get_hermes_home() / "state.db"

SCHEMA_VERSION = 9

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    user_id TEXT,
    model TEXT,
    model_config TEXT,
    system_prompt TEXT,
    parent_session_id TEXT,
    attached_mission_id TEXT,
    local_todo_state TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    billing_provider TEXT,
    billing_base_url TEXT,
    billing_mode TEXT,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    cost_status TEXT,
    cost_source TEXT,
    pricing_version TEXT,
    title TEXT,
    FOREIGN KEY (parent_session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL,
    token_count INTEGER,
    finish_reason TEXT,
    reasoning TEXT,
    reasoning_details TEXT,
    codex_reasoning_items TEXT
 );

CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);
"""

RUNTIME_SIGNAL_AUDIT_SQL = """
CREATE TABLE IF NOT EXISTS runtime_signal_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL,
    event_type TEXT NOT NULL,
    phase TEXT NOT NULL,
    occurred_at REAL NOT NULL,
    publisher TEXT NOT NULL,
    session_id TEXT,
    mission_id TEXT,
    correlation_id TEXT NOT NULL,
    sequence_no INTEGER,
    actor_json TEXT,
    subject_json TEXT,
    provenance TEXT NOT NULL,
    payload_json TEXT,
    payload_bytes INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
 );
CREATE INDEX IF NOT EXISTS idx_runtime_signal_session ON runtime_signal_audit(session_id, id);
CREATE INDEX IF NOT EXISTS idx_runtime_signal_type_time ON runtime_signal_audit(event_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_runtime_signal_correlation ON runtime_signal_audit(correlation_id);
CREATE INDEX IF NOT EXISTS idx_runtime_signal_idempotency ON runtime_signal_audit(idempotency_key);
"""

MISSION_STATE_SQL = """
CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL,
    created_by_session_id TEXT,
    approved_by_session_id TEXT,
    activated_by_session_id TEXT,
    metadata_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    approved_at REAL,
    activated_at REAL
 );
CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_missions_created_by ON missions(created_by_session_id);

CREATE TABLE IF NOT EXISTS mission_nodes (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    parent_node_id TEXT REFERENCES mission_nodes(id) ON DELETE CASCADE,
    external_id TEXT,
    node_type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    status TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
 );
CREATE INDEX IF NOT EXISTS idx_mission_nodes_mission_pos ON mission_nodes(mission_id, position, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mission_nodes_external ON mission_nodes(mission_id, external_id) WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS mission_links (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    source_node_id TEXT NOT NULL REFERENCES mission_nodes(id) ON DELETE CASCADE,
    target_node_id TEXT NOT NULL REFERENCES mission_nodes(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL,
    metadata_json TEXT,
    created_at REAL NOT NULL
 );
CREATE INDEX IF NOT EXISTS idx_mission_links_mission ON mission_links(mission_id, created_at);

CREATE TABLE IF NOT EXISTS handoff_packets (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    from_session_id TEXT,
    to_session_id TEXT,
    child_session_id TEXT,
    goal TEXT NOT NULL,
    context TEXT,
    summary TEXT,
    status TEXT NOT NULL,
    metadata_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
 );
CREATE INDEX IF NOT EXISTS idx_handoff_packets_mission ON handoff_packets(mission_id, created_at);

CREATE TABLE IF NOT EXISTS mission_checkpoints (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    session_id TEXT,
    checkpoint_type TEXT NOT NULL,
    title TEXT,
    payload_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
 );
CREATE INDEX IF NOT EXISTS idx_mission_checkpoints_mission ON mission_checkpoints(mission_id, checkpoint_type, created_at);
"""


DOMAIN_STATE_SQL = """
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    request_type TEXT NOT NULL,
    requested_at REAL NOT NULL,
    approved_at REAL,
    approved_by TEXT,
    status TEXT NOT NULL,
    payload_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
 );
CREATE INDEX IF NOT EXISTS idx_approvals_session ON approvals(session_id, status, created_at);


CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    proposal_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL,
    scaffold_path TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    reviewed_at REAL
 );
CREATE INDEX IF NOT EXISTS idx_proposals_session ON proposals(session_id, status, created_at);


CREATE TABLE IF NOT EXISTS model_mutations (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    key TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT NOT NULL,
    requested_at REAL NOT NULL,
    approved_at REAL,
    status TEXT NOT NULL,
    rollback_value TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
 );
CREATE INDEX IF NOT EXISTS idx_model_mutations_session ON model_mutations(session_id, status, created_at);


CREATE TABLE IF NOT EXISTS learning_exports (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    export_type TEXT NOT NULL,
    path TEXT,
    status TEXT NOT NULL,
    result_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
 );
CREATE INDEX IF NOT EXISTS idx_learning_exports_session ON learning_exports(session_id, status, created_at);


CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    eval_type TEXT NOT NULL,
    result_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
 );
CREATE INDEX IF NOT EXISTS idx_eval_runs_session ON eval_runs(session_id, eval_type, created_at);


CREATE TABLE IF NOT EXISTS projection_cursors (
    id TEXT PRIMARY KEY,
    projection_type TEXT NOT NULL UNIQUE,
    last_applied_audit_id INTEGER,
    last_snapshot_hash TEXT,
    last_projection_version INTEGER DEFAULT 0,
    updated_at REAL NOT NULL
 );
CREATE INDEX IF NOT EXISTS idx_projection_cursors_type ON projection_cursors(projection_type);


CREATE TABLE IF NOT EXISTS analytics_rollups (
    id TEXT PRIMARY KEY,
    rollup_type TEXT NOT NULL,
    period_start REAL NOT NULL,
    period_end REAL NOT NULL,
    data_json TEXT NOT NULL,
    created_at REAL NOT NULL
 );
CREATE INDEX IF NOT EXISTS idx_analytics_rollups_type_period ON analytics_rollups(rollup_type, period_start DESC);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content=messages,
    content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


class SessionDB:
    """
    SQLite-backed session storage with FTS5 search.

    Thread-safe for the common gateway pattern (multiple reader threads,
    single writer via WAL mode). Each method opens its own cursor.
    """

    # ── Write-contention tuning ──
    # With multiple hermes processes (gateway + CLI sessions + worktree agents)
    # all sharing one state.db, WAL write-lock contention causes visible TUI
    # freezes.  SQLite's built-in busy handler uses a deterministic sleep
    # schedule that causes convoy effects under high concurrency.
    #
    # Instead, we keep the SQLite timeout short (1s) and handle retries at the
    # application level with random jitter, which naturally staggers competing
    # writers and avoids the convoy.
    _WRITE_MAX_RETRIES = 15
    _WRITE_RETRY_MIN_S = 0.020   # 20ms
    _WRITE_RETRY_MAX_S = 0.150   # 150ms
    # Attempt a PASSIVE WAL checkpoint every N successful writes.
    _CHECKPOINT_EVERY_N_WRITES = 50

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._write_count = 0
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            # Short timeout — application-level retry with random jitter
            # handles contention instead of sitting in SQLite's internal
            # busy handler for up to 30s.
            timeout=1.0,
            # Autocommit mode: Python's default isolation_level="" auto-starts
            # transactions on DML, which conflicts with our explicit
            # BEGIN IMMEDIATE.  None = we manage transactions ourselves.
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._init_schema()

    # ── Core write helper ──

    def _execute_write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Execute a write transaction with BEGIN IMMEDIATE and jitter retry.

        *fn* receives the connection and should perform INSERT/UPDATE/DELETE
        statements.  The caller must NOT call ``commit()`` — that's handled
        here after *fn* returns.

        BEGIN IMMEDIATE acquires the WAL write lock at transaction start
        (not at commit time), so lock contention surfaces immediately.
        On ``database is locked``, we release the Python lock, sleep a
        random 20-150ms, and retry — breaking the convoy pattern that
        SQLite's built-in deterministic backoff creates.

        Returns whatever *fn* returns.
        """
        last_err: Optional[Exception] = None
        for attempt in range(self._WRITE_MAX_RETRIES):
            try:
                with self._lock:
                    self._conn.execute("BEGIN IMMEDIATE")
                    try:
                        result = fn(self._conn)
                        self._conn.commit()
                    except BaseException:
                        try:
                            self._conn.rollback()
                        except Exception:
                            pass
                        raise
                # Success — periodic best-effort checkpoint.
                self._write_count += 1
                if self._write_count % self._CHECKPOINT_EVERY_N_WRITES == 0:
                    self._try_wal_checkpoint()
                return result
            except sqlite3.OperationalError as exc:
                err_msg = str(exc).lower()
                if "locked" in err_msg or "busy" in err_msg:
                    last_err = exc
                    if attempt < self._WRITE_MAX_RETRIES - 1:
                        jitter = random.uniform(
                            self._WRITE_RETRY_MIN_S,
                            self._WRITE_RETRY_MAX_S,
                        )
                        time.sleep(jitter)
                        continue
                # Non-lock error or retries exhausted — propagate.
                raise
        # Retries exhausted (shouldn't normally reach here).
        raise last_err or sqlite3.OperationalError(
            "database is locked after max retries"
        )

    def _try_wal_checkpoint(self) -> None:
        """Best-effort PASSIVE WAL checkpoint.  Never blocks, never raises.

        Flushes committed WAL frames back into the main DB file for any
        frames that no other connection currently needs.  Keeps the WAL
        from growing unbounded when many processes hold persistent
        connections.
        """
        try:
            with self._lock:
                result = self._conn.execute(
                    "PRAGMA wal_checkpoint(PASSIVE)"
                ).fetchone()
                if result and result[1] > 0:
                    logger.debug(
                        "WAL checkpoint: %d/%d pages checkpointed",
                        result[2], result[1],
                    )
        except Exception:
            pass  # Best effort — never fatal.

    def close(self):
        """Close the database connection.

        Attempts a PASSIVE WAL checkpoint first so that exiting processes
        help keep the WAL file from growing unbounded.
        """
        with self._lock:
            if self._conn:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                except Exception:
                    pass
                self._conn.close()
                self._conn = None

    def _init_schema(self):
        """Create tables and FTS if they don't exist, run migrations."""
        cursor = self._conn.cursor()

        cursor.executescript(SCHEMA_SQL)
        cursor.executescript(RUNTIME_SIGNAL_AUDIT_SQL)
        cursor.executescript(DOMAIN_STATE_SQL)
        # Check schema version and run migrations
        cursor.execute("SELECT version FROM schema_version LIMIT 1")
        row = cursor.fetchone()
        if row is None:
            cursor.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        else:
            current_version = row["version"] if isinstance(row, sqlite3.Row) else row[0]
            if current_version < 2:
                # v2: add finish_reason column to messages
                try:
                    cursor.execute("ALTER TABLE messages ADD COLUMN finish_reason TEXT")
                except sqlite3.OperationalError:
                    pass  # Column already exists
                cursor.execute("UPDATE schema_version SET version = 2")
            if current_version < 3:
                # v3: add title column to sessions
                try:
                    cursor.execute("ALTER TABLE sessions ADD COLUMN title TEXT")
                except sqlite3.OperationalError:
                    pass  # Column already exists
                cursor.execute("UPDATE schema_version SET version = 3")
            if current_version < 4:
                # v4: replace the old global title index with per-user/source scoping.
                try:
                    cursor.execute("DROP INDEX IF EXISTS idx_sessions_title_unique")
                    cursor.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_title_scoped "
                        "ON sessions(source, COALESCE(user_id, ''), title) WHERE title IS NOT NULL"
                    )
                except sqlite3.OperationalError:
                    pass  # Index already exists
                cursor.execute("UPDATE schema_version SET version = 4")
            if current_version < 5:
                new_columns = [
                    ("cache_read_tokens", "INTEGER DEFAULT 0"),
                    ("cache_write_tokens", "INTEGER DEFAULT 0"),
                    ("reasoning_tokens", "INTEGER DEFAULT 0"),
                    ("billing_provider", "TEXT"),
                    ("billing_base_url", "TEXT"),
                    ("billing_mode", "TEXT"),
                    ("estimated_cost_usd", "REAL"),
                    ("actual_cost_usd", "REAL"),
                    ("cost_status", "TEXT"),
                    ("cost_source", "TEXT"),
                    ("pricing_version", "TEXT"),
                ]
                for name, column_type in new_columns:
                    try:
                        # name and column_type come from the hardcoded tuple above,
                        # not user input. Double-quote identifier escaping is applied
                        # as defense-in-depth; SQLite DDL cannot be parameterized.
                        safe_name = name.replace('"', '""')
                        cursor.execute(f'ALTER TABLE sessions ADD COLUMN "{safe_name}" {column_type}')
                    except sqlite3.OperationalError:
                        pass
                cursor.execute("UPDATE schema_version SET version = 5")
            if current_version < 6:
                # v6: add reasoning columns to messages table — preserves assistant
                # reasoning text and structured reasoning_details across gateway
                # session turns.  Without these, reasoning chains are lost on
                # session reload, breaking multi-turn reasoning continuity for
                # providers that replay reasoning (OpenRouter, OpenAI, Nous).
                for col_name, col_type in [
                    ("reasoning", "TEXT"),
                    ("reasoning_details", "TEXT"),
                    ("codex_reasoning_items", "TEXT"),
                ]:
                    try:
                        safe = col_name.replace('"', '""')
                        cursor.execute(
                            f'ALTER TABLE messages ADD COLUMN "{safe}" {col_type}'
                        )
                    except sqlite3.OperationalError:
                        pass  # Column already exists
                cursor.execute("UPDATE schema_version SET version = 6")

            if current_version < 7:
                # v7: add bounded runtime-signal audit storage for later runtime
                # hook and projection integration. Delivery remains at-least-once;
                # audit rows are observational, not authoritative domain truth.
                cursor.executescript(RUNTIME_SIGNAL_AUDIT_SQL)
                cursor.execute("UPDATE schema_version SET version = 7")

            if current_version < 8:
                # v8: add canonical mission state, handoff/checkpoint records, and
                # per-session mission/todo attachment metadata for the Phase 2
                # mission authority cutover.
                for col_name, col_type in [
                    ("attached_mission_id", "TEXT"),
                    ("local_todo_state", "TEXT"),
                ]:
                    try:
                        safe = col_name.replace('"', '""')
                        cursor.execute(
                            f'ALTER TABLE sessions ADD COLUMN "{safe}" {col_type}'
                        )
                    except sqlite3.OperationalError:
                        pass
                cursor.executescript(MISSION_STATE_SQL)
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sessions_attached_mission ON sessions(attached_mission_id)"
                )
                cursor.execute("UPDATE schema_version SET version = 8")

            if current_version < 9:
                # v9: add authoritative domain tables for proposals, model mutations,
                # learning exports, eval runs, projection cursors, and analytics rollups.
                cursor.executescript(DOMAIN_STATE_SQL)
                cursor.execute("UPDATE schema_version SET version = 9")

        try:
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_attached_mission ON sessions(attached_mission_id)"
            )
        except sqlite3.OperationalError:
            pass

        # Scoped title index — titles are unique only within the same source/user namespace.
        try:
            cursor.execute("DROP INDEX IF EXISTS idx_sessions_title_unique")
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_title_scoped "
                "ON sessions(source, COALESCE(user_id, ''), title) WHERE title IS NOT NULL"
            )
        except sqlite3.OperationalError:
            pass  # Index already exists
            pass  # Index already exists

        # FTS5 setup (separate because CREATE VIRTUAL TABLE can't be in executescript with IF NOT EXISTS reliably)
        try:
            cursor.execute("SELECT * FROM messages_fts LIMIT 0")
        except sqlite3.OperationalError:
            cursor.executescript(FTS_SQL)

        self._conn.commit()

    # =========================================================================
    # Session lifecycle
    # =========================================================================

    def create_session(
        self,
        session_id: str,
        source: str,
        model: str = None,
        model_config: Dict[str, Any] = None,
        system_prompt: str = None,
        user_id: str = None,
        parent_session_id: str = None,
    ) -> str:
        """Create a new session record. Returns the session_id."""
        def _do(conn):
            conn.execute(
                """INSERT OR IGNORE INTO sessions (id, source, user_id, model, model_config,
                   system_prompt, parent_session_id, started_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    source,
                    user_id,
                    model,
                    json.dumps(model_config) if model_config else None,
                    system_prompt,
                    parent_session_id,
                    time.time(),
                ),
            )
        self._execute_write(_do)
        return session_id

    def end_session(self, session_id: str, end_reason: str) -> None:
        """Mark a session as ended."""
        def _do(conn):
            conn.execute(
                "UPDATE sessions SET ended_at = ?, end_reason = ? WHERE id = ?",
                (time.time(), end_reason, session_id),
            )
        self._execute_write(_do)

    def reopen_session(self, session_id: str) -> None:
        """Clear ended_at/end_reason so a session can be resumed."""
        def _do(conn):
            conn.execute(
                "UPDATE sessions SET ended_at = NULL, end_reason = NULL WHERE id = ?",
                (session_id,),
            )
        self._execute_write(_do)

    def update_system_prompt(self, session_id: str, system_prompt: str) -> None:
        """Store the full assembled system prompt snapshot."""
        def _do(conn):
            conn.execute(
                "UPDATE sessions SET system_prompt = ? WHERE id = ?",
                (system_prompt, session_id),
            )
        self._execute_write(_do)

    def update_token_counts(
        self,
        session_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = None,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
        estimated_cost_usd: Optional[float] = None,
        actual_cost_usd: Optional[float] = None,
        cost_status: Optional[str] = None,
        cost_source: Optional[str] = None,
        pricing_version: Optional[str] = None,
        billing_provider: Optional[str] = None,
        billing_base_url: Optional[str] = None,
        billing_mode: Optional[str] = None,
        absolute: bool = False,
    ) -> None:
        """Update token counters and backfill model if not already set.

        When *absolute* is False (default), values are **incremented** — use
        this for per-API-call deltas (CLI path).

        When *absolute* is True, values are **set directly** — use this when
        the caller already holds cumulative totals (gateway path, where the
        cached agent accumulates across messages).
        """
        if absolute:
            sql = """UPDATE sessions SET
                   input_tokens = ?,
                   output_tokens = ?,
                   cache_read_tokens = ?,
                   cache_write_tokens = ?,
                   reasoning_tokens = ?,
                   estimated_cost_usd = COALESCE(?, 0),
                   actual_cost_usd = CASE
                       WHEN ? IS NULL THEN actual_cost_usd
                       ELSE ?
                   END,
                   cost_status = COALESCE(?, cost_status),
                   cost_source = COALESCE(?, cost_source),
                   pricing_version = COALESCE(?, pricing_version),
                   billing_provider = COALESCE(billing_provider, ?),
                   billing_base_url = COALESCE(billing_base_url, ?),
                   billing_mode = COALESCE(billing_mode, ?),
                   model = COALESCE(model, ?)
                   WHERE id = ?"""
        else:
            sql = """UPDATE sessions SET
                   input_tokens = input_tokens + ?,
                   output_tokens = output_tokens + ?,
                   cache_read_tokens = cache_read_tokens + ?,
                   cache_write_tokens = cache_write_tokens + ?,
                   reasoning_tokens = reasoning_tokens + ?,
                   estimated_cost_usd = COALESCE(estimated_cost_usd, 0) + COALESCE(?, 0),
                   actual_cost_usd = CASE
                       WHEN ? IS NULL THEN actual_cost_usd
                       ELSE COALESCE(actual_cost_usd, 0) + ?
                   END,
                   cost_status = COALESCE(?, cost_status),
                   cost_source = COALESCE(?, cost_source),
                   pricing_version = COALESCE(?, pricing_version),
                   billing_provider = COALESCE(billing_provider, ?),
                   billing_base_url = COALESCE(billing_base_url, ?),
                   billing_mode = COALESCE(billing_mode, ?),
                   model = COALESCE(model, ?)
                   WHERE id = ?"""
        params = (
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_write_tokens,
            reasoning_tokens,
            estimated_cost_usd,
            actual_cost_usd,
            actual_cost_usd,
            cost_status,
            cost_source,
            pricing_version,
            billing_provider,
            billing_base_url,
            billing_mode,
            model,
            session_id,
        )
        def _do(conn):
            conn.execute(sql, params)
        self._execute_write(_do)

    def ensure_session(
        self,
        session_id: str,
        source: str = "unknown",
        model: str = None,
        user_id: str = None,
    ) -> None:
        """Ensure a session row exists, creating it with minimal metadata if absent.

        Used by _flush_messages_to_session_db to recover from a failed
        create_session() call (e.g. transient SQLite lock at agent startup).
        INSERT OR IGNORE is safe to call even when the row already exists.
        """
        def _do(conn):
            conn.execute(
                """INSERT OR IGNORE INTO sessions
                   (id, source, user_id, model, started_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, source, user_id, model, time.time()),
            )
        self._execute_write(_do)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a session by ID."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def resolve_session_id(self, session_id_or_prefix: str) -> Optional[str]:
        """Resolve an exact or uniquely prefixed session ID to the full ID.

        Returns the exact ID when it exists. Otherwise treats the input as a
        prefix and returns the single matching session ID if the prefix is
        unambiguous. Returns None for no matches or ambiguous prefixes.
        """
        exact = self.get_session(session_id_or_prefix)
        if exact:
            return exact["id"]

        escaped = (
            session_id_or_prefix
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        with self._lock:
            cursor = self._conn.execute(
                "SELECT id FROM sessions WHERE id LIKE ? ESCAPE '\\' ORDER BY started_at DESC LIMIT 2",
                (f"{escaped}%",),
            )
            matches = [row["id"] for row in cursor.fetchall()]
        if len(matches) == 1:
            return matches[0]
        return None

    # Maximum length for session titles
    MAX_TITLE_LENGTH = 100

    @staticmethod
    def sanitize_title(title: Optional[str]) -> Optional[str]:
        """Validate and sanitize a session title.

        - Strips leading/trailing whitespace
        - Removes ASCII control characters (0x00-0x1F, 0x7F) and problematic
          Unicode control chars (zero-width, RTL/LTR overrides, etc.)
        - Collapses internal whitespace runs to single spaces
        - Normalizes empty/whitespace-only strings to None
        - Enforces MAX_TITLE_LENGTH

        Returns the cleaned title string or None.
        Raises ValueError if the title exceeds MAX_TITLE_LENGTH after cleaning.
        """
        if not title:
            return None

        # Remove ASCII control characters (0x00-0x1F, 0x7F) but keep
        # whitespace chars (\t=0x09, \n=0x0A, \r=0x0D) so they can be
        # normalized to spaces by the whitespace collapsing step below
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', title)

        # Remove problematic Unicode control characters:
        # - Zero-width chars (U+200B-U+200F, U+FEFF)
        # - Directional overrides (U+202A-U+202E, U+2066-U+2069)
        # - Object replacement (U+FFFC), interlinear annotation (U+FFF9-U+FFFB)
        cleaned = re.sub(
            r'[\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff\ufffc\ufff9-\ufffb]',
            '', cleaned,
        )

        # Collapse internal whitespace runs and strip
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        if not cleaned:
            return None

        if len(cleaned) > SessionDB.MAX_TITLE_LENGTH:
            raise ValueError(
                f"Title too long ({len(cleaned)} chars, max {SessionDB.MAX_TITLE_LENGTH})"
            )

        return cleaned

    def set_session_title(self, session_id: str, title: str) -> bool:
        """Set or update a session's title.

        Returns True if session was found and title was set.
        Raises ValueError if title is already in use by another session,
        or if the title fails validation (too long, invalid characters).
        Empty/whitespace-only strings are normalized to None (clearing the title).
        """
        title = self.sanitize_title(title)
        def _do(conn):
            cursor = conn.execute(
                "SELECT source, user_id FROM sessions WHERE id = ?",
                (session_id,),
            )
            current = cursor.fetchone()
            if not current:
                return 0
            if title:
                # Check uniqueness within the same source/user namespace.
                cursor = conn.execute(
                    "SELECT id FROM sessions WHERE title = ? AND id != ? AND source = ? AND ((user_id IS NULL AND ? IS NULL) OR user_id = ?)",
                    (title, session_id, current["source"], current["user_id"], current["user_id"]),
                )
                conflict = cursor.fetchone()
                if conflict:
                    raise ValueError(f"Title '{title}' is already in use.")
            cursor = conn.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title, session_id),
            )
            return cursor.rowcount
        rowcount = self._execute_write(_do)
        return rowcount > 0

    def get_session_title(self, session_id: str) -> Optional[str]:
        """Get the title for a session, or None."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT title FROM sessions WHERE id = ?", (session_id,)
            )
            row = cursor.fetchone()
        return row["title"] if row else None

    def get_session_by_title(self, title: str, user_id: str = None, source: str = None) -> Optional[Dict[str, Any]]:
        """Look up a session by exact title. Returns session dict or None."""
        where = ["title = ?"]
        params: list[Any] = [title]
        if source is not None:
            where.append("source = ?")
            params.append(source)
        if user_id is not None:
            where.append("user_id = ?")
            params.append(user_id)
        with self._lock:
            cursor = self._conn.execute(
                f"SELECT * FROM sessions WHERE {' AND '.join(where)} ORDER BY started_at DESC",
                params,
            )
            rows = cursor.fetchall()
        if not rows:
            return None
        if user_id is None and source is None and len(rows) > 1:
            return None
        return dict(rows[0])

    def resolve_session_by_title(self, title: str, user_id: str = None, source: str = None) -> Optional[str]:
        """Resolve a title to a session ID, preferring the latest in a lineage.

        If the exact title exists, returns that session's ID.
        If not, searches for "title #N" variants and returns the latest one.
        If the exact title exists AND numbered variants exist, returns the
        latest numbered variant (the most recent continuation).
        """
        # First try exact match
        exact = self.get_session_by_title(title, user_id=user_id, source=source)

        # Also search for numbered variants: "title #2", "title #3", etc.
        # Escape SQL LIKE wildcards (%, _) in the title to prevent false matches
        escaped = title.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where = ["title LIKE ? ESCAPE '\\'"]
        params: list[Any] = [f"{escaped} #%"]
        if source is not None:
            where.append("source = ?")
            params.append(source)
        if user_id is not None:
            where.append("user_id = ?")
            params.append(user_id)
        with self._lock:
            cursor = self._conn.execute(
                "SELECT id, title, started_at FROM sessions "
                f"WHERE {' AND '.join(where)} ORDER BY started_at DESC",
                params,
            )
            numbered = cursor.fetchall()

        if numbered:
            # Return the most recent numbered variant
            return numbered[0]["id"]
        elif exact:
            return exact["id"]
        return None

    def get_next_title_in_lineage(
        self,
        base_title: str,
        *,
        source: str = None,
        user_id: str = None,
    ) -> str:
        """Generate the next title in a lineage (e.g., "my session" → "my session #2").

        Strips any existing " #N" suffix to find the base name, then finds
        the highest existing number and increments within the same source/user namespace.
        """
        match = re.match(r'^(.*?) #(\d+)$', base_title)
        base = match.group(1) if match else base_title

        escaped = base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where = ["(title = ? OR title LIKE ? ESCAPE '\\')"]
        params: list[Any] = [base, f"{escaped} #%"]
        if source is not None:
            where.append("source = ?")
            params.append(source)
        if user_id is not None:
            where.append("user_id = ?")
            params.append(user_id)
        with self._lock:
            cursor = self._conn.execute(
                f"SELECT title FROM sessions WHERE {' AND '.join(where)}",
                params,
            )
            titles = [row["title"] for row in cursor.fetchall() if row["title"]]

        if not titles:
            return base

        max_num = 1 if base in titles else 0
        pattern = re.compile(rf'^{re.escape(base)} #(\d+)$')
        for title in titles:
            m = pattern.match(title)
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"{base} #{max_num + 1}"

    def list_sessions_rich(
        self,
        source: str = None,
        exclude_sources: List[str] = None,
        limit: int = 20,
        offset: int = 0,
        include_children: bool = False,
        user_id: str = None,
    ) -> List[Dict[str, Any]]:
        """List sessions with preview (first user message) and last active timestamp.

        Returns dicts with keys: id, source, model, title, started_at, ended_at,
        message_count, preview (first 60 chars of first user message),
        last_active (timestamp of last message).

        Uses a single query with correlated subqueries instead of N+2 queries.

        By default, child sessions (subagent runs, compression continuations)
        are excluded.  Pass ``include_children=True`` to include them.
        """
        where_clauses = []
        params = []

        if not include_children:
            where_clauses.append("s.parent_session_id IS NULL")

        if source:
            where_clauses.append("s.source = ?")
            params.append(source)
        if exclude_sources:
            placeholders = ",".join("?" for _ in exclude_sources)
            where_clauses.append(f"s.source NOT IN ({placeholders})")
            params.extend(exclude_sources)
        if user_id is not None:
            where_clauses.append("s.user_id = ?")
            params.append(user_id)
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query = f"""
            SELECT s.*,
                COALESCE(
                    (SELECT SUBSTR(REPLACE(REPLACE(m.content, X'0A', ' '), X'0D', ' '), 1, 63)
                     FROM messages m
                     WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
                     ORDER BY m.timestamp, m.id LIMIT 1),
                    ''
                ) AS _preview_raw,
                COALESCE(
                    (SELECT MAX(m2.timestamp) FROM messages m2 WHERE m2.session_id = s.id),
                    s.started_at
                ) AS last_active
            FROM sessions s
            {where_sql}
            ORDER BY s.started_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        with self._lock:
            cursor = self._conn.execute(query, params)
            rows = cursor.fetchall()
        sessions = []
        for row in rows:
            s = dict(row)
            # Build the preview from the raw substring
            raw = s.pop("_preview_raw", "").strip()
            if raw:
                text = raw[:60]
                s["preview"] = text + ("..." if len(raw) > 60 else "")
            else:
                s["preview"] = ""
            sessions.append(s)

        return sessions

    # =========================================================================
    # Message storage
    # =========================================================================

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str = None,
        tool_name: str = None,
        tool_calls: Any = None,
        tool_call_id: str = None,
        token_count: int = None,
        finish_reason: str = None,
        reasoning: str = None,
        reasoning_details: Any = None,
        codex_reasoning_items: Any = None,
    ) -> int:
        """
        Append a message to a session. Returns the message row ID.

        Also increments the session's message_count (and tool_call_count
        if role is 'tool' or tool_calls is present).
        """
        # Serialize structured fields to JSON before entering the write txn
        reasoning_details_json = (
            json.dumps(reasoning_details)
            if reasoning_details else None
        )
        codex_items_json = (
            json.dumps(codex_reasoning_items)
            if codex_reasoning_items else None
        )
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None

        # Pre-compute tool call count
        num_tool_calls = 0
        if tool_calls is not None:
            num_tool_calls = len(tool_calls) if isinstance(tool_calls, list) else 1

        def _do(conn):
            cursor = conn.execute(
                """INSERT INTO messages (session_id, role, content, tool_call_id,
                   tool_calls, tool_name, timestamp, token_count, finish_reason,
                   reasoning, reasoning_details, codex_reasoning_items)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    role,
                    content,
                    tool_call_id,
                    tool_calls_json,
                    tool_name,
                    time.time(),
                    token_count,
                    finish_reason,
                    reasoning,
                    reasoning_details_json,
                    codex_items_json,
                ),
            )
            msg_id = cursor.lastrowid

            # Update counters
            if num_tool_calls > 0:
                conn.execute(
                    """UPDATE sessions SET message_count = message_count + 1,
                       tool_call_count = tool_call_count + ? WHERE id = ?""",
                    (num_tool_calls, session_id),
                )
            else:
                conn.execute(
                    "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
                    (session_id,),
                )
            return msg_id

        return self._execute_write(_do)

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Load all messages for a session, ordered by timestamp."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp, id",
                (session_id,),
            )
            rows = cursor.fetchall()
        result = []
        for row in rows:
            msg = dict(row)
            if msg.get("tool_calls"):
                try:
                    msg["tool_calls"] = json.loads(msg["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Failed to deserialize tool_calls in get_messages, falling back to []")
                    msg["tool_calls"] = []
            result.append(msg)
        return result

    def get_messages_as_conversation(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Load messages in the OpenAI conversation format (role + content dicts).
        Used by the gateway to restore conversation history.
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT role, content, tool_call_id, tool_calls, tool_name, "
                "reasoning, reasoning_details, codex_reasoning_items "
                "FROM messages WHERE session_id = ? ORDER BY timestamp, id",
                (session_id,),
            )
            rows = cursor.fetchall()
        messages = []
        for row in rows:
            msg = {"role": row["role"], "content": row["content"]}
            if row["tool_call_id"]:
                msg["tool_call_id"] = row["tool_call_id"]
            if row["tool_name"]:
                msg["tool_name"] = row["tool_name"]
            if row["tool_calls"]:
                try:
                    msg["tool_calls"] = json.loads(row["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Failed to deserialize tool_calls in conversation replay, falling back to []")
                    msg["tool_calls"] = []
            # Restore reasoning fields on assistant messages so providers
            # that replay reasoning (OpenRouter, OpenAI, Nous) receive
            # coherent multi-turn reasoning context.
            if row["role"] == "assistant":
                if row["reasoning"]:
                    msg["reasoning"] = row["reasoning"]
                if row["reasoning_details"]:
                    try:
                        msg["reasoning_details"] = json.loads(row["reasoning_details"])
                    except (json.JSONDecodeError, TypeError):
                        logger.warning("Failed to deserialize reasoning_details, falling back to None")
                        msg["reasoning_details"] = None
                if row["codex_reasoning_items"]:
                    try:
                        msg["codex_reasoning_items"] = json.loads(row["codex_reasoning_items"])
                    except (json.JSONDecodeError, TypeError):
                        logger.warning("Failed to deserialize codex_reasoning_items, falling back to None")
                        msg["codex_reasoning_items"] = None
            messages.append(msg)
        return messages

    @staticmethod
    def _decode_json_column(raw: Optional[str]) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to deserialize JSON column in SessionDB")
            return None

    def _runtime_signal_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "audit_id": row["audit_id"],
            "event_id": row["event_id"],
            "idempotency_key": row["idempotency_key"],
            "event_type": row["event_type"],
            "phase": row["phase"],
            "occurred_at": row["occurred_at"],
            "publisher": row["publisher"],
            "session_id": row["session_id"],
            "mission_id": row["mission_id"],
            "correlation_id": row["correlation_id"],
            "sequence_no": row["sequence_no"],
            "actor": self._decode_json_column(row["actor_json"]),
            "subject": self._decode_json_column(row["subject_json"]),
            "provenance": row["provenance"],
            "payload": self._decode_json_column(row["payload_json"]),
            "payload_bytes": row["payload_bytes"],
            "created_at": row["created_at"],
        }

    def append_runtime_signal_audit(self, signal: RuntimeSignal | Dict[str, Any]) -> int:
        """Persist one runtime-signal audit row and return its audit ID."""
        envelope = signal if isinstance(signal, RuntimeSignal) else RuntimeSignal.from_dict(signal)
        actor_json = json.dumps(envelope.actor.to_dict(), ensure_ascii=False, separators=(",", ":")) if envelope.actor else None
        subject_json = json.dumps(envelope.subject.to_dict(), ensure_ascii=False, separators=(",", ":")) if envelope.subject else None
        payload_json = json.dumps(envelope.payload, ensure_ascii=False, separators=(",", ":")) if envelope.payload is not None else None
        payload_bytes = len(payload_json.encode("utf-8")) if payload_json else 0

        def _do(conn):
            cursor = conn.execute(
                """INSERT OR IGNORE INTO runtime_signal_audit (
                   event_id, idempotency_key, event_type, phase, occurred_at, publisher,
                   session_id, mission_id, correlation_id, sequence_no, actor_json,
                   subject_json, provenance, payload_json, payload_bytes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    envelope.event_id,
                    envelope.idempotency_key,
                    envelope.event_type,
                    envelope.phase,
                    envelope.occurred_at,
                    envelope.publisher,
                    envelope.session_id,
                    envelope.mission_id,
                    envelope.correlation_id,
                    envelope.sequence_no,
                    actor_json,
                    subject_json,
                    envelope.provenance,
                    payload_json,
                    payload_bytes,
                    time.time(),
                ),
            )
            if cursor.rowcount == 0:
                existing = conn.execute(
                    "SELECT id FROM runtime_signal_audit WHERE event_id = ?",
                    (envelope.event_id,),
                ).fetchone()
                return existing["id"] if existing else 0
            return cursor.lastrowid

        return self._execute_write(_do)

    def get_runtime_signal_audit(self, audit_id: int) -> Optional[Dict[str, Any]]:
        """Load a persisted runtime-signal audit row by its integer ID."""
        with self._lock:
            row = self._conn.execute(
                """SELECT
                   id AS audit_id, event_id, idempotency_key, event_type, phase,
                   occurred_at, publisher, session_id, mission_id, correlation_id,
                   sequence_no, actor_json, subject_json, provenance, payload_json,
                   payload_bytes, created_at
                   FROM runtime_signal_audit WHERE id = ?""",
                (audit_id,),
            ).fetchone()
        return self._runtime_signal_row_to_dict(row) if row else None

    def list_runtime_signal_audit(
        self,
        *,
        session_id: str | None = None,
        event_type_prefix: str | None = None,
        correlation_id: str | None = None,
        after_audit_id: int | None = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List runtime-signal audit rows in durable insertion order."""
        where_clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            where_clauses.append("session_id = ?")
            params.append(session_id)
        if event_type_prefix is not None:
            where_clauses.append("event_type LIKE ?")
            params.append(f"{event_type_prefix}%")
        if correlation_id is not None:
            where_clauses.append("correlation_id = ?")
            params.append(correlation_id)
        if after_audit_id is not None:
            where_clauses.append("id > ?")
            params.append(after_audit_id)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(
                f"""SELECT
                    id AS audit_id, event_id, idempotency_key, event_type, phase,
                    occurred_at, publisher, session_id, mission_id, correlation_id,
                    sequence_no, actor_json, subject_json, provenance, payload_json,
                    payload_bytes, created_at
                    FROM runtime_signal_audit
                    {where_sql}
                    ORDER BY id ASC
                    LIMIT ?""",
                params,
            ).fetchall()
        return [self._runtime_signal_row_to_dict(row) for row in rows]


    # =========================================================================
    # Search
    # =========================================================================

    @staticmethod
    def _sanitize_fts5_query(query: str) -> str:
        """Sanitize user input for safe use in FTS5 MATCH queries.

        FTS5 has its own query syntax where characters like ``"``, ``(``, ``)``,
        ``+``, ``*``, ``{``, ``}`` and bare boolean operators (``AND``, ``OR``,
        ``NOT``) have special meaning.  Passing raw user input directly to
        MATCH can cause ``sqlite3.OperationalError``.

        Strategy:
        - Preserve properly paired quoted phrases (``"exact phrase"``)
        - Strip unmatched FTS5-special characters that would cause errors
        - Wrap unquoted hyphenated and dotted terms in quotes so FTS5
          matches them as exact phrases instead of splitting on the
          hyphen/dot (e.g. ``chat-send``, ``P2.2``, ``my-app.config.ts``)
        """
        # Step 1: Extract balanced double-quoted phrases and protect them
        # from further processing via numbered placeholders.
        _quoted_parts: list = []

        def _preserve_quoted(m: re.Match) -> str:
            _quoted_parts.append(m.group(0))
            return f"\x00Q{len(_quoted_parts) - 1}\x00"

        sanitized = re.sub(r'"[^"]*"', _preserve_quoted, query)

        # Step 2: Strip remaining (unmatched) FTS5-special characters
        sanitized = re.sub(r'[+{}()\"^]', " ", sanitized)

        # Step 3: Collapse repeated * (e.g. "***") into a single one,
        # and remove leading * (prefix-only needs at least one char before *)
        sanitized = re.sub(r"\*+", "*", sanitized)
        sanitized = re.sub(r"(^|\s)\*", r"\1", sanitized)

        # Step 4: Remove dangling boolean operators at start/end that would
        # cause syntax errors (e.g. "hello AND" or "OR world")
        sanitized = re.sub(r"(?i)^(AND|OR|NOT)\b\s*", "", sanitized.strip())
        sanitized = re.sub(r"(?i)\s+(AND|OR|NOT)\s*$", "", sanitized.strip())

        # Step 5: Wrap unquoted dotted and/or hyphenated terms in double
        # quotes.  FTS5's tokenizer splits on dots and hyphens, turning
        # ``chat-send`` into ``chat AND send`` and ``P2.2`` into ``p2 AND 2``.
        # Quoting preserves phrase semantics.  A single pass avoids the
        # double-quoting bug that would occur if dotted and hyphenated
        # patterns were applied sequentially (e.g. ``my-app.config``).
        sanitized = re.sub(r"\b(\w+(?:[.-]\w+)+)\b", r'"\1"', sanitized)

        # Step 6: Restore preserved quoted phrases
        for i, quoted in enumerate(_quoted_parts):
            sanitized = sanitized.replace(f"\x00Q{i}\x00", quoted)

        return sanitized.strip()


    @staticmethod
    def _contains_cjk(text: str) -> bool:
        """Check if text contains CJK (Chinese, Japanese, Korean) characters."""
        for ch in text:
            cp = ord(ch)
            if (0x4E00 <= cp <= 0x9FFF or    # CJK Unified Ideographs
                0x3400 <= cp <= 0x4DBF or    # CJK Extension A
                0x20000 <= cp <= 0x2A6DF or  # CJK Extension B
                0x3000 <= cp <= 0x303F or    # CJK Symbols
                0x3040 <= cp <= 0x309F or    # Hiragana
                0x30A0 <= cp <= 0x30FF or    # Katakana
                0xAC00 <= cp <= 0xD7AF):     # Hangul Syllables
                return True
        return False

    def search_messages(
        self,
        query: str,
        source_filter: List[str] = None,
        exclude_sources: List[str] = None,
        role_filter: List[str] = None,
        limit: int = 20,
        offset: int = 0,
        user_id: str = None,
    ) -> List[Dict[str, Any]]:
        """
        Full-text search across session messages using FTS5.

        Supports FTS5 query syntax:
          - Simple keywords: "docker deployment"
          - Phrases: '"exact phrase"'
          - Boolean: "docker OR kubernetes", "python NOT java"
          - Prefix: "deploy*"

        Returns matching messages with session metadata, content snippet,
        and surrounding context (1 message before and after the match).
        """
        if not query or not query.strip():
            return []

        query = self._sanitize_fts5_query(query)
        if not query:
            return []

        # Build WHERE clauses dynamically
        where_clauses = ["messages_fts MATCH ?"]
        params: list = [query]

        if source_filter is not None:
            source_placeholders = ",".join("?" for _ in source_filter)
            where_clauses.append(f"s.source IN ({source_placeholders})")
            params.extend(source_filter)

        if exclude_sources is not None:
            exclude_placeholders = ",".join("?" for _ in exclude_sources)
            where_clauses.append(f"s.source NOT IN ({exclude_placeholders})")
            params.extend(exclude_sources)

        if role_filter:
            role_placeholders = ",".join("?" for _ in role_filter)
            where_clauses.append(f"m.role IN ({role_placeholders})")
            params.extend(role_filter)
        if user_id is not None:
            where_clauses.append("s.user_id = ?")
            params.append(user_id)
        where_sql = " AND ".join(where_clauses)
        params.extend([limit, offset])

        sql = f"""
            SELECT
                m.id,
                m.session_id,
                m.role,
                snippet(messages_fts, 0, '>>>', '<<<', '...', 40) AS snippet,
                m.content,
                m.timestamp,
                m.tool_name,
                s.source,
                s.model,
                s.started_at AS session_started
            FROM messages_fts
            JOIN messages m ON m.id = messages_fts.rowid
            JOIN sessions s ON s.id = m.session_id
            WHERE {where_sql}
            ORDER BY rank
            LIMIT ? OFFSET ?
        """

        with self._lock:
            try:
                cursor = self._conn.execute(sql, params)
            except sqlite3.OperationalError:
                # FTS5 query syntax error despite sanitization — return empty
                # unless query contains CJK (fall back to LIKE below)
                if not self._contains_cjk(query):
                    return []
                matches = []
            else:
                matches = [dict(row) for row in cursor.fetchall()]

        # LIKE fallback for CJK queries: FTS5 default tokenizer splits CJK
        # characters individually, causing multi-character queries to fail.
        if not matches and self._contains_cjk(query):
            raw_query = query.strip('"').strip()
            like_where = ["m.content LIKE ?"]
            like_params: list = [f"%{raw_query}%"]
            if source_filter is not None:
                like_where.append(f"s.source IN ({','.join('?' for _ in source_filter)})")
                like_params.extend(source_filter)
            if exclude_sources is not None:
                like_where.append(f"s.source NOT IN ({','.join('?' for _ in exclude_sources)})")
                like_params.extend(exclude_sources)
            if role_filter:
                like_where.append(f"m.role IN ({','.join('?' for _ in role_filter)})")
                like_params.extend(role_filter)
            if user_id is not None:
                like_where.append("s.user_id = ?")
                like_params.append(user_id)
            like_sql = f"""
                SELECT m.id, m.session_id, m.role,
                       substr(m.content,
                              max(1, instr(m.content, ?) - 40),
                              120) AS snippet,
                       m.content, m.timestamp, m.tool_name,
                       s.source, s.model, s.started_at AS session_started
                FROM messages m
                JOIN sessions s ON s.id = m.session_id
                WHERE {' AND '.join(like_where)}
                ORDER BY m.timestamp DESC
                LIMIT ? OFFSET ?
            """
            like_params.extend([limit, offset])
            # instr() parameter goes first in the bound list
            like_params = [raw_query] + like_params
            with self._lock:
                like_cursor = self._conn.execute(like_sql, like_params)
                matches = [dict(row) for row in like_cursor.fetchall()]

        # Add surrounding context (1 message before + after each match).
        # Done outside the lock so we don't hold it across N sequential queries.
        for match in matches:
            try:
                with self._lock:
                    ctx_cursor = self._conn.execute(
                        """SELECT role, content FROM messages
                           WHERE session_id = ? AND id >= ? - 1 AND id <= ? + 1
                           ORDER BY id""",
                        (match["session_id"], match["id"], match["id"]),
                    )
                    context_msgs = [
                        {"role": r["role"], "content": (r["content"] or "")[:200]}
                        for r in ctx_cursor.fetchall()
                    ]
                match["context"] = context_msgs
            except Exception:
                match["context"] = []

        # Remove full content from result (snippet is enough, saves tokens)
        for match in matches:
            match.pop("content", None)

        return matches

    def search_sessions(
        self,
        source: str = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List sessions, optionally filtered by source."""
        with self._lock:
            if source:
                cursor = self._conn.execute(
                    "SELECT * FROM sessions WHERE source = ? ORDER BY started_at DESC LIMIT ? OFFSET ?",
                    (source, limit, offset),
                )
            else:
                cursor = self._conn.execute(
                    "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # Utility
    # =========================================================================

    def session_count(self, source: str = None) -> int:
        """Count sessions, optionally filtered by source."""
        with self._lock:
            if source:
                cursor = self._conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE source = ?", (source,)
                )
            else:
                cursor = self._conn.execute("SELECT COUNT(*) FROM sessions")
            return cursor.fetchone()[0]

    def message_count(self, session_id: str = None) -> int:
        """Count messages, optionally for a specific session."""
        with self._lock:
            if session_id:
                cursor = self._conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
                )
            else:
                cursor = self._conn.execute("SELECT COUNT(*) FROM messages")
            return cursor.fetchone()[0]

    # =========================================================================
    # Export and cleanup
    # =========================================================================

    def export_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Export a single session with all its messages as a dict."""
        session = self.get_session(session_id)
        if not session:
            return None
        messages = self.get_messages(session_id)
        return {**session, "messages": messages}

    def export_all(self, source: str = None) -> List[Dict[str, Any]]:
        """
        Export all sessions (with messages) as a list of dicts.
        Suitable for writing to a JSONL file for backup/analysis.
        """
        sessions = self.search_sessions(source=source, limit=100000)
        results = []
        for session in sessions:
            messages = self.get_messages(session["id"])
            results.append({**session, "messages": messages})
        return results

    def clear_messages(self, session_id: str) -> None:
        """Delete all messages for a session and reset its counters."""
        def _do(conn):
            conn.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
            conn.execute(
                "UPDATE sessions SET message_count = 0, tool_call_count = 0 WHERE id = ?",
                (session_id,),
            )
        self._execute_write(_do)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its messages.

        Child sessions are orphaned (parent_session_id set to NULL) rather
        than cascade-deleted, so they remain accessible independently.
        Returns True if the session was found and deleted.
        """
        def _do(conn):
            cursor = conn.execute(
                "SELECT attached_mission_id FROM sessions WHERE id = ?", (session_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return False
            attached_mission_id = row["attached_mission_id"]
            # Orphan child sessions so FK constraint is satisfied
            conn.execute(
                "UPDATE sessions SET parent_session_id = NULL "
                "WHERE parent_session_id = ?",
                (session_id,),
            )
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM runtime_signal_audit WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            if attached_mission_id:
                remaining = conn.execute(
                    "SELECT 1 FROM sessions WHERE attached_mission_id = ? LIMIT 1",
                    (attached_mission_id,),
                ).fetchone()
                if remaining is None:
                    conn.execute(
                        "UPDATE missions SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                        ("approved", time.time(), attached_mission_id, "active"),
                    )
            return True
        return self._execute_write(_do)

    def prune_sessions(self, older_than_days: int = 90, source: str = None) -> int:
        """Delete sessions older than N days. Returns count of deleted sessions.

        Only prunes ended sessions (not active ones).  Child sessions outside
        the prune window are orphaned (parent_session_id set to NULL) rather
        than cascade-deleted.
        """
        cutoff = time.time() - (older_than_days * 86400)

        def _do(conn):
            if source:
                cursor = conn.execute(
                    """SELECT id, attached_mission_id FROM sessions
                       WHERE started_at < ? AND ended_at IS NOT NULL AND source = ?""",
                    (cutoff, source),
                )
            else:
                cursor = conn.execute(
                    "SELECT id, attached_mission_id FROM sessions WHERE started_at < ? AND ended_at IS NOT NULL",
                    (cutoff,),
                )
            rows = cursor.fetchall()
            session_ids = {row["id"] for row in rows}

            if not session_ids:
                return 0

            mission_ids = {row["attached_mission_id"] for row in rows if row["attached_mission_id"]}

            # Orphan any sessions whose parent is about to be deleted
            placeholders = ",".join("?" * len(session_ids))
            conn.execute(
                f"UPDATE sessions SET parent_session_id = NULL "
                f"WHERE parent_session_id IN ({placeholders})",
                list(session_ids),
            )

            for sid in session_ids:
                conn.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
                conn.execute("DELETE FROM runtime_signal_audit WHERE session_id = ?", (sid,))
                conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))

            for mission_id in mission_ids:
                remaining = conn.execute(
                    "SELECT 1 FROM sessions WHERE attached_mission_id = ? LIMIT 1",
                    (mission_id,),
                ).fetchone()
                if remaining is None:
                    conn.execute(
                        "UPDATE missions SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                        ("approved", time.time(), mission_id, "active"),
                    )
            return len(session_ids)

        return self._execute_write(_do)
