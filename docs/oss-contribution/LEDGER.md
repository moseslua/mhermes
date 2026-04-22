# Ledger

The ledger is the **source of truth** for all harness activity. You maintain a private GitHub repository where every target repo is tracked as a GitHub issue.

The ledger survives session compaction, agent restarts, and context churn. Any agent, in any session, can read the issue and resume exactly where the last one left off.

---

## Why GitHub Issues?

- **Survives compaction:** State lives outside the agent session.
- **Resumable:** Any later run can reconstruct progress from checkboxes and comments.
- **Auditable:** Decisions, drafts, and pauses are preserved.
- **Notifying:** Native GitHub notifications keep you informed.
- **Structured:** Checkbox state is easy for both humans and agents to parse.

---

## Issue Template

Every ledger issue follows this format:

```markdown
## Repo: owner/repo

### Status
- [ ] Stage 1: Candidate extraction
- [ ] Stage 2: Direction alignment
- [ ] Stage 3: Deep interview
- [ ] Stage 4: Cross-check
- [ ] Stage 5: Local reproduction
- [ ] Stage 6: Load-bearing exclusion
- [ ] Stage 7: Scope check
- [ ] Stage 8: Merge pattern match
- [ ] Stage 9: Draft issue/PR
- [ ] Stage 10: Human review & send
- [ ] Stage 11: Maintainer response
- [ ] Stage 12: PR draft & send (if issue-first)
- [ ] Stage 13: Review response

### Metadata
- **Security fix:** yes / no
- **Direct PR:** yes / no
- **First contact date:** YYYY-MM-DD
- **Issue URL:** (filled after Stage 10 if issue-first)
- **PR URL:** (filled after Stage 10 or Stage 12)

### Notes
- Maintainer response time: N days
- Outcome: pending / merged / declined / no-response / cooldown
- Worktree path: `/path/to/isolated/worktree`
- Reproduction evidence: (link to worktree, test output, or notes)
```

---

## Labels

Apply these labels for filtering and reporting:

| Label | Meaning |
|---|---|
| `status:active` | Currently progressing through stages |
| `status:waiting` | Waiting on maintainer response |
| `status:deferred` | Deferred due to cooldown, timing, or backlog concerns |
| `status:declined` | Maintainer declined or closed without merge |
| `status:merged` | PR was merged |
| `status:no-response` | No maintainer response after one bump and 7 days |
| `status:cooldown` | Temporarily paused due to trust or timing signals |
| `priority:high` | High-value bug or urgent fix |
| `priority:normal` | Standard bug fix |
| `priority:low` | Minor fix, nice-to-have |

---

## Checkbox Conventions

Checkboxes are the canonical progress indicator.

- **Checked (`[x]`):** Stage complete
- **Unchecked (`[ ]`):** Stage pending
- **Checked with note:** Stage complete with a caveat documented in a comment
- **Strikethrough:** Stage intentionally skipped

Examples:
- Direct PR for a trivial fix: `~~[ ] Stage 12: PR draft & send (if issue-first)~~`
- Submission dropped after failed reproduction: later stages remain unchecked

### Agent behavior

When an agent completes a stage, it should:
1. Check the box
2. Add a comment with:
   - what was done
   - links to artifacts
   - any key decisions made
   - the next required action

### Human behavior

When you complete a stage, you should:
1. Check the box
2. Add a short confirming comment

Examples:
- `Issue submitted: https://github.com/owner/repo/issues/123`
- `PR submitted: https://github.com/owner/repo/pull/456`
- `Cooldown started after maintainer asked to slow down; revisit after 2026-05-15`

---

## State Transitions

```text
[Stage 1] → [Stage 2] → [Stage 3] → [Stage 4] → [Stage 5] → [Stage 6] → [Stage 7] → [Stage 8] → [Stage 9] → [Stage 10] → [Stage 11] → [Stage 12] → [Stage 13]
```

Special paths:
- **Stage 3 deferred** → `status:deferred` → re-enters queue after cooldown
- **Stage 5 no reproduction** → `status:declined` (terminal)
- **Stage 9 direct PR chosen** → Stage 10 submits PR directly; Stage 12 is skipped
- **Stage 11 no response after one bump** → `status:no-response` (terminal)
- **Stage 11 declined** → `status:declined` (terminal)
- **Stage 13 merged** → `status:merged` (terminal)
- **Maintainer frustration / spam signal** → `status:cooldown` until manual re-review

---

## Terminal States

A ledger issue ends in one of these states:

| Terminal state | Meaning |
|---|---|
| `merged` | PR merged successfully |
| `declined` | Dropped, rejected, or not worth continuing |
| `no-response` | No maintainer response after reasonable follow-up |
| `cooldown` | Stopped due to trust or timing signal; do not resume automatically |

---

## Resume Rules

When resuming from the ledger:

1. Read the latest checkbox state
2. Read the latest comments
3. Determine whether a cooldown or wait period is active
4. Resume from the **first unchecked stage** unless a comment explicitly says otherwise
5. Never repeat a completed stage unless new evidence requires redoing it

Examples:
- If Stage 10 is checked and Stage 11 is unchecked, you are waiting on maintainer response
- If Stage 5 is unchecked and a comment says reproduction failed, the issue is effectively terminal even if later boxes remain unchecked
- If Stage 12 is struck through, the contribution used the direct-PR path

---

## Comments as Durable Memory

Comments should preserve the reasoning that checkboxes cannot.

Use comments to record:
- why a candidate was deferred
- why a bug was judged non-load-bearing
- which merged PRs shaped the writing style
- what reproduction command proved the issue
- why a direct PR was chosen instead of issue-first
- why a cooldown was entered

Good comments are short, factual, and legible to a future you who has forgotten the repo.

---

## Example Ledger Entries

### Example 1: Standard Bug Fix (Success Path)

```markdown
## Repo: acme/widget-lib

### Status
- [x] Stage 1: Candidate extraction — Found null-pointer bug in `Widget.render()`
- [x] Stage 2: Direction alignment — Contributing guide accepts bug fixes
- [x] Stage 3: Deep interview — Proceed; not spam-like
- [x] Stage 4: Cross-check — No duplicates found
- [x] Stage 5: Local reproduction — Reproduced in worktree `/tmp/harness/acme-widget-lib`
- [x] Stage 6: Load-bearing exclusion — Not load-bearing
- [x] Stage 7: Scope check — Minor fix, appropriate
- [x] Stage 8: Merge pattern match — Maintainer prefers concise commits, tests required
- [x] Stage 9: Draft issue/PR — Drafted issue with reproduction steps and proposed fix
- [x] Stage 10: Human review & send — Submitted issue: https://github.com/acme/widget-lib/issues/42
- [x] Stage 11: Maintainer response — Maintainer acknowledged, asked for PR
- [x] Stage 12: PR draft & send — Submitted PR: https://github.com/acme/widget-lib/pull/43
- [x] Stage 13: Review response — Approved and merged

### Metadata
- **Security fix:** no
- **Direct PR:** no
- **First contact date:** 2026-04-01
- **Issue URL:** https://github.com/acme/widget-lib/issues/42
- **PR URL:** https://github.com/acme/widget-lib/pull/43

### Notes
- Outcome: merged
- Maintainer response time: 2 days
- Worktree path: `/tmp/harness/acme-widget-lib`
```

### Example 2: Declined (No Reproduction)

```markdown
## Repo: acme/other-lib

### Status
- [x] Stage 1: Candidate extraction — Found race condition in `ConnectionPool`
- [x] Stage 2: Direction alignment — OK
- [x] Stage 3: Deep interview — Proceed cautiously
- [x] Stage 4: Cross-check — No duplicates
- [ ] Stage 5: Local reproduction — Could not reproduce reliably after 5 attempts
- [ ] Stage 6: Load-bearing exclusion
- [ ] Stage 7: Scope check
- [ ] Stage 8: Merge pattern match
- [ ] Stage 9: Draft issue/PR
- [ ] Stage 10: Human review & send
- [ ] Stage 11: Maintainer response
- [ ] Stage 12: PR draft & send (if issue-first)
- [ ] Stage 13: Review response

### Metadata
- **Security fix:** no
- **Direct PR:** no
- **First contact date:** 2026-04-05
- **Issue URL:**
- **PR URL:**

### Notes
- Outcome: declined
- Reason: Could not reliably reproduce after 5 attempts
- Worktree path: `/tmp/harness/acme-other-lib`
- Decision: Drop. No reproduction = no submission.
```

### Example 3: Deferred (Cooldown)

```markdown
## Repo: acme/popular-lib

### Status
- [x] Stage 1: Candidate extraction — Found off-by-one in `Parser.tokenize()`
- [x] Stage 2: Direction alignment — OK
- [ ] Stage 3: Deep interview — DEFERRED
- [ ] Stage 4: Cross-check
- [ ] Stage 5: Local reproduction
- [ ] Stage 6: Load-bearing exclusion
- [ ] Stage 7: Scope check
- [ ] Stage 8: Merge pattern match
- [ ] Stage 9: Draft issue/PR
- [ ] Stage 10: Human review & send
- [ ] Stage 11: Maintainer response
- [ ] Stage 12: PR draft & send (if issue-first)
- [ ] Stage 13: Review response

### Metadata
- **Security fix:** no
- **Direct PR:** no
- **First contact date:** 2026-04-12
- **Issue URL:**
- **PR URL:**

### Notes
- Outcome: cooldown
- Reason: Similar contribution to this repo was sent 14 days ago; wait before re-engaging
- Cooldown until: 2026-04-26
```

### Example 4: Direct PR (Trivial Fix)

```markdown
## Repo: acme/docs-site

### Status
- [x] Stage 1: Candidate extraction — Found broken docs code sample
- [x] Stage 2: Direction alignment — Docs fixes accepted directly
- [x] Stage 3: Deep interview — Proceed; trivial and useful
- [x] Stage 4: Cross-check — No duplicate docs fix open
- [x] Stage 5: Local reproduction — Confirmed snippet fails as written
- [x] Stage 6: Load-bearing exclusion — Not load-bearing
- [x] Stage 7: Scope check — Tiny docs change
- [x] Stage 8: Merge pattern match — Maintainers accept direct docs PRs
- [x] Stage 9: Draft issue/PR — Drafted direct PR
- [x] Stage 10: Human review & send — Submitted PR: https://github.com/acme/docs-site/pull/88
- [x] Stage 11: Maintainer response — Review requested one wording change
- ~~[ ] Stage 12: PR draft & send (if issue-first)~~
- [x] Stage 13: Review response — Updated PR and merged

### Metadata
- **Security fix:** no
- **Direct PR:** yes
- **First contact date:** 2026-04-18
- **Issue URL:**
- **PR URL:** https://github.com/acme/docs-site/pull/88

### Notes
- Outcome: merged
- Maintainer response time: 1 day
```

---

## Ledger Sync

A periodic sync job can mirror ledger issue state into local state, but the GitHub issue remains canonical.

A sync pass should:
1. fetch ledger issues
2. parse checkbox state and labels
3. update local queue / waiting / cooldown views
4. never overwrite the ledger from stale local state

The direction of truth is simple:

**GitHub issue first. Local cache second.**
