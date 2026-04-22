---
name: merge-pattern
description: Extract conventions from a repo's last 10 merged PRs — commit message style, test expectations, merge strategy, review turnaround, and maintainer review style. Use before drafting an issue or PR to match the social shape of accepted contributions.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [open-source, contribution, PR, merge-pattern, conventions, git-history]
    related_skills: [github-pr-workflow, github-code-review, requesting-code-review]
prerequisites:
  commands: [git, gh]
---

# Merge Pattern Extraction

Extract the social shape of accepted contributions from a repository's recent merge history. CONTRIBUTING.md describes the rules; the last 10 merges describe the reality. Read the merges first.

## When to Use

- Before drafting an issue or PR for an unfamiliar repo
- When CONTRIBUTING.md and observed practice seem to diverge
- To determine whether squash vs rebase vs merge is the local norm
- To calibrate commit message style, test expectations, and review tone
- Stage 8 of the OSS contribution pipeline: shape the writing to match accepted PRs

## Prerequisites

- Git repository cloned locally or accessible via `gh`
- `gh` CLI authenticated (or fallback to `git log` + GitHub API via curl)

## 1. Fetch the Last 10 Merged PRs

### With `gh` (recommended)

```bash
OWNER_REPO="owner/repo"
gh pr list --repo "$OWNER_REPO" --state merged --limit 10 --json \
  number,title,author,mergedAt,mergeCommit,headRefName,baseRefName,body,additions,deletions,changedFiles,labels,reviewDecision,comments,reviews \
  > /tmp/last10_merged.json

cat /tmp/last10_merged.json | python3 -c "
import sys, json
prs = json.load(sys.stdin)
for p in prs:
    print(f\"#{p['number']} | {p['title'][:60]} | {p['author']['login']} | +{p['additions']}/-{p['deletions']} | {p['mergedAt'][:10]}\")
"
```

### With `git log` only (no API access)

```bash
# Find merge commits on the default branch
git log --merges --oneline -10

# Deeper: show merged branches and subjects
git log --merges --format="%h | %s | %cn | %cd" --date=short -10

# For each merge commit, inspect the individual commits that were merged
MERGE_COMMIT=$(git log --merges --format=%H -1)
git log --format="  %h %s" "$MERGE_COMMIT^1..$MERGE_COMMIT^2"
```

### With GitHub REST API (fallback)

```bash
OWNER="owner"
REPO="repo"
curl -s "https://api.github.com/repos/$OWNER/$REPO/pulls?state=closed&per_page=20" \
  | python3 -c "
import sys, json
prs = json.load(sys.stdin)
merged = [p for p in prs if p.get('merged_at')]
for p in merged[:10]:
    print(f\"#{p['number']} | {p['title'][:60]} | {p['user']['login']} | {p['merged_at'][:10]}\")
"
```

## 2. Inspect Commit Message Style

For each of the last 10 merges, examine the merge commit and the commits within the PR:

```bash
# Show full messages of the last 10 merge commits
git log --merges --format="%H%n%s%n%b---" -10

# Check for conventional commit prefixes (feat:, fix:, docs:, test:, refactor:, chore:, perf:, ci:)
git log --merges --format=%s -10 | grep -oE '^[a-z]+(\([^)]+\))?:' | sort | uniq -c | sort -rn
```

**Record:**
- Are prefixes used? Which ones? In what frequency?
- Is the scope `(module)` present or absent?
- Are messages imperative ("Add feature") or past tense ("Added feature")?
- Is there a body with explanation? Bullet points? Issue references (`Fixes #123`)?
- Are trailers present (`Co-authored-by`, `Signed-off-by`)?

## 3. Determine Merge Strategy

```bash
# Inspect the merge commits: is it a merge commit, squash merge, or rebase?
git log --merges --format="%H %s" -10

# For a specific PR number (e.g. #42), inspect the merge commit message
git log --all --oneline --grep="#42" -5
```

**Record:**
- Are merge commits present (two parents)? → merge strategy is "merge"
- Are there single-parent commits with PR title + number? → likely squash
- Is history linear with no merge commits? → likely rebase + fast-forward
- Check the repo settings if you have admin access:
  ```bash
  gh api repos/OWNER/REPO | jq '.allow_squash_merge, .allow_rebase_merge, .allow_merge_commit, .squash_merge_commit_title, .squash_merge_commit_message'
  ```

## 4. Assess Test Expectations

For each PR, check if tests were added or modified:

```bash
# List files changed in the last 10 merge commits, filter for test files
for commit in $(git log --merges --format=%H -10); do
    echo "=== $commit ==="
    git diff-tree --no-commit-id --name-only -r "$commit" | grep -iE '(test|spec)'
done
```

With `gh` (richer data):

```bash
cat /tmp/last10_merged.json | python3 -c "
import sys, json
prs = json.load(sys.stdin)
for p in prs:
    print(f\"#{p['number']}: {p['changedFiles']} files, +{p['additions']}/-{p['deletions']}\")
"
```

**Record:**
- What percentage of PRs touched test files?
- Are there test-only PRs? (indicates test culture)
- Is there a test command in CI? Check `.github/workflows/` or similar:
  ```bash
  find .github/workflows -name '*.yml' -o -name '*.yaml' | xargs grep -l 'test'
  ```

## 5. Measure Review Turnaround Time

With `gh`:

```bash
cat /tmp/last10_merged.json | python3 -c "
import sys, json
from datetime import datetime
prs = json.load(sys.stdin)
for p in prs:
    created = datetime.fromisoformat(p['createdAt'].replace('Z', '+00:00'))
    merged = datetime.fromisoformat(p['mergedAt'].replace('Z', '+00:00'))
    delta = merged - created
    print(f\"#{p['number']}: {delta.days}d {delta.seconds//3600}h | reviews: {len(p.get('reviews', []))}\")
"
```

**Record:**
- Median time from open to merge
- Number of review rounds (count distinct reviewers or review events)
- Are there PRs with zero reviews that were merged? (indicates maintainer self-merge or bot-merge)

## 6. Characterize Maintainer Review Style

Read the review comments on 2-3 representative PRs:

```bash
# Fetch reviews for a specific PR
gh pr view 42 --repo OWNER/REPO --json reviews --jq '.reviews[] | \"{user: .author.login, state: .state, body: .body[:100]}\"'

# Or via API
curl -s "https://api.github.com/repos/OWNER/REPO/pulls/42/reviews" | python3 -c "
import sys, json
for r in json.load(sys.stdin):
    print(f\"{r['user']['login']}: {r['state']} | {r.get('body', '')[:100]}\")
"
```

**Record:**
- Tone: direct/corrective, coaching/suggestive, or minimal (LGTM-only)?
- Focus areas: style, architecture, tests, docs, performance, security?
- Are there "nit" labels or style-only comments?
- Do maintainers request changes (`CHANGES_REQUESTED`) or just comment?
- Is there a bot reviewer (e.g., lint-bot, CLA-bot, coverage-bot)?

## 7. Synthesize the Pattern Profile

Produce a concise profile (3-5 bullets) that shapes your own contribution:

```markdown
## Merge Pattern Profile: OWNER/REPO

**Commit style:** Imperative conventional commits with scope. Example: `feat(auth): add JWT validation`
**Merge strategy:** Squash merge. PR title becomes commit subject.
**Tests expected:** ~80% of merged PRs include test changes. CI runs pytest + mypy.
**Review pace:** 2-5 days median. 1-2 review rounds typical. Maintainers are direct, focus on API design.
**Attestation:** DCO sign-off (`Signed-off-by`) required on all commits.
```

## 8. Apply to Your Contribution

Before opening your PR, check alignment:

- [ ] Commit messages match the observed prefix + scope style
- [ ] PR title follows the squash-merge commit pattern
- [ ] Tests added or modified if the pattern expects them
- [ ] Body references related issues using the local convention (`Fixes #123`, `Closes #123`, `Relates to #123`)
- [ ] DCO / CLA / sign-off applied if observed in merged PRs
- [ ] Branch name follows local convention if discernible

## Pitfalls

1. **Don't read CONTRIBUTING.md instead of merges.** Docs describe aspiration; merges describe enforcement. Use both, but weight merges higher.
2. **Don't infer from a single PR.** One maintainer on vacation, one emergency hotfix — outliers mislead. Use 10 as a minimum sample.
3. **Don't ignore bot merges.** If 7 of 10 PRs were merged by a bot after CI pass, the review bar is CI, not human review.
4. **Don't assume the default branch is `main`.** Check `git remote show origin` or `gh repo view --json defaultBranchRef`.
5. **Don't miss fork-specific norms.** If contributing to a fork, the merge patterns may differ from upstream. Read the fork.

## Quick Reference

| Signal | How to Read It |
|--------|---------------|
| Merge commit with two parents | `git cat-file -p SHA` shows two `parent` lines |
| Squash merge | Single parent, commit message contains PR title + `(#NNN)` |
| Rebase merge | Linear history, commit messages unchanged, no merge commits |
| Conventional commits | `git log --format=%s` shows `type(scope):` pattern |
| DCO/Sign-off | `git log --format=%B` shows `Signed-off-by:` trailers |
| Zero-review merges | `gh pr list --json reviews` shows empty review arrays |

## Hermes Agent Integration

### Within a Pipeline

Use this skill as Stage 8 of the OSS contribution pipeline. Feed the output profile into the issue/PR drafting stage so the contribution matches the social shape of accepted PRs.

### Command Pattern

```bash
# One-shot: generate profile for any public repo
OWNER_REPO="facebook/react"
gh pr list --repo "$OWNER_REPO" --state merged --limit 10 --json \
  number,title,author,mergedAt,mergeCommit,additions,deletions,changedFiles,createdAt,reviews \
  > /tmp/merge_pattern.json

# Then process with a python script or jq to extract the profile
```

### With Delegate Task

When operating across many repos in parallel, delegate merge-pattern extraction per repo. The profile output is a lightweight JSON or markdown artifact consumed by the drafting agent.

---

**Key principle:** The social shape of an accepted PR is etched more clearly in merge history than in docs. Read the last 10 merges before you write.
