from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.memory_manager import MemoryManager
    from hermes_state import SessionDB
    from tools.memory_tool import MemoryStore


_HIDDEN_SESSION_SOURCES = ("tool",)


class SharedMemoryService:
    """Read-only view over canonical curated memory and session history.

    Canonical inputs are limited to the built-in curated memory files
    (``MEMORY.md`` / ``USER.md``) and the SQLite session database. Derived
    projections and LLM summaries are intentionally excluded.
    """

    def __init__(
        self,
        *,
        memory_store: MemoryStore | None = None,
        memory_manager: MemoryManager | None = None,
        session_db: SessionDB | None = None,
        current_session_id: str | None = None,
        user_id: str | None = None,
        source: str | None = None,
        hidden_sources: Iterable[str] = _HIDDEN_SESSION_SOURCES,
    ) -> None:
        self._memory_store = memory_store
        self._memory_manager = memory_manager
        self._session_db = session_db
        self._current_session_id = current_session_id
        self._user_id = user_id
        self._source = source
        self._hidden_sources = tuple(hidden_sources)

    def get_curated_memory(self) -> dict[str, Any]:
        return {
            "canonical_sources": ["MEMORY.md", "USER.md"],
            "memory": self._get_target_state("memory"),
            "user": self._get_target_state("user"),
        }

    def list_recent_history(
        self,
        *,
        limit: int = 10,
        current_session_id: str | None = None,
    ) -> dict[str, Any]:
        if self._session_db is None:
            return self._empty_history("recent", limit)

        effective_limit = max(1, int(limit))
        current_root = self._resolve_to_root_session_id(
            current_session_id or self._current_session_id
        )
        batch_size = max(200, effective_limit * 20)
        offset = 0
        lineages: dict[str, dict[str, Any]] = {}
        while True:
            sessions = self._session_db.list_sessions_rich(
                source=self._source,
                limit=batch_size,
                offset=offset,
                exclude_sources=list(self._hidden_sources),
                include_children=True,
                user_id=self._user_id,
            )
            if not sessions:
                break
            for session in sessions:
                session_id = session.get("id")
                if not session_id:
                    continue
                root_session_id = self._resolve_to_root_session_id(session_id) or session_id
                if current_root and root_session_id == current_root:
                    continue
                if current_session_id and session_id == current_session_id:
                    continue
                if root_session_id not in lineages:
                    root_session = (
                        session
                        if session_id == root_session_id
                        else (self._session_db.get_session(root_session_id) or {})
                    )
                    lineages[root_session_id] = {
                        "session_id": root_session_id,
                        "lineage_root_session_id": root_session_id,
                        "title": root_session.get("title") or None,
                        "source": root_session.get("source") or session.get("source"),
                        "started_at": root_session.get("started_at") or session.get("started_at"),
                        "last_active": session.get("last_active"),
                        "message_count": 0,
                        "preview": self._latest_message_preview(session_id) or session.get("preview", ""),
                    }
                lineage = lineages[root_session_id]
                lineage["message_count"] += int(session.get("message_count") or 0)
                if self._activity_sort_key(session.get("last_active")) >= self._activity_sort_key(
                    lineage.get("last_active")
                ):
                    lineage["last_active"] = session.get("last_active")
                    lineage["preview"] = self._latest_message_preview(session_id) or session.get(
                        "preview", ""
                    )
            if len(sessions) < batch_size:
                break
            offset += batch_size
        results = sorted(
            lineages.values(),
            key=lambda record: (
                self._activity_sort_key(record.get("last_active")),
                self._activity_sort_key(record.get("started_at")),
            ),
            reverse=True,
        )[:effective_limit]

        return {
            "mode": "recent",
            "canonical_sources": ["sqlite.sessions", "sqlite.messages"],
            "results": results,
            "count": len(results),
            "limit": effective_limit,
        }

    def search_history(
        self,
        query: str,
        *,
        role_filter: str | list[str] | tuple[str, ...] | None = None,
        limit: int = 5,
        current_session_id: str | None = None,
    ) -> dict[str, Any]:
        if self._session_db is None:
            return self._empty_history("search", limit, query=query)

        clean_query = (query or "").strip()
        if not clean_query:
            return {
                **self._empty_history("search", limit, query=clean_query),
                "role_filter": self._normalize_role_filter(role_filter),
            }

        effective_limit = max(1, int(limit))
        roles = self._normalize_role_filter(role_filter)
        current_root = self._resolve_to_root_session_id(
            current_session_id or self._current_session_id
        )
        grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
        raw_match_count = 0
        batch_size = max(200, effective_limit * 20)
        offset = 0
        while len(grouped) < effective_limit:
            raw_results = self._session_db.search_messages(
                query=clean_query,
                source_filter=[self._source] if self._source else None,
                exclude_sources=list(self._hidden_sources),
                role_filter=roles or None,
                limit=batch_size,
                offset=offset,
                user_id=self._user_id,
            )
            if not raw_results:
                break
            for match in raw_results:
                raw_session_id = match.get("session_id")
                if not raw_session_id:
                    continue
                resolved_session_id = self._resolve_to_root_session_id(raw_session_id)
                if current_root and resolved_session_id == current_root:
                    continue
                if current_session_id and raw_session_id == current_session_id:
                    continue
                if resolved_session_id not in grouped:
                    if len(grouped) >= effective_limit:
                        continue
                    grouped[resolved_session_id] = self._build_match_group(resolved_session_id)
                group = grouped[resolved_session_id]
                group["matches"].append(
                    {
                        "message_id": match.get("id"),
                        "source_session_id": raw_session_id,
                        "role": match.get("role"),
                        "snippet": match.get("snippet", ""),
                        "timestamp": match.get("timestamp"),
                        "tool_name": match.get("tool_name"),
                        "context": list(match.get("context") or []),
                    }
                )
                if raw_session_id not in group["matched_session_ids"]:
                    group["matched_session_ids"].append(raw_session_id)
                raw_match_count += 1
            if len(raw_results) < batch_size:
                break
            offset += batch_size

        results = []
        for group in grouped.values():
            group["match_count"] = len(group["matches"])
            results.append(group)

        return {
            "mode": "search",
            "query": clean_query,
            "role_filter": roles,
            "canonical_sources": ["sqlite.sessions", "sqlite.messages"],
            "results": results,
            "count": len(results),
            "raw_match_count": raw_match_count,
            "limit": effective_limit,
        }

    def build_shared_memory(
        self,
        *,
        history_query: str | None = None,
        history_limit: int = 5,
        role_filter: str | list[str] | tuple[str, ...] | None = None,
        current_session_id: str | None = None,
    ) -> dict[str, Any]:
        history = (
            self.search_history(
                history_query,
                role_filter=role_filter,
                limit=history_limit,
                current_session_id=current_session_id,
            )
            if history_query and history_query.strip()
            else self.list_recent_history(
                limit=history_limit,
                current_session_id=current_session_id,
            )
        )
        return {
            "curated_memory": self.get_curated_memory(),
            "provider_status": self._provider_status(),
            "history": history,
        }

    def _get_target_state(self, target: str) -> dict[str, Any]:
        if self._memory_store is None:
            return {
                "target": target,
                "entries": [],
                "entry_count": 0,
                "char_count": 0,
                "char_limit": 0,
                "usage": "0/0",
                "snapshot": None,
                "path": None,
            }
        return self._memory_store.get_target_state(target)

    def _provider_status(self) -> dict[str, Any]:
        if self._memory_manager is None:
            status = {
                "active": False,
                "provider_count": 0,
                "provider_names": [],
                "external_provider_name": None,
                "external_provider_count": 0,
                "has_external_provider": False,
            }
        else:
            status = dict(self._memory_manager.get_provider_status())
        if self._memory_store is not None and "builtin" not in status["provider_names"]:
            status["provider_names"] = ["builtin", *status["provider_names"]]
            status["provider_count"] = len(status["provider_names"])
            status["active"] = True
        return status

    def _resolve_to_root_session_id(self, session_id: str | None) -> str | None:
        if not session_id or self._session_db is None:
            return session_id
        visited: set[str] = set()
        current = session_id
        while current and current not in visited:
            visited.add(current)
            session = self._session_db.get_session(current)
            if not session:
                break
            parent = session.get("parent_session_id")
            if not parent:
                break
            current = parent
        return current

    def _latest_message_preview(self, session_id: str) -> str:
        if self._session_db is None:
            return ""
        try:
            messages = self._session_db.get_messages(session_id)
        except Exception:
            return ""
        for message in reversed(messages):
            content = str(message.get("content") or "").strip()
            if content:
                preview = content[:60]
                return preview + ("..." if len(content) > 60 else "")
        return ""


    def _build_match_group(self, session_id: str) -> dict[str, Any]:
        session = self._session_db.get_session(session_id) if self._session_db else None
        return {
            "session_id": session_id,
            "lineage_root_session_id": session_id,
            "title": session.get("title") if session else None,
            "source": session.get("source") if session else None,
            "started_at": session.get("started_at") if session else None,
            "matched_session_ids": [],
            "match_count": 0,
            "matches": [],
        }

    @staticmethod
    def _session_record(session: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": session.get("id"),
            "lineage_root_session_id": session.get("id"),
            "title": session.get("title") or None,
            "source": session.get("source"),
            "started_at": session.get("started_at"),
            "last_active": session.get("last_active"),
            "message_count": session.get("message_count", 0),
            "preview": session.get("preview", ""),
        }

    @staticmethod
    def _activity_sort_key(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("-inf")


    @staticmethod
    def _normalize_role_filter(
        role_filter: str | list[str] | tuple[str, ...] | None,
    ) -> list[str]:
        if role_filter is None:
            return []
        if isinstance(role_filter, str):
            candidates = role_filter.split(",")
        else:
            candidates = role_filter
        return [str(role).strip() for role in candidates if str(role).strip()]

    @staticmethod
    def _empty_history(mode: str, limit: int, *, query: str | None = None) -> dict[str, Any]:
        result = {
            "mode": mode,
            "canonical_sources": ["sqlite.sessions", "sqlite.messages"],
            "results": [],
            "count": 0,
            "limit": max(1, int(limit)),
        }
        if query is not None:
            result["query"] = query
        return result
