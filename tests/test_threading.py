"""Tests for the HMAOM Cross-Session Thread Manager."""

from __future__ import annotations

import time

import pytest

from hmaom.config import ThreadingConfig
from hmaom.protocol.schemas import TaskDescription
from hmaom.state.threading import ThreadContext, ThreadManager, _extract_keywords, _jaccard_similarity


class TestKeywordSimilarity:
    def test_jaccard_identical_sets(self):
        assert _jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_jaccard_no_overlap(self):
        assert _jaccard_similarity({"a"}, {"b"}) == 0.0

    def test_jaccard_partial_overlap(self):
        assert _jaccard_similarity({"a", "b", "c"}, {"a", "b", "d"}) == 0.5

    def test_jaccard_empty_both(self):
        assert _jaccard_similarity(set(), set()) == 1.0

    def test_extract_keywords_basic(self):
        assert _extract_keywords("Hello world!") == {"hello", "world"}

    def test_extract_keywords_filters_short(self):
        assert _extract_keywords("a bb ccc") == {"ccc"}

    def test_extract_keywords_strips_punctuation(self):
        assert _extract_keywords("foo, bar; baz!") == {"foo", "bar", "baz"}


class TestThreadManagerCreate:
    def test_create_thread_returns_uuid(self):
        tm = ThreadManager()
        tid = tm.create_thread("user_1", "session_1")
        assert isinstance(tid, str)
        assert len(tid) > 0

    def test_create_thread_tracks_user(self):
        tm = ThreadManager()
        tid = tm.create_thread("user_1", "session_1")
        ctx = tm.get_thread_context(tid)
        assert ctx.user_id == "user_1"
        assert ctx.sessions == ["session_1"]

    def test_create_thread_deduped_sessions(self):
        tm = ThreadManager()
        tid = tm.create_thread("user_1", "session_1")
        tm.add_to_thread(tid, "session_2")
        tm.add_to_thread(tid, "session_1")  # duplicate
        ctx = tm.get_thread_context(tid)
        assert ctx.sessions == ["session_1", "session_2"]


class TestThreadManagerAddToThread:
    def test_add_result_to_thread(self):
        tm = ThreadManager()
        tid = tm.create_thread("user_1", "session_1")
        tm.add_to_thread(tid, "session_2", {"text": "result A"})
        ctx = tm.get_thread_context(tid)
        assert len(ctx.unresolved_tasks) == 1
        assert ctx.unresolved_tasks[0]["text"] == "result A"

    def test_add_to_nonexistent_thread_raises(self):
        tm = ThreadManager()
        with pytest.raises(ValueError):
            tm.add_to_thread("nonexistent", "session_x")


class TestThreadManagerFindBySimilarity:
    def test_find_thread_by_keyword_similarity(self):
        tm = ThreadManager(ThreadingConfig(similarity_threshold=0.1))
        tid = tm.create_thread("user_1", "session_1")
        tm.add_to_thread(tid, "session_2", {"text": "optimize portfolio risk using black scholes"})

        found = tm.find_thread("user_1", ["portfolio risk optimization"])
        assert found == tid

    def test_find_thread_no_match_below_threshold(self):
        tm = ThreadManager(ThreadingConfig(similarity_threshold=0.9))
        tid = tm.create_thread("user_1", "session_1")
        tm.add_to_thread(tid, "session_2", {"text": "optimize portfolio"})

        found = tm.find_thread("user_1", ["quantum physics simulation"])
        assert found is None

    def test_find_thread_isolates_users(self):
        tm = ThreadManager(ThreadingConfig(similarity_threshold=0.1))
        tid_a = tm.create_thread("user_a", "session_1")
        tm.add_to_thread(tid_a, "session_2", {"text": "machine learning models"})

        found = tm.find_thread("user_b", ["machine learning models"])
        assert found is None

    def test_find_thread_no_threads_for_user(self):
        tm = ThreadManager()
        assert tm.find_thread("unknown_user", ["anything"]) is None

    def test_find_thread_empty_unresolved_tasks(self):
        tm = ThreadManager(ThreadingConfig(similarity_threshold=0.1))
        tid = tm.create_thread("user_1", "session_1")
        # No unresolved tasks added
        found = tm.find_thread("user_1", ["portfolio"])
        assert found is None

    def test_find_thread_multiple_candidates_best_match(self):
        tm = ThreadManager(ThreadingConfig(similarity_threshold=0.0))
        tid1 = tm.create_thread("user_1", "session_1")
        tm.add_to_thread(tid1, "session_2", {"text": "apple banana cherry"})
        tid2 = tm.create_thread("user_1", "session_3")
        tm.add_to_thread(tid2, "session_4", {"text": "apple banana date elderberry"})

        found = tm.find_thread("user_1", ["apple banana date"])
        assert found == tid2


class TestThreadManagerInjectContext:
    def test_inject_context_prepends_unresolved(self):
        tm = ThreadManager()
        tid = tm.create_thread("user_1", "session_1")
        tm.add_to_thread(tid, "session_2", {"text": "previous task about risk"})

        task = TaskDescription(title="new", description="calculate volatility")
        injected = tm.inject_context(tid, task)
        assert "Unresolved thread context:" in injected.description
        assert "previous task about risk" in injected.description
        assert "calculate volatility" in injected.description

    def test_inject_context_includes_preferences(self):
        tm = ThreadManager()
        tid = tm.create_thread("user_1", "session_1")
        ctx = tm.get_thread_context(tid)
        ctx.preferences = {"language": "en", "detail": "high"}

        task = TaskDescription(title="new", description="do something")
        injected = tm.inject_context(tid, task)
        assert "User preferences:" in injected.description
        assert "language" in injected.description

    def test_inject_context_no_changes_for_missing_thread(self):
        tm = ThreadManager()
        task = TaskDescription(title="new", description="do something")
        result = tm.inject_context("missing", task)
        assert result.description == "do something"

    def test_inject_context_empty_context_returns_original(self):
        tm = ThreadManager()
        tid = tm.create_thread("user_1", "session_1")
        task = TaskDescription(title="new", description="do something")
        result = tm.inject_context(tid, task)
        assert result.description == "do something"


class TestThreadManagerPruneInactive:
    def test_prune_removes_old_threads(self):
        tm = ThreadManager()
        tid = tm.create_thread("user_1", "session_1")
        # Backdate last_active
        tm._threads[tid].last_active = time.time() - (10 * 86400)
        pruned = tm.prune_inactive(days=7)
        assert pruned == 1
        assert tm.thread_count() == 0

    def test_prune_keeps_recent_threads(self):
        tm = ThreadManager()
        tid = tm.create_thread("user_1", "session_1")
        pruned = tm.prune_inactive(days=7)
        assert pruned == 0
        assert tm.thread_count() == 1

    def test_prune_cleans_user_index(self):
        tm = ThreadManager()
        tid = tm.create_thread("user_1", "session_1")
        tm._threads[tid].last_active = time.time() - (30 * 86400)
        tm.prune_inactive(days=7)
        assert "user_1" not in tm._user_threads

    def test_prune_partial_cleanup(self):
        tm = ThreadManager()
        old_tid = tm.create_thread("user_1", "session_1")
        tm._threads[old_tid].last_active = time.time() - (30 * 86400)
        new_tid = tm.create_thread("user_1", "session_2")

        pruned = tm.prune_inactive(days=7)
        assert pruned == 1
        assert tm.thread_count() == 1
        assert new_tid in tm._threads


class TestThreadManagerMultiUserIsolation:
    def test_users_cannot_see_each_other_threads(self):
        tm = ThreadManager()
        tid_a = tm.create_thread("alice", "s1")
        tid_b = tm.create_thread("bob", "s2")

        alice_threads = tm.list_threads_for_user("alice")
        bob_threads = tm.list_threads_for_user("bob")

        assert len(alice_threads) == 1
        assert alice_threads[0].thread_id == tid_a
        assert len(bob_threads) == 1
        assert bob_threads[0].thread_id == tid_b

    def test_thread_count_accurate(self):
        tm = ThreadManager()
        assert tm.thread_count() == 0
        tm.create_thread("alice", "s1")
        assert tm.thread_count() == 1
        tm.create_thread("bob", "s2")
        assert tm.thread_count() == 2
