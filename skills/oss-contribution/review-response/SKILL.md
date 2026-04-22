---
name: review-response
description: Stage 13 of the OSS contribution harness. Analyze maintainer and bot feedback on open PRs, decide the next action (revise, comment, close, or proceed), track review sentiment, and flag identities for cooldown when maintainers express frustration.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [OSS, Open-Source, Pull-Requests, Code-Review, Maintainer-Relations, Stage-13]
    related_skills: [github-pr-workflow, github-code-review, draft-pr, merge-pattern]
---

# Review Response Loop (Stage 13)

After a PR has been submitted and reviewed by maintainers or bots, analyze the feedback, decide the correct next action, and update the ledger. This skill is the final gate before a contribution is either merged, revised, or abandoned.

## Prerequisites

- The PR has been submitted (see `draft-pr` skill, Stage 12)
- The ledger issue for this repo is in `status: pr_submitted`
- Authenticated with GitHub (see `github-auth` skill)

### Setup

```bash
if command -v gh &>/dev/null && gh auth status &>/dev/null; then
  AUTH="gh"
else
  AUTH="git"
  if [ -z "$GITHUB_TOKEN" ]; then
    if [ -f ~/.hermes/.env ] && grep -q "^GITHUB_TOKEN=" ~/.hermes/.env; then
      GITHUB_TOKEN=$(grep "^GITHUB_TOKEN=" ~/.hermes/.env | head -1 | cut -d= -f2 | tr -d '\n\r')
    elif grep -q "github.com" ~/.git-credentials 2>/dev/null; then
      GITHUB_TOKEN=$(grep "github.com" ~/.git-credentials 2>/dev/null | head -1 | sed 's|https://[^:]*:\([^@]*\)@.*|\1|')
    fi
  fi
fi

REMOTE_URL=$(git remote get-url origin)
OWNER_REPO=$(echo "$REMOTE_URL" | sed -E 's|.*github\.com[:/]||; s|\.git$||')
OWNER=$(echo "$OWNER_REPO" | cut -d/ -f1)
REPO=$(echo "$OWNER_REPO" | cut -d/ -f2)
```

---

## 1. Fetch Review Feedback

Pull all comments, review summaries, and labels on the PR.

### List PR Reviews

**With gh:**

```bash
gh pr view <PR_NUMBER> --json number,state,title,labels,reviews,comments,mergeStateStatus
```

**With curl:**

```bash
PR_NUMBER=<number>

curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/$PR_NUMBER \
  | python3 -c "
import sys, json
pr = json.load(sys.stdin)
print(f\"State: {pr['state']}\")
print(f\"Mergeable: {pr.get('mergeable_state', 'unknown')}\")
print(f\"Labels: {[l['name'] for l in pr.get('labels', [])]}\")
"
```

### Fetch Review Comments

**With gh:**

```bash
gh api repos/$OWNER/$REPO/pulls/$PR_NUMBER/reviews --jq '.[] | {user: .user.login, state: .state, body: .body}'
```

**With curl:**

```bash
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/$PR_NUMBER/reviews \
  | python3 -c "
import sys, json
for r in json.load(sys.stdin):
    print(f\"Reviewer: {r['user']['login']}\")
    print(f\"State: {r['state']}\")
    print(f\"Body: {r.get('body','')[:200]}\")
    print('---')
"
```

### Fetch Issue-Level Comments

**With gh:**

```bash
gh pr view $PR_NUMBER --comments
```

**With curl:**

```bash
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/issues/$PR_NUMBER/comments \
  | python3 -c "
import sys, json
for c in json.load(sys.stdin):
    print(f\"{c['user']['login']}: {c['body'][:200]}\")
"
```

### Fetch Check Status

**With gh:**

```bash
gh pr checks $PR_NUMBER
```

**With curl:**

```bash
SHA=$(curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/$PR_NUMBER \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['head']['sha'])")

curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/commits/$SHA/check-runs \
  | python3 -c "
import sys, json
for cr in json.load(sys.stdin).get('check_runs', []):
    print(f\"  {cr['name']}: {cr['status']} / {cr['conclusion'] or 'pending'}\")
"
```

---

## 2. Analyze Sentiment

Classify each review into one of four buckets. This drives the decision in Section 3.

| Sentiment | Signals | Example Phrases |
|-----------|---------|-----------------|
| **Positive** | Approve, LGTM, minor nits only | "LGTM", "Looks good, just one suggestion", "Approved with minor comments" |
| **Neutral / Constructive** | Request for specific changes, questions | "Can you add a test for this?", "Why did you choose X over Y?", "Please update the docs" |
| **Negative / Frustrated** | Complaints about volume, tone, or process | "Please slow down", "Too many PRs", "We are overwhelmed", "Stop opening PRs" |
| **Reject** | Spam/invalid labels, explicit closure | Label `spam`, `invalid`, `wontfix`; "This is not a bug"; "Closing as not planned" |

### Sentiment Heuristics

- **Frustration keywords:** `stop`, `slow down`, `spam`, `overwhelm`, `too many`, `volume`, `noise`
- **Rejection keywords:** `not a bug`, `won't fix`, `closing`, `decline`, `reject`, `invalid`
- **Approval keywords:** `LGTM`, `approve`, `looks good`, `merge`, `ship it`, `fine by me`

If a maintainer uses frustration keywords, flag the identity for cooldown regardless of whether the PR is eventually merged.

---

## 3. Decide Next Action

Use the most severe sentiment found across all reviews as the deciding factor.

| Most Severe Sentiment | Action | Ledger Update |
|-----------------------|--------|---------------|
| **Reject** (`spam`, `invalid`, or explicit close) | **Halt immediately.** Close the PR (or let maintainer close it). Do not comment further. Trigger human review of the method. | `status: halted_spam_flag` |
| **Negative / Frustrated** | **Cooldown.** Draft a brief, polite acknowledgment if one has not been sent. Do not push new commits or open new PRs to this repo. Flag identity for 14 day cooldown. | `status: cooldown_maintainer_frustration` |
| **Neutral / Constructive** | **Revise.** Address each review comment with a commit or an inline reply. Push changes and re-request review. | `status: revising` |
| **Positive** | **Wait or merge.** If approved and CI passes, the operator may merge. If waiting for additional reviews, do nothing. | `status: approved_pending_merge` or `status: approved` |

### Decision Checklist

Before taking action, verify:

- [ ] All reviews have been read (not just the latest)
- [ ] Labels have been checked (`spam`, `invalid`, `wontfix`)
- [ ] CI status has been checked (a "looks good" with failing CI still needs work)
- [ ] The most severe sentiment has been identified correctly
- [ ] The action chosen is the most conservative valid option

---

## 4. Cooldown & Identity Flagging

### When to Flag

Flag the operator identity for cooldown when **any** of the following occur:

1. A maintainer explicitly asks the contributor to slow down or stop.
2. A maintainer uses the word `spam` or `volume` in reference to the contribution.
3. A PR receives the label `spam` or `invalid`.
4. Two or more consecutive PRs to the same repo are closed without merge.

### Cooldown Rules

| Trigger | Duration | Effect |
|---------|----------|--------|
| Maintainer frustration language | 14 days | No new first-contact to any repo. Existing in-flight issues/PRs may still be monitored but not bumped. |
| `spam` or `invalid` label on PR | 30 days | Full halt. No submissions, no bumps, no comments. Human review required before resuming. |
| Two consecutive closed PRs (same repo, no merge) | 30 days | No contact with that specific repo. Other repos unaffected. |

### Cooldown Command

Update the ledger and local state:

```bash
# In the ledger issue, add a comment:
cat <<'EOF'
## Cooldown Flagged
- Reason: maintainer expressed frustration in PR #<NUMBER>
- Duration: 14 days
- Expires: <DATE>
- Action: no new first-contact until expiry
EOF
```

If using MCP state:

```bash
# Pseudocode — adapt to your OMX state implementation
# mcp_omx_state_state_write(mode="team", state={
#   "identity": "<operator_handle>",
#   "cooldown_until": "<ISO_DATE>",
#   "cooldown_reason": "maintainer_frustration",
#   "source_repo": "owner/repo",
#   "source_pr": <NUMBER>
# })
```

---

## 5. Drafting Responses

### For Neutral / Constructive Reviews

Address every comment. Use inline replies on the PR where possible; reserve issue-level comments for high-level discussion.

**Reply to a single review comment:**

**With gh:**

```bash
# Reply to a specific review comment (requires the comment_id)
gh api repos/$OWNER/$REPO/pulls/$PR_NUMBER/comments/<COMMENT_ID> \
  --method POST \
  -f body="Good catch — fixed in the latest commit."
```

**With curl:**

```bash
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/$PR_NUMBER/comments/<COMMENT_ID>/replies \
  -d '{"body": "Good catch — fixed in the latest commit."}'
```

### General PR Comment After Revisions

**With gh:**

```bash
gh pr comment $PR_NUMBER --body "Thanks for the review. I've addressed all feedback:

- Added the missing test in commit <SHA>
- Updated the docstring per your suggestion
- Rebased onto latest main to resolve the conflict

Please take another look when you have a moment."
```

**With curl:**

```bash
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/issues/$PR_NUMBER/comments \
  -d '{
    "body": "Thanks for the review. I have addressed all feedback in the latest push. Please take another look."
  }'
```

### For Maintainer Frustration

Keep it short, sincere, and non-defensive. Do not justify or explain the harness.

```markdown
Understood — I'll hold off on further contributions here for now. Appreciate the time you've taken to review.
```

Never argue with a maintainer who is frustrated. The goal is to preserve the relationship, not win the argument.

---

## 6. Update the Ledger

After every review-response cycle, update the ledger issue:

```markdown
## Review Response Cycle — <DATE>

- PR: #<NUMBER>
- Review sentiment: positive / neutral / negative / reject
- CI status: passing / failing / pending
- Action taken: revise / cooldown / close / wait
- Next check: <DATE + 48h>
```

If the PR is merged:

```markdown
## Outcome: Merged
- PR: #<NUMBER>
- Merge commit: <SHA>
- Final status: success
```

If the PR is closed or rejected:

```markdown
## Outcome: Closed
- PR: #<NUMBER>
- Reason: <maintainer feedback summary>
- Cooldown applied: yes/no
- Duration: <N> days
```

---

## 7. Auto-Action Patterns

### Daily Poll Loop

The `maintainer-poll` cron job runs every 6 hours. For each open PR in the ledger:

1. Fetch new reviews and comments since the last check.
2. Run sentiment analysis.
3. If sentiment changed to a more severe bucket, trigger the corresponding action.
4. Update the ledger.

### Re-Request Review

After pushing revisions, explicitly re-request review from each reviewer:

**With gh:**

```bash
gh pr ready $PR_NUMBER   # if it was a draft
```

There is no direct CLI command for re-requesting review; use the API:

```bash
gh api repos/$OWNER/$REPO/pulls/$PR_NUMBER/requested_reviewers \
  --method POST \
  -f "reviewers[]=<USERNAME>"
```

**With curl:**

```bash
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/$PR_NUMBER/requested_reviewers \
  -d '{"reviewers": ["<USERNAME>"]}'
```

---

## 8. Emergency Halt

If a PR is labeled `spam` or `invalid`:

1. **Immediately** stop all activity for this identity across all repos.
2. Add a halt comment to the ledger:
   ```markdown
   ## EMERGENCY HALT
   - Trigger: PR #<NUMBER> labeled `spam` or `invalid`
   - Time: <TIMESTAMP>
   - Required: Human operator review before any further submissions.
   ```
3. Notify the operator via their configured notification channel.
4. Do not resume until the operator manually clears the halt.

This is a hard stop. No exceptions.

---

## Summary

| Situation | Do This | Don't Do This |
|-----------|---------|---------------|
| Maintainer approves + CI passes | Merge or wait for second review | Rush to merge without human sign-off |
| Maintainer requests changes | Revise, commit, reply inline | Ignore comments or argue |
| Maintainer seems frustrated | Acknowledge politely, enter cooldown | Defend, explain, or open another PR |
| PR labeled `spam` / `invalid` | Halt all activity, alert human | Comment further or submit elsewhere |
| CI fails after approval | Fix CI, re-push, re-request review | Ask maintainer to merge with failing CI |
| No new reviews for 7 days | Mark `status: stale_review`, deprioritize repo | Bump the PR or maintainer |
