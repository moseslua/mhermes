"""Tests for SemanticCache."""

import tempfile
import time

import pytest

from hmaom.state.semantic_cache import SemanticCache


class TestSemanticCache:
    def test_cache_hit(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
            cache = SemanticCache(db_path=tmp.name, similarity_threshold=0.95)
            cache.store("hello world", {"answer": 42})
            result = cache.lookup("hello world")
            assert result == {"answer": 42}
            cache.close()

    def test_cache_miss(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
            cache = SemanticCache(db_path=tmp.name, similarity_threshold=0.95)
            result = cache.lookup("totally unrelated query")
            assert result is None
            cache.close()

    def test_ttl_expiry(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
            cache = SemanticCache(db_path=tmp.name, ttl_seconds=0)
            cache.store("hello world", {"answer": 42})
            time.sleep(0.1)
            result = cache.lookup("hello world")
            assert result is None
            cache.close()

    def test_per_user_isolation(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
            cache = SemanticCache(db_path=tmp.name)
            cache.store("hello world", {"answer": 42}, user_id="alice")
            cache.store("hello world", {"answer": 99}, user_id="bob")

            assert cache.lookup("hello world", user_id="alice") == {"answer": 42}
            assert cache.lookup("hello world", user_id="bob") == {"answer": 99}
            assert cache.lookup("hello world", user_id="charlie") is None
            cache.close()

    def test_similarity_threshold(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
            cache = SemanticCache(db_path=tmp.name, similarity_threshold=0.99)
            cache.store("hello world", {"answer": 42})
            # Same text should hit
            assert cache.lookup("hello world") == {"answer": 42}
            # Very different text should miss at high threshold
            assert cache.lookup("quantum physics") is None
            cache.close()

    def test_similar_queries_hit_at_low_threshold(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
            cache = SemanticCache(db_path=tmp.name, similarity_threshold=0.80)
            cache.store("hello world", {"answer": 42})
            # Same words in different order produce identical embedding
            result = cache.lookup("world hello")
            assert result == {"answer": 42}
            cache.close()

    def test_prune_expired(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
            cache = SemanticCache(db_path=tmp.name, ttl_seconds=0)
            cache.store("hello world", {"answer": 42})
            time.sleep(0.1)
            deleted = cache.prune_expired()
            assert deleted >= 1
            result = cache.lookup("hello world")
            assert result is None
            cache.close()

    def test_prune_returns_zero_when_nothing_expired(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
            cache = SemanticCache(db_path=tmp.name, ttl_seconds=3600)
            cache.store("hello world", {"answer": 42})
            deleted = cache.prune_expired()
            assert deleted == 0
            cache.close()

    def test_embedding_is_deterministic(self):
        cache = SemanticCache(db_path=":memory:")
        e1 = cache._embed("hello world")
        e2 = cache._embed("hello world")
        assert e1 == e2
        cache.close()

    def test_cosine_similarity_identical(self):
        cache = SemanticCache(db_path=":memory:")
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert cache._cosine_similarity(a, b) == pytest.approx(1.0)
        cache.close()

    def test_cosine_similarity_orthogonal(self):
        cache = SemanticCache(db_path=":memory:")
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cache._cosine_similarity(a, b) == pytest.approx(0.0)
        cache.close()

    def test_max_entries_prunes_oldest(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
            # Set a very low max entries for testing
            original_max = SemanticCache.MAX_ENTRIES
            SemanticCache.MAX_ENTRIES = 3
            try:
                cache = SemanticCache(db_path=tmp.name)
                cache.store("query1", {"answer": 1})
                cache.store("query2", {"answer": 2})
                cache.store("query3", {"answer": 3})
                cache.store("query4", {"answer": 4})

                # query1 should have been pruned
                assert cache.lookup("query1") is None
                assert cache.lookup("query2") == {"answer": 2}
                assert cache.lookup("query3") == {"answer": 3}
                assert cache.lookup("query4") == {"answer": 4}
            finally:
                SemanticCache.MAX_ENTRIES = original_max
                cache.close()