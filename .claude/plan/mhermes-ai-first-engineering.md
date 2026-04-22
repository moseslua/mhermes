# Implementation Plan: Integrate AI-First Engineering Traits into Hermes Agent

## Requirements Summary
Integrate AI-first engineering traits into Hermes Agent without changing production behavior first:
- planning quality matters more than typing speed
- eval coverage matters more than anecdotal confidence
- review should prioritize behavior regressions, security assumptions, data integrity, failure handling, and rollout safety
- architecture guidance should favor explicit boundaries, stable contracts, typed interfaces, and deterministic tests
- generated code should require regression coverage, explicit edge-case assertions, and interface-boundary integration checks

## Task Type
- [ ] Frontend (→ Gemini)
- [ ] Backend (→ Codex)
- [x] Fullstack / repo-wide workflow change (docs + skills + CI + targeted architecture hardening)

## Technical Solution
Treat AI-first engineering as a layered workflow contract instead of a runtime-prompt rewrite.

The recommended design has three layers:
1. **Contributor contract layer** — update docs, templates, and plan/review skills so every non-trivial change carries explicit acceptance criteria, regression evidence, risk framing, and eval selection.
2. **Mechanical verification layer** — align local and CI verification around the existing hermetic runner and define a lightweight eval ladder so contributor evidence is reproducible.
3. **Targeted architecture-hardening layer** — only where the repo already exposes fragile boundaries (tool schemas, slash-command registry, prompt assembly, session/storage, gateway/TUI event contracts), add typed contracts and deterministic boundary tests.

This fits the current repo because:
- planning and review skills already exist and are high leverage (`skills/software-development/plan/SKILL.md`, `skills/software-development/writing-plans/SKILL.md`, `skills/software-development/requesting-code-review/SKILL.md`)
- deterministic testing infrastructure already exists (`scripts/run_tests.sh`, `tests/conftest.py`)
- agent-eval infrastructure already exists (`environments/README.md`, TBLite/TB2/YC-Bench)
- prompt-caching docs explicitly warn against polluting the stable prompt prefix with volatile policy (`website/docs/developer-guide/prompt-assembly.md`, `agent/prompt_caching.py`)

## Current Strengths to Preserve
- `/plan` already writes planning artifacts in the active workspace via `build_plan_path()` (`agent/skill_commands.py:26-44`)
- the bundled plan skill is already planning-only and artifact-oriented (`skills/software-development/plan/SKILL.md:17-57`)
- the writing-plans skill already demands exact paths, TDD, and verification (`skills/software-development/writing-plans/SKILL.md:64-203`)
- the requesting-code-review skill already encodes baseline-aware verification and independent review (`skills/software-development/requesting-code-review/SKILL.md:35-238`)
- local deterministic testing is stronger than most repos already (`scripts/run_tests.sh:1-104`, `tests/conftest.py:1-258`)
- prompt assembly and caching are already explicitly designed around stable vs ephemeral context (`website/docs/developer-guide/prompt-assembly.md:27-40`, `website/docs/developer-guide/prompt-assembly.md:201-210`, `agent/prompt_caching.py:41-72`)

## Important Gaps
- PR workflow asks for generic test steps but not measurable acceptance criteria or AI-first evidence (`.github/PULL_REQUEST_TEMPLATE.md:13-61`)
- contributor docs still point to raw pytest flows instead of the canonical hermetic runner (`CONTRIBUTING.md` verification guidance; `scripts/run_tests.sh:1-104`)
- CI uses direct pytest and `-n auto`, diverging from the pinned-worker hermetic workflow (`.github/workflows/tests.yml:17-77`)
- benchmark/eval infrastructure exists but is not connected to normal contributor decision-making (`environments/README.md:138-154`)
- existing review skill is strong, but its results are not reflected in the human-facing PR contract by default

## Recommended Rollout Order
1. Docs/spec/template changes first
2. Plan/review skill changes second
3. CI alignment third
4. Targeted contract hardening and boundary tests after the workflow contract lands

This keeps the first PR small, reversible, and caching-safe.

## Implementation Steps

### Step 1 — Add a source-of-truth AI-first workflow spec
**Expected deliverable:** one concise repo spec that defines the policy once and lets other docs/skills point to it.

Create a small spec, for example `docs/specs/ai-first-engineering-workflow.md`, modeled after the repo’s existing behavior/spec format (`docs/specs/container-cli-review-fixes.md:1-220`).

The spec should define:
- what “AI-first evidence” means in this repo
- which change classes require which verification depth
- what reviewers must check beyond style
- what must stay out of cached runtime prompts
- how capability evals differ from regression evals

Suggested structure:
```markdown
# AI-First Engineering Workflow

## Principles
- Plans are executable contracts
- Evidence beats anecdotes
- Reviews prioritize behavior and trust boundaries
- Deterministic tests first, expensive evals second

## Change Classes
- docs/process-only
- planning/review skill changes
- prompt assembly / caching / memory
- gateway / TUI / MCP / tool contract changes
- benchmark / environment changes

## Required Evidence by Class
| Change class | Required proof |
|---|---|
| docs/process-only | targeted docs lint/check + no code path changes |
| plan/review skill | targeted slash/skill tests + one manual invocation path |
| prompt/cache/memory | targeted regression tests + compatibility tests |
| gateway/TUI/tool contract | boundary tests + integration checks |
| benchmark changes | benchmark-specific validation notes |
```

### Step 2 — Make contributor-facing process AI-first by default
**Expected deliverable:** contributor docs and PR template ask for behavior/evidence, not just prose.

Update `CONTRIBUTING.md` and `.github/PULL_REQUEST_TEMPLATE.md` together.

#### 2a. Update contributor verification guidance
Replace direct `pytest` guidance with the canonical hermetic runner and explicitly require targeted evidence.

Rationale:
- `scripts/run_tests.sh` enforces UTC, C.UTF-8, `PYTHONHASHSEED=0`, credential stripping, and pinned workers (`scripts/run_tests.sh:1-104`)
- `tests/conftest.py` reinforces hermetic invariants (`tests/conftest.py:1-258`)

Add a short “AI-first engineering” section to `CONTRIBUTING.md` that says:
- plan before non-trivial implementation
- every behavior change needs explicit acceptance criteria
- generated code must come with regression proof for touched domains
- reviewers care most about behavior, security, data integrity, failure handling, and rollout safety
- use `scripts/run_tests.sh`, not raw `pytest`, unless the task explicitly justifies something narrower

#### 2b. Upgrade the PR template
Extend `.github/PULL_REQUEST_TEMPLATE.md` (`.github/PULL_REQUEST_TEMPLATE.md:13-61`) with mandatory evidence fields.

Suggested additions:
```markdown
## Behavior Contract
- What user-visible or system-visible behavior changes?
- What must remain unchanged?

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Verification Evidence
| Claim | Command / Eval | Result | Notes |
|---|---|---|---|
| | | | |

## AI-First Review Risks
- Behavior regressions:
- Security assumptions:
- Data integrity risks:
- Failure handling / degraded mode:
- Rollout / rollback safety:

## Interface Boundaries Touched
- [ ] none
- [ ] tool schema / registry
- [ ] slash command / CLI surface
- [ ] gateway/TUI event contract
- [ ] prompt assembly / caching
- [ ] memory/session storage
- [ ] benchmark / eval harness
```

### Step 3 — Rework planning skills around contracts and evals
**Expected deliverable:** plan artifacts ask for measurable proof, not just task lists.

Update:
- `skills/software-development/plan/SKILL.md` (`:17-57`)
- `skills/software-development/writing-plans/SKILL.md` (`:64-203`)
- optionally the surrounding docs for `/plan`

Required additions to generated plans:
- explicit in-scope / out-of-scope list
- touched contracts/boundaries
- deterministic test targets
- edge-case assertions
- regression vs capability eval choice
- failure-mode expectations
- rollout/rollback note when relevant
- prompt-caching impact note when touching prompt assembly, memory, skills, or context compression

Suggested plan block:
```markdown
## Contract and Evidence
- In scope:
- Out of scope:
- Stable interfaces touched:
- Data integrity assumptions:
- Failure behavior:
- Rollout / rollback:
- Deterministic tests:
- Edge cases:
- Eval tier: none | targeted tests | TBLite subset | TB2 | YC-Bench
```

Important constraint: do **not** move volatile workflow policy into cached runtime layers. Keep this in skill output and docs, not `agent/prompt_caching.py` or the stable prompt prefix.

### Step 4 — Rework the review skill around AI-first failure modes
**Expected deliverable:** the review skill produces findings in behavior-oriented buckets.

Update `skills/software-development/requesting-code-review/SKILL.md` (`:114-238`).

Keep the existing baseline-aware verification and independent reviewer concept, but change the rubric shape from generic issues into explicit AI-first categories.

Suggested reviewer output shape:
```json
{
  "passed": false,
  "behavior_regressions": [],
  "security_assumptions": [],
  "data_integrity": [],
  "failure_handling": [],
  "rollout_safety": [],
  "test_gaps": [],
  "summary": "one sentence verdict"
}
```

Also change the self-review checklist so it explicitly asks:
- what old callers might break?
- what malformed/empty/error inputs were asserted?
- what degraded behavior is expected if a provider/tool/subprocess fails?
- what state mutation must remain atomic/consistent?

### Step 5 — Align CI with the repo’s deterministic test contract
**Expected deliverable:** CI and local evidence are materially closer.

Update `.github/workflows/tests.yml` (`:17-77`) so the main Python test job invokes `scripts/run_tests.sh` or mirrors its behavior exactly.

Minimum target:
- same hermetic env stripping expectations
- same UTC/locale/hashseed semantics
- same worker count or a documented reason for divergence

Recommended shape:
```yaml
- name: Run hermetic tests
  run: |
    source .venv/bin/activate
    scripts/run_tests.sh tests/
```

Keep `tests/e2e` separate if needed, but document the difference clearly.

### Step 6 — Document a lightweight eval ladder using existing benchmark infrastructure
**Expected deliverable:** contributors know when to stop at targeted regression tests and when to escalate to agent benchmarks.

Use `environments/README.md` and benchmark docs to define a practical ladder, not a maximalist one.

Recommended ladder:
1. **Targeted deterministic regression tests** — default for most code changes
2. **Focused integration/boundary checks** — when touching slash-command plumbing, tool schemas, gateway/TUI contracts, memory/session compatibility, prompt assembly
3. **TBLite subset** — for prompt/tool/agent-loop changes expected to affect coding-agent behavior
4. **TB2 subset/full** — only when changing terminal agent behavior or claiming benchmark-level improvement
5. **YC-Bench fast_test/default** — only for long-horizon planning/strategy changes

Suggested documentation table:
```markdown
| Surface touched | Required proof | Optional escalation |
|---|---|---|
| docs/process only | targeted docs checks | none |
| /plan, skill plumbing | targeted CLI/gateway tests | manual skill run |
| prompt/memory/caching | targeted regression tests | TBLite subset |
| tool/gateway/TUI contracts | boundary tests + integration checks | TBLite/TB2 subset |
| benchmark code | benchmark-specific validation | full benchmark run |
```

### Step 7 — Add targeted contract hardening only where it pays off
**Expected deliverable:** a prioritized backlog, not a speculative refactor wave.

After the workflow contract lands, harden the most fragile boundaries with explicit types and deterministic tests.

Start with surfaces that historically regress or fan out widely:
- `agent/skill_commands.py:26-44` — plan path and slash-command contract
- tool registry / schemas (`tools/registry.py`, `model_tools.py`) — stable tool contracts
- session/storage compatibility surfaces (`hermes_state.py`, related callers)
- prompt assembly / caching boundaries (`agent/prompt_builder.py`, `agent/prompt_caching.py`)
- gateway/TUI event contracts (`tui_gateway`, `ui-tui` bridge)

Use small types (`TypedDict`, dataclasses, existing typing patterns) and boundary tests. Do **not** add a new dependency or rewrite broad modules just to satisfy the principle.

## Key Files
| File | Operation | Description |
|------|-----------|-------------|
| `docs/specs/ai-first-engineering-workflow.md` | Create | Source-of-truth workflow contract for plans, review, and eval tiers |
| `CONTRIBUTING.md` | Modify | Add AI-first engineering section and replace raw pytest guidance with `scripts/run_tests.sh` |
| `.github/PULL_REQUEST_TEMPLATE.md` | Modify | Require acceptance criteria, verification evidence, risk framing, and interface-boundary disclosure |
| `skills/software-development/plan/SKILL.md` | Modify | Make `/plan` outputs contract/eval aware |
| `skills/software-development/writing-plans/SKILL.md` | Modify | Replace code-dump bias with contract/evidence requirements |
| `skills/software-development/requesting-code-review/SKILL.md` | Modify | Shift reviewer rubric to behavior/security/data/failure/rollout categories |
| `.github/workflows/tests.yml` | Modify | Align CI with the hermetic deterministic test runner |
| `environments/README.md` | Modify | Add contributor-facing eval ladder using existing benchmark infrastructure |
| `website/docs/developer-guide/prompt-assembly.md` | Modify (small) | Add a warning that contributor workflow policy should stay outside stable cached prompt layers |
| `agent/prompt_caching.py` | No code change expected | Preserve as a pure caching primitive; reference only in docs/spec rationale |

## Test / Verification Strategy
### Minimum deterministic regression bundle
- `scripts/run_tests.sh tests/agent/test_skill_commands.py`
- `scripts/run_tests.sh tests/cli/test_cli_plan_command.py`
- `scripts/run_tests.sh tests/gateway/test_plan_command.py`
- if prompt/caching docs or behavior change extends to code paths: `scripts/run_tests.sh tests/agent/test_prompt_caching.py`

### CI verification
- confirm `.github/workflows/tests.yml` now materially matches the hermetic runner or documents any intentional divergence

### Optional evaluation bundle
- TBLite subset for agent-loop/prompt/tool behavior changes
- TB2 or YC-Bench only if the touched surface justifies it

## Pseudo-code / Checklist Snippets
### Contributor verification matrix
```markdown
## Verification Evidence
| Claim | Command / Eval | Result | Notes |
|---|---|---|---|
| /plan still writes workspace-relative plans | scripts/run_tests.sh tests/cli/test_cli_plan_command.py tests/gateway/test_plan_command.py | pass | |
| skill command plan path stays backend-aware | scripts/run_tests.sh tests/agent/test_skill_commands.py | pass | |
| prompt caching behavior unchanged | scripts/run_tests.sh tests/agent/test_prompt_caching.py | pass | only if touched |
```

### Eval tier selector
```python
if change_class in {"docs-only", "process-only"}:
    eval_tier = "none"
elif change_class in {"plan-skill", "review-skill", "slash-command-plumbing"}:
    eval_tier = "targeted deterministic tests"
elif change_class in {"prompt-assembly", "memory", "tool-contract", "gateway-tui-boundary"}:
    eval_tier = "targeted tests + integration checks"
    optional = "TBLite subset"
elif change_class in {"agent-loop", "benchmark-runtime"}:
    eval_tier = "targeted tests + benchmark subset"
```

## Risks and Mitigation
| Risk | Mitigation |
|------|------------|
| Turning AI-first engineering into checklist theater | Keep enforcement focused on objective evidence fields and a small eval ladder; avoid broad prose-only mandates |
| Increasing contributor friction too much | Land docs/template changes first; add CI mechanics only after the workflow is stable |
| Polluting prompt caching with volatile process policy | Keep policy in docs, PR template, and opt-in skills; avoid adding it to stable prompt layers |
| Requiring expensive agent benchmarks on every change | Use the eval ladder; reserve TBLite/TB2/YC-Bench for the surfaces that justify them |
| Over-abstracting architecture in the name of typed boundaries | Harden only high-value boundaries with focused tests and small types |
| CI/local divergence remains hidden | Make the test workflow use `scripts/run_tests.sh` or document the exact exception |

## Open Questions
1. Should the first rollout be docs/skills only, or should CI alignment land in the same PR?
2. Should AI-first workflow policy get a small static note in `AGENTS.md`, or stay entirely in `CONTRIBUTING.md` + skills to avoid enlarging cached project context?
3. Which repo surfaces should trigger optional TBLite subset runs by policy: prompt assembly only, or also tool/gateway contract changes?

## SESSION_ID (for /ccg:execute use)
- CODEX_SESSION: `019da613-0deb-74b2-9c10-bd1f06c9552c`
- CODEX_ANALYSIS_SESSION: `019da60e-424d-77b0-8caf-d1e0dfb59574`
- GEMINI_SESSION: `[blocked] local Gemini CLI is not installed in this environment; ".ccg" wrapper/prompt paths were absent, and OMX team mode was unavailable outside tmux`

## Validation Notes
- Plan grounded in repo files and docs, not implementation guesses
- No production code was modified
- Plan artifact saved outside normal runtime `.hermes/plans` flow because this request explicitly asked for `.claude/plan/*`
