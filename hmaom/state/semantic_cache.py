"""Semantic query cache with keyword-hash embeddings."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Optional


class SemanticCache:
    """SQLite-backed semantic cache using keyword-hash embeddings.

    Avoids external dependencies (no sentence-transformers) by computing
    a deterministic embedding from sorted word hashes.
    """

    MAX_ENTRIES = 10000

    def __init__(
        self,
        db_path: Optional[str] = None,
        similarity_threshold: float = 0.95,
        ttl_seconds: int = 3600,
    ) -> None:
        self.similarity_threshold = similarity_threshold
        self.ttl_seconds = ttl_seconds

        if db_path is None:
            db_path = str(Path.home() / ".hmaom" / "state" / "semantic_cache.sqlite")
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_hash TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT 'default',
                created_at REAL NOT NULL,
                ttl REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_user ON cache_entries(user_id)"
        )
        self._conn.commit()

    def _embed(self, text: str) -> list[float]:
        """Keyword-hash fallback embedding.

        Splits text into words, sorts them, hashes each word, and returns
        a fixed-length vector of normalised hash values.
        """
        words = sorted(set(text.lower().split()))
        vector_size = 128
        vector = [0.0] * vector_size
        for i, word in enumerate(words):
            digest = hashlib.sha256(word.encode()).hexdigest()
            # Spread the hex digest across the vector deterministically
            for j in range(vector_size):
                hex_start = (j * 2) % 64
                hex_val = int(digest[hex_start : hex_start + 2], 16)
                vector[j] += hex_val * (1.0 if i % 2 == 0 else -1.0)
        # Normalise to unit length
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        return dot  # already normalised

    def lookup(self, text: str, user_id: str = "default") -> Optional[dict]:
        """Return the cached result for a semantically similar query, or None."""
        embedding = self._embed(text)
        now = time.time()

        cursor = self._conn.execute(
            "SELECT embedding_json, result_json, created_at, ttl FROM cache_entries WHERE user_id = ? ORDER BY created_at DESC LIMIT 100",
            (user_id,),
        )

        best_match: Optional[dict] = None
        best_score = 0.0

        for row in cursor.fetchall():
            emb_json, result_json, created_at, ttl = row
            if now > created_at + ttl:
                continue
            stored_emb = json.loads(emb_json)
            score = self._cosine_similarity(embedding, stored_emb)
            if score > best_score and score >= self.similarity_threshold:
                best_score = score
                best_match = json.loads(result_json)

        return best_match

    def store(self, text: str, result: dict, user_id: str = "default") -> None:
        """Save a query, its embedding, and the result to the cache."""
        embedding = self._embed(text)
        query_hash = hashlib.sha256(text.encode()).hexdigest()
        now = time.time()

        self._conn.execute(
            "INSERT INTO cache_entries (query_hash, embedding_json, result_json, user_id, created_at, ttl) VALUES (?, ?, ?, ?, ?, ?)",
            (
                query_hash,
                json.dumps(embedding),
                json.dumps(result),
                user_id,
                now,
                self.ttl_seconds,
            ),
        )
        self._conn.commit()

        # Prune oldest entries if over limit
        count = self._conn.execute(
            "SELECT COUNT(*) FROM cache_entries"
        ).fetchone()[0]
        if count > self.MAX_ENTRIES:
            self._conn.execute(
                """
                DELETE FROM cache_entries WHERE id IN (
                    SELECT id FROM cache_entries ORDER BY created_at ASC LIMIT ?
                )
                """,
                (count - self.MAX_ENTRIES,),
            )
            self._conn.commit()

    def prune_expired(self) -> int:
        """Remove TTL-expired entries. Returns the number of rows deleted."""
        now = time.time()
        cursor = self._conn.execute(
            "DELETE FROM cache_entries WHERE created_at + ttl < ?",
            (now,),
        )
        self._conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        self._conn.close()
