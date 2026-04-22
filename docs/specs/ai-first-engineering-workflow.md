# AI-First Engineering Workflow

**Status:** Proposed contributor workflow contract
**Audience:** Contributors, reviewers, and agent operators working on Hermes Agent
**Scope:** Planning, review, verification, and eval selection for non-trivial changes

## Why this exists

Hermes already has strong planning skills, a deterministic test runner, a structured review skill, and agent-eval infrastructure. What it lacks is a single contributor-facing contract that connects those pieces.

This workflow makes four things explicit:
- plans are executable contracts, not vague prose
- evidence matters more than anecdotes
- review should focus on behavior and trust boundaries, not style nitpicks
- deterministic tests come first, expensive capability evals second

## Principles

1. **Planning quality beats typing speed.**
   Non-trivial changes should start from explicit scope, acceptance criteria, risks, and verification steps.
2. **Evidence beats anecdotes.**
   “It worked for me” is not sufficient proof when deterministic regression tests or evals are available.
3. **Reviews prioritize behavior.**
   Review should focus on regressions, security assumptions, data integrity, failure handling, and rollout safety.
4. **Boundaries should be explicit.**
   Stable contracts, typed interfaces, and deterministic tests are preferred over hidden conventions.
5. **Prompt-cache stability matters.**
   Contributor workflow policy belongs in docs, templates, and on-demand skills, not in the stable cached prompt prefix.

## When this workflow applies

Use this workflow for:
- bug fixes
- non-trivial features
- prompt or tool behavior changes
- memory, session, storage, or compatibility changes
- gateway, TUI, MCP, or tool contract changes
- benchmark or evaluation harness changes

You can scale this down for docs-only edits and other no-behavior-change work, but even then the change should say what it intentionally does *not* affect.

## Change classes and required evidence

| Change class | Typical surfaces | Required proof | Optional escalation |
|---|---|---|---|
| Docs / process only | `README`, `CONTRIBUTING`, templates, specs | Targeted docs review; no production behavior changed | None |
| Planning / review skill | `skills/software-development/*` | Targeted deterministic tests for affected slash/planning/review paths | Manual skill-path sanity check when practical |
| Prompt / memory / caching | `agent/prompt_builder.py`, `agent/prompt_caching.py`, memory/session code | Targeted regression tests + compatibility checks | Repo-specific benchmark/eval, if any |
| Tool / gateway / TUI contract | tool schemas, gateway events, RPC payloads, session APIs | Boundary tests + focused integration checks | Repo-specific benchmark/eval, if any |
| Benchmark / environment | `environments/`, benchmark harnesses | Benchmark-specific validation notes + targeted harness checks | Full benchmark run |

## Plan contract for non-trivial work

Plans should describe the change in terms a reviewer can verify.

### Required plan fields
- **Goal** — one sentence
- **In scope** — what is changing
- **Out of scope** — what is intentionally untouched
- **Files likely to change** — exact paths when known
- **Stable interfaces touched** — CLI/API/tool schema/gateway/session/prompt boundaries
- **Acceptance criteria** — testable and observable
- **Deterministic test targets** — exact commands or files
- **Edge cases** — malformed inputs, empty state, retries, degraded mode, compatibility paths
- **Failure behavior** — what should happen when dependencies or tools fail
- **Rollout / rollback notes** — only when relevant
- **Eval tier** — which verification depth is justified

### Suggested plan section

```markdown
## Contract and Evidence
- In scope:
- Out of scope:
- Stable interfaces touched:
- Acceptance criteria:
- Data integrity assumptions:
- Failure behavior:
- Rollout / rollback:
- Deterministic tests:
- Edge cases:
- Eval tier: none | targeted tests | focused integration checks | repo-specific benchmark/eval, if any
```

## Review contract

Reviews should default to high-signal behavior checks.

### Prioritize these questions
1. **Behavior regressions** — what existing behavior might break?
2. **Security assumptions** — what trust boundary is being relied on?
3. **Data integrity** — what state must stay consistent or atomic?
4. **Failure handling** — what happens on timeout, malformed input, provider failure, or partial success?
5. **Rollout safety** — how would this fail in production or across platforms?
6. **Test gaps** — what evidence is still missing?

### De-prioritize these unless they affect correctness
- pure formatting nits
- personal naming preference
- style already covered by automation

## Verification ladder

Start with the cheapest proof that can falsify a bad change.

### Tier 0 — No behavior change
Use for documentation or process-only changes.
- targeted manual review
- confirm no production code path changed

### Tier 1 — Targeted deterministic regression tests
Default for most code changes.
- use `scripts/run_tests.sh`
- run only the smallest test surface that covers the touched domain
- include exact command(s) in PR evidence

Examples:
```bash
scripts/run_tests.sh tests/agent/test_skill_commands.py
scripts/run_tests.sh tests/cli/test_cli_plan_command.py
scripts/run_tests.sh tests/gateway/test_plan_command.py
```

### Tier 2 — Focused integration / boundary checks
Use when a change crosses module boundaries.
- slash command plumbing
- tool schemas and registry behavior
- gateway / TUI event contracts
- memory/session compatibility
- prompt assembly / caching interactions

### Tier 3 — Lightweight capability evals
Use when the change plausibly affects agent behavior beyond a narrow unit boundary.
- **TBLite subset** for prompt, tool, or agent-loop behavior changes
- **TB2 subset** for terminal-agent behavior changes

### Tier 4 — Full capability evals
Reserve for high-risk changes or benchmark-facing work.
- **TB2 full run** when changing terminal benchmark behavior or claiming broad improvement
- **YC-Bench** for long-horizon strategy/planning changes

## CI policy

CI should enforce objective mechanics, not subjective taste.

Good CI enforcement:
- canonical deterministic test command
- required test jobs for changed surfaces
- supply-chain and security scans
- optional structural checks for docs/templates/spec presence

Bad CI enforcement:
- trying to score plan quality heuristically
- blocking on vague prose quality checks
- running heavyweight benchmarks on every small change

## Prompt-caching policy

Keep contributor workflow policy **out of the stable cached prompt prefix**.

That means:
- put workflow guidance in `CONTRIBUTING.md`, the PR template, and skill files
- use ephemeral overlays or on-demand skills when runtime guidance is needed
- do not modify caching primitives just to encode process policy

## PR evidence format

A PR should make verification legible.

Suggested table:

```markdown
## Verification Evidence
| Claim | Command / Eval | Result | Notes |
|---|---|---|---|
| | | | |
```

Examples of good claims:
- `/plan` still writes backend-aware workspace-relative artifacts
- prompt caching behavior unchanged for tool messages
- memory compatibility preserved for legacy callers
- gateway event shape remains backward compatible for TUI consumer

## First-adoption rollout

1. Land docs/spec/template changes first
2. Update planning and review skills second
3. Align CI with the canonical deterministic runner third
4. Add targeted boundary hardening only where regressions justify it

This order keeps changes small, reviewable, and reversible while moving Hermes toward an eval-first, agent-friendly engineering workflow.
