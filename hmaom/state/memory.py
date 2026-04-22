"""HMAOM Three-Layer Memory Architecture.

Layer 1: Working Memory (in-context, current turn)
Layer 2: Session Memory (current conversation, JSON files)
Layer 3: Long-Term Memory (cross-session, SQLite + vector embeddings)
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from hmaom.config import StateConfig
from hmaom.protocol.schemas import AgentAddress, ContextSlice



class MemoryManager:
    """Manages the three-layer memory architecture.

    - L1: Working memory is ephemeral (stored in Python objects)
    - L2: Session memory is persisted per conversation
    - L3: Long-term memory uses SQLite with optional vector similarity
    """
    @staticmethod
    def _sanitize_id(session_id: str) -> str:
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', session_id)
        if len(sanitized) > 128:
            sanitized = sanitized[:128]
        return sanitized

    def __init__(self, config: Optional[StateConfig] = None) -> None:
        self.config = config or StateConfig()
        self._working: dict[str, Any] = {}
        self._db: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        vector_path = Path(self.config.vector_index_path)
        vector_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(vector_path), check_same_thread=False)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS long_term_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT,  -- JSON array of floats
                agent_harness TEXT,
                agent_name TEXT,
                created_at REAL NOT NULL,
                access_level TEXT DEFAULT 'shared',  -- private | shared | broadcast
                ttl_seconds INTEGER
            )
        """)
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_ltm_key ON long_term_memory(key)
        """)
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_ltm_agent ON long_term_memory(agent_harness)
        """)
        try:
            self._db.execute("ALTER TABLE long_term_memory ADD COLUMN ttl_seconds INTEGER")
            self._db.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
        self.prune_old_entries()

    # ── Layer 1: Working Memory ──

    def working_set(self, key: str, value: Any) -> None:
        """Set a value in working memory."""
        self._working[key] = {"value": value, "set_at": time.time()}

    def working_get(self, key: str) -> Any:
        """Get a value from working memory."""
        entry = self._working.get(key)
        return entry["value"] if entry else None

    def working_clear(self) -> None:
        """Clear all working memory."""
        self._working.clear()

    def working_slice(
        self,
        query: str,
        max_tokens: int = 5000,
    ) -> ContextSlice:
        """Create a context slice from working memory relevant to a query.

        Simple keyword matching; can be enhanced with embeddings.
        """
        relevant_parts: list[str] = []
        for key, entry in self._working.items():
            if any(term in key.lower() for term in query.lower().split()):
                relevant_parts.append(f"{key}: {json.dumps(entry['value'])}")

        content = "\n".join(relevant_parts)
        # Rough token estimate: ~4 chars per token
        token_estimate = len(content) // 4

        return ContextSlice(
            source_agent="working_memory",
            relevance_score=0.8 if relevant_parts else 0.0,
            content=content[:max_tokens * 4],  # Rough truncation
            memory_keys=list(self._working.keys()),
            token_estimate=min(token_estimate, max_tokens),
        )

    # ── Layer 2: Session Memory ──

    def session_save(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Save session memory to disk."""
        session_dir = Path(self.config.sqlite_path).parent / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / f"{self._sanitize_id(session_id)}.json"

        data = {
            "session_id": session_id,
            "saved_at": time.time(),
            "messages": messages,
            "metadata": metadata or {},
        }
        path.write_text(json.dumps(data, indent=2))
        return str(path)

    def session_load(self, session_id: str) -> Optional[dict[str, Any]]:
        """Load session memory from disk."""
        session_dir = Path(self.config.sqlite_path).parent / "sessions"
        path = session_dir / f"{self._sanitize_id(session_id)}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def session_list(self) -> list[str]:
        """List all saved session IDs."""
        session_dir = Path(self.config.sqlite_path).parent / "sessions"
        if not session_dir.exists():
            return []
        return [p.stem for p in session_dir.glob("*.json")]

    # ── Layer 3: Long-Term Memory ──

    def long_term_store(
        self,
        key: str,
        content: str,
        agent: Optional[AgentAddress] = None,
        embedding: Optional[list[float]] = None,
        access_level: str = "shared",
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Store a fact in long-term memory."""
        if self._db is None:
            return

        self._db.execute(
            """
            INSERT INTO long_term_memory
            (key, content, embedding, agent_harness, agent_name, created_at, access_level, ttl_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                content,
                json.dumps(embedding) if embedding else None,
                agent.harness if agent else None,
                agent.agent if agent else None,
                time.time(),
                access_level,
                ttl_seconds,
            ),
        )
        self._db.commit()
        self.prune_old_entries()

    def long_term_search(
        self,
        query: str,
        harness: Optional[str] = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search long-term memory.

        Currently uses simple keyword matching. Vector similarity can be
        added when an embedding provider is configured.
        """
        if self._db is None:
            return []

        terms = [f"%{term}%" for term in query.lower().split() if len(term) > 2]
        if not terms:
            return []

        # Build a simple OR query
        where_conditions = [" OR ".join(["content LIKE ?"] * len(terms))]
        params: list[Any] = list(terms)

        if harness is not None:
            where_conditions.append("agent_harness = ?")
            params.append(harness)

        where_clause = " AND ".join(f"({c})" for c in where_conditions)

        cursor = self._db.execute(
            f"""
            SELECT key, content, agent_harness, agent_name, created_at
            FROM long_term_memory
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params + [limit],
        )

        results: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            results.append({
                "key": row[0],
                "content": row[1],
                "harness": row[2],
                "agent": row[3],
            "created_at": row[4],
            })
        return results


    def prune_old_entries(self) -> int:
        """Remove expired long-term memory entries. Returns count removed."""
        if self._db is None:
            return 0
        now = time.time()
        try:
            cursor = self._db.execute(
                """
                DELETE FROM long_term_memory
                WHERE ttl_seconds IS NOT NULL AND created_at + ttl_seconds < ?
                """,
                (now,),
            )
            self._db.commit()
            return cursor.rowcount
        except sqlite3.OperationalError:
            return 0

    def compact_old_sessions(self, max_age_days: int = 7) -> int:
        """Summarize and archive old session files."""
        session_dir = Path(self.config.sqlite_path).parent / "sessions"
        if not session_dir.exists():
            return 0

        cutoff = time.time() - (max_age_days * 86400)
        compacted = 0

        for path in session_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                if data.get("saved_at", 0) < cutoff:
                    # Extract key facts and store in long-term memory
                    session_id = data.get("session_id", path.stem)
                    messages = data.get("messages", [])
                    summary = f"Session {session_id}: {len(messages)} messages"
                    self.long_term_store(
                        key=f"session-summary/{session_id}",
                        content=summary,
                        access_level="shared",
                    )
                    path.unlink()
                    compacted += 1
            except (json.JSONDecodeError, OSError):
                continue

        return compacted

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
