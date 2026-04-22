import copy
import time
from contextlib import contextmanager
from unittest.mock import patch

from agent.memory_manager import MemoryManager
from agent.memory_provider import MemoryProvider
from agent.shared_memory import SharedMemoryService
from hermes_state import SessionDB
from tools.memory_tool import MemoryStore


class _FakeMemoryProvider(MemoryProvider):
    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id, **kwargs):
        pass

    def system_prompt_block(self) -> str:
        return ""

    def prefetch(self, query, *, session_id=""):
        return ""

    def sync_turn(self, user_content, assistant_content, *, session_id=""):
        pass

    def get_tool_schemas(self):
        return []

    def handle_tool_call(self, tool_name, args, **kwargs):
        raise AssertionError("not used in shared-memory tests")


def _make_store(tmp_path, monkeypatch) -> MemoryStore:
    memory_dir = tmp_path / "memories"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("kept at load", encoding="utf-8")
    (memory_dir / "USER.md").write_text("prefers concise answers", encoding="utf-8")
    monkeypatch.setattr("tools.memory_tool.get_memory_dir", lambda: memory_dir)
    store = MemoryStore(memory_char_limit=500, user_char_limit=300)
    store.load_from_disk()
    return store


def test_build_shared_memory_uses_canonical_sources_without_mutation(tmp_path, monkeypatch):
    store = _make_store(tmp_path, monkeypatch)
    store.add("memory", "learned after snapshot")

    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        db.create_session("recent", "cli")
        db.append_message("recent", role="user", content="Discussed canonical shared memory")
        db.append_message("recent", role="assistant", content="Kept reads on canonical files only")

        before_messages = copy.deepcopy(db.get_messages_as_conversation("recent"))
        before_snapshot = store.format_for_system_prompt("memory")

        service = SharedMemoryService(memory_store=store, session_db=db, source="cli")
        payload = service.build_shared_memory(history_limit=5)

        curated_memory = payload["curated_memory"]["memory"]
        assert curated_memory["entries"] == ["kept at load", "learned after snapshot"]
        assert curated_memory["snapshot"] == before_snapshot
        assert "learned after snapshot" not in curated_memory["snapshot"]
        assert payload["provider_status"]["has_external_provider"] is False
        assert payload["history"]["mode"] == "recent"
        assert payload["history"]["results"][0]["session_id"] == "recent"

        after_messages = db.get_messages_as_conversation("recent")
        assert after_messages == before_messages
        assert store.format_for_system_prompt("memory") == before_snapshot
    finally:
        db.close()


def test_search_history_resolves_child_sessions_to_parent_lineage(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        db.create_session("parent", "cli")
        db.create_session("child", "cli", parent_session_id="parent")
        db.append_message("child", role="user", content="delegated needle lives here")
        db.append_message("child", role="assistant", content="child detail")

        service = SharedMemoryService(session_db=db, source="cli", current_session_id="other")
        results = service.search_history("needle", limit=5)

        assert results["count"] == 1
        match = results["results"][0]
        assert match["session_id"] == "parent"
        assert match["lineage_root_session_id"] == "parent"
        assert match["matched_session_ids"] == ["child"]
        assert match["matches"][0]["source_session_id"] == "child"
        assert "needle" in match["matches"][0]["snippet"].lower()
    finally:
        db.close()


def test_search_history_skips_current_lineage_even_when_it_saturates_matches(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        db.create_session("current-root", "cli")
        db.create_session("current-child", "cli", parent_session_id="current-root")
        for _ in range(60):
            db.append_message("current-child", role="user", content="needle in current lineage")
        db.create_session("other", "cli")
        db.append_message("other", role="user", content="needle in another session")

        service = SharedMemoryService(
            session_db=db,
            source="cli",
            current_session_id="current-child",
        )
        results = service.search_history("needle", limit=1)

        assert results["count"] == 1
        assert results["results"][0]["session_id"] == "other"
    finally:
        db.close()


def test_provider_status_preserves_one_external_provider_invariant():
    manager = MemoryManager()
    manager.add_provider(_FakeMemoryProvider("builtin"))
    manager.add_provider(_FakeMemoryProvider("mem0"))
    manager.add_provider(_FakeMemoryProvider("hindsight"))

    service = SharedMemoryService(memory_manager=manager)
    provider_status = service.build_shared_memory()["provider_status"]

    assert provider_status == {
        "active": True,
        "provider_count": 2,
        "provider_names": ["builtin", "mem0"],
        "external_provider_name": "mem0",
        "external_provider_count": 1,
        "has_external_provider": True,
    }


@contextmanager
def _patched_run_agent_runtime():
    import importlib
    import sys
    import types
    from unittest.mock import MagicMock

    fake_openai = types.SimpleNamespace(OpenAI=MagicMock())
    fake_fire = types.SimpleNamespace(Fire=MagicMock())
    fake_dotenv = types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None)
    fake_auxiliary_client = types.SimpleNamespace(
        _validate_base_url=lambda url: url,
        _validate_proxy_env_urls=lambda: None,
        call_llm=MagicMock(),
        async_call_llm=MagicMock(),
        extract_content_or_reasoning=lambda response: "",
        resolve_provider_client=lambda *args, **kwargs: (None, None),
    )
    with patch.dict(
        sys.modules,
        {
            "openai": fake_openai,
            "fire": fake_fire,
            "dotenv": fake_dotenv,
            "agent.auxiliary_client": fake_auxiliary_client,
        },
    ):
        if "run_agent" in sys.modules:
            module = importlib.reload(sys.modules["run_agent"])
        else:
            module = importlib.import_module("run_agent")
        yield module


def test_run_agent_initializes_shared_memory_service(tmp_path, monkeypatch):
    cfg = {
        "memory": {
            "memory_enabled": True,
            "user_profile_enabled": False,
            "provider": "",
        },
        "agent": {},
    }
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    with _patched_run_agent_runtime() as run_agent_module, \
         patch("hermes_cli.config.load_config", return_value=cfg), \
         patch("agent.model_metadata.get_model_context_length", return_value=204_800), \
         patch.object(run_agent_module, "get_tool_definitions", return_value=[]), \
         patch.object(run_agent_module, "check_toolset_requirements", return_value={}):
        AIAgent = run_agent_module.AIAgent

        agent = AIAgent(
            api_key="test-key-1234567890",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=False,
        )
    assert isinstance(agent._shared_memory_service, SharedMemoryService)
    assert agent._shared_memory_service.get_curated_memory()["memory"]["path"].endswith("MEMORY.md")

def test_run_agent_shared_memory_reports_builtin_plus_external_provider(tmp_path, monkeypatch):
    cfg = {
        "memory": {
            "memory_enabled": True,
            "user_profile_enabled": False,
            "provider": "mem0",
        },
        "agent": {},
    }
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    with _patched_run_agent_runtime() as run_agent_module, \
         patch("hermes_cli.config.load_config", return_value=cfg), \
         patch("agent.model_metadata.get_model_context_length", return_value=204_800), \
         patch.object(run_agent_module, "get_tool_definitions", return_value=[]), \
         patch.object(run_agent_module, "check_toolset_requirements", return_value={}), \
         patch("plugins.memory.load_memory_provider", return_value=_FakeMemoryProvider("mem0")):
        AIAgent = run_agent_module.AIAgent

        agent = AIAgent(
            api_key="test-key-1234567890",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=False,
        )
    provider_status = agent._shared_memory_service.build_shared_memory()["provider_status"]
    assert provider_status["provider_names"] == ["builtin", "mem0"]
    assert provider_status["provider_count"] == 2
    assert provider_status["external_provider_name"] == "mem0"


def test_curated_memory_reloads_live_disk_state_across_store_instances(tmp_path, monkeypatch):
    first_store = _make_store(tmp_path, monkeypatch)
    second_store = MemoryStore(memory_char_limit=500, user_char_limit=300)
    second_store.load_from_disk()

    snapshot_before = first_store.format_for_system_prompt("memory")
    second_store.add("memory", "written by another session")

    service = SharedMemoryService(memory_store=first_store)
    curated_memory = service.get_curated_memory()["memory"]

    assert curated_memory["entries"] == ["kept at load", "written by another session"]
    assert curated_memory["snapshot"] == snapshot_before
    assert "written by another session" not in snapshot_before


def test_shared_memory_service_handles_missing_dependencies_and_blank_query():
    service = SharedMemoryService()

    payload = service.build_shared_memory(history_query="   ", history_limit=3)

    assert payload["curated_memory"]["memory"]["entries"] == []
    assert payload["curated_memory"]["memory"]["path"] is None
    assert payload["provider_status"]["has_external_provider"] is False
    assert payload["history"] == {
        "mode": "recent",
        "canonical_sources": ["sqlite.sessions", "sqlite.messages"],
        "results": [],
        "count": 0,
        "limit": 3,
    }



def test_recent_history_rolls_child_activity_up_to_parent_lineage(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        db.create_session("parent-a", "cli")
        db.append_message("parent-a", role="user", content="older root")
        db.create_session("child-a", "cli", parent_session_id="parent-a")
        db.append_message("child-a", role="user", content="child started long ago")
        time.sleep(0.01)
        db.create_session("parent-b", "cli")
        db.append_message("parent-b", role="user", content="newer unrelated root")
        time.sleep(0.01)
        db.append_message("child-a", role="user", content="fresh child activity")

        service = SharedMemoryService(session_db=db, source="cli")
        recent = service.list_recent_history(limit=1)

        assert recent["results"][0]["session_id"] == "parent-a"
        assert recent["results"][0]["preview"] == "fresh child activity"
        assert recent["results"][0]["message_count"] == 3
    finally:
        db.close()


def test_recent_history_does_not_drop_old_parent_with_new_child_activity(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        db.create_session("parent-a", "cli")
        db.create_session("child-a", "cli", parent_session_id="parent-a")
        for index in range(60):
            db.create_session(f"root-{index}", "cli")
            db.append_message(f"root-{index}", role="user", content=f"root {index}")
        time.sleep(0.01)
        db.append_message("child-a", role="user", content="lineage woke up last")

        service = SharedMemoryService(session_db=db, source="cli")
        recent = service.list_recent_history(limit=1)

        assert recent["results"][0]["session_id"] == "parent-a"
        assert recent["results"][0]["preview"] == "lineage woke up last"
    finally:
        db.close()


def test_recent_history_pages_past_current_lineage_saturation():
    class PagingRecentDB:
        def list_sessions_rich(self, **kwargs):
            offset = kwargs["offset"]
            limit = kwargs["limit"]
            if offset == 0:
                return [
                    {
                        "id": f"child-{idx}",
                        "parent_session_id": "current-root",
                        "source": "cli",
                        "started_at": float(idx),
                        "last_active": float(idx),
                        "message_count": 1,
                        "preview": f"child {idx}",
                    }
                    for idx in range(limit)
                ]
            if offset == limit:
                return [{
                    "id": "other-root",
                    "parent_session_id": None,
                    "source": "cli",
                    "started_at": 999999.0,
                    "last_active": 999999.0,
                    "message_count": 1,
                    "preview": "other root",
                }]
            return []

        def get_session(self, session_id):
            if session_id.startswith("child-") or session_id == "current-child":
                return {"id": session_id, "parent_session_id": "current-root", "source": "cli"}
            if session_id == "current-root":
                return {"id": "current-root", "parent_session_id": None, "source": "cli", "started_at": 0.0}
            if session_id == "other-root":
                return {"id": "other-root", "parent_session_id": None, "source": "cli", "started_at": 999999.0}
            return None

        def get_messages(self, session_id):
            return [{"content": f"preview for {session_id}"}]

    service = SharedMemoryService(
        session_db=PagingRecentDB(),
        source="cli",
        current_session_id="current-child",
    )
    recent = service.list_recent_history(limit=1)

    assert recent["count"] == 1
    assert recent["results"][0]["session_id"] == "other-root"


def test_search_history_pages_past_current_lineage_saturation():
    class PagingSearchDB:
        def search_messages(self, **kwargs):
            offset = kwargs["offset"]
            limit = kwargs["limit"]
            if offset == 0:
                return [
                    {
                        "id": idx,
                        "session_id": f"child-{idx}",
                        "role": "user",
                        "snippet": "needle current",
                        "timestamp": float(idx),
                        "tool_name": None,
                        "context": [],
                    }
                    for idx in range(limit)
                ]
            if offset == limit:
                return [{
                    "id": limit + 1,
                    "session_id": "other-root",
                    "role": "user",
                    "snippet": "needle other",
                    "timestamp": 999999.0,
                    "tool_name": None,
                    "context": [],
                }]
            return []

        def get_session(self, session_id):
            if session_id.startswith("child-") or session_id == "current-child":
                return {"id": session_id, "parent_session_id": "current-root", "source": "cli"}
            if session_id == "current-root":
                return {"id": "current-root", "parent_session_id": None, "source": "cli"}
            if session_id == "other-root":
                return {"id": "other-root", "parent_session_id": None, "source": "cli", "started_at": 999999.0}
            return None

    service = SharedMemoryService(
        session_db=PagingSearchDB(),
        source="cli",
        current_session_id="current-child",
    )
    results = service.search_history("needle", limit=1)

    assert results["count"] == 1
    assert results["results"][0]["session_id"] == "other-root"