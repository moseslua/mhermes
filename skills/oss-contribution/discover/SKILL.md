---
name: oss-contribution-discover
description: Stage 1 of OSS contribution — discover fix and security candidates from a target repository's recent merged PRs, release diffs, and SECURITY.md. Use when scouting an open-source project for contribution opportunities.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [OSS, Open-Source, Contribution, Security, PR-Analysis, Release-Diff, Discovery]
    related_skills: [github-auth, github-repo-management, github-issues]
prerequisites:
  commands: [git, python3]
---

# OSS Contribution Discovery — Stage 1

Scout an open-source repository for contribution opportunities by analyzing its recent merged PRs, release diffs, and security posture. This skill produces a ranked list of fix/security candidates worth investigating further.

## When to Use

- You want to contribute to an open-source project but don't know where to start
- You're doing security research on a target repository
- You're assessing a project's maintenance health before adopting it
- You need to find "good first issues" backed by recent activity patterns

## Prerequisites

- Authenticated with GitHub (see `github-auth` skill)
- `git` and `python3` installed
- Target repository identified (`owner/repo`)

### Setup

```bash
if command -v gh &>/dev/null && gh auth status &>/dev/null; then
  AUTH="gh"
else
  AUTH="curl"
  if [ -z "$GITHUB_TOKEN" ]; then
    if [ -f ~/.hermes/.env ] && grep -q "^GITHUB_TOKEN=" ~/.hermes/.env; then
      GITHUB_TOKEN=$(grep "^GITHUB_TOKEN=" ~/.hermes/.env | head -1 | cut -d= -f2 | tr -d '\n\r')
    elif grep -q "github.com" ~/.git-credentials 2>/dev/null; then
      GITHUB_TOKEN=$(grep "github.com" ~/.git-credentials 2>/dev/null | head -1 | sed 's|https://[^:]*:\([^@]*\)@.*|\1|')
    fi
  fi
fi

OWNER="<owner>"
REPO="<repo>"
```

---

## 1. Fetch and Analyze Last 20 Merged PRs

Extract patterns from recently merged work: bug fixes, regressions, incomplete fixes, follow-ups, and security-related changes.

**With gh:**

```bash
gh pr list --repo "$OWNER/$REPO" --state merged --limit 20 --json number,title,body,mergedAt,labels,author,mergeCommit,headRefName
```

**With curl:**

```bash
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/$OWNER/$REPO/pulls?state=closed&sort=updated&direction=desc&per_page=20" \
  | python3 -c "
import sys, json
prs = [p for p in json.load(sys.stdin) if p.get('merged_at')]
for p in prs[:20]:
    labels = ', '.join(l['name'] for l in p['labels'])
    print(f\"{p['number']:6}  {p['merged_at'][:10]}  {labels:30}  {p['title']}\")
"
```

### What to Look For

| Signal | Indicator | Follow-up Action |
|--------|-----------|------------------|
| Bug fix PRs | title/body contains "fix", "bug", "regression", "patch" | Check if the fix has gaps or related unclosed issues |
| Security PRs | labels like `security`, `cve`, `vulnerability`, or title mentions "security" | Note the CVE/severity; check if similar code patterns exist elsewhere |
| Revert PRs | title starts with `Revert` | Indicates a merged PR caused problems — investigate the original |
| Follow-up PRs | title contains "follow-up", "followup", "also" | Suggests an earlier fix was incomplete |
| Documentation-only PRs | only docs changed | Lower priority unless they reveal API gaps |
| Test-only PRs | only tests changed | May indicate a recently discovered edge case |

### Candidate Extraction Script

```bash
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/$OWNER/$REPO/pulls?state=closed&sort=updated&direction=desc&per_page=30" \
  | python3 -c "
import sys, json, re
prs = [p for p in json.load(sys.stdin) if p.get('merged_at')]

candidates = []
keywords_fix = re.compile(r'\\b(fix|bug|regression|patch|repair|correct)\\b', re.I)
keywords_sec = re.compile(r'\\b(security|cve|vuln|exploit|leak|auth|injection|overflow|sandbox|escape)\\b', re.I)
keywords_follow = re.compile(r'\\b(follow[- ]?up|also|additionally|revert)\\b', re.I)

for p in prs[:20]:
    title = p['title']
    body = p.get('body') or ''
    text = f'{title} {body}'
    labels = [l['name'].lower() for l in p['labels']]
    score = 0
    reasons = []

    if keywords_sec.search(text) or any('security' in l or 'cve' in l for l in labels):
        score += 3
        reasons.append('security')
    if keywords_fix.search(text) or any('bug' in l for l in labels):
        score += 2
        reasons.append('fix')
    if keywords_follow.search(text):
        score += 2
        reasons.append('follow-up')
    if 'revert' in title.lower():
        score += 2
        reasons.append('revert')
    if any('documentation' in l for l in labels) and score == 0:
        score = 0

    if score > 0:
        candidates.append((score, p['number'], title, reasons))

candidates.sort(reverse=True)
for score, num, title, reasons in candidates:
    print(f'  [score={score}] #{num}: {title}  ({\", \".join(reasons)})')
"
```

---

## 2. Analyze Last 5 Release-Tag Diffs

Release diffs show what changed between versions — useful for spotting regressions, incomplete fixes, and security patches that might need broader application.

**With gh:**

```bash
gh api repos/$OWNER/$REPO/releases --jq '.[:5] | .[] | "\(.tag_name) \(.published_at)"'
```

**With curl:**

```bash
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/$OWNER/$REPO/releases?per_page=5" \
  | python3 -c "
import sys, json
for r in json.load(sys.stdin):
    print(f\"{r['tag_name']:20}  {r['published_at'][:10]}  {r['name']}\")
"
```

### Fetch Diff Between Releases

```bash
# List tags (newest first)
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/$OWNER/$REPO/tags?per_page=6" \
  | python3 -c "
import sys, json
tags = [t['name'] for t in json.load(sys.stdin)]
for i in range(min(5, len(tags)-1)):
    print(f'{tags[i]}...{tags[i+1]}')
" > /tmp/tag_pairs.txt

# Fetch each diff summary
while read pair; do
  echo "=== $pair ==="
  curl -s \
    -H "Authorization: token $GITHUB_TOKEN" \
    "https://api.github.com/repos/$OWNER/$REPO/compare/$pair" \
    | python3 -c "
import sys, json
c = json.load(sys.stdin)
files = c.get('files', [])
commits = c.get('commits', [])
print(f'  Commits: {len(commits)}  Files changed: {len(files)}')
for f in sorted(files, key=lambda x: x['changes'], reverse=True)[:10]:
    print(f\"    {f['status']:10} {f['changes']:4}  {f['filename']}\")
"
done < /tmp/tag_pairs.txt
```

### What to Look For in Release Diffs

| Signal | Indicator | Follow-up Action |
|--------|-----------|------------------|
| Large security-related file changes | `status/security` files, auth modules, crypto | Cross-reference with CVE databases |
| Backports | same files changed across multiple releases | Indicates a fix that maintainers consider critical |
| Reverted files | `status: removed` or `status: renamed` in fix areas | Check if revert was intentional or accidental |
| Test-only changes in patch releases | tests added without src changes | Suggests a discovered edge case or regression |
| Config/CI changes | `.github/`, `Dockerfile`, build scripts | May indicate supply-chain security fixes |

---

## 3. Check SECURITY.md for Disclosure Process

Understanding how the project handles vulnerabilities tells you where security contributions fit and whether coordinated disclosure is possible.

### Fetch SECURITY.md

```bash
# Try common locations
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/$OWNER/$REPO/contents/SECURITY.md" \
  | python3 -c "
import sys, json, base64
j = json.load(sys.stdin)
if 'content' in j:
    print(base64.b64decode(j['content']).decode('utf-8'))
else:
    print('SECURITY.md not found')
"

# Also check .github/SECURITY.md
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/$OWNER/$REPO/contents/.github/SECURITY.md" \
  | python3 -c "
import sys, json, base64
j = json.load(sys.stdin)
if 'content' in j:
    print(base64.b64decode(j['content']).decode('utf-8'))
else:
    print('.github/SECURITY.md not found')
"
```

### Key Fields to Extract

| Field | Why It Matters |
|-------|----------------|
| Supported versions | Tells you which branches to target |
| Reporting email/contact | Where to send vulnerability reports |
| PGP key | Whether they accept encrypted disclosures |
| Response timeline | Sets expectations for disclosure coordination |
| Bug bounty program | Indicates paid security research opportunities |
| Hall of fame / credits | Incentive for responsible disclosure |
| Security advisory location | Where published advisories live (GitHub Security Advisories, mailing list, etc.) |

If `SECURITY.md` is **missing**, note this as a candidate contribution itself — many projects welcome a PR adding one.

---

## 4. Rank and Output Candidates

Combine findings into a prioritized list.

### Scoring Rubric

| Factor | Points | Notes |
|--------|--------|-------|
| Security-related | +3 | Highest priority; may lead to CVE or bounty |
| Follow-up / incomplete fix | +2 | High likelihood of acceptance |
| Revert indicates regression | +2 | Clear problem statement exists |
| Missing SECURITY.md | +2 | Easy, high-value documentation contribution |
| Recent release touched same code | +1 | Context is fresh in maintainers' minds |
| Has linked issue with discussion | +1 | Problem is validated by community |
| Large / complex diff | -1 | Harder to reason about correctness |
| Documentation-only | 0 | Low priority unless reveals API gaps |

### Output Template

```
OSS Contribution Candidates: $OWNER/$REPO
=========================================

PR Candidates (last 20 merged):
  [score=5] #123: Fix sandbox escape in renderer process  (security, fix)
  [score=4] #120: Follow-up: also validate input in batch mode  (follow-up, fix)
  [score=3] #118: Revert "optimize path resolver" — caused regressions  (revert)

Release Diff Signals:
  v2.1.0...v2.0.5: 15 commits, auth module changed → check if token validation fix is complete
  v2.0.5...v2.0.4: 3 commits, test-only → possible edge case discovered

Security Posture:
  SECURITY.md: PRESENT / MISSING
  Disclosure contact: <email or "not specified">
  Supported versions: <list or "not specified">
  Bug bounty: YES / NO / NOT SPECIFIED

Next Steps:
  1. Deep-dive highest-scoring PR candidate (read issue, reproduce, assess fix gap)
  2. If security-focused, verify against supported versions and prepare coordinated disclosure
  3. If SECURITY.md missing, draft one as a standalone contribution
```

---

## 5. Quick Start (All-in-One)

Run the full discovery pipeline for a target repo:

```bash
OWNER="<owner>"
REPO="<repo>"

echo "=== 1. Last 20 Merged PRs ==="
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/$OWNER/$REPO/pulls?state=closed&sort=updated&direction=desc&per_page=30" \
  | python3 -c "
import sys, json, re
prs = [p for p in json.load(sys.stdin) if p.get('merged_at')]
keywords = re.compile(r'\\b(fix|bug|security|cve|vuln|regression|follow[- ]?up|revert|patch)\\b', re.I)
for p in prs[:20]:
    text = f\"{p['title']} {p.get('body','')}\"
    hits = keywords.findall(text)
    if hits:
        print(f\"  [#{p['number']}] {p['title']}  (tags: {', '.join(set(hits))})\")
"

echo ""
echo "=== 2. Last 5 Releases ==="
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/$OWNER/$REPO/releases?per_page=5" \
  | python3 -c "
import sys, json
for r in json.load(sys.stdin):
    print(f\"  {r['tag_name']:20} {r['published_at'][:10]}  {r['name']}\")
"

echo ""
echo "=== 3. SECURITY.md Check ==="
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/$OWNER/$REPO/contents/SECURITY.md" \
  | python3 -c "
import sys, json
j = json.load(sys.stdin)
if 'content' in j:
    print('  PRESENT')
else:
    print('  MISSING — candidate contribution')
"
```

---

## Pitfalls

1. **Closed != Merged** — The GitHub API `/pulls?state=closed` returns both merged and unmerged closed PRs. Always filter for `merged_at` not null.
2. **Rate limits** — Unauthenticated curl hits 60 req/hour. Authenticated tokens get 5000. For large scans, use `gh` or pace requests.
3. **False positives on keywords** — "Fix documentation" is not a code fix. Read the actual diff or files changed before scoring.
4. **Security without context** — A PR mentioning "security" may be a dependency bump, not a vulnerability fix. Check the diff.
5. **Release notes != Diff** — Release notes are curated marketing. The actual `compare/` diff shows what really changed.
6. **Don't skip SECURITY.md** — Even if a project has a security program, the process may be outdated or unpublished. This is itself a discovery finding.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `404` on SECURITY.md | File doesn't exist — note as candidate contribution |
| Empty PR list | Repo may use merge commits instead of PRs, or all PRs are open — try `state=all` |
| Rate limit hit | Add `--header "Authorization: token $GITHUB_TOKEN"` or switch to `gh` |
| No releases | Some projects don't use GitHub releases — fall back to tags: `/tags?per_page=5` |
| Private repo | Ensure token has `repo` scope and access to the repository |
| Large diffs timeout | Use `per_page` limits and fetch commit SHAs only, then inspect individual commits |

---

## When to Proceed to Stage 2

Move to the next stage (investigate/reproduce) when you have:

- At least one candidate with a score >= 3, OR
- A confirmed missing SECURITY.md, OR
- A security-related PR that references a CVE or vulnerability class

Don't proceed if all candidates score 0-1 — either pick a different repository or expand the search window (last 50 PRs, last 10 releases).
