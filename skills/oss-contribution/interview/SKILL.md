---
name: oss-contribution-interview
description: Stage 3 deep interview — Ouroboros-inspired Socratic interrogation that decides whether to branch for each candidate. Applies rate-compliance checkpoints, spam-gate analysis, and contribution-farming detection before any code is written.
version: 2.5.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [oss, open-source, contribution, interview, rate-limit, compliance, spam-gate, ouroboros]
    related_skills: [github-pr-workflow, github-auth, github-repo-management]
---

# OSS Contribution Interview — Stage 3

## Overview

Before any branch is created, before any code is written, the candidate contribution must face the Ouroboros: a self-referential interrogation that devours its own assumptions.

This stage is the **spam gate** and the **rate checkpoint**. It asks questions that expose whether the contribution is genuine value or performative activity. The interview is **pass/fail** — a single fatal answer stops the process.

**Core principle:** A contribution that cannot survive honest scrutiny should not exist.

## When to Use

**Always:**

- After Stage 2 candidate vetting (issue triage, repo analysis)
- Before creating any branch
- Before writing any code
- Before engaging with maintainers

**Never skip:**

- No matter how "obvious" the fix seemed
- No matter how trivial the change
- No matter how urgent the user feels

---

## The Iron Law

```
NO BRANCH WITHOUT PASSING THE INTERVIEW
```

Write code before the interview? Delete it. Start over.

---

## The Three Gates

The interview proceeds through three gates. Each gate must be cleared before proceeding to the next. A single NO at any gate is terminal.

### Gate 1 — Value Gate

**Question:** Does this contribution solve a real problem that matters to the project?

**Interrogation protocol:**

1. Restate the issue in your own words. Do not quote the issue title.
2. Who is affected? Be specific about users, workflows, or downstream systems.
3. What is the cost of the problem remaining unsolved?
4. What is the smallest fix that solves it? (Not the most elegant — the smallest.)
5. If you were the maintainer, would you want to review this PR?

**Stop conditions (answer honestly):**

- You cannot explain the problem without referencing the issue text verbatim
- The affected audience is hypothetical or speculative
- The cost is "it would be nice" or "for consistency"
- The smallest fix is still larger than 50 lines — scope may be wrong
- As maintainer, you would sigh seeing this in the queue

**Fatal answer:** NO — the contribution lacks genuine value.

---

### Gate 2 — Timing Gate

**Question:** Is now the right time for this contribution?

**Interrogation protocol:**

1. Has a maintainer acknowledged or labeled this issue?
2. Are there open PRs addressing this same problem?
3. Is the project in a feature freeze, release window, or maintenance mode?
4. Does the project have a backlog policy (e.g., "good first issue" only)?
5. Would maintainers welcome an external contribution here, or is this internal territory?

**Stop conditions:**

- Issue is unacknowledged and over 90 days old with no maintainer response
- An open PR already exists (even if draft or stalled)
- Project is in release freeze and only accepting critical fixes
- The fix touches code with a CODEOWNERS file suggesting core-team ownership

**Fatal answer:** NO — timing is wrong. Park and revisit later.

---

### Gate 3 — Rate Compliance Gate (v2.5)

**Question:** Would submitting this fix violate rate limits or trigger cooldown rejection?

Rate limits are the primary compliance mechanism for single-operator OSS contribution. This gate enforces them.

**Rate compliance questions (ALL must be YES to proceed):**

1. **30-day repo contact check:** Have I contacted this repo in the last 30 days?
   - YES means STOP — rate limit applies. Wait until 30 days have passed since the last contact.
   - NO means proceed.

2. **Weekly budget check:** Is this week's submission budget already spent?
   - Default budget: one submission per 7-day rolling window.
   - If a submission was made in the last 7 days, STOP.
   - If the budget is unspent, proceed.

3. **Burst pattern check:** Would this submission create a burst pattern?
   - A burst is two or more submissions within 14 days across any repo.
   - If this submission would create a burst, STOP.
   - If spacing is healthy, proceed.

**Cooldown questions (ALL must be YES to proceed):**

4. **Spam appearance check:** Would submitting this fix create the appearance of spam?
   - Is the fix meaningful, or does it look like drive-by activity?
   - Would a maintainer reading the PR title think "this is noise"?
   - Is the timing clustered with other contributions in a way that looks artificial?

5. **Rejection recency check:** Has a similar contribution been recently rejected?
   - Was a PR on this same issue or area rejected in the last 90 days?
   - If rejected, has the underlying reason been addressed?
   - Resubmitting unchanged work is a rate violation.

6. **Triviality farming check:** Is the fix trivial enough that it might be perceived as farming contributions?
   - Does the change reduce to "add a comma," "fix indentation," or "remove unused import"?
   - Would the PR description require more text than the code change itself?
   - Is the primary motivation "I need a green square on my profile" rather than "this improves the project"?

**Stop conditions:**

- Any of the six checkpoint questions answers NO
- The fix is purely cosmetic with no functional or documentation improvement
- The operator has contacted this repo within the last 30 days
- The weekly submission budget is spent
- This submission would create a burst pattern (2+ in 14 days)
- A similar contribution was rejected in the last 90 days without material change

**Fatal answer:** NO — rate or cooldown violation. Do not submit.

---

## Ouroboros Loop — Self-Referential Interrogation

After the three gates, perform one final recursive check:

> "If every contributor applied this exact decision framework, would the project be healthier?"

If the answer is NO, your reasoning has a hole. Re-examine.

If the answer is YES, proceed.

---

## Decision Matrix

| Gate 1 (Value) | Gate 2 (Timing) | Gate 3 (Rate) | Decision |
|---|---|---|---|
| YES | YES | YES | **BRANCH** — Proceed to implementation |
| NO | — | — | **DROP** — No value, no contribution |
| YES | NO | — | **PARK** — Wait for better timing, set reminder |
| YES | YES | NO | **DROP** — Rate or cooldown violation, do not submit |

**No partial credit.** A contribution that clears two gates but fails the third is still a rejection.

---

## Anti-Patterns — Red Flags

If you find yourself thinking any of these, **stop and restart the interview**:

- "It's just a small fix, what's the harm?"
- "I need to keep my contribution streak going."
- "This will look good on my profile."
- "The maintainer can just close it if they don't want it."
- "It's technically a valid improvement."
- "Other people have done similar PRs and they got merged."
- "I'll submit it and see what happens."

All of these are rationalizations that bypass the interview. The interview exists precisely to catch these thoughts.

---

## Verification Checklist

Before creating a branch:

- [ ] Restated the problem in my own words
- [ ] Identified specific affected users or systems
- [ ] Confirmed no open PR addresses this issue
- [ ] Confirmed project timing allows external contributions
- [ ] 30-day repo contact check: NO — no contact in last 30 days
- [ ] Weekly budget check: NO — budget not spent
- [ ] Burst pattern check: NO — would not create a burst
- [ ] Spam appearance check: YES — not spam
- [ ] Rejection recency check: YES — no recent similar rejection
- [ ] Triviality farming check: YES — not contribution farming
- [ ] Ouroboros loop: YES — universal application is healthy
- [ ] Decision recorded with reasoning

Can't check all boxes? Do not branch. Start over or drop the candidate.

---

## Output Format

After the interview, produce a structured verdict:

```
## Interview Verdict: [BRANCH / PARK / DROP]

### Candidate
- Issue/Repo: <link>
- Proposed fix: <one-line summary>

### Gate Results
- Value Gate: [PASS / FAIL] — <reasoning>
- Timing Gate: [PASS / FAIL] — <reasoning>
- Rate Gate: [PASS / FAIL] — <reasoning>

### Rate Compliance Answers
- 30-day repo contact: [YES / NO] — <reasoning>
- Weekly budget spent: [YES / NO] — <reasoning>
- Burst pattern: [YES / NO] — <reasoning>

### Cooldown Answers
- Spam appearance: [YES / NO] — <reasoning>
- Rejection recency: [YES / NO] — <reasoning>
- Triviality farming: [YES / NO] — <reasoning>

### Ouroboros Loop
- Universal health check: [YES / NO] — <reasoning>

### Final Reasoning
<2-3 sentences on why this decision protects the project and the contributor>
```

**PARK decisions must include:**
- Condition to revisit (e.g., "after next release", "if maintainer labels issue")
- Recommended reminder date

**DROP decisions must include:**
- Specific gate that failed
- Why proceeding would harm the project or the contributor's reputation
- Alternative suggestion (if any)

---

## Hermes Agent Integration

### Running the Interview

Use the `terminal` tool to verify conditions:

```bash
# Check for existing PRs on the same issue
gh pr list --repo owner/repo --search "<issue-keyword>" --state all

# Check recent contribution history for this identity
gh pr list --repo owner/repo --author <identity> --state merged --limit 20

# Check issue age and maintainer engagement
gh issue view <issue-number> --repo owner/repo
```

### With delegate_task

When delegating Stage 3, pass:

1. The candidate issue link and summary
2. The proposed fix scope
3. The identity that would submit the PR
4. This skill file as context

The delegate must return the structured verdict above before any code is written.

---

## Common Rationalizations

| Excuse | Reality |
|---|---|
| "It's just a typo fix" | If truly trivial, it fails cooldown. If not, it passes. |
| "I already started the code" | Delete it. Interview comes first. |
| "The project welcomes all contributions" | No project welcomes spam. Verify, don't assume. |
| "I'll be more careful next time" | This contribution must pass on its own merits. |
| "My other contributions were genuine" | Each contribution is interviewed independently. |
| "The maintainers can filter it out" | Passing spam to maintainers is disrespectful. |
| "I need this for my profile/resume" | The interview exists to prevent exactly this motivation. |
| "The rate limit is too strict" | The rate limit is the compliance mechanism. Obey it. |

---

## When Stuck

| Problem | Solution |
|---|---|
| Can't find maintainer engagement history | Check issue comments, recent PR merges, and project README/CONTRIBUTING. |
| Unsure if fix is trivial | Write the fix in your head. If it takes under 5 minutes, it's trivial. |
| Identity has mixed contribution history | Judge the pattern on this project, not globally. |
| Timing is ambiguous (e.g., "soon" release) | Err toward PARK. Better to wait than to annoy. |
| Two of three checkpoints are borderline | Borderline = NO. The gate is a filter, not a hurdle to clear by stretching. |
| Unsure when 30-day window resets | Check the date of the last merged PR or issue comment from this identity. |

---

## Version History

- v2.5.0 — Replaced Policy-Compliance Gate with Rate Compliance Gate. Rate limits are the primary compliance mechanism. Added burst-pattern check, weekly budget check, and 30-day repo contact check. Retained cooldown questions as secondary filters.
- v2.0.0 — Added Policy-Compliance Gate with three checkpoint questions (spam appearance, identity recency, triviality farming)
- v1.0.0 — Initial three-gate interview (Value, Timing, Reputation)
