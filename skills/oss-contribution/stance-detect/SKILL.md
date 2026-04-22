---
name: stance-detect
description: Evaluate whether a target OSS project is healthy and receptive to external contributions by inspecting CONTRIBUTING.md, README.md, recent maintainer activity, and issue volume. Classifies viability as proceed, defer, or security-track.
version: 2.5.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [OSS, Contributing, Project-Health, Viability, Open-Source]
    related_skills: [github-repo-management, github-issues, github-pr-workflow]
---

# OSS Project Vibe Check

Inspect an open-source repository to determine whether it is a viable target for an external contribution. This skill reads public project files and recent maintainer communications, then classifies the project's contribution health.

## When to Use

- Before opening a PR or issue to an unfamiliar repository
- When evaluating whether a project is worth investing time in
- During repository audits for contribution viability
- When the user asks "Should I contribute to this project?"

## Prerequisites

- Access to the target repository (public, or authenticated for private)
- `gh` CLI or `curl` with a `GITHUB_TOKEN` for activity queries

## 1. Files to Inspect

Read these files in the target repo's default branch. Use `raw.githubusercontent.com`, `gh`, or local clone.

### Primary Sources

| File | What to Look For |
|------|------------------|
| `CONTRIBUTING.md` | Contribution guidelines, coding standards, PR requirements, environment setup |
| `README.md` | Project description, maturity badges, maintenance status, contribution call-to-action |
| `SECURITY.md` | Security policy presence, disclosure process, contact method |
| `.github/ISSUE_TEMPLATE/*.md` | Issue triage process, required fields, maintainer engagement style |
| `.github/pull_request_template.md` | PR expectations, review process, checklist items |

### Secondary Sources

- **Recent closed issues/PRs** (last 90 days): maintainer response time, merge cadence, tone
- **Open issue count**: total volume and whether the project appears overwhelmed
- **Recent commits**: maintainer activity on the default branch
- **Pinned issues**: maintenance status announcements, contribution calls

## 2. Decision Rules

Classify into exactly one of `proceed`, `defer_overwhelmed`, `defer_inactive`, or `security_track_needed`.

### `defer_inactive`

Match **any** of these:
- No commits to the default branch in the last 90 days
- No maintainer responses to issues or PRs in the last 90 days
- README or pinned issue explicitly states the project is unmaintained, archived, or seeking new maintainers
- Last release was more than 12 months ago with no recent activity

### `defer_overwhelmed`

Match **any** of these:
- 500+ open issues with minimal maintainer triage activity
- PR backlog of 50+ open PRs with no recent merges or reviews
- Maintainers are responsive but clearly backlogged (e.g., "we're behind on reviews", "please be patient")
- High issue-to-maintainer ratio with slow turnaround

### `security_track_needed`

Match **all** of these:
- Project has a `SECURITY.md` file or documented security policy
- The contribution being considered is security-related (bug fix, vulnerability patch, hardening)
- The security disclosure process requires coordinated disclosure or pre-reporting

### `proceed`

Default classification. Match **all** of these:
- Project shows active maintainer engagement within the last 90 days
- Open issue count is below 500 or maintainer triage is keeping pace
- CONTRIBUTING.md exists and provides clear guidance (or README covers it adequately)
- No signals indicating the project is unmaintained or overwhelmed

## 3. Inspection Workflow

```bash
# Set target repo
OWNER_REPO="owner/repo"

# 1. Fetch CONTRIBUTING.md
curl -sL "https://raw.githubusercontent.com/$OWNER_REPO/HEAD/CONTRIBUTING.md" | head -100

# 2. Fetch README.md
curl -sL "https://raw.githubusercontent.com/$OWNER_REPO/HEAD/README.md" | head -100

# 3. Fetch SECURITY.md if present
curl -sL "https://raw.githubusercontent.com/$OWNER_REPO/HEAD/SECURITY.md" | head -50

# 4. Check open issue count and recent activity
curl -s "https://api.github.com/repos/$OWNER_REPO" \
  -H "Authorization: token $GITHUB_TOKEN" | jq '{open_issues, forks, pushed_at, updated_at}'

# 5. List recent closed PRs to gauge merge cadence
curl -s "https://api.github.com/repos/$OWNER_REPO/pulls?state=closed&sort=updated&direction=desc&per_page=10" \
  -H "Authorization: token $GITHUB_TOKEN" | jq -r '.[] | "#\(.number): \(.title) (merged: \(.merged_at // "not merged"))"'

# 6. List recent issues with maintainer comments
curl -s "https://api.github.com/repos/$OWNER_REPO/issues?state=all&sort=updated&direction=desc&per_page=20" \
  -H "Authorization: token $GITHUB_TOKEN" | jq -r '.[] | "#\(.number): \(.title) (updated: \(.updated_at), comments: \(.comments))"'
```

## 4. Health Signals

Use these signals to weight evidence.

### Positive Signals
- Recent merges or releases within the last 30-90 days
- Maintainers actively commenting on and closing issues
- Clear CONTRIBUTING.md with setup instructions and review process
- Pinned issues inviting contributions or outlining good first issues
- Security policy present and documented

### Negative Signals
- No commits in 90+ days
- Issues and PRs left untouched for months
- README disclaimer: "not actively maintained", "looking for maintainers", "archived"
- 500+ open issues with no triage labels or responses
- PRs auto-closed by stale bots without maintainer review

### Neutral / Context-Dependent Signals
- DCO or CLA required (proceed, but note the requirement)
- Strict coding standards or test requirements (proceed, but account for extra effort)
- Non-English primary language (proceed, but communication may need translation)

## 5. Output Format

After inspection, report findings in this exact structure:

```yaml
repo: owner/repo
classification: proceed | defer_overwhelmed | defer_inactive | security_track_needed
confidence: high | medium | low
sources_inspected:
  - CONTRIBUTING.md: <found / not_found / partial>
  - README.md: <found / not_found / partial>
  - SECURITY.md: <found / not_found>
  - open_issues: <count>
  - recent_maintainer_activity: <active / sporadic / none>
evidence:
  positive:
    - "<exact quote or summary>"
  negative:
    - "<exact quote or summary>"
  neutral:
    - "<exact quote or summary>"
recommendation: "<proceed | defer | track_security>"
notes: "<optional context>"
```

### Recommendation Mapping

| Classification | Recommendation |
|----------------|----------------|
| `proceed` | `proceed` — project is healthy and receptive |
| `defer_overwhelmed` | `defer` — wait or choose a narrower, well-scoped contribution |
| `defer_inactive` | `defer` — project is unmaintained; contributions may not be reviewed |
| `security_track_needed` | `track_security` — follow the project's security disclosure process before proceeding |

## 6. Edge Cases

- **No CONTRIBUTING.md exists:** Rely on README, recent activity, and maintainer engagement. Default to `proceed` if activity is healthy, `defer_inactive` if activity is stale.
- **Fork vs upstream:** Inspect the repo you intend to contribute to. A fork may have different maintenance status than upstream.
- **Multi-org projects (e.g., CNCF, Apache):** Foundation projects often have healthy infrastructure but slower review cycles. Account for bureaucratic overhead in classification.
- **Non-English repos:** Translate key sections before classification. Maintainership signals (dates, commit activity) are language-independent.
- **Monorepos:** Check activity in the specific sub-package or directory you intend to touch, not just the whole repo.

## 7. Verification Checklist

Before finalizing the report:

- [ ] CONTRIBUTING.md read (or confirmed absent)
- [ ] README.md scanned for maintenance status and contribution guidance
- [ ] SECURITY.md checked for security policy presence
- [ ] Open issue count noted
- [ ] Recent maintainer activity reviewed (minimum 5 issues/PRs if available)
- [ ] Classification matches strongest signal found
- [ ] Confidence level justified by evidence volume and clarity
