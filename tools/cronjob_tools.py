"""
Cron job management tools for Hermes Agent.

Expose a single compressed action-oriented tool to avoid schema/context bloat.
Compatibility wrappers remain for direct Python callers and legacy tests.
"""

import json
import logging
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import display_hermes_home

logger = logging.getLogger(__name__)

# Import from cron module (will be available when properly installed)
sys.path.insert(0, str(Path(__file__).parent.parent))

from cron.jobs import (
    create_job,
    get_job,
    list_jobs,
    parse_schedule,
    pause_job,
    remove_job,
    resume_job,
    trigger_job,
    update_job,
 )


# ---------------------------------------------------------------------------
# Cron prompt scanning — critical-severity patterns only, since cron prompts
# run in fresh sessions with full tool access.
# ---------------------------------------------------------------------------

_CRON_THREAT_PATTERNS = [
    (r'(?:ignore|forget)[\W_]+(?:\w+[\W_]+)*(?:current|previous|all|above|prior|earlier)[\W_]+(?:\w+[\W_]+)*(?:instructions|rules|guidelines|guidance)', "prompt_injection"),
    (r'do[\W_]+not[\W_]+(?:\w+[\W_]+)*(?:tell|mention)[\W_]+(?:\w+[\W_]+)*user', "deception_hide"),
    (r'don[\W_]*t[\W_]+(?:\w+[\W_]+)*(?:tell|mention)[\W_]+(?:\w+[\W_]+)*user', "deception_hide"),
    (r'system[\W_]+prompt[\W_]+override', "sys_prompt_override"),
    (r'disregard[\W_]+(?:the[\W_]+above[\W_]+)?(?:your|all|any|above)?[\W_]*(instructions|rules|guidelines|guidance)', "disregard_rules"),
    (r'(?:use|call|run)[\W_]+(?:the[\W_]+)?(?:execute_code|terminal|bash|shell)[\W_]+(?:tool|to)?', "tool_invocation"),
    (r'(?s)(?:requests\.(?:post|put)|httpx\.(?:post|put)|urllib\.request\.urlopen)[\s\S]{0,200}(?:os\.environ|os\.getenv|getenv\(|read_text\(|open\(|pathlib\.Path\()', "exfil_code_pattern"),
    (r'(?s)(?:os\.environ|os\.getenv|getenv\(|read_text\(|open\(|pathlib\.Path\()[\s\S]{0,200}(?:requests\.(?:post|put)|httpx\.(?:post|put)|urllib\.request\.urlopen)', "exfil_code_pattern"),
    (r'(?s)(?:open|read|show|include|paste|quote|print|return|report|respond\s+with|reply\s+with|send)[\s\S]{0,120}(?:contents?|content|text|data)?[\s\S]{0,80}(?:~|/)[^\n]*(?:\.[A-Za-z0-9._-]+rc|\.git-credentials|\.aws/credentials|\.docker/config\.json|\.env|credentials|\.netrc|\.pgpass|\.ssh|id_rsa|id_ed25519)', "natural_language_exfil"),
    (r'(?s)(?:~|/)[^\n]*(?:\.[A-Za-z0-9._-]+rc|\.git-credentials|\.aws/credentials|\.docker/config\.json|\.env|credentials|\.netrc|\.pgpass|\.ssh|id_rsa|id_ed25519)[\s\S]{0,120}(?:contents?|content|text|data)[\s\S]{0,80}(?:open|read|show|include|paste|quote|print|return|report|respond\s+with|reply\s+with|send)', "natural_language_exfil"),
    (r'(?s)(?:~|/)[^\n]*(?:\.[A-Za-z0-9._-]+rc|\.git-credentials|\.aws/credentials|\.docker/config\.json|\.env|credentials|\.netrc|\.pgpass|\.ssh|id_rsa|id_ed25519)[\s\S]{0,160}(?:send|upload|post|transmit|exfiltrat\w*|https?://)', "natural_language_exfil"),
    (r'(?s)(?:send|upload|post|transmit|exfiltrat\w*)[\s\S]{0,160}(?:~|/)[^\n]*(?:\.[A-Za-z0-9._-]+rc|\.git-credentials|\.aws/credentials|\.docker/config\.json|\.env|credentials|\.netrc|\.pgpass|\.ssh|id_rsa|id_ed25519)', "natural_language_exfil"),
    (r'(?:print|echo)[\W_]+\$[A-Z_][A-Z0-9_]*', "secret_echo"),
    (r'read[\W_]+(?:~|/)[^\n]*(?:\.ssh|id_rsa|id_ed25519)', "read_ssh_material"),
    (r'(?:curl|wget)\s+[^\n]*(?:\$\(|os\.environ|getenv\(|printenv\b)', "exfil_command_substitution"),
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_curl"),
    (r'wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_wget"),
    (r'(?m)(?:^|[;&|]\s*)(?:scp|rsync|sftp|nc|netcat)\b[^\n]*', "remote_transfer_tool"),
    (r'(?m)(?:^|[;&|]\s*)ssh\b[^\n]*\S+@\S+', "remote_transfer_tool"),
    (r'(?m)(?:^|[;&|]\s*)mail(?:x)?\b[^\n]*@', "remote_transfer_tool"),
    (r'cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass)', "read_secrets"),
    (r'authorized_keys', "ssh_backdoor"),
    (r'/etc/sudoers|visudo', "sudoers_mod"),
    (r'rm\s+-rf\s+/', "destructive_root_rm"),
]

_CRON_INVISIBLE_CHARS = {
    '\u200b', '\u200c', '\u200d', '\u2060', '\ufeff',
    '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
}

_CRON_CONFUSABLE_MAP = str.maketrans({
    'а': 'a', 'α': 'a', 'ɑ': 'a',
    'с': 'c', 'ϲ': 'c',
    'е': 'e', 'ε': 'e',
    'һ': 'h', 'η': 'h', 'н': 'h',
    'і': 'i', 'ι': 'i', 'ӏ': 'i',
    'ј': 'j',
    'κ': 'k', 'к': 'k',
    'м': 'm', 'μ': 'm',
    'ո': 'n', 'п': 'n',
    'ο': 'o', 'о': 'o',
    'ρ': 'p', 'р': 'p',
    'ѕ': 's',
    'τ': 't', 'т': 't',
    'υ': 'u',
    'ν': 'v',
    'ԝ': 'w',
    'х': 'x', 'χ': 'x',
    'у': 'y', 'γ': 'y',
    'з': 'z',
})

_DELIVERY_TRAVERSAL_MARKERS = ("../", "..\\", "/..", "\\..")


def _normalize_prompt_for_scan(prompt: str) -> str:
    normalized = unicodedata.normalize("NFKC", prompt).casefold()
    normalized = normalized.translate(_CRON_CONFUSABLE_MAP)
    normalized = "".join(
        char for char in unicodedata.normalize("NFKD", normalized)
        if not unicodedata.combining(char)
    )
    return normalized


def _scan_cron_prompt(prompt: str) -> str:
    """Scan a cron prompt for critical threats. Returns error string if blocked, else empty."""
    for char in _CRON_INVISIBLE_CHARS:
        if char in prompt:
            return f"Blocked: prompt contains invisible unicode U+{ord(char):04X} (possible injection)."
    normalized_prompt = _normalize_prompt_for_scan(prompt)
    for pattern, pid in _CRON_THREAT_PATTERNS:
        if re.search(pattern, normalized_prompt, re.IGNORECASE):
            return f"Blocked: prompt matches threat pattern '{pid}'. Cron prompts must not contain injection or exfiltration payloads."
    return ""



def _origin_from_env() -> Optional[Dict[str, str]]:
    from gateway.session_context import get_session_env
    origin_platform = get_session_env("HERMES_SESSION_PLATFORM")
    origin_chat_id = get_session_env("HERMES_SESSION_CHAT_ID")
    if origin_platform and origin_chat_id:
        thread_id = get_session_env("HERMES_SESSION_THREAD_ID") or None
        if thread_id:
            logger.debug(
                "Cron origin captured thread_id=%s for %s:%s",
                thread_id, origin_platform, origin_chat_id,
            )
        return {
            "platform": origin_platform,
            "chat_id": origin_chat_id,
            "chat_name": get_session_env("HERMES_SESSION_CHAT_NAME") or None,
            "thread_id": thread_id,
            "user_id": get_session_env("HERMES_SESSION_USER_ID") or None,
        }
    return None




def _job_matches_origin(job: Dict[str, Any], origin: Optional[Dict[str, str]]) -> bool:
    if not origin:
        return True
    job_origin = job.get("origin") or {}
    if job_origin.get("platform") != origin.get("platform"):
        return False
    if str(job_origin.get("chat_id")) != str(origin.get("chat_id")):
        return False
    if str(job_origin.get("thread_id") or "") != str(origin.get("thread_id") or ""):
        return False
    if origin.get("user_id") or job_origin.get("user_id"):
        return str(job_origin.get("user_id") or "") == str(origin.get("user_id") or "")
    return True

def _repeat_display(job: Dict[str, Any]) -> str:
    times = (job.get("repeat") or {}).get("times")
    completed = (job.get("repeat") or {}).get("completed", 0)
    if times is None:
        return "forever"
    if times == 1:
        return "once" if completed == 0 else "1/1"
    return f"{completed}/{times}" if completed else f"{times} times"


def _canonical_skills(skill: Optional[str] = None, skills: Optional[Any] = None) -> List[str]:
    if skills is None:
        raw_items = [skill] if skill else []
    elif isinstance(skills, str):
        raw_items = [skills]
    else:
        raw_items = list(skills)

    normalized: List[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized




def _resolve_model_override(model_obj: Optional[Dict[str, Any]]) -> tuple:
    """Resolve a model override object into (provider, model) for job storage.

    If provider is omitted, pins the current main provider from config so the
    job doesn't drift when the user later changes their default via hermes model.

    Returns (provider_str_or_none, model_str_or_none).
    """
    if not model_obj or not isinstance(model_obj, dict):
        return (None, None)
    model_name = (model_obj.get("model") or "").strip() or None
    provider_name = (model_obj.get("provider") or "").strip() or None
    if model_name and not provider_name:
        # Pin to the current main provider so the job is stable
        try:
            from hermes_cli.config import load_config
            cfg = load_config()
            model_cfg = cfg.get("model", {})
            if isinstance(model_cfg, dict):
                provider_name = model_cfg.get("provider") or None
        except Exception:
            pass  # Best-effort; provider stays None
    return (provider_name, model_name)


def _normalize_optional_job_value(value: Optional[Any], *, strip_trailing_slash: bool = False) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if strip_trailing_slash:
        text = text.rstrip("/")
    return text or None




_KNOWN_DELIVERY_PLATFORMS = frozenset({
    "telegram", "discord", "slack", "whatsapp", "signal", "matrix", "mattermost",
    "homeassistant", "dingtalk", "feishu", "wecom", "wecom_callback", "weixin",
    "sms", "email", "bluebubbles", "qqbot",
})


def _looks_like_delivery_traversal(target_ref: str) -> bool:
    stripped = target_ref.strip()
    lowered = stripped.lower()
    if not stripped or lowered in {".", ".."}:
        return True
    if stripped.startswith(("/", "\\", "~")):
        return True
    if len(stripped) >= 2 and stripped[1] == ":" and stripped[0].isalpha():
        return True
    return any(marker in lowered for marker in _DELIVERY_TRAVERSAL_MARKERS)


def _validate_deliver_target(deliver: Optional[str]) -> Optional[str]:
    if deliver is None:
        return None
    parts = [p.strip() for p in str(deliver).split(",")]
    if not any(parts):
        return "Delivery target cannot be empty"
    from tools.send_message_tool import _parse_target_ref

    origin_context = _origin_from_env()

    for part in parts:
        if not part:
            return "Delivery target contains an empty entry"
        if part == "origin":
            if not origin_context:
                return "Delivery target 'origin' requires a current origin conversation"
            continue
        if part == "local":
            continue
        if ":" not in part:
            platform_name = part.lower()
            if platform_name not in _KNOWN_DELIVERY_PLATFORMS:
                return f"Unknown delivery platform '{platform_name}'"
            continue

        platform_name, target_ref = part.split(":", 1)
        platform_name = platform_name.strip().lower()
        if platform_name not in _KNOWN_DELIVERY_PLATFORMS:
            return f"Unknown delivery platform '{platform_name}'"

        target_ref = target_ref.strip()
        if not target_ref:
            return f"Delivery target '{part}' is missing a target identifier"
        if _looks_like_delivery_traversal(target_ref):
            return f"Delivery target '{part}' contains a blocked path-like target"

        parsed_chat_id, _parsed_thread_id, is_explicit = _parse_target_ref(platform_name, target_ref)
        if is_explicit and parsed_chat_id:
            continue
        if platform_name in {"telegram", "discord"} and ":" in target_ref:
            return f"Delivery target '{part}' is malformed"
        if platform_name == "matrix" and (target_ref.startswith(("!", "@", "#")) or target_ref.lstrip("-").isdigit() or ":" in target_ref):
            return f"Matrix delivery target '{part}' is malformed"
        if target_ref.startswith(":") or target_ref.endswith(":") or "::" in target_ref:
            return f"Delivery target '{part}' is malformed"
    return None


def _validate_cron_script_path(script: Optional[str]) -> Optional[str]:
    """Validate a cron job script path at the API boundary.

    Scripts must be relative paths that resolve within HERMES_HOME/scripts/.
    Absolute paths and ~ expansion are rejected to prevent arbitrary script
    execution via prompt injection.

    Returns an error string if blocked, else None (valid).
    """
    if not script or not script.strip():
        return None  # empty/None = clearing the field, always OK

    from hermes_constants import get_hermes_home

    raw = script.strip()

    # Reject absolute paths and ~ expansion at the API boundary.
    # Only relative paths within ~/.hermes/scripts/ are allowed.
    if raw.startswith(("/", "~")) or (len(raw) >= 2 and raw[1] == ":"):
        return (
            f"Script path must be relative to ~/.hermes/scripts/. "
            f"Got absolute or home-relative path: {raw!r}. "
            f"Place scripts in ~/.hermes/scripts/ and use just the filename."
        )

    # Validate containment after resolution
    from tools.path_security import validate_within_dir

    scripts_dir = get_hermes_home() / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    containment_error = validate_within_dir(scripts_dir / raw, scripts_dir)
    if containment_error:
        return (
            f"Script path escapes the scripts directory via traversal: {raw!r}"
        )

    return None




def _redact_job_view_for_cron_session(job_view: Dict[str, Any]) -> Dict[str, Any]:
    redacted = dict(job_view)
    for key in ("prompt_preview", "model", "provider", "base_url", "script", "deliver"):
        redacted.pop(key, None)
    redacted["name"] = redacted.get("job_id", "[redacted]")
    return redacted

def _format_job(job: Dict[str, Any]) -> Dict[str, Any]:
    prompt = job.get("prompt", "")
    skills = _canonical_skills(job.get("skill"), job.get("skills"))
    health = job.get("health") or {}
    trigger = job.get("reactive_trigger")
    result = {
        "job_id": job["id"],
        "name": job["name"],
        "skill": skills[0] if skills else None,
        "skills": skills,
        "prompt_preview": prompt[:100] + "..." if len(prompt) > 100 else prompt,
        "model": job.get("model"),
        "provider": job.get("provider"),
        "base_url": job.get("base_url"),
        "schedule": job.get("schedule_display"),
        "repeat": _repeat_display(job),
        "deliver": job.get("deliver", "local"),
        "next_run_at": job.get("next_run_at"),
        "last_run_at": job.get("last_run_at"),
        "last_status": job.get("last_status"),
        "last_error": job.get("last_error"),
        "last_delivery_error": job.get("last_delivery_error"),
        "enabled": job.get("enabled", True),
        "state": job.get("state", "scheduled" if job.get("enabled", True) else "paused"),
        "paused_at": job.get("paused_at"),
        "paused_reason": job.get("paused_reason"),
        "health": health,
        "reactive_trigger": trigger,
    }
    if job.get("script"):
        result["script"] = job["script"]
    return result


def cronjob(
    action: str,
    job_id: Optional[str] = None,
    prompt: Optional[str] = None,
    schedule: Optional[str] = None,
    name: Optional[str] = None,
    repeat: Optional[int] = None,
    deliver: Optional[str] = None,
    include_disabled: bool = False,
    skill: Optional[str] = None,
    skills: Optional[List[str]] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    reason: Optional[str] = None,
    script: Optional[str] = None,
    trigger_job_id: Optional[str] = None,
    trigger_after_failures: Optional[int] = None,
    clear_trigger: bool = False,
    task_id: str = None,
 ) -> str:
    """Unified cron job management tool."""
    del task_id  # unused but kept for handler signature compatibility

    try:
        normalized = (action or "").strip().lower()
        from gateway.session_context import get_session_env

        if get_session_env("HERMES_CRON_SESSION") == "1" and normalized in {"create", "update", "remove", "resume", "run", "run_now", "trigger"}:
            return tool_error(
                "Cron-run sessions may not create, update, remove, resume, or trigger cron jobs. They may inspect and pause existing jobs only.",
                success=False,
            )
        deliver_error = _validate_deliver_target(deliver)
        if deliver_error:
            return tool_error(deliver_error, success=False)

        from gateway.session_context import get_session_env
        current_platform = get_session_env("HERMES_SESSION_PLATFORM", "").strip().lower()
        if normalized == "create":
            canonical_skills = _canonical_skills(skill, skills)
            if not prompt and not canonical_skills:
                return tool_error("create requires either prompt or at least one skill", success=False)
            if prompt:
                scan_error = _scan_cron_prompt(prompt)
                if scan_error:
                    return tool_error(scan_error, success=False)

            if script and current_platform and current_platform not in {"cli", "local", "tui"}:
                return tool_error("Cron scripts may only be configured from trusted local CLI sessions", success=False)
            if script:
                script_error = _validate_cron_script_path(script)
                if script_error:
                    return tool_error(script_error, success=False)
            reactive_trigger = None
            if trigger_job_id is not None or trigger_after_failures is not None:
                if not trigger_job_id or trigger_after_failures is None:
                    return tool_error("Reactive triggers require both trigger_job_id and trigger_after_failures", success=False)
                source_job = get_job(str(trigger_job_id).strip())
                if not source_job:
                    return tool_error(f"Reactive trigger source job '{trigger_job_id}' not found", success=False)
                current_origin = _origin_from_env()
                source_origin = source_job.get("origin")
                if current_origin:
                    if not _job_matches_origin({"origin": source_origin}, current_origin):
                        return tool_error("Reactive triggers may only target jobs from the same origin conversation", success=False)
                elif source_origin:
                    return tool_error("Reactive triggers for origin-bound jobs require the same origin context", success=False)
                reactive_trigger = {
                    "job_id": source_job["id"],
                    "after_consecutive_failures": int(trigger_after_failures),
                }

            job = create_job(
                prompt=prompt or "",
                schedule=schedule,
                name=name,
                repeat=repeat,
                deliver=deliver,
                origin=_origin_from_env(),
                skills=canonical_skills,
                model=_normalize_optional_job_value(model),
                provider=_normalize_optional_job_value(provider),
                base_url=_normalize_optional_job_value(base_url, strip_trailing_slash=True),
                script=_normalize_optional_job_value(script),
                reactive_trigger=reactive_trigger,
            )
            return json.dumps(
                {
                    "success": True,
                    "job_id": job["id"],
                    "name": job["name"],
                    "skill": job.get("skill"),
                    "skills": job.get("skills", []),
                    "schedule": job["schedule_display"],
                    "repeat": _repeat_display(job),
                    "deliver": job.get("deliver", "local"),
                    "next_run_at": job["next_run_at"],
                    "job": _format_job(job),
                    "message": f"Cron job '{job['name']}' created.",
                },
                indent=2,
            )

        if normalized == "list":
            raw_jobs = list_jobs(include_disabled=include_disabled)
            from gateway.session_context import get_session_env
            if get_session_env("HERMES_CRON_SESSION") == "1":
                current_job_id = get_session_env("HERMES_CRON_JOB_ID", "").strip()
                if not current_job_id:
                    return tool_error("Cron session missing current job id for scoped listing", success=False)
                current_job = get_job(current_job_id)
                current_skills = current_job.get("skills") if current_job else []
                if "hermes-cron-health" in (current_skills or []):
                    current_origin = current_job.get("origin") if current_job else None
                    if current_origin:
                        raw_jobs = [
                            job for job in raw_jobs
                            if _job_matches_origin(job, current_origin)
                        ]
                    else:
                        raw_jobs = [job for job in raw_jobs if not job.get("origin")]
                else:
                    allowed_ids = {current_job_id}
                    if current_job and current_job.get("reactive_trigger"):
                        allowed_ids.add(current_job["reactive_trigger"]["job_id"])
                    raw_jobs = [job for job in raw_jobs if job.get("id") in allowed_ids]
                jobs = [_redact_job_view_for_cron_session(_format_job(job)) for job in raw_jobs]
            else:
                current_origin = _origin_from_env()
                if current_origin:
                    raw_jobs = [job for job in raw_jobs if _job_matches_origin(job, current_origin)]
                jobs = [_format_job(job) for job in raw_jobs]
            return json.dumps({"success": True, "count": len(jobs), "jobs": jobs}, indent=2)

        if not job_id:
            return tool_error(f"job_id is required for action '{normalized}'", success=False)

        job = get_job(job_id)
        if not job:
            return json.dumps(
                {"success": False, "error": f"Job with ID '{job_id}' not found. Use cronjob(action='list') to inspect jobs."},
                indent=2,
            )
        current_origin = _origin_from_env()
        if current_origin and not _job_matches_origin(job, current_origin):
            return tool_error("Job is not accessible from the current origin conversation", success=False)


        if normalized == "remove":
            removed = remove_job(job_id)
            if not removed:
                return tool_error(f"Failed to remove job '{job_id}'", success=False)
            return json.dumps(
                {
                    "success": True,
                    "message": f"Cron job '{job['name']}' removed.",
                    "removed_job": {
                        "id": job_id,
                        "name": job["name"],
                        "schedule": job.get("schedule_display"),
                    },
                },
                indent=2,
            )

        if normalized == "pause":
            updated = pause_job(job_id, reason=reason)
            job_view = _format_job(updated)
            from gateway.session_context import get_session_env
            if get_session_env("HERMES_CRON_SESSION") == "1":
                job_view = _redact_job_view_for_cron_session(job_view)
            return json.dumps({"success": True, "job": job_view}, indent=2)

        if normalized == "resume":
            updated = resume_job(job_id)
            job_view = _format_job(updated)
            from gateway.session_context import get_session_env
            if get_session_env("HERMES_CRON_SESSION") == "1":
                job_view = _redact_job_view_for_cron_session(job_view)
            return json.dumps({"success": True, "job": job_view}, indent=2)
        if deliver is not None:
            deliver_error = _validate_deliver_target(deliver)
            if deliver_error:
                return tool_error(deliver_error, success=False)


        if normalized in {"run", "run_now", "trigger"}:
            updated = trigger_job(job_id)
            job_view = _format_job(updated)
            from gateway.session_context import get_session_env
            if get_session_env("HERMES_CRON_SESSION") == "1":
                job_view = _redact_job_view_for_cron_session(job_view)
            return json.dumps({"success": True, "job": job_view}, indent=2)

        if normalized == "update":
            updates: Dict[str, Any] = {}
            if prompt is not None:
                scan_error = _scan_cron_prompt(prompt)
                if scan_error:
                    return tool_error(scan_error, success=False)
                updates["prompt"] = prompt
            if name is not None:
                updates["name"] = name
            if deliver is not None:
                updates["deliver"] = deliver
            if skills is not None or skill is not None:
                canonical_skills = _canonical_skills(skill, skills)
                updates["skills"] = canonical_skills
                updates["skill"] = canonical_skills[0] if canonical_skills else None
            if model is not None:
                updates["model"] = _normalize_optional_job_value(model)
            if provider is not None:
                updates["provider"] = _normalize_optional_job_value(provider)
            if base_url is not None:
                updates["base_url"] = _normalize_optional_job_value(base_url, strip_trailing_slash=True)
            if script is not None:
                if script and current_platform and current_platform not in {"cli", "local", "tui"}:
                    return tool_error("Cron scripts may only be configured from trusted local CLI sessions", success=False)
                if script:
                    script_error = _validate_cron_script_path(script)
                    if script_error:
                        return tool_error(script_error, success=False)
                updates["script"] = _normalize_optional_job_value(script) if script else None
            if repeat is not None:
                normalized_repeat = None if repeat <= 0 else repeat
                repeat_state = dict(job.get("repeat") or {})
                repeat_state["times"] = normalized_repeat
                updates["repeat"] = repeat_state
            if schedule is not None:
                if schedule == "":
                    updates["schedule"] = None
                    updates["schedule_display"] = "reactive"
                    if job.get("state") != "paused":
                        updates["state"] = "reactive_waiting"
                        updates["enabled"] = True
                else:
                    parsed_schedule = parse_schedule(schedule)
                    updates["schedule"] = parsed_schedule
                    updates["schedule_display"] = parsed_schedule.get("display", schedule)
                    if job.get("state") != "paused":
                        updates["state"] = "scheduled"
                        updates["enabled"] = True
            if clear_trigger:
                updates["reactive_trigger"] = None
            elif trigger_job_id is not None or trigger_after_failures is not None:
                if not trigger_job_id or trigger_after_failures is None:
                    return tool_error("Reactive triggers require both trigger_job_id and trigger_after_failures", success=False)
                source_job = get_job(str(trigger_job_id).strip())
                if not source_job:
                    return tool_error(f"Reactive trigger source job '{trigger_job_id}' not found", success=False)
                current_origin = _origin_from_env()
                source_origin = source_job.get("origin")
                if current_origin:
                    if not _job_matches_origin({"origin": source_origin}, current_origin):
                        return tool_error("Reactive triggers may only target jobs from the same origin conversation", success=False)
                elif source_origin:
                    return tool_error("Reactive triggers for origin-bound jobs require the same origin context", success=False)
                if source_job["id"] == job_id:
                    return tool_error("A cron job cannot reactively trigger itself", success=False)
                updates["reactive_trigger"] = {
                    "job_id": source_job["id"],
                    "after_consecutive_failures": int(trigger_after_failures),
                    "last_seen_failure_at": None,
                }
                if job.get("schedule") is None and job.get("state") != "paused":
                    updates["state"] = "reactive_waiting"
                    updates["enabled"] = True
            if not updates:
                return tool_error("No updates provided.", success=False)
            updated = update_job(job_id, updates)
            return json.dumps({"success": True, "job": _format_job(updated)}, indent=2)

        return tool_error(f"Unknown cron action '{action}'", success=False)

    except Exception as e:
        return tool_error(str(e), success=False)



CRONJOB_SCHEMA = {
    "name": "cronjob",
    "description": """Manage scheduled cron jobs with a single compressed tool.

Use action='create' to schedule a new job from a prompt or one or more skills, or to create a reactive follow-up / repair job.
Use action='list' to inspect jobs and their health metrics.
Use action='update', 'pause', 'resume', 'remove', or 'run' to manage an existing job.

To stop a job the user no longer wants: first action='list' to find the job_id, then action='remove' with that job_id. Never guess job IDs — always list first.

Jobs run in a fresh session with no current-chat context, so prompts must be self-contained.
If skills are provided on create, the future cron run loads those skills in order, then follows the prompt as the task instruction.
On update, passing skills=[] clears attached skills.
Reactive triggers let one job run when another job keeps failing. Use trigger_job_id + trigger_after_failures to create a repair or follow-up job that wakes after repeated failures of a source job.

NOTE: The agent's final response is auto-delivered to the target. Put the primary
user-facing content in the final response. Cron jobs run autonomously with no user
present — they cannot ask questions or request clarification.

Important safety rule: cron-run sessions should not recursively schedule more cron jobs.""",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "One of: create, list, update, pause, resume, remove, run"
            },
            "job_id": {
                "type": "string",
                "description": "Required for update/pause/resume/remove/run"
            },
            "prompt": {
                "type": "string",
                "description": "For create: the full self-contained prompt. If skills are also provided, this becomes the task instruction paired with those skills."
            },
            "schedule": {
                "type": "string",
                "description": "Optional for create/update when using a reactive trigger only. Otherwise: '30m', 'every 2h', '0 9 * * *', or ISO timestamp"
            },
            "name": {
                "type": "string",
                "description": "Optional human-friendly name"
            },
            "repeat": {
                "type": "integer",
                "description": "Optional repeat count. Omit for defaults (once for one-shot, forever for recurring)."
            },
            "deliver": {
                "type": "string",
                "description": "Omit this parameter to auto-deliver back to the current chat and topic (recommended). Auto-detection preserves thread/topic context. Only set explicitly when the user asks to deliver somewhere OTHER than the current conversation. Values: 'origin' (same as omitting), 'local' (no delivery, save only), or platform:chat_id:thread_id for a specific destination. Examples: 'telegram:-1001234567890:17585', 'discord:#engineering', 'sms:+15551234567'. WARNING: 'platform:chat_id' without :thread_id loses topic targeting."
            },
            "skills": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional ordered list of skill names to load before executing the cron prompt. On update, pass an empty array to clear attached skills."
            },
            "model": {
                "type": "object",
                "description": "Optional per-job model override. If provider is omitted, the current main provider is pinned at creation time so the job stays stable.",
                "properties": {
                    "provider": {
                        "type": "string",
                        "description": "Provider name (e.g. 'openrouter', 'anthropic'). Omit to use and pin the current provider."
                    },
                    "model": {
                        "type": "string",
                        "description": "Model name (e.g. 'anthropic/claude-sonnet-4', 'claude-sonnet-4')"
                    }
                },
                "required": ["model"]
            },
            "trigger_job_id": {
                "type": "string",
                "description": "Optional source job ID for a reactive trigger. Requires trigger_after_failures."
            },
            "trigger_after_failures": {
                "type": "integer",
                "description": "Optional consecutive-failure threshold for reactive triggers. Requires trigger_job_id."
            },
            "clear_trigger": {
                "type": "boolean",
                "description": "Optional flag for action='update' to remove the reactive trigger from a job."
            },
            "script": {
                "type": "string",
                "description": f"Optional path to a Python script that runs before each cron job execution. Its stdout is injected into the prompt as context. Use for data collection and change detection. Relative paths resolve under {display_hermes_home()}/scripts/. On update, pass empty string to clear."
            },
        },
        "required": ["action"]
    }
}


def check_cronjob_requirements() -> bool:
    """Check if cronjob tools can be used."""
    from gateway.session_context import get_session_env
    return bool(
        os.getenv("HERMES_INTERACTIVE")
        or os.getenv("HERMES_GATEWAY_SESSION")
        or os.getenv("HERMES_EXEC_ASK")
        or get_session_env("HERMES_CRON_SESSION") == "1"
    )


# --- Registry ---
from tools.registry import registry, tool_error

registry.register(
    name="cronjob",
    toolset="cronjob",
    schema=CRONJOB_SCHEMA,
    handler=lambda args, **kw: (lambda _mo=_resolve_model_override(args.get("model")): cronjob(
        action=args.get("action", ""),
        job_id=args.get("job_id"),
        prompt=args.get("prompt"),
        schedule=args.get("schedule"),
        name=args.get("name"),
        repeat=args.get("repeat"),
        deliver=args.get("deliver"),
        include_disabled=args.get("include_disabled", True),
        skill=args.get("skill"),
        skills=args.get("skills"),
        model=_mo[1],
        provider=_mo[0] or args.get("provider"),
        base_url=args.get("base_url"),
        reason=args.get("reason"),
        script=args.get("script"),
        trigger_job_id=args.get("trigger_job_id"),
        trigger_after_failures=args.get("trigger_after_failures"),
        clear_trigger=args.get("clear_trigger", False),
        task_id=kw.get("task_id"),
    ))(),
    check_fn=check_cronjob_requirements,
    emoji="⏰",
)
