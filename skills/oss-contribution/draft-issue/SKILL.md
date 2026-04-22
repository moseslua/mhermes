---
name: draft-issue
description: Draft a high-quality GitHub issue for an upstream project — clear bug description, minimal reproduction, expected vs actual behavior, proposed fix direction, and an offer to submit a PR. Works with gh CLI or plain git + curl.
version: 2.5.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [Open-Source, OSS, GitHub, Issues, Bug-Report, Upstream, Contribution]
    related_skills: [github-auth, github-issues, github-pr-workflow]
---

# Drafting an Upstream Issue

Write a focused, respectful issue report for an external project you have inspected but do not own. The goal is to give maintainers everything they need to reproduce and triage, while offering to follow up with a PR.

For trivial fixes (docs typos, one-liners), a direct PR is acceptable instead of an issue.

## Prerequisites

- You have reproduced the bug in the upstream project (not just read the code)
- You are inside a clone of the upstream repo, or you know `OWNER/REPO`
- Authenticated with GitHub (see `github-auth` skill)

### Quick Auth Detection

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

REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
OWNER_REPO=$(echo "$REMOTE_URL" | sed -E 's|.*github\.com[:/]||; s|\.git$||')
OWNER=$(echo "$OWNER_REPO" | cut -d/ -f1)
REPO=$(echo "$OWNER_REPO" | cut -d/ -f2)
```

---

## 1. Search for Duplicates

Before opening a new issue, search open and closed issues for the same bug.

**With gh:**

```bash
gh issue list --search "<keyword>" --state all --limit 20
```

**With curl:**

```bash
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/search/issues?q=<keyword>+repo:$OWNER/$REPO+is:issue" \
  | python3 -c "
import sys, json
for i in json.load(sys.stdin)['items']:
    print(f\"#{i['number']}  {i['state']:6}  {i['title']}\")"
```

> If a duplicate exists, comment on it with any new reproduction details instead of opening a new issue.

---

## 2. Draft the Issue Body

A well-drafted issue contains exactly these sections:

### Template

```markdown
## Bug Description
<A single sentence describing what is wrong. Be specific: which function, file, or behavior.>

## Steps to Reproduce
1. <Step 1 — e.g., clone repo at commit `abc1234`>
2. <Step 2 — e.g., run `npm test` or a specific script>
3. <Step 3 — e.g., observe the failure>

> **Minimal reproduction:** If possible, link to a gist, repo, or paste the smallest code snippet that triggers the bug.

## Expected Behavior
<What the code should do, per documentation or reasonable expectation.>

## Actual Behavior
<What actually happens, including exact error messages, stack traces, or output.>
```
<paste full stack trace or log here>
```

## Environment
- OS / version:
- Language / runtime version:
- Library / dependency version:
- Commit or version tested:

## Proposed Fix Direction
<Brief technical pointer: which file/method looks responsible, and what change would resolve it. Keep this tentative — you are offering insight, not prescribing.>

## Offer to Contribute
<I am happy to open a PR with a fix and tests if the maintainers agree with the proposed direction.>
```

Do not include boilerplate about how the issue was found. Write in the project's natural voice.

---

## 3. Create the Issue

**With gh:**

```bash
gh issue create \
  --title "fix: <concise description of the bug>" \
  --body "$(cat <<'EOF'
## Bug Description
...
EOF
)" \
  --label "bug"
```

**With curl:**

```bash
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/issues \
  -d '{
    "title": "fix: <concise description of the bug>",
    "body": "## Bug Description\n...\n\n## Steps to Reproduce\n1. ...\n\n## Expected Behavior\n...\n\n## Actual Behavior\n...\n\n## Proposed Fix Direction\n...\n\n## Offer to Contribute\n...",
    "labels": ["bug"]
  }'
```

---

## 4. Follow-Up

After creating the issue:

1. **Watch for maintainer response.** Do not open a PR until asked or until consensus emerges in the issue thread.
2. **If asked for more info,** reply promptly with logs, narrower reproductions, or environment details.
3. **If the fix is straightforward and the maintainers agree,** proceed to the `github-pr-workflow` skill to open a PR that references the issue (`Closes #N`).

---

## Checklist

- [ ] I searched open and closed issues for duplicates.
- [ ] The reproduction steps are minimal and reliable.
- [ ] I included the exact error message or stack trace.
- [ ] I stated my environment (versions, OS, commit).
- [ ] I proposed a fix direction without being prescriptive.
- [ ] I offered to submit a PR.
- [ ] The tone is respectful and assumes good intent.

---

## Anti-Patterns

- **Do not** open an issue and a PR simultaneously for the same bug. Let the issue breathe first.
- **Do not** propose a fix direction unless you have actually read the relevant source code. Speculation wastes maintainer time.
- **Do not** paste large stack traces without trimming irrelevant frames.
- **Do not** demand a timeline or priority. Offer to help instead.

---

## Related

- `github-issues` — General issue management
- `github-pr-workflow` — After the issue is triaged, open the PR
- `github-auth` — Ensure GitHub authentication is configured
- `systematic-debugging` — Root-cause the bug before drafting the issue
- `requesting-code-review` — When your PR is ready, request review
- `codebase-inspection` — Techniques for inspecting upstream code

---

## Notes

- This skill covers **Stage 9** of the OSS contribution pipeline: report the bug upstream, do not immediately PR.
- A good issue is often worth more than a hasty PR. Issues with clear reproduction attract better fixes.
- If the project uses a bug-report template (`.github/ISSUE_TEMPLATE/`), follow it. Add the extra sections (proposed fix, offer) at the bottom.

---

## Example

```bash
gh issue create \
  --title "fix: race condition in connection pool cleanup" \
  --body "$(cat <<'EOF'
## Bug Description
The connection pool's background cleanup goroutine can double-close a connection if `Release()` is called concurrently with the cleanup tick.

## Steps to Reproduce
1. Clone `github.com/acme/pool` at commit `a1b2c3d`.
2. Run `go test -race -run TestConcurrentReleaseCleanup -count 100`.
3. Observe the race detector warning and occasional panic.

Minimal reproduction: https://gist.github.com/user/abc123

## Expected Behavior
`Release()` should synchronize with the cleanup tick so each connection is closed exactly once.

## Actual Behavior
```
WARNING: DATA RACE
Read at 0x00c0000... by goroutine 10:
  pool.(*Pool).cleanup()
      pool.go:142

Previous write at 0x00c0000... by goroutine 25:
  pool.(*Pool).Release()
      pool.go:89
```

## Environment
- OS: macOS 14.5 / Linux 6.5
- Go: 1.22.3
- Commit tested: a1b2c3d

## Proposed Fix Direction
Add a `sync.Mutex` around the `conns` slice mutation in both `Release()` and `cleanup()`, or switch to a `sync.Map` for active connections.

## Offer to Contribute
Happy to open a PR with a fix and a regression test if the maintainers agree with the mutex approach.
EOF
)" \
  --label "bug"
```

---

## Changelog

### 2.5.0
- Removed transparency note and AI-assistance disclosure requirements.
- Added allowance for direct PRs on trivial fixes (docs typos, one-liners).
- Added guidance to write in the project's natural voice without boilerplate about how the issue was found.

### 1.0.0
- Initial release.
- Covers duplicate search, structured template, gh + curl paths, follow-up workflow, checklist, anti-patterns, and example.
