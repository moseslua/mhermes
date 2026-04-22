---
name: oss-reproduce
description: Stage 5 of the OSS contribution pipeline — fork the target repo, reproduce the candidate bug in an isolated worktree, and record evidence. If it does not reproduce, drop the candidate immediately.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [open-source, oss, reproduction, bug, worktree, fork, git, evidence]
    related_skills: [github-repo-management, systematic-debugging, test-driven-development]
---

# OSS Contribution — Stage 5: Local Reproduction

**Purpose:** Separate real bugs from hallucinated ones. A candidate that does not reproduce in a clean fork is dropped on the spot — no exceptions.

**Philosophy:** "Looks like a bug" is a hypothesis, not a bug report. Only candidates that survive a fork-and-reproduce test proceed. This single gate is responsible for the majority of merge-rate improvement in the pipeline.

---

## Prerequisites

- GitHub authentication configured (see `github-auth` skill)
- `gh` CLI or `git` + `curl` available
- A candidate bug from Stage 3/4 with a source repo, commit range, and reproduction hypothesis

---

## 1. Fork the Repository

Create a personal fork on GitHub, then clone it into a dedicated directory.

**With `gh`:**

```bash
# Fork under your own account and clone
gh repo fork owner/repo-name --clone

# Move into a dedicated workspace for this candidate
cd repo-name
```

**With `git` + `curl`:**

```bash
# Create fork via API
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/owner/repo-name/forks

# Wait briefly for GitHub to provision the fork
sleep 5

# Clone your fork
git clone https://github.com/$GH_USER/repo-name.git repo-name-repro
cd repo-name-repro

# Add upstream for reference
git remote add upstream https://github.com/owner/repo-name.git
```

---

## 2. Create an Isolated Worktree

Do not reproduce on `main` in your fork. Create a detached worktree so the reproduction environment is isolated and can be preserved.

```bash
# Ensure you are in the fork clone
cd /path/to/repo-name-repro

# Create a detached worktree for reproduction
git worktree add ../repo-name-repro-worktree -b reproduce/$(date +%Y%m%d)-candidate-id

# Enter the worktree
cd ../repo-name-repro-worktree
```

**Naming convention:** `reproduce/YYYYMMDD-<candidate-id>` (e.g., `reproduce/20260421-fix-null-deref`)

---

## 3. Prepare the Environment

Install dependencies and build the project exactly as upstream documents. Do not skip this.

```bash
# Checkout the exact commit where the bug is hypothesized to exist
git log --oneline -10
git checkout <commit-sha-or-tag>

# Follow the project's documented setup steps
# Examples:
#   pip install -e ".[dev]"
#   npm install
#   cargo build
#   make dev
```

**If the project requires a specific runtime, Python version, Node version, etc.:** match it exactly. Reproduction failures caused by environment mismatch are false negatives — they waste a candidate.

---

## 4. Reproduce the Bug

Translate the reproduction hypothesis into concrete steps and run them.

### 4.1 Extract the Reproduction Steps

From the candidate record produced by earlier stages, extract:
- The **trigger condition** (input, config, command, state)
- The **expected behavior**
- The **observed (buggy) behavior**
- The **commit range** where it was introduced (if known)

### 4.2 Run the Reproduction

```bash
# Example: run the failing test hypothesized in the candidate
pytest tests/test_module.py::test_specific_case -xvs

# Example: run a CLI invocation that triggers the bug
python -m my_tool --flag problematic-input.json

# Example: build and run a minimal reproducer script
python reproducer.py
```

### 4.3 Reproduction Decision Tree

| Outcome | Action |
|---------|--------|
| Bug reproduces exactly as hypothesized | Proceed to Section 5 |
| Bug reproduces, but symptom is different | Update the candidate record with corrected symptoms, then proceed |
| Bug does NOT reproduce | **Drop the candidate immediately.** Record the attempt in the ledger with `status: not-reproduced` and clean up the worktree |
| Cannot build / environment is incompatible | Record `status: blocked-environment`, preserve the worktree, and flag for human review |
| Flaky / non-deterministic | Run at least 5 times. If still inconsistent, record `status: flaky` and drop |

**Rule:** If the bug does not reproduce, do not rationalize, do not "try one more thing." Drop it.

---

## 5. Record Evidence

When the bug reproduces, capture everything needed for a future issue/PR.

### 5.1 Capture Console Output

```bash
# Run with output captured to a file
pytest tests/test_module.py::test_specific_case -xvs 2>&1 | tee evidence/reproduction.log

# If the bug is a crash, capture the backtrace
python reproducer.py 2>&1 | tee evidence/crash.log
```

### 5.2 Capture System State

```bash
# Record the exact commit
GIT_COMMIT=$(git rev-parse HEAD)
echo "Commit: $GIT_COMMIT" > evidence/environment.txt

# Record relevant dependency versions
pip freeze > evidence/requirements.txt   # or equivalent
node --version >> evidence/environment.txt
python --version >> evidence/environment.txt
```

### 5.3 Capture Screenshots / Artifacts (if applicable)

For UI bugs or visual regressions, capture screenshots before and after the trigger.

---

## 6. Preserve the Worktree

The worktree is the canonical reproduction environment. Preserve it so any agent, in any future session, can resume from the exact state.

### 6.1 Commit Evidence to the Worktree Branch

```bash
mkdir -p evidence
git add evidence/
git commit -m "repro: record evidence for <candidate-id>

- Reproduced on commit $GIT_COMMIT
- Trigger: <one-line description of trigger>
- Symptom: <one-line description of observed behavior>
"
```

### 6.2 Do Not Delete the Worktree

Keep the worktree intact. The branch `reproduce/YYYYMMDD-<candidate-id>` and the worktree directory serve as the durable reproduction context.

**If disk space is a concern:** compress the worktree directory into a tarball, but do not delete it until the candidate is either merged or permanently dropped.

```bash
tar czf ../repo-name-repro-worktree.tar.gz ../repo-name-repro-worktree
```

---

## 7. Link in the Ledger

Update the candidate ledger (or the tracking issue) with the reproduction outcome. The ledger is the source of truth that survives session restarts and agent handoffs.

### 7.1 Ledger Entry Format

```yaml
- candidate_id: <uuid-or-short-name>
  repo: owner/repo-name
  fork: $GH_USER/repo-name
  stage: 5
  status: reproduced          # or not-reproduced, blocked-environment, flaky
  worktree_path: /absolute/path/to/repo-name-repro-worktree
  branch: reproduce/YYYYMMDD-candidate-id
  commit: <full-sha>
  reproduced_at: <ISO-8601>
  evidence_dir: evidence/
  trigger: "<one-line trigger description>"
  symptom: "<one-line symptom description>"
  notes: "<any caveats, flakiness observations, or environment requirements>"
```

### 7.2 Update the GitHub Tracking Issue (if used)

If the pipeline uses a GitHub issue as the source-of-truth checklist, update the Stage 5 checkbox:

```markdown
- [x] Stage 5 — Local reproduction
  - Worktree: `/path/to/repo-name-repro-worktree`
  - Branch: `reproduce/20260421-candidate-id`
  - Commit: `abc123def...`
  - Evidence: `evidence/reproduction.log`
```

---

## 8. Cleanup on Drop

If the candidate was dropped (not reproduced, flaky, or blocked with no path forward):

```bash
# Remove the worktree
git worktree remove ../repo-name-repro-worktree --force

# Delete the local branch
git branch -D reproduce/YYYYMMDD-candidate-id

# Optionally delete the remote branch on your fork
git push origin --delete reproduce/YYYYMMDD-candidate-id
```

**Retain:** the ledger entry with `status: not-reproduced` so the candidate is not re-evaluated in a future run.

---

## Quick Reference

| Step | Command / Action |
|------|------------------|
| Fork | `gh repo fork owner/repo --clone` |
| Worktree | `git worktree add ../repo-repro -b reproduce/YYYYMMDD-id` |
| Checkout target | `git checkout <commit-sha>` |
| Reproduce | Run the hypothesized trigger; observe |
| Drop rule | If it does not reproduce → drop immediately |
| Record | `tee evidence/reproduction.log`, capture env, commit to branch |
| Preserve | Keep worktree + branch intact; link in ledger |
| Link | Update ledger YAML and GitHub issue checkbox |

---

## Anti-Patterns

- **Do not reproduce on the fork's `main` branch** — always use an isolated worktree.
- **Do not skip the build/setup step** — "it probably works" is not a valid assumption.
- **Do not chase flaky bugs** — if it is not reliably reproducible, drop it.
- **Do not rationalize non-reproduction** — "maybe it needs a specific database" means the hypothesis was wrong. Drop it.
- **Do not delete the worktree before linking it** — the ledger must contain a durable path.

---

## Related Skills

- `github-repo-management` — Forking, cloning, and remote management
- `systematic-debugging` — Root-cause analysis when reproduction reveals unexpected behavior
- `test-driven-development` — Writing a failing test as the reproduction artifact

---

**End of Stage 5.** If `status: reproduced`, the candidate proceeds to Stage 6 (Re-examination). If dropped, return to Stage 3 for the next candidate.

Stage 5 is the gate. Respect it.
