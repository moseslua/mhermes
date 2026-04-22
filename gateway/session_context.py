"""
Session-scoped context variables for the Hermes gateway.

Replaces the previous ``os.environ``-based session state
(``HERMES_SESSION_PLATFORM``, ``HERMES_SESSION_CHAT_ID``, etc.) with
Python's ``contextvars.ContextVar``.

**Why this matters**

The gateway processes messages concurrently via ``asyncio``.  When two
messages arrive at the same time the old code did:

    os.environ["HERMES_SESSION_THREAD_ID"] = str(context.source.thread_id)

Because ``os.environ`` is *process-global*, Message A's value was
silently overwritten by Message B before Message A's agent finished
running.  Background-task notifications and tool calls therefore routed
to the wrong thread.

``contextvars.ContextVar`` values are *task-local*: each ``asyncio``
task (and any ``run_in_executor`` thread it spawns) gets its own copy,
so concurrent messages never interfere.

**Backward compatibility**

The public helper ``get_session_env(name, default="")`` mirrors the old
``os.getenv("HERMES_SESSION_*", ...)`` calls.  Existing tool code only
needs to replace the import + call site:

    # before
    import os
    platform = os.getenv("HERMES_SESSION_PLATFORM", "")

    # after
    from gateway.session_context import get_session_env
    platform = get_session_env("HERMES_SESSION_PLATFORM", "")
"""

import hashlib
from contextvars import ContextVar
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

# Sentinel to distinguish "never set in this context" from "explicitly set to empty".
# When a contextvar holds _UNSET, we fall back to os.environ (CLI/cron compat).
# When it holds "" (after clear_session_vars resets it), we return "" — no fallback.
_UNSET: Any = object()

# ---------------------------------------------------------------------------
# Per-task session variables
# ---------------------------------------------------------------------------

_SESSION_PLATFORM: ContextVar = ContextVar("HERMES_SESSION_PLATFORM", default=_UNSET)
_SESSION_CHAT_ID: ContextVar = ContextVar("HERMES_SESSION_CHAT_ID", default=_UNSET)
_SESSION_CHAT_NAME: ContextVar = ContextVar("HERMES_SESSION_CHAT_NAME", default=_UNSET)
_SESSION_THREAD_ID: ContextVar = ContextVar("HERMES_SESSION_THREAD_ID", default=_UNSET)
_SESSION_USER_ID: ContextVar = ContextVar("HERMES_SESSION_USER_ID", default=_UNSET)
_SESSION_USER_NAME: ContextVar = ContextVar("HERMES_SESSION_USER_NAME", default=_UNSET)
_SESSION_KEY: ContextVar = ContextVar("HERMES_SESSION_KEY", default=_UNSET)
_CRON_SESSION: ContextVar = ContextVar("HERMES_CRON_SESSION", default=_UNSET)
_CRON_JOB_ID: ContextVar = ContextVar("HERMES_CRON_JOB_ID", default=_UNSET)

# Cron auto-delivery vars — set per-job in run_job() so concurrent jobs
# don't clobber each other's delivery targets.
_CRON_AUTO_DELIVER_PLATFORM: ContextVar = ContextVar("HERMES_CRON_AUTO_DELIVER_PLATFORM", default=_UNSET)
_CRON_AUTO_DELIVER_CHAT_ID: ContextVar = ContextVar("HERMES_CRON_AUTO_DELIVER_CHAT_ID", default=_UNSET)
_CRON_AUTO_DELIVER_THREAD_ID: ContextVar = ContextVar("HERMES_CRON_AUTO_DELIVER_THREAD_ID", default=_UNSET)

# Attachment and env override context vars
_ATTACHMENT_SCOPE_ID: ContextVar = ContextVar("HERMES_ATTACHMENT_SCOPE_ID", default=_UNSET)
_SESSION_ATTACHMENT_PATHS: ContextVar = ContextVar("HERMES_SESSION_ATTACHMENT_PATHS", default=_UNSET)
_SESSION_ENV_OVERRIDES: ContextVar = ContextVar("HERMES_SESSION_ENV_OVERRIDES", default=_UNSET)
_VAR_MAP = {
    "HERMES_SESSION_PLATFORM": _SESSION_PLATFORM,
    "HERMES_SESSION_CHAT_ID": _SESSION_CHAT_ID,
    "HERMES_SESSION_CHAT_NAME": _SESSION_CHAT_NAME,
    "HERMES_SESSION_THREAD_ID": _SESSION_THREAD_ID,
    "HERMES_SESSION_USER_ID": _SESSION_USER_ID,
    "HERMES_SESSION_USER_NAME": _SESSION_USER_NAME,
    "HERMES_SESSION_KEY": _SESSION_KEY,
    "HERMES_CRON_SESSION": _CRON_SESSION,
    "HERMES_CRON_JOB_ID": _CRON_JOB_ID,
    "HERMES_CRON_AUTO_DELIVER_PLATFORM": _CRON_AUTO_DELIVER_PLATFORM,
    "HERMES_CRON_AUTO_DELIVER_CHAT_ID": _CRON_AUTO_DELIVER_CHAT_ID,
    "HERMES_CRON_AUTO_DELIVER_THREAD_ID": _CRON_AUTO_DELIVER_THREAD_ID,
}
_ATTACHMENT_REGISTRY_LOCK = Lock()
_ATTACHMENT_REGISTRY: dict[str, set[str]] = {}


def get_attachment_scope_id() -> str:
    value = _ATTACHMENT_SCOPE_ID.get()
    if value is _UNSET or value in (None, ""):
        return ""
    return str(value)


def _current_attachment_scope_key() -> str | None:
    scope_id = get_attachment_scope_id()
    if scope_id:
        return f"scope:{scope_id}"
    session_key = _SESSION_KEY.get()
    if session_key is not _UNSET and session_key:
        return f"session:{session_key}"
    cron_session = _CRON_SESSION.get()
    cron_job_id = _CRON_JOB_ID.get()
    if cron_session is not _UNSET and cron_session == "1" and cron_job_id is not _UNSET and cron_job_id:
        return f"cron:{cron_job_id}"
    return None


def clear_session_attachment_scope() -> None:
    scope_key = _current_attachment_scope_key()
    if scope_key:
        with _ATTACHMENT_REGISTRY_LOCK:
            _ATTACHMENT_REGISTRY.pop(scope_key, None)
    _SESSION_ATTACHMENT_PATHS.set(set())

def set_attachment_scope(scope_id: str, allowed_attachments: Iterable[str] | None = None) -> tuple[Any, Any]:
    return (
        _ATTACHMENT_SCOPE_ID.set(scope_id),
        _SESSION_ATTACHMENT_PATHS.set({str(path) for path in (allowed_attachments or [])}),
    )


def restore_attachment_scope(tokens: tuple[Any, Any]) -> None:
    scope_token, attachments_token = tokens
    _SESSION_ATTACHMENT_PATHS.reset(attachments_token)
    _ATTACHMENT_SCOPE_ID.reset(scope_token)





def set_session_vars(
    platform: str = "",
    chat_id: str = "",
    chat_name: str = "",
    thread_id: str = "",
    user_id: str = "",
    user_name: str = "",
    session_key: str = "",
    cron_session: str = "",
    cron_job_id: str = "",
    cron_auto_deliver_platform: str = "",
    cron_auto_deliver_chat_id: str = "",
    cron_auto_deliver_thread_id: str = "",
    env_overrides: dict[str, str] | None = None,
    allowed_attachments: Iterable[str] | None = None,
    attachment_scope: str = "",
 ) -> list:
    """Set all session context variables and return reset tokens."""
    tokens = [
        _SESSION_PLATFORM.set(platform),
        _SESSION_CHAT_ID.set(chat_id),
        _SESSION_CHAT_NAME.set(chat_name),
        _SESSION_THREAD_ID.set(thread_id),
        _SESSION_USER_ID.set(user_id),
        _SESSION_USER_NAME.set(user_name),
        _SESSION_KEY.set(session_key),
        _CRON_SESSION.set(cron_session),
        _CRON_JOB_ID.set(cron_job_id),
        _CRON_AUTO_DELIVER_PLATFORM.set(cron_auto_deliver_platform),
        _CRON_AUTO_DELIVER_CHAT_ID.set(cron_auto_deliver_chat_id),
        _CRON_AUTO_DELIVER_THREAD_ID.set(cron_auto_deliver_thread_id),
        _ATTACHMENT_SCOPE_ID.set(attachment_scope),
        _SESSION_ATTACHMENT_PATHS.set({str(path) for path in (allowed_attachments or [])}),
        _SESSION_ENV_OVERRIDES.set(dict(env_overrides or {})),
    ]
    return tokens


def clear_session_vars(tokens: list) -> None:
    """Clear user-session variables while restoring unrelated cron/env context."""
    clear_session_attachment_scope()
    for var in (
        _SESSION_PLATFORM,
        _SESSION_CHAT_ID,
        _SESSION_CHAT_NAME,
        _SESSION_THREAD_ID,
        _SESSION_USER_ID,
        _SESSION_USER_NAME,
        _SESSION_KEY,
    ):
        var.set("")
    for var, token in zip((
        _CRON_SESSION,
        _CRON_JOB_ID,
        _CRON_AUTO_DELIVER_PLATFORM,
        _CRON_AUTO_DELIVER_CHAT_ID,
        _CRON_AUTO_DELIVER_THREAD_ID,
        _ATTACHMENT_SCOPE_ID,
        _SESSION_ATTACHMENT_PATHS,
        _SESSION_ENV_OVERRIDES,
    ), tokens[7:]):
        var.reset(token)


def restore_session_vars(tokens: list) -> None:
    """Restore prior ContextVar values using the tokens returned by set_session_vars()."""
    for var, token in zip((
        _SESSION_PLATFORM,
        _SESSION_CHAT_ID,
        _SESSION_CHAT_NAME,
        _SESSION_THREAD_ID,
        _SESSION_USER_ID,
        _SESSION_USER_NAME,
        _SESSION_KEY,
        _CRON_SESSION,
        _CRON_JOB_ID,
        _CRON_AUTO_DELIVER_PLATFORM,
        _CRON_AUTO_DELIVER_CHAT_ID,
        _CRON_AUTO_DELIVER_THREAD_ID,
        _ATTACHMENT_SCOPE_ID,
        _SESSION_ATTACHMENT_PATHS,
        _SESSION_ENV_OVERRIDES,
    ), tokens):
        var.reset(token)


def _attachment_fingerprint(path: str) -> tuple[int, int, str] | None:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        return None
    digest = hashlib.sha256()
    with resolved.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = resolved.stat()
    return (int(stat.st_size), int(stat.st_mtime_ns), digest.hexdigest())


def _normalize_attachment_registry(value) -> dict[str, tuple[int, int, str] | None]:
    if value is _UNSET or value in (None, ""):
        return {}
    if isinstance(value, dict):
        return {str(path): fp for path, fp in value.items()}
    return {str(Path(path).expanduser().resolve()): _attachment_fingerprint(str(path)) for path in value}


def get_session_env_overrides() -> dict[str, str]:
    value = _SESSION_ENV_OVERRIDES.get()
    if value is _UNSET or value in (None, ""):
        return {}
    return dict(value)

def get_session_attachment_paths() -> set[str]:
    registry = _normalize_attachment_registry(_SESSION_ATTACHMENT_PATHS.get())
    paths = set(registry.keys())
    scope_key = _current_attachment_scope_key()
    if scope_key:
        with _ATTACHMENT_REGISTRY_LOCK:
            paths.update(_ATTACHMENT_REGISTRY.get(scope_key, {}).keys())
    return paths


def register_session_attachment_path(path: str) -> str:
    resolved = str(Path(path).expanduser().resolve())
    fingerprint = _attachment_fingerprint(resolved)
    current = _normalize_attachment_registry(_SESSION_ATTACHMENT_PATHS.get())
    current[resolved] = fingerprint
    _SESSION_ATTACHMENT_PATHS.set(current)
    scope_key = _current_attachment_scope_key()
    if scope_key:
        with _ATTACHMENT_REGISTRY_LOCK:
            scoped = dict(_ATTACHMENT_REGISTRY.get(scope_key, {}))
            scoped[resolved] = fingerprint
            _ATTACHMENT_REGISTRY[scope_key] = scoped
    return resolved


def register_session_attachment_paths(paths: Iterable[str]) -> set[str]:
    current = _normalize_attachment_registry(_SESSION_ATTACHMENT_PATHS.get())
    resolved_paths = {}
    for path in paths:
        resolved = str(Path(path).expanduser().resolve())
        resolved_paths[resolved] = _attachment_fingerprint(resolved)
    current.update(resolved_paths)
    _SESSION_ATTACHMENT_PATHS.set(current)
    scope_key = _current_attachment_scope_key()
    if scope_key:
        with _ATTACHMENT_REGISTRY_LOCK:
            scoped = dict(_ATTACHMENT_REGISTRY.get(scope_key, {}))
            scoped.update(resolved_paths)
            _ATTACHMENT_REGISTRY[scope_key] = scoped
    return set(current.keys())


def is_session_attachment_path_allowed(path: str) -> bool:
    resolved = str(Path(path).expanduser().resolve())
    current = _normalize_attachment_registry(_SESSION_ATTACHMENT_PATHS.get())
    scope_key = _current_attachment_scope_key()
    scoped = {}
    if scope_key:
        with _ATTACHMENT_REGISTRY_LOCK:
            scoped = dict(_ATTACHMENT_REGISTRY.get(scope_key, {}))
    if resolved in scoped:
        return scoped[resolved] == _attachment_fingerprint(resolved)
    if resolved in current:
        return current[resolved] == _attachment_fingerprint(resolved)
    return False


def get_session_env(name: str, default: str = "") -> str:
    """Read a session context variable by its legacy ``HERMES_SESSION_*`` name.

    Drop-in replacement for ``os.getenv("HERMES_SESSION_*", default)``.

    Resolution order:
    1. Context variable (set by the gateway for concurrency-safe access).
       If the variable was explicitly set (even to ``""``) via
       ``set_session_vars`` or ``clear_session_vars``, that value is
       returned — **no fallback to os.environ**.
    2. ``os.environ`` (only when the context variable was never set in
       this context — i.e. CLI, cron scheduler, and test processes that
       don't use ``set_session_vars`` at all).
    3. *default*
    """
    import os

    var = _VAR_MAP.get(name)
    if var is not None:
        value = var.get()
        if value is not _UNSET:
            return value
    # Fall back to os.environ for CLI, cron, and test compatibility
    return os.getenv(name, default)
