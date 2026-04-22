---
name: draft-pr
description: Draft a pull request only after explicit maintainer acknowledgment of the linked issue. Scope changes minimally, add tests, and follow conventional commits.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [oss, open-source, pull-request, github, contribution, maintainer-first]
    related_skills: [github-pr-workflow, github-issues, requesting-code-review]
---

# Draft PR After Maintainer Acknowledgment

Open a pull request only after a maintainer has explicitly acknowledged the linked issue
as worth fixing or a good change. This prevents noise, respects maintainer time, and
aligns with GitHub's expectations for genuine contribution.

**Core principle:** No PR without an ACK. A maintainer comment like "PR welcome," "good catch,"
"go ahead," or assigning the issue counts. Silence, unconfirmed labels, or bot reactions do not.

---

## Prerequisites

- A fork of the target repository with a branch containing the fix
- An open issue with explicit maintainer acknowledgment (see check below)
- Local reproduction and test verification completed
- `git` configured with author info matching your GitHub account

---

## 1. Verify Maintainer Acknowledgment

Before creating the PR, confirm the issue has a green light:

```bash
# Fetch the issue comments via GitHub API
OWNER="<owner>"
REPO="<repo>"
ISSUE="<issue_number>"

curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/$OWNER/$REPO/issues/$ISSUE/comments" | \
  python3 -c "
import sys, json
comments = json.load(sys.stdin)
for c in comments:
    user = c['user']['login']
    body = c['body'].lower()
    if user in ['dependabot[bot]', 'github-actions[bot]']:
        continue
    if any(x in body for x in ['pr welcome', 'pull request welcome', 'go ahead', 'good catch',
                                 'worth fixing', 'sounds good', 'feel free', 'accepted']):
        print(f'ACK found from {user}: {c[\"body\"][:80]}...')
        sys.exit(0)
print('No maintainer ACK found. Do not open a PR yet.')
sys.exit(1)
"
```

**What counts as acknowledgment:**
- Maintainer says "PR welcome" or "feel free to open a PR"
- Maintainer assigns the issue to you or themselves
- Maintainer adds a label like `help wanted` or `good first issue` after discussion
- Maintainer confirms the bug/change is valid and desired

**What does NOT count:**
- Automated bot labels (`stale`, `triage`)
- Generic emoji reactions without text
- Non-maintainer enthusiasm
- Silence after issue creation

If no ACK exists, stop. Comment on the issue with a concise update and ask if a PR would be welcome.

---

## 2. Scope the Change to Minimum

The PR must touch only what the issue describes. No drive-by cleanups, no unrelated refactors.

**Scoping checklist:**
- [ ] Every changed line is justifiable by the linked issue
- [ ] No whitespace or formatting changes in untouched code
- [ ] No dependency bumps unless required by the fix
- [ ] No new abstractions unless the issue explicitly asks for them
- [ ] No renames that aren't part of the fix

```bash
# Verify diff scope before committing
git diff --stat
git diff --name-only
```

If the diff includes files unrelated to the issue, `git checkout -- <file>` them or split into a separate branch.

---

## 3. Add Tests

Every behavioral change must include tests. If the repo has no test infrastructure, note this in the PR body.

```bash
# Check if tests exist for the affected module
git ls-files | grep -i test | grep <module_name>

# Run the test suite to establish baseline
cargo test        # Rust
pytest            # Python
npm test          # Node
```

**Test requirements:**
- [ ] Regression test reproduces the bug before the fix (fails on main, passes on branch)
- [ ] At least one happy-path test for the new behavior
- [ ] Edge-case test for empty/null/invalid input if applicable
- [ ] All existing tests still pass

If adding a full test is infeasible, explain why in the PR body and provide manual reproduction steps.

---

## 4. Follow Commit Conventions

Use [Conventional Commits](https://www.conventionalcommits.org/) matching the project's style.

```bash
git commit -m "fix: resolve off-by-one in pagination offset

- Fixes incorrect boundary check in PageIterator.next()
- Adds regression test for empty result set edge case

Refs #<issue_number>"
```

**Types by change class:**
- `fix:` — bug fix
- `feat:` — new feature (only if issue asked for one)
- `docs:` — documentation-only change
- `test:` — adding or correcting tests
- `refactor:` — code change that neither fixes a bug nor adds a feature (rare for minimal PRs)

**Rules:**
- One logical change per commit. If you fixed the bug and added docs, two commits.
- Subject line under 72 characters.
- Body explains *what* and *why*, not *how* (the diff shows how).
- Reference the issue with `Refs #NNN` or `Fixes #NNN` only if the PR will close it.

---

## 5. Open the PR

Only proceed if Steps 1–4 are satisfied.

The PR description should match the project's conventions and voice. Do not include boilerplate about how the PR was prepared.

### With `gh`:

```bash
gh pr create \
  --title "fix: <short description>" \
  --body "## Summary
Fixes #<issue_number>

<One-paragraph description of the bug and fix.>

## Test Plan
- [x] Reproduced the bug in a local fork
- [x] Added regression test
- [x] All existing tests pass" \
  --base main
```

### With `curl`:

```bash
BRANCH=$(git branch --show-current)
OWNER="<owner>"
REPO="<repo>"

BODY=$(cat <<'EOF'
## Summary
Fixes #<issue_number>

<description>

## Test Plan
- [x] Reproduced the bug in a local fork
- [x] Added regression test
- [x] All existing tests pass
EOF
)

curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/$OWNER/$REPO/pulls \
  -d "{
    \"title\": \"fix: <short description>\",
    \"body\": $(echo "$BODY" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
    \"head\": \"$BRANCH\",
    \"base\": \"main\"
  }"
```

---

## 6. Post-Submission

After the PR is open:

1. Link the PR in the issue with a comment: `Opened #<pr_number> to address this.`
2. Monitor CI and respond to bot feedback within 24 hours.
3. If a maintainer requests changes, address them in new commits with clear messages.
4. Do not open additional PRs for the same issue.

---

## 7. Pitfalls

- **Opening before ACK** — The fastest way to be marked as spam. Wait for human maintainer confirmation.
- **Overscoping** — A 500-line refactor in a bug-fix PR looks like a drive-by. Keep it minimal.
- **Missing tests** — Untested fixes signal low effort. Add tests or explain why it's impossible.
- **Bulk PRs** — If running across many repos, space submissions by at least a few hours per project. Volume itself is a signal.
- **Duplicate PRs** — Search open PRs before opening yours. Duplicate work wastes everyone's time.

---

## 8. Integration with Other Skills

**github-pr-workflow:** Use for branch creation, CI monitoring, and merge steps after this skill completes.

**github-issues:** Use to find issues, check for existing PRs, and confirm maintainer engagement before drafting.

**requesting-code-review:** Run the pre-commit verification pipeline before pushing the branch.

**github-code-review:** Use to review your own diff one last time before submission, as a sanity check.

---

## 9. Why This Matters

A PR without an acknowledged issue is unsolicited. Unsolicited PRs at volume trigger
abuse detection regardless of individual quality. The ACK gate ensures every PR is
expected, scoped, and welcome before it consumes maintainer attention.

---

## 10. Reference: PR Body Template

```markdown
## Summary
Fixes #<issue_number>

<What changed and why, in one paragraph.>

## Test Plan
- [x] Bug reproduced in local fork before fix
- [x] Regression test added
- [x] All existing tests pass (`<command>`)

## Checklist
- [ ] Change is scoped to the linked issue only
- [ ] Commits follow conventional commit format
- [ ] No unrelated formatting or refactoring
```

Replace `<issue_number>`, `<command>`, and the summary paragraph before submitting.
