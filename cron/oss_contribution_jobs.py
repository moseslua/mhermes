"""OSS contribution harness cron jobs.

Factory functions for the operational cron jobs that support the toned-down,
single-operator OSS contribution harness:

    ledger_sync          — sync ledger state from GitHub API every 15 min
    maintainer_poll      — check for maintainer responses every 6 hours
    bump_draft           — draft bump comments daily at 9am
    rate_limit_check     — enforce single-operator/per-repo rate limits hourly
    repo_claim_cleanup   — legacy cleanup for stale in-progress ledger markers

The first four jobs are the active workflow rails. `repo_claim_cleanup` remains
as local-state hygiene for older ledger entries that still use claim or active
markers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from cron.jobs import create_job

logger = logging.getLogger(__name__)


def _build_repair_prompt(job_name: str, schedule: str) -> str:
    """Return a generic repair prompt for reactive follow-up jobs."""
    return (
        f"The '{job_name}' cron job (schedule: {schedule}) has failed repeatedly. "
        "Investigate the root cause, check the ledger state, rate-limit counters, "
        "cooldown markers, and any stale in-progress entries. Report findings and "
        "suggest a remediation plan."
    )


def _reject_direct_reactive_trigger(
    job_name: str,
    reactive_trigger: Optional[Dict[str, Any]],
) -> None:
    """Scheduled OSS jobs cannot be made reactive directly.

    `create_job` forbids a job from being both scheduled and reactive. We keep the
    argument for a clearer failure mode and direct callers to the supported wiring
    path: `register_all_oss_jobs(repair_after_failures=...)`.
    """
    if reactive_trigger is None:
        return
    raise ValueError(
        f"{job_name} is a scheduled job and cannot accept reactive_trigger directly; "
        "use register_all_oss_jobs(repair_after_failures=...) to attach reactive repair jobs."
    )


def ledger_sync(
    reactive_trigger: Optional[Dict[str, Any]] = None,
    deliver: Optional[str] = None,
) -> Dict[str, Any]:
    """Register the ledger-sync job."""
    name = "ledger_sync"
    _reject_direct_reactive_trigger(name, reactive_trigger)
    schedule = "every 15m"
    prompt = (
        "Sync the OSS contribution ledger from GitHub API to local MCP state.\n\n"
        "Tasks:\n"
        "1. Fetch all open issues from the private ledger repo.\n"
        "2. Update local state with the latest issue metadata, labels, comments, and assignees.\n"
        "3. Detect any new maintainer responses and flag them for downstream processing.\n"
        "4. Report sync summary: issues synced, new responses found, errors.\n"
        "If nothing changed, respond with [SILENT]."
    )
    try:
        job = create_job(
            prompt=prompt,
            schedule=schedule,
            name=name,
            deliver=deliver,
        )
        logger.info("Registered '%s' job: %s", name, job.get("id"))
        return job
    except Exception as exc:
        logger.error("Failed to register '%s' job: %s", name, exc)
        raise


def maintainer_poll(
    reactive_trigger: Optional[Dict[str, Any]] = None,
    deliver: Optional[str] = None,
) -> Dict[str, Any]:
    """Register the maintainer-poll job."""
    name = "maintainer_poll"
    _reject_direct_reactive_trigger(name, reactive_trigger)
    schedule = "every 6h"
    prompt = (
        "Poll upstream GitHub repos for maintainer responses on operator-submitted, "
        "harness-tracked issues and PRs.\n\n"
        "Tasks:\n"
        "1. Query the ledger for entries currently waiting on maintainer response.\n"
        "2. For each entry, fetch the latest comments, reviews, reactions, and labels from the target repo via GitHub API.\n"
        "3. Update the ledger notes/status based on maintainer response:\n"
        "   - positive ack or requested follow-up → keep active and surface next action\n"
        "   - maintainer asks to slow down or otherwise signals frustration → apply a 14-day repo cooldown\n"
        "   - PR labeled spam/invalid → apply a 30-day global halt flag and require manual review\n"
        "   - negative/declined → mark declined and start the 30-day repo re-contact cooldown\n"
        "   - no response after one bump and 7 days → mark no-response and start the 30-day repo re-contact cooldown\n"
        "   - otherwise → leave waiting\n"
        "4. Report summary: replies found, cooldown signals, declines, no-response transitions, still-waiting, errors.\n"
        "If nothing changed, respond with [SILENT]."
    )
    try:
        job = create_job(
            prompt=prompt,
            schedule=schedule,
            name=name,
            deliver=deliver,
        )
        logger.info("Registered '%s' job: %s", name, job.get("id"))
        return job
    except Exception as exc:
        logger.error("Failed to register '%s' job: %s", name, exc)
        raise


def bump_draft(
    reactive_trigger: Optional[Dict[str, Any]] = None,
    deliver: Optional[str] = None,
) -> Dict[str, Any]:
    """Register the bump-draft job."""
    name = "bump_draft"
    _reject_direct_reactive_trigger(name, reactive_trigger)
    schedule = "0 9 * * *"
    prompt = (
        "Draft bump comments for stale OSS contribution threads.\n\n"
        "Tasks:\n"
        "1. Query the ledger for entries waiting on maintainer response with no activity for at least 72 hours.\n"
        "2. Verify rate-limit rules: no more than one bump per issue or PR, never faster than every 72 hours.\n"
        "3. For each eligible entry, draft a short, polite bump comment for human operator review.\n"
        "4. Record the proposed bump in the ledger notes without changing the final outcome state.\n"
        "5. Report summary: eligible entries, bumps drafted, skips, errors.\n"
        "If nothing changed, respond with [SILENT]."
    )
    try:
        job = create_job(
            prompt=prompt,
            schedule=schedule,
            name=name,
            deliver=deliver,
        )
        logger.info("Registered '%s' job: %s", name, job.get("id"))
        return job
    except Exception as exc:
        logger.error("Failed to register '%s' job: %s", name, exc)
        raise


def rate_limit_check(
    reactive_trigger: Optional[Dict[str, Any]] = None,
    deliver: Optional[str] = None,
) -> Dict[str, Any]:
    """Register the rate-limit-check job."""
    name = "rate_limit_check"
    _reject_direct_reactive_trigger(name, reactive_trigger)
    schedule = "every 1h"
    prompt = (
        "Enforce single-operator and per-repo rate limits for the OSS contribution harness.\n\n"
        "Tasks:\n"
        "1. Load current rate-limit counters from ledger/MCP state.\n"
        "2. Enforce weekly operator limits:\n"
        "   - do not exceed 5 new repo first contacts per week; lower counts are acceptable\n"
        "   - issue submissions: up to 3/week\n"
        "   - PR submissions: up to 2/week\n"
        "3. Enforce spacing and per-repo limits:\n"
        "   - minimum 6 hours between issue submissions to different repos\n"
        "   - minimum 24 hours between issue submissions to the same repo\n"
        "   - one new issue or direct PR per repo per 30 days\n"
        "   - the only routine exception is one acknowledged issue-first follow-up PR after 48 hours\n"
        "   - one bump maximum per issue or PR with a 72h minimum gap\n"
        "4. Enforce cooldown triggers:\n"
        "   - maintainer frustration or 'slow down' feedback → 14-day repo cooldown\n"
        "   - PR labeled spam/invalid → 30-day global halt and manual review\n"
        "   - declined or post-bump no-response on a repo → 30-day re-contact cooldown for that repo\n"
        "   - three consecutive no-responses from the same org → 30-day org cooldown\n"
        "   - similar recent rejection in the same repo → 30-day repo cooldown\n"
        "5. Queue blocked actions for later instead of dropping them, and report remaining budget, violations, and cooldowns.\n"
        "If nothing changed, respond with [SILENT]."
    )
    try:
        job = create_job(
            prompt=prompt,
            schedule=schedule,
            name=name,
            deliver=deliver,
        )
        logger.info("Registered '%s' job: %s", name, job.get("id"))
        return job
    except Exception as exc:
        logger.error("Failed to register '%s' job: %s", name, exc)
        raise


def repo_claim_cleanup(
    reactive_trigger: Optional[Dict[str, Any]] = None,
    deliver: Optional[str] = None,
) -> Dict[str, Any]:
    """Register the legacy repo-claim-cleanup job."""
    name = "repo_claim_cleanup"
    _reject_direct_reactive_trigger(name, reactive_trigger)
    schedule = "0 0 * * 0"
    prompt = (
        "Clean up stale in-progress entries in the OSS contribution harness.\n\n"
        "Tasks:\n"
        "1. Query the ledger for repos marked active or claimed but with no meaningful activity in the last 30 days.\n"
        "2. Treat this as legacy local-state hygiene for a single operator, not as a multi-operator coordination system.\n"
        "3. Review whether those entries should be released, deferred, or left untouched for manual follow-up.\n"
        "4. Clear stale claim/in-progress markers where safe to do so and record the cleanup decision in the ledger notes.\n"
        "5. Report summary: entries examined, cleared, retained, errors.\n"
        "If nothing changed, respond with [SILENT]."
    )
    try:
        job = create_job(
            prompt=prompt,
            schedule=schedule,
            name=name,
            deliver=deliver,
        )
        logger.info("Registered '%s' job: %s", name, job.get("id"))
        return job
    except Exception as exc:
        logger.error("Failed to register '%s' job: %s", name, exc)
        raise


def register_all_oss_jobs(
    deliver: Optional[str] = None,
    repair_after_failures: int = 2,
    repair_deliver: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Register the full set of OSS contribution harness cron jobs.

    The weekly cleanup job is retained as legacy local-state hygiene. If
    *repair_after_failures* is provided (> 0), each scheduled job gets a
    reactive repair child that runs when the parent fails repeatedly.
    """
    results: Dict[str, Dict[str, Any]] = {}

    jobs = [
        ledger_sync,
        maintainer_poll,
        bump_draft,
        rate_limit_check,
        repo_claim_cleanup,
    ]

    for factory in jobs:
        try:
            job = factory(deliver=deliver)
            results[job["name"]] = job
        except Exception as exc:
            logger.error("Failed to register OSS job '%s': %s", factory.__name__, exc)
            raise

    if repair_after_failures and repair_after_failures > 0:
        for name, source_job in list(results.items()):
            try:
                repair = create_job(
                    prompt=_build_repair_prompt(name, source_job.get("schedule_display", "")),
                    name=f"{name}_repair",
                    deliver=repair_deliver or deliver,
                    reactive_trigger={
                        "job_id": source_job["id"],
                        "after_consecutive_failures": repair_after_failures,
                    },
                )
                results[f"{name}_repair"] = repair
                logger.info(
                    "Registered repair job '%s' → triggers on '%s' failure",
                    repair["name"],
                    name,
                )
            except Exception as exc:
                logger.error("Failed to register repair job for '%s': %s", name, exc)
                raise

    return results


__all__ = [
    "ledger_sync",
    "maintainer_poll",
    "bump_draft",
    "rate_limit_check",
    "repo_claim_cleanup",
    "register_all_oss_jobs",
]
