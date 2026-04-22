"""OSS contribution ledger tool for querying and managing the contribution backlog.

Provides a JSON-backed ledger for tracking repos through the OSS contribution
pipeline (stages 0-13) with operator claims and rate-limit tracking.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_hermes_home
from tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────

_LEDGER_DIR = get_hermes_home() / "oss-contribution"
_LEDGER_PATH = _LEDGER_DIR / "ledger.json"
_RATE_LIMITS_PATH = _LEDGER_DIR / "rate_limits.json"

# ── Stage definitions (from harness v2 design) ───────────────────────────────

_STAGE_NAMES: Dict[int, str] = {
    0: "stance-detect",
    1: "discover",
    2: "investigate",
    3: "interview",
    4: "cross-check",
    5: "reproduce",
    6: "load-bearing-exclusion",
    7: "value-assessment",
    8: "merge-pattern",
    9: "draft-issue",
    10: "human-attestation-issue",
    11: "maintainer-ack",
    12: "draft-pr",
    13: "review-response",
}

_VALID_STAGES = set(_STAGE_NAMES.keys())

_VALID_STATUSES = frozenset({
    "backlog",
    "discovered",
    "interviewed",
    "reproduced",
    "not-reproduced",
    "blocked-environment",
    "flaky",
    "issue-drafted",
    "issue-submitted",
    "pr-drafted",
    "pr-submitted",
    "merged",
    "closed",
    "cooldown",
    "halted",
    "dropped",
})

# ── Ledger I/O ───────────────────────────────────────────────────────────────


def _ensure_ledger_dir() -> None:
    _LEDGER_DIR.mkdir(parents=True, exist_ok=True)


def _load_ledger() -> Dict[str, Any]:
    _ensure_ledger_dir()
    if not _LEDGER_PATH.exists():
        return {"repos": {}, "version": 1}
    try:
        with open(_LEDGER_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load ledger, starting fresh: %s", exc)
        return {"repos": {}, "version": 1}
    if not isinstance(data, dict):
        return {"repos": {}, "version": 1}
    if "repos" not in data or not isinstance(data["repos"], dict):
        data["repos"] = {}
    return data


def _save_ledger(data: Dict[str, Any]) -> None:
    _ensure_ledger_dir()
    tmp = _LEDGER_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(_LEDGER_PATH)


def _load_rate_limits() -> Dict[str, Any]:
    _ensure_ledger_dir()
    if not _RATE_LIMITS_PATH.exists():
        return {
            "operator": {"issue_timestamps": [], "pr_timestamps": []},
            "repos": {},
            "global": {"weekly_issue_cap": 25, "weekly_pr_cap": 10},
            "version": 1,
        }
    try:
        with open(_RATE_LIMITS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load rate limits, starting fresh: %s", exc)
        return {
            "operator": {"issue_timestamps": [], "pr_timestamps": []},
            "repos": {},
            "global": {"weekly_issue_cap": 25, "weekly_pr_cap": 10},
            "version": 1,
        }
    if not isinstance(data, dict):
        return {
            "operator": {"issue_timestamps": [], "pr_timestamps": []},
            "repos": {},
            "global": {"weekly_issue_cap": 25, "weekly_pr_cap": 10},
            "version": 1,
        }
    data.setdefault("operator", {"issue_timestamps": [], "pr_timestamps": []})
    data.setdefault("repos", {})
    data.setdefault("global", {"weekly_issue_cap": 25, "weekly_pr_cap": 10})
    return data


def _save_rate_limits(data: Dict[str, Any]) -> None:
    _ensure_ledger_dir()
    tmp = _RATE_LIMITS_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(_RATE_LIMITS_PATH)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _repo_key(repo: str) -> str:
    return repo.strip().lower()


def _next_stage_action(repo_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return the recommended next action for a repo based on its ledger state."""
    stage = repo_entry.get("stage", 0)
    status = repo_entry.get("status", "backlog")
    claimed_by = repo_entry.get("claimed_by")

    if status in {"halted", "dropped", "closed", "merged"}:
        return {
            "action": "none",
            "reason": f"Repo is in terminal status '{status}'. No further action.",
        }

    if status == "cooldown":
        return {
            "action": "wait",
            "reason": "Repo is in cooldown. Wait for cooldown period to expire.",
        }

    if not claimed_by:
        return {
            "action": "claim",
            "reason": "Repo is unclaimed. An operator must claim it before proceeding.",
        }

    if stage == 0:
        return {"action": "stance-detect", "reason": "Detect contribution stance from project files."}
    if stage == 1:
        return {"action": "discover", "reason": "Extract fix candidates from PRs/tags."}
    if stage == 2:
        return {"action": "investigate", "reason": "Investigate candidate viability."}
    if stage == 3:
        return {"action": "interview", "reason": "Run Ouroboros-style deep interview (spam gate)."}
    if stage == 4:
        return {"action": "cross-check", "reason": "Cross-check for duplicate contributions."}
    if stage == 5:
        return {"action": "reproduce", "reason": "Fork, clone, and reproduce in isolated worktree."}
    if stage == 6:
        return {"action": "load-bearing-exclusion", "reason": "Apply load-bearing exclusion gate."}
    if stage == 7:
        return {"action": "value-assessment", "reason": "Assess contribution value."}
    if stage == 8:
        return {"action": "merge-pattern", "reason": "Extract conventions from merged PRs."}
    if stage == 9:
        return {"action": "draft-issue", "reason": "Draft the initial maintainer-first issue."}
    if stage == 10:
        return {"action": "human-attestation", "reason": "Human operator review and attestation."}
    if stage == 11:
        return {"action": "maintainer-ack", "reason": "Wait for maintainer acknowledgment."}
    if stage == 12:
        return {"action": "draft-pr", "reason": "Draft PR after maintainer ack."}
    if stage == 13:
        return {"action": "review-response", "reason": "Analyze maintainer feedback and respond."}

    return {"action": "unknown", "reason": f"Unrecognized stage {stage}."}


# ── Schema ───────────────────────────────────────────────────────────────────

OSS_CONTRIBUTION_SCHEMA = {
    "name": "oss_contribution",
    "description": (
        "Query and manage the OSS contribution ledger state. "
        "List repos, get repo details, update status, claim/release repos, "
        "check rate limits, and determine the next action for a repo."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_repos",
                    "get_repo",
                    "update_status",
                    "check_rate_limits",
                    "claim_repo",
                    "release_repo",
                    "get_next_action",
                ],
                "description": "OSS contribution ledger operation to perform.",
            },
            "repo": {
                "type": "string",
                "description": "Repository identifier in 'owner/repo-name' format.",
            },
            "status": {
                "type": "string",
                "description": "Status filter for list_repos, or new status for update_status.",
            },
            "stage": {
                "type": "integer",
                "description": "Pipeline stage (0-13) for update_status.",
            },
            "operator": {
                "type": "string",
                "description": "Operator identity for claim/release actions.",
            },
            "limit": {
                "type": "integer",
                "default": 50,
                "description": "Maximum number of repos to return for list_repos.",
            },
            "include_claimed": {
                "type": "boolean",
                "default": True,
                "description": "Whether to include claimed repos in list_repos results.",
            },
        },
        "required": ["action"],
    },
}


# ── Handlers ─────────────────────────────────────────────────────────────────


def check_oss_contribution_requirements() -> bool:
    return True


def _handle_list_repos(
    status_filter: Optional[str] = None,
    limit: int = 50,
    include_claimed: bool = True,
) -> str:
    ledger = _load_ledger()
    repos: Dict[str, Any] = ledger.get("repos", {})
    results: List[Dict[str, Any]] = []

    for key, entry in repos.items():
        if status_filter and entry.get("status") != status_filter:
            continue
        if not include_claimed and entry.get("claimed_by"):
            continue
        results.append(
            {
                "repo": entry.get("repo", key),
                "status": entry.get("status", "backlog"),
                "stage": entry.get("stage", 0),
                "claimed_by": entry.get("claimed_by"),
                "updated_at": entry.get("updated_at"),
            }
        )

    results.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
    if limit > 0:
        results = results[:limit]

    return tool_result(success=True, repos=results, total=len(results))


def _handle_get_repo(repo: str) -> str:
    if not repo or not repo.strip():
        return tool_error("repo is required for get_repo")
    ledger = _load_ledger()
    entry = ledger.get("repos", {}).get(_repo_key(repo))
    if not entry:
        return tool_error(f"Repo not found in ledger: {repo}")
    return tool_result(success=True, repo=entry)


def _handle_update_status(
    repo: str,
    status: Optional[str] = None,
    stage: Optional[int] = None,
) -> str:
    if not repo or not repo.strip():
        return tool_error("repo is required for update_status")
    if status is None and stage is None:
        return tool_error("At least one of status or stage is required for update_status")
    if status is not None and status not in _VALID_STATUSES:
        return tool_error(
            f"Invalid status '{status}'. Valid: {', '.join(sorted(_VALID_STATUSES))}"
        )
    if stage is not None and stage not in _VALID_STAGES:
        return tool_error(
            f"Invalid stage {stage}. Valid stages: {sorted(_VALID_STAGES)}"
        )

    ledger = _load_ledger()
    key = _repo_key(repo)
    entry = ledger.setdefault("repos", {}).get(key)
    if not entry:
        entry = {
            "repo": repo.strip(),
            "candidate_id": None,
            "stage": 0,
            "status": "backlog",
            "claimed_by": None,
            "claimed_at": None,
            "fork": None,
            "worktree_path": None,
            "branch": None,
            "commit": None,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "notes": None,
        }
        ledger["repos"][key] = entry

    if status is not None:
        entry["status"] = status
    if stage is not None:
        entry["stage"] = stage
    entry["updated_at"] = _now_iso()

    _save_ledger(ledger)
    return tool_result(success=True, repo=entry)


def _handle_check_rate_limits() -> str:
    rl = _load_rate_limits()
    now = time.time()
    week_ago = now - 7 * 24 * 3600

    # Single-operator weekly consumption
    data = rl.get("operator", {})
    issues_this_week = sum(
        1 for ts in data.get("issue_timestamps", [])
        if isinstance(ts, (int, float)) and ts > week_ago
    )
    prs_this_week = sum(
        1 for ts in data.get("pr_timestamps", [])
        if isinstance(ts, (int, float)) and ts > week_ago
    )
    operator_usage = {
        "issues_this_week": issues_this_week,
        "prs_this_week": prs_this_week,
        "weekly_issue_cap": rl.get("global", {}).get("weekly_issue_cap", 25),
        "weekly_pr_cap": rl.get("global", {}).get("weekly_pr_cap", 10),
        "issue_remaining": max(
            0, rl.get("global", {}).get("weekly_issue_cap", 25) - issues_this_week
        ),
        "pr_remaining": max(
            0, rl.get("global", {}).get("weekly_pr_cap", 10) - prs_this_week
        ),
    }

    # Repo 30-day contact counts
    repo_usage: Dict[str, Any] = {}
    month_ago = now - 30 * 24 * 3600
    for rkey, data in rl.get("repos", {}).items():
        contacts = sum(
            1 for ts in data.get("contact_timestamps", [])
            if isinstance(ts, (int, float)) and ts > month_ago
        )
        repo_usage[rkey] = {
            "contacts_last_30d": contacts,
            "contact_limit": 1,
            "available": contacts == 0,
        }

    return tool_result(
        success=True,
        operator=operator_usage,
        repos=repo_usage,
        global_caps=rl.get("global", {}),
    )


def _handle_claim_repo(repo: str, operator: str) -> str:
    if not repo or not repo.strip():
        return tool_error("repo is required for claim_repo")
    if not operator or not operator.strip():
        return tool_error("operator is required for claim_repo")

    ledger = _load_ledger()
    key = _repo_key(repo)
    entry = ledger.setdefault("repos", {}).get(key)
    if not entry:
        entry = {
            "repo": repo.strip(),
            "candidate_id": None,
            "stage": 0,
            "status": "backlog",
            "claimed_by": None,
            "claimed_at": None,
            "fork": None,
            "worktree_path": None,
            "branch": None,
            "commit": None,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "notes": None,
        }
        ledger["repos"][key] = entry

    if entry.get("claimed_by") and entry["claimed_by"] != operator.strip():
        return tool_error(
            f"Repo already claimed by {entry['claimed_by']}. Release before re-claiming.",
            claimed_by=entry["claimed_by"],
        )

    entry["claimed_by"] = operator.strip()
    entry["claimed_at"] = _now_iso()
    entry["updated_at"] = _now_iso()
    _save_ledger(ledger)
    return tool_result(success=True, repo=entry)


def _handle_release_repo(repo: str, operator: Optional[str] = None) -> str:
    if not repo or not repo.strip():
        return tool_error("repo is required for release_repo")

    ledger = _load_ledger()
    key = _repo_key(repo)
    entry = ledger.get("repos", {}).get(key)
    if not entry:
        return tool_error(f"Repo not found in ledger: {repo}")

    if not entry.get("claimed_by"):
        return tool_error(f"Repo {repo} is not claimed.")

    if operator and operator.strip() and entry["claimed_by"] != operator.strip():
        return tool_error(
            f"Repo claimed by {entry['claimed_by']}, not {operator}. Cannot release.",
            claimed_by=entry["claimed_by"],
        )

    entry["claimed_by"] = None
    entry["claimed_at"] = None
    entry["updated_at"] = _now_iso()
    _save_ledger(ledger)
    return tool_result(success=True, repo=entry)


def _handle_get_next_action(repo: str) -> str:
    if not repo or not repo.strip():
        return tool_error("repo is required for get_next_action")

    ledger = _load_ledger()
    key = _repo_key(repo)
    entry = ledger.get("repos", {}).get(key)
    if not entry:
        return tool_error(f"Repo not found in ledger: {repo}")

    next_action = _next_stage_action(entry)
    return tool_result(
        success=True,
        repo=entry.get("repo", key),
        stage=entry.get("stage", 0),
        status=entry.get("status", "backlog"),
        claimed_by=entry.get("claimed_by"),
        next_action=next_action,
    )


# ── Router ───────────────────────────────────────────────────────────────────


def oss_contribution_tool(
    *,
    action: str,
    repo: Optional[str] = None,
    status: Optional[str] = None,
    stage: Optional[int] = None,
    operator: Optional[str] = None,
    limit: int = 50,
    include_claimed: bool = True,
    identity: Optional[str] = None,
) -> str:
    normalized = (action or "").strip().lower()

    if normalized == "list_repos":
        return _handle_list_repos(
            status_filter=status,
            limit=limit,
            include_claimed=include_claimed,
        )
    if normalized == "get_repo":
        return _handle_get_repo(repo or "")
    if normalized == "update_status":
        return _handle_update_status(repo or "", status=status, stage=stage)
    if normalized == "check_rate_limits":
        return _handle_check_rate_limits()
    if normalized == "claim_repo":
        return _handle_claim_repo(repo or "", operator or "")
    if normalized == "release_repo":
        return _handle_release_repo(repo or "", operator)
    if normalized == "get_next_action":
        return _handle_get_next_action(repo or "")

    return tool_error(f"Unknown oss_contribution action: {action}")


# ── Registration ─────────────────────────────────────────────────────────────

registry.register(
    name="oss_contribution",
    toolset="oss_contribution",
    schema=OSS_CONTRIBUTION_SCHEMA,
    handler=lambda args, **kw: oss_contribution_tool(
        action=args.get("action", ""),
        repo=args.get("repo"),
        status=args.get("status"),
        stage=args.get("stage"),
        operator=args.get("operator"),
        limit=args.get("limit", 50),
        include_claimed=args.get("include_claimed", True),
        identity=args.get("identity"),
    ),
    check_fn=check_oss_contribution_requirements,
    requires_env=[],
    is_async=False,
    description="Query and manage the OSS contribution ledger state",
    emoji="🌍",
)

# Backwards-compat alias
registry.register(
    name="oss_contribution_ledger",
    toolset="oss_contribution",
    schema=OSS_CONTRIBUTION_SCHEMA,
    handler=lambda args, **kw: oss_contribution_tool(
        action=args.get("action", ""),
        repo=args.get("repo"),
        status=args.get("status"),
        stage=args.get("stage"),
        operator=args.get("operator"),
        limit=args.get("limit", 50),
        include_claimed=args.get("include_claimed", True),
        identity=args.get("identity"),
    ),
    check_fn=check_oss_contribution_requirements,
    requires_env=[],
    is_async=False,
    description="Alias for oss_contribution",
    emoji="🌍",
)


# ── Compatibility wrappers for direct Python callers ─────────────────────────


def list_repos(
    status: Optional[str] = None,
    limit: int = 50,
    include_claimed: bool = True,
) -> str:
    return _handle_list_repos(status_filter=status, limit=limit, include_claimed=include_claimed)


def get_repo(repo: str) -> str:
    return _handle_get_repo(repo)


def update_status(repo: str, status: Optional[str] = None, stage: Optional[int] = None) -> str:
    return _handle_update_status(repo, status=status, stage=stage)


def check_rate_limits() -> str:
    return _handle_check_rate_limits()


def claim_repo(repo: str, operator: str) -> str:
    return _handle_claim_repo(repo, operator)


def release_repo(repo: str, operator: Optional[str] = None) -> str:
    return _handle_release_repo(repo, operator)


def get_next_action(repo: str) -> str:
    return _handle_get_next_action(repo)


def oss_contribution(
    action: str,
    repo: Optional[str] = None,
    status: Optional[str] = None,
    stage: Optional[int] = None,
    operator: Optional[str] = None,
    limit: int = 50,
    include_claimed: bool = True,
    identity: Optional[str] = None,
) -> str:
    return oss_contribution_tool(
        action=action,
        repo=repo,
        status=status,
        stage=stage,
        operator=operator,
        limit=limit,
        include_claimed=include_claimed,
        identity=identity,
    )


# Optional: expose constants for consumers
__all__ = [
    "oss_contribution",
    "oss_contribution_tool",
    "list_repos",
    "get_repo",
    "update_status",
    "check_rate_limits",
    "claim_repo",
    "release_repo",
    "get_next_action",
    "_VALID_STATUSES",
    "_VALID_STAGES",
    "_STAGE_NAMES",
]