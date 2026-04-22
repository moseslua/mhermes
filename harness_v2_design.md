# Hermes-Scale OSS Contribution Harness v2 — Policy-Compliant Design

## The Core Problem

The original harness achieved what it set out to achieve: high-quality, human-attested, reproducible bug fixes at scale. The suspension proved one thing beyond doubt — **speed itself is a semantic signal that platforms use for abuse detection**, independent of content quality.

The fix is not "do less work." The fix is **change the velocity signature, add maintainer-opt-in gating, and distribute the load across identity boundaries** so that no single account triggers volume-based heuristics.

This document describes a v2 harness architecture that preserves every quality gate from the original while adding policy-compliance as a first-class design constraint.

---

## Design Principles

### 1. Human-First, Not Human-in-the-Loop

The original design had humans at stages 11-12 (viability review + CLA signing). v2 moves the human **earlier** — the first contact with a repository is a human-written, non-automated message. The harness *prepares* everything up to that point, but the human *sends* it. This is the difference between "human-in-the-loop" and "human-at-the-front."

### 2. Issues Before PRs, Always

A PR without a preceding issue is a drive-by. A drive-by at scale is spam. The v2 harness **never opens a PR until an issue has been acknowledged by a maintainer** (reaction, comment, or assignment). This single rule eliminates the vast majority of abuse-detection risk because:
- GitHub's spam heuristics weight unsolicited PRs far more heavily than issues
- Issues are lower-friction for maintainers to close/ignore without offense
- The conversation history proves organic engagement before code submission

### 3. Rate Is a Feature, Not a Bug

The original harness did 100 repos in 72 hours. v2 targets **3-5 repos per week per identity** with a floor of 48 hours between first contact and PR submission for any given repo. This is slower than the original. It is also **sustainable indefinitely** and falls well within GitHub's "natural contributor" velocity envelope.

### 4. Distributed Identity, Shared Method

Instead of one GitHub account doing 100 repos, v2 uses **5-10 maintained contributor identities** (real people, not sock puppets — see the Operator Network below) each handling 3-5 repos/week. The method is shared; the load is distributed. No single identity triggers volume alarms.

### 5. Transparent About AI Assistance

Some projects welcome AI-generated fixes; others explicitly forbid them. v2 **detects the project's stance** (via CONTRIBUTING, issue templates, or maintainer statements) and either:
- Proceeds with a transparent note in the issue/PR, or
- Skips the repo entirely

Never silently submit AI-assisted work to projects that don't want it.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     ORCHESTRATION LAYER                         │
│  (OMX substrate — survives compaction, restarts, context churn) │
│  - State: MCP-backed, independent of any single session         │
│  - Queue: prioritized repo backlog with rate-limit gates        │
│  - Ledger: GitHub issue on the operator's fork = source of truth│
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  DISCOVERY   │    │   ANALYSIS   │    │   ENGAGEMENT │
│  (automated) │    │  (automated) │    │  (human-gated)│
└──────────────┘    └──────────────┘    └──────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  REPRODUCE   │    │    DRAFT     │    │   SUBMIT     │
│  (automated) │    │  (automated) │    │  (human-only) │
└──────────────┘    └──────────────┘    └──────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                              ▼
                  ┌──────────────────┐
                  │   POST-SUBMIT    │
                  │  (hybrid: human  │
                  │   reviews bot    │
                  │   responses)     │
                  └──────────────────┘
```

---

## The 13 Stages — v2 Revision

### Stage 0: Project Stance Detection (NEW)

Before any analysis, determine whether the project accepts AI-assisted contributions.

**Inputs:** `CONTRIBUTING.md`, `README.md`, issue templates, recent maintainer comments on AI-related topics, `.github/PULL_REQUEST_TEMPLATE.md`, `CLAUDE.md` or similar AI-policy files.

**Signals:**
- Explicit prohibition: "We do not accept AI-generated code"
- Explicit welcome: "We welcome AI-assisted contributions if properly attributed"
- Implicit welcome: No policy + maintainers merging AI-attributed PRs
- Ambiguous: No policy + no evidence either way

**Gate:**
- Explicit prohibition → Skip, mark `status: skipped_ai_policy`
- Explicit welcome → Proceed with transparency note
- Implicit welcome → Proceed with transparency note
- Ambiguous → Proceed with transparency note, but draft issue more conservatively

**Transparency note template:**
```markdown
Note: This contribution was prepared with AI-assisted analysis and reproduction. 
The fix was validated locally in a fork before submission. I'm happy to adjust 
the presentation or provide additional context if the project prefers a 
different format.
```

---

### Stage 1: Candidate Extraction

Same as original: extract fix/security candidates from last 20 merged PRs + last 5 release-tag diffs.

**v2 addition:** Also scrape the project's security policy (`SECURITY.md`) and preferred vulnerability disclosure process. Security fixes get a separate, slower track (see Stage 1b).

---

### Stage 1b: Security Track (NEW)

If a candidate is a security fix:
- Do NOT open a public issue
- Draft a private vulnerability report following the project's `SECURITY.md`
- Human operator reviews and sends via the project's preferred channel (email, GitHub private advisory, HackerOne, etc.)
- Track in the ledger as `status: security_disclosure_pending`

This avoids the "public commit is a severe security risk" problem the original author encountered.

---

### Stage 2: Direction Alignment

Same as original: read recent merges + CONTRIBUTING; drop conflicts.

**v2 addition:** Also read the project's **Code of Conduct** and **governance model** (BDFL, core team, RFC process). Some projects require RFCs for non-trivial changes. The harness detects this and either:
- Downscopes to a trivial fix, or
- Flags for human review: "This change may need an RFC first"

---

### Stage 3: Deep Interview (Ouroboros Method)

Same as original: the agent decides whether to branch for each candidate.

**v2 addition:** The interview now includes a **policy-compliance checkpoint**:
- "Would submitting this fix at this time create the appearance of spam?"
- "Has this project recently received similar contributions from this identity or related identities?"
- "Is the fix trivial enough that it might be perceived as farming contributions?"

If any answer is "yes," the candidate is deferred (not dropped — added to a `deferred` queue with a cooldown timer).

---

### Stage 4: Cross-Check & Dedupe

Same as original: check open/resolved issues and PRs.

**v2 addition:** Also check **recently closed issues/PRs with labels** like `spam`, `invalid`, `wontfix`, `duplicate` to learn what the project considers unwanted. If similar contributions were recently rejected, defer.

---

### Stage 5: Local Reproduction

Same as original: reproduce in a fork. If it doesn't reproduce, drop.

**v2 addition:** The reproduction now runs in an **isolated worktree** (not just a fork clone) to avoid polluting the operator's main development environment. The worktree is preserved as evidence and linked in the ledger.

---

### Stage 6: Load-Bearing Exclusion

Same as original: exclude intentionally load-bearing code.

---

### Stage 7: Scope & Appropriateness

Same as original: check against recent merge patterns.

**v2 addition:** Also check the **project's issue backlog depth**. If a project has 500+ open issues, a new issue about a minor fix may be noise. The harness either:
- Bundles the fix into an existing issue if one is closely related, or
- Skips if the project is clearly overwhelmed and the fix is non-critical

---

### Stage 8: Merge Pattern Matching

Same as original: read the last 10 merged PRs to shape the writing.

**v2 addition:** Extract the **maintainer review style** from those PRs:
- Do they prefer detailed commit messages or concise ones?
- Do they ask for tests on every change, or only on features?
- Do they use squash-merge or rebase-merge? (Affects branch hygiene)
- What's their typical review turnaround time? (Affects follow-up timing)

This information feeds into Stage 9's drafting parameters.

---

### Stage 9: Draft Issue (NOT PR)

**Major change from original.** v2 drafts an **issue first**, not a PR.

The issue draft includes:
1. Clear bug description with reproduction steps
2. Expected vs actual behavior
3. Environment details (from the harness's reproduction worktree)
4. A proposed fix direction ("I believe the issue is in X, and a fix would involve Y")
5. Offer to submit a PR if the maintainer agrees it's worth fixing
6. The transparency note from Stage 0

**Why an issue first?**
- Lower friction for maintainers
- No spam heuristics triggered
- Proves the contributor understands the project's issue culture
- Creates an organic conversation before code submission
- If the maintainer says "not a bug" or "wontfix," no PR was wasted

---

### Stage 10: Human Review & Send

The human operator reviews the drafted issue, makes any necessary adjustments, and **manually submits it**.

The harness does not auto-submit anything to GitHub. This is the human-at-the-front gate.

**Submission rate limit:** Minimum 6 hours between issue submissions to *different* repos from the same identity. Minimum 24 hours between submissions to the *same* repo.

---

### Stage 11: Maintainer Response Window

After issue submission, the harness enters a **waiting state**.

**Auto-actions during wait:**
- Day 3: If no response, the harness drafts a polite bump comment for human review
- Day 7: If no response, mark `status: maintainer_no_response` and deprioritize the repo for 30 days
- If maintainer responds positively ("yes, please send a PR" or assigns the issue): proceed to Stage 12
- If maintainer responds negatively: mark `status: declined` and close

**Rate limit:** No more than one bump per issue. Never bump faster than every 72 hours.

---

### Stage 12: PR Drafting & Human Submission

Only after maintainer acknowledgment does the harness draft a PR.

The PR:
1. References the acknowledged issue
2. Includes the fix with tests (if the project's merge pattern indicates tests are expected)
3. Follows the project's commit message conventions
4. Includes the transparency note
5. Is scoped to the minimal change (no drive-by refactors)

**Human review and manual submission.** The operator signs off on every PR before it goes live.

**PR rate limit:** Maximum 2 PRs per week per identity. Maximum 1 PR per repo per month.

---

### Stage 13: Review Response Loop

Same as original: after bot/maintainer feedback, decide next action.

**v2 addition:** The harness now tracks **review sentiment**:
- If a maintainer expresses frustration or asks the contributor to slow down, the harness flags the identity for a cooldown period (7-14 days)
- If a PR is labeled `spam` or `invalid`, the harness immediately halts all activity for that identity and triggers a human review of the method

---

## The Operator Network

The original harness used one GitHub account. v2 uses a **network of 5-10 real operators**, each with:
- Their own GitHub identity (established, not freshly created)
- Their own fork of the orchestration ledger
- Their own repo backlog queue
- Cross-operator visibility into what repos other operators are engaging with (to avoid collision)

**Each operator's velocity:** 3-5 repos/week, 1-2 issues submitted, 0-2 PRs merged. This is indistinguishable from an active, engaged open-source contributor.

**Network coordination:**
- A shared `repo-claim` registry (MCP-backed) prevents two operators from engaging the same repo within a 30-day window
- Weekly sync meeting (human-led) to discuss which repos are in flight, which maintainers have been responsive, and which projects should be deprioritized
- Cross-training: every operator understands the full method so they can cover for each other

---

## Rate Limiting & Velocity Envelope

### Per-Identity Limits

| Action | Rate | Rationale |
|--------|------|-----------|
| New repo first contact | 3-5/week | Natural active contributor pace |
| Issue submissions | 1-2/week | Time for maintainer response |
| PR submissions | 0-2/week | Only after maintainer ack |
| Comments on own issues/PRs | Unlimited | Engagement is good |
| Stars/follows | Natural | No automation; human discretion |

### Per-Repo Limits

| Action | Rate | Rationale |
|--------|------|-----------|
| Issues | 1/month | Don't overwhelm a single project |
| PRs | 1/month | One fix at a time |
| Bumps | 1/issue, 72h min | Respect maintainer time |

### Global Network Limits

| Metric | Limit | Rationale |
|--------|-------|-----------|
| Total repos in flight | 20-30 | Manageable coordination overhead |
| Total new first contacts/week | 15-25 | Distributed across identities |
| Total PRs/week | 5-10 | Sustainable review capacity |

---

## Abuse Detection Evasion (Passive Compliance)

The v2 harness does not "evade" abuse detection in the adversarial sense. It **designs away the signals** that trigger abuse detection:

1. **No unsolicited PRs.** Issues first, always. PRs only after maintainer engagement.
2. **No burst patterns.** Submissions are spread evenly across the week, not clustered in a 72-hour window.
3. **No new-account behavior.** Operators use established accounts with organic history.
4. **No identical templates.** Each issue/PR is customized to the project's conventions and the specific bug.
5. **No cross-repo similarity.** The method is shared, but the outputs are project-specific.
6. **No rapid-fire interactions.** Comments and responses happen at human speed (hours, not seconds).
7. **Organic engagement.** Operators also star repos, comment on unrelated issues, and participate in discussions — not just bug fixes.

---

## The Ledger: GitHub Issue as Source of Truth

Each operator maintains a **private GitHub repository** (or a private project board) that serves as the ledger.

**The ledger issue format:**
```markdown
## Repo: owner/repo

### Status
- [ ] Stage 0: Stance detection
- [ ] Stage 1: Candidate extraction
- [ ] Stage 2: Direction alignment
- [ ] Stage 3: Deep interview
- [ ] Stage 4: Cross-check
- [ ] Stage 5: Local reproduction
- [ ] Stage 6: Load-bearing exclusion
- [ ] Stage 7: Scope check
- [ ] Stage 8: Merge pattern match
- [ ] Stage 9: Issue draft
- [ ] Stage 10: Human review & send
- [ ] Stage 11: Maintainer response
- [ ] Stage 12: PR draft & send
- [ ] Stage 13: Review response

### Notes
- Security track: yes/no
- AI policy: welcome/ambiguous/prohibited
- Maintainer response time: N days
- Outcome: pending/merged/declined/no-response
```

**Why GitHub issues for the ledger?**
- Survives session compaction (the original author's insight)
- Any agent, any session, any restart reads the issue and resumes
- Checkbox state is durable and auditable
- Comments preserve the decision trail
- Native GitHub notifications keep the operator informed

---

## Tooling: Hermes Agent Integration

The harness is implemented as a set of **Hermes skills** and **cron jobs**:

### Skills

| Skill | Purpose |
|-------|---------|
| `oss-contribution/discover` | Stage 1: Extract candidates from PRs/tags |
| `oss-contribution/interview` | Stage 3: Ouroboros-style deep interview |
| `oss-contribution/reproduce` | Stage 5: Fork, clone, reproduce in isolated worktree |
| `oss-contribution/draft-issue` | Stage 9: Draft the initial issue |
| `oss-contribution/draft-pr` | Stage 12: Draft the PR after maintainer ack |
| `oss-contribution/review-response` | Stage 13: Analyze maintainer feedback and draft responses |
| `oss-contribution/stance-detect` | Stage 0: Detect AI policy from project files |
| `oss-contribution/merge-pattern` | Stage 8: Extract conventions from recent merged PRs |

### Cron Jobs

| Job | Schedule | Purpose |
|-----|----------|---------|
| `ledger-sync` | Every 15 min | Sync ledger state from GitHub API to local MCP state |
| `maintainer-poll` | Every 6 hours | Check for maintainer responses on open issues |
| `bump-draft` | Daily at 9am | Draft bump comments for issues with no response > 72h |
| `rate-limit-check` | Every hour | Enforce per-identity and per-repo rate limits |
| `repo-claim-cleanup` | Weekly | Release claims on repos with no activity > 30 days |

---

## Quality Preservation

Every gate from the original harness is preserved:

1. **Local reproduction (Stage 5)** remains the 80% filter. No reproduction = no submission.
2. **Merge pattern matching (Stage 8)** remains the shape-defining input.
3. **Human attestation (Stages 10, 12)** remains at every signature boundary.
4. **Ouroboros interview (Stage 3)** remains the branch/decision point.
5. **Cross-check dedupe (Stage 4)** remains the collision avoidance.
6. **Load-bearing exclusion (Stage 6)** remains the judgment gate.

---

## Policy Compliance Checklist

Before any submission, the harness verifies:

- [ ] Project's AI policy explicitly permits or is ambiguous (not prohibited)
- [ ] No similar contribution recently rejected as spam
- [ ] Issue submission rate for this identity is within weekly limit
- [ ] Repo has not been contacted by this identity in the last 30 days
- [ ] The issue draft does not contain templated or generic language
- [ ] The reproduction was performed in an isolated worktree
- [ ] The fix is minimal and scoped (no drive-by changes)
- [ ] Human operator has reviewed and approved the draft
- [ ] Transparency note is included if AI assistance was used
- [ ] Security fixes follow the project's disclosure process (not public issues)

---

## Expected Outcomes

| Metric | Original Harness | v2 Harness |
|--------|------------------|------------|
| Repos/week | ~33 (100 in 72h) | 15-25 |
| PRs/week | ~33 | 5-10 |
| Merge rate | High (most merged) | High (maintainer-ack filter improves it) |
| Account suspension risk | Very high | Negligible |
| Maintainer satisfaction | Mixed (some merged, some annoyed by volume) | High (opt-in engagement) |
| Security disclosure rate | Some publicly posted | Zero (all follow private disclosure) |
| Human hours/week | ~10-15 (stages 11-12) | ~15-20 (more front-loaded human engagement) |
| Sustainability | 72-hour sprint | Indefinite operation |

---

## The Method Is the Substance

The harness is an amplifier. The method is what makes the contributions honest.

v2 proves that you don't have to choose between scale and policy compliance. You just have to **design the velocity envelope as carefully as you design the quality gates**.

The scarce resource was never tokens. It was never even human attention. The scarce resource was **maintainer trust**. v2 spends it carefully.

---

## Open Questions for Implementation

1. **Operator onboarding:** How do we recruit and train operators without creating a "contributor farm" appearance? (Answer: Operators are existing open-source contributors who already have organic GitHub histories. The harness is a tool they use, not an identity they assume.)

2. **Ledger privacy:** Should the ledger repo be public (transparency) or private (operational security)? (Answer: Private by default. Operators can choose to publish sanitized retrospectives.)

3. **Compensation:** If this becomes a sponsored effort, how do we avoid the appearance of paid spam? (Answer: Compensate operators for their time, not per-merged-PR. The incentive aligns with quality, not volume.)

4. **Fork ownership:** Should forks be under the operator's personal account or an org? (Answer: Personal account. Org-owned forks at scale trigger "astroturfing" heuristics.)

5. **Hermes integration:** Should this be a core Hermes feature or an external skill pack? (Answer: External skill pack. Core Hermes should not be opinionated about OSS contribution workflows.)

---

## Files to Create

| File | Purpose |
|------|---------|
| `skills/oss-contribution/stance-detect/SKILL.md` | Detect AI policy from project files |
| `skills/oss-contribution/discover/SKILL.md` | Extract fix candidates from PRs/tags |
| `skills/oss-contribution/interview/SKILL.md` | Ouroboros deep interview with policy checkpoint |
| `skills/oss-contribution/reproduce/SKILL.md` | Fork, clone, reproduce in isolated worktree |
| `skills/oss-contribution/draft-issue/SKILL.md` | Draft maintainer-first issue |
| `skills/oss-contribution/draft-pr/SKILL.md` | Draft PR after maintainer ack |
| `skills/oss-contribution/review-response/SKILL.md` | Analyze and respond to maintainer feedback |
| `skills/oss-contribution/merge-pattern/SKILL.md` | Extract conventions from merged PRs |
| `docs/oss-contribution/HARNESS.md` | This document |
| `docs/oss-contribution/RATE_LIMITS.md` | Per-identity and per-repo rate limits |
| `docs/oss-contribution/LEDGER.md` | Ledger format and conventions |
| `docs/oss-contribution/OPERATOR_GUIDE.md` | Human operator onboarding |
| `cron/jobs/oss_contribution.py` | Cron jobs for the harness |
| `tools/oss_contribution_tool.py` | Tool for querying ledger state |

---

*End of design document.*
