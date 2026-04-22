# Operator Guide

This guide explains how a single operator runs the toned-down OSS contribution harness in a way that preserves the original method while staying inside a normal contributor velocity envelope.

The harness still does the heavy lifting:
- candidate discovery
- project-direction filtering
- deep interview / branch decision
- local reproduction
- merge-pattern matching
- draft issue / PR preparation

The operator still owns the trust boundaries:
- deciding what is worth sending
- reading every draft before it leaves the machine
- submitting issues and PRs manually
- signing CLAs and contributor agreements personally
- deciding whether to respond, pause, or drop after feedback

---

## Weekly Budget

You have **3-5 repo slots per week**.

Spend them on the highest-value candidates:
1. clearly reproducible bugs
2. small, scoped fixes that match recent merges
3. repos with active maintainers and normal review flow
4. changes that are worth a maintainer's time

Do not try to "use up" the budget. Unused capacity is fine. The point is to avoid burst behavior, not to maximize weekly output.

---

## Daily Routine

### 1. Review the ledger

Start with your private ledger repo.

Check:
- repos waiting on Stage 10 human review
- repos waiting on Stage 11 maintainer response
- repos in cooldown
- repos deferred for later re-check
- your remaining weekly submission budget

### 2. Pick the next repo

Prefer this order:
1. existing in-flight work with maintainer replies
2. repos where reproduction is already complete
3. new candidates only if you still have weekly budget

### 3. Run the harness stages

For each repo, move through the stages in order:
1. Candidate extraction
2. Direction alignment
3. Deep interview
4. Cross-check / dedupe
5. Local reproduction
6. Load-bearing exclusion
7. Scope check
8. Merge-pattern match
9. Draft issue or PR
10. Human review & send
11. Maintainer response
12. PR draft & send (if issue-first and acknowledged)
13. Review response

The rule is unchanged from the original harness:

**No reproduction = no submission.**

### 4. Human review before every send

Before clicking submit, read the draft as if you were the maintainer.

Ask:
- Is this actually useful?
- Is the tone natural for this project?
- Is the scope small enough?
- Would I merge this if I maintained the repo?
- Does this look like a real contribution, not a harness artifact?

If the answer is no, fix the draft or drop it.

---

## Issue-First vs Direct PR

### Use issue-first for:
- non-trivial bug fixes
- unclear maintainer intent
- behavior changes
- anything that needs discussion
- repos with conservative review culture

### Use a direct PR for:
- docs typos
- small null checks
- tiny test fixes
- one-line obvious correctness fixes
- projects where recent merges show maintainers accept small direct PRs

When in doubt, open the issue first.

---

## Submission Rules

Stay inside these limits:

### Weekly
- **New repo first contact:** 3-5 repos
- **Issue submissions:** up to 3
- **PR submissions:** up to 2

### Per repo
- **One new issue or direct PR per month** for the same repo
- **One acknowledged follow-up PR** allowed on an issue-first path after 48 hours
- **Minimum 6 hours between issue submissions** to different repos
- **Minimum 24 hours between issue submissions** to the same repo
- **One bump maximum** per issue or PR
- **Minimum 72 hours before bumping**

These are not productivity constraints. They are trust-preservation constraints.

---

## Security Fixes

Do not invent a special security workflow if the project does not ask for one.

Instead:
1. Check `SECURITY.md`
2. If the project requires private disclosure, follow it
3. If the project has no special policy, treat the fix like a normal contribution
4. If the issue feels too sensitive for public handling, stop and decide manually before sending anything

The harness can identify security-like candidates. The operator decides how to send them.

---

## Cooldown Rules

Pause work when trust signals turn negative.

### Scoped cooldown triggers

| Trigger | Cooldown | Action |
|---|---:|---|
| Maintainer asks you to slow down | 14 days | Stop all activity on that repo |
| Similar contribution was recently rejected | 30 days | Defer and revisit that repo later |
| Same org has 3 consecutive no-responses | 30 days | Deprioritize that organization |

### Hard stop triggers

| Trigger | Action |
|---|---|
| PR labeled `spam` or `invalid` | Stop all harness submissions for 30 days and review your method |
| GitHub warning / restriction / suspension | Stop immediately and do not resume until you understand why |
| Your own draft feels templated or unnatural | Do not send it |

---

## Handling Maintainer Feedback

### Positive response
- reply normally
- keep the diff small
- answer the comment directly
- do not introduce new scope
- update the ledger immediately

### No response
- wait
- if 72+ hours have passed, draft one polite bump
- if 7 days pass with no response after the bump, mark `no-response`, start the 30-day repo re-contact cooldown, and move on

### Negative response
- do not argue
- close cleanly if appropriate
- mark the repo `declined` and start the 30-day repo re-contact cooldown
- log the reason in the ledger
- move on

### Frustrated response
Examples:
- "please slow down"
- "too many PRs"
- "this feels like contribution farming"
- "please open an issue first next time"

Action:
1. acknowledge briefly if a response is needed
2. stop activity on that repo
3. enter cooldown
4. log it in your weekly personal review
5. adjust the method if the criticism is fair

---

## Weekly Personal Review

Once a week, review the ledger and your GitHub activity.

Check:
- how many repos you touched
- how many submissions you made
- how many got responses
- how many merged
- whether any maintainers seemed annoyed
- whether your drafts are getting too templated
- whether you're drifting toward low-value fixes

Suggested review questions:
1. Which submissions were clearly worth it?
2. Which ones felt marginal in hindsight?
3. Where did the harness save time?
4. Where did it produce drafts that needed heavy human correction?
5. Are you staying inside the weekly budget naturally, or forcing throughput?

If the answer to (5) is "forcing throughput," slow down.

---

## Identity Maintenance

Your GitHub identity is an asset. Protect it.

- Star repos organically
- Comment on discussions you actually care about
- Make non-harness contributions too
- Avoid bursty behavior
- Let your profile look like a person who uses tools, not a tool wearing a person

The goal is not disguise. The goal is to behave like an actual, thoughtful contributor — because that is what you are supposed to be.

---

## When to Pause

Stop and review your activity in these situations:

| Situation | Action |
|---|---|
| Your GitHub account receives a warning or suspension | Immediate stop |
| A maintainer accuses you of spam or farming | Enter cooldown and review your recent submissions |
| You discover a potentially sensitive security issue | Check `SECURITY.md` and decide manually before sending |
| The harness draft feels wrong in tone, scope, or confidence | Do not submit |
| You suspect you are violating weekly limits | Stop and review `RATE_LIMITS.md` |

---

## The Point

The original harness was right about the method.

What needed changing was not the quality bar. It was the rate.

This guide keeps the original idea intact:
- real bugs
- real reproduction
- real maintainer fit
- real human attestation

It just runs at a speed that a platform can read as normal contribution instead of coordinated abuse.
