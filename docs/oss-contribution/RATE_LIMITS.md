# Rate Limits

This document defines all rate limits enforced by the Hermes OSS Contribution Harness v2.5. Limits are organized by scope: per-identity and per-repo.

All limits are **enforced, not advisory**. The `rate_limit_check` cron job runs every hour and blocks any action that would exceed a limit.

---

## Per-Identity Limits

Each operator identity (GitHub account) has its own rate envelope. These limits are designed to keep the account within GitHub's "natural active contributor" velocity signature.

| Action | Rate | Rationale |
|--------|------|-----------|
| **New repo first contact** | 3–5 repos / week | Matches the pace of an active open-source contributor who explores new projects organically. Below the threshold that triggers GitHub's volume-based abuse heuristics. |
| **Issue submissions** | Up to 3 / week | Gives maintainers time to respond before the next submission. Prevents the account from appearing as a "drive-by" reporter. |
| **PR submissions** | Up to 2 / week | Keeps both direct PRs and acknowledged issue-first follow-up PRs inside a natural contributor envelope. This limit ensures the account is not perceived as a high-volume contributor. |
| **Comments on own issues/PRs** | Unlimited | Engaging in follow-up conversation on your own issues and PRs is expected behavior. There is no limit because it signals genuine interest. |
| **Stars / follows** | Natural, no automation | Star and follow activity must be organic and at human discretion. Automated starring is a known abuse signal. |
| **Issue submission spacing (different repos)** | Minimum 6 hours | Prevents burst patterns. Even across different repos, rapid-fire submissions look automated. |
| **Issue submission spacing (same repo)** | Minimum 24 hours | Respect the maintainer's time. Never flood a single project with multiple issues in quick succession. |

### Cooldown Triggers

| Trigger | Cooldown | Rationale |
|---------|----------|-----------|
| Maintainer asks contributor to slow down or expresses frustration | 14 days | Repo-level pause to reset the local trust signal and demonstrate responsiveness to feedback. |
| PR labeled `spam` or `invalid` | 30 days | Emergency brake. All activity stops until the operator reviews the method and clears the flag. |
| Similar PR/issue rejected by same repo (same category of fix) | 30 days | Prevents repeated attempts that would be perceived as spam. Reassess the approach before re-engaging. |
| 3 consecutive no-responses from the same organization | 30 days | Signals the org is not receptive to outside contributions. Cooldown prevents wasting both sides' time. |

---

## Per-Repo Limits

These limits prevent any single project from being overwhelmed by contributions from the harness.

| Action | Rate | Rationale |
|--------|------|-----------|
| **New issue or direct PR** | 1 / month per identity | A single project should not receive more than one new issue or direct PR per month from the same account. This respects project bandwidth. |
| **Acknowledged follow-up PR** | 1 after 48 hours on an issue-first path | The only routine exception is the single follow-up PR after maintainer acknowledgment on an issue-first contribution. |
| **Bumps** | 1 per issue or PR, minimum 72 hours between bumps | Only one polite bump is allowed per issue or PR. Bumping faster than 72 hours is considered nagging and damages maintainer trust. |
| **Repo re-contact cooldown** | 30 days after `declined` or post-bump `no-response` | If a repo declines an issue, or still does not respond 7 days after the single allowed bump, the identity must wait 30 days before re-engaging that repo. |

---

## Enforcement

The `rate_limit_check` cron job runs every hour and performs the following checks before allowing new issue or PR creation actions:

1. **Identity velocity check:** Counts actions (issues, PRs, first contacts) in the trailing 7-day window for the acting identity.
2. **Repo contact check:** Verifies the repo has not received a new issue or direct PR from the identity in the last 30 days, unless the current action is the single allowed follow-up PR on an acknowledged issue-first path.
3. **Bump eligibility check:** Verifies at least 72 hours have passed since the last bump on this issue or PR, and no bump has already been sent.
4. **Cooldown check:** Verifies repo-level, org-level, and global cooldown markers separately before allowing the action.

If any check fails, the action is **queued** (not dropped) and retried at the next check interval. The operator is notified via the ledger.

---

## Why These Limits?

The original harness did 100 repos in 72 hours. That velocity signature is what triggered suspension. The v2.5 limits are derived from observing the behavior of established, trusted open-source contributors:

- An active contributor might touch 3–5 new repos in a week while exploring.
- They submit a few issues per week, not a flood.
- They open PRs only after a conversation, not before.
- They don't bump maintainers aggressively.
- They engage in organic discussion, not just bug reports.

By designing the velocity envelope to match natural contributor behavior, the harness stays within GitHub's natural contributor envelope and avoids tripping volume-based abuse heuristics. The goal is to be indistinguishable from a human contributor — because it *is* a human, amplified by tooling, not replaced by it.

Rate limits are the **primary compliance mechanism**. They protect the account, respect maintainers, and keep the harness sustainable over the long term.
