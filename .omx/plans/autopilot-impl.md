# Autopilot Implementation Plan — Hermes All-Features Integration

## Source
`.omx/plans/autopilot-spec.md` → `.omx/plans/prd-hermes-all-features-integration.md`

## State
79 files modified, ~8k lines uncommitted on `main`. Prior session completed Phase 1 (runtime signals, mission state) and Phase 2 (shared memory scaffolding).

---

## Phase A — Protect Current Work (sequential, must be first)

**Goal:** Commit the 79-file diff to a feature branch before any further work.

**Steps:**
1. `git checkout -b feat/all-features-integration`
2. `git add -A`
3. `git commit -m "wip(hermes): phase 1-2 — runtime signals, mission graph, shared memory scaffolding"`
4. Push branch (optional, preserves remote backup)

**Acceptance:** `git status` shows clean working tree on the feature branch.

---

## Phase B — Schema Completion (sequential)

**Goal:** Add all missing authoritative domain tables to `hermes_state.py`.

**Files:**
- `hermes_state.py` — add CREATE TABLE statements
- `tests/conftest.py` — ensure migration fixture covers new tables

**Missing tables:**
- `approvals` (approval_id, session_id, request_type, requested_at, approved_at, approved_by, status, payload_json)
- `proposals` (proposal_id, session_id, proposal_type, title, description, status, created_at, reviewed_at, scaffold_path)
- `model_mutations` (mutation_id, session_id, key, old_value, new_value, requested_at, approved_at, status, rollback_value)
- `learning_exports` (export_id, session_id, export_type, path, created_at, status)
- `eval_runs` (eval_id, session_id, eval_type, result_json, created_at)
- `projection_cursors` (cursor_id, projection_type, last_applied_audit_id, last_snapshot_hash, last_projection_version, updated_at)
- `analytics_rollups` (rollup_id, rollup_type, period_start, period_end, data_json, created_at)

**Acceptance:** All new tables are queryable after `SessionDB` initialization. Migration tests pass.

---

## Phase C — Parallel Implementation Lanes (3 lanes)

### Lane C1 — Runtime Policy + CaMeL Trust Boundary (Gate 1-2)

**Goal:** Implement CaMeL-style provenance tagging and capability gating.

**Files:**
- **Create** `agent/runtime_policy.py`:
  - `Provenance` enum: `trusted`, `untrusted`
  - `Capability` enum: `terminal`, `memory`, `plugin`, `messaging`, `scheduling`, `browser`, `file_write`, `model_mutation`
  - `PolicyMode` enum: `off`, `monitor`, `enforce`
  - `RuntimePolicy` class: evaluate capability requests against policy mode
  - `strip_provider_metadata(payload)` — redact sensitive fields before outbound calls
- **Modify** `agent/runtime_signals.py`:
  - Add `provenance` field to `RuntimeSignal`
  - Add `actor` and `subject` fields
- **Modify** `run_agent.py`:
  - Tag tool outputs, file content, browser content, MCP data as `untrusted` provenance
  - Tag operator intent (direct user messages) as `trusted`
  - Route sensitive capabilities through policy check before execution
- **Modify** `model_tools.py`:
  - Emit `tool.call.*` signals with provenance metadata
- **Modify** `tools/approval.py`:
  - Emit `approval.*` signals
- **Tests:**
  - `tests/agent/test_runtime_policy.py` — policy evaluation, provenance tagging
  - `tests/agent/test_runtime_signals.py` — signal emission, sequence_no monotonicity

**Acceptance:**
- `enforce` mode blocks unauthorized sensitive side effects
- `monitor` mode records decisions without blocking
- All declared runtime hooks fire from canonical publishers
- Adversarial tests pass (prompt injection in tool outputs → blocked in enforce mode)

### Lane C2 — Proposal Engine + ModelOps (Gate 4, Gate 6)

**Goal:** Implement approval-gated proposal generation and protected model mutation path.

**Files:**
- **Create** `agent/proposal_engine.py`:
  - `ProposalEngine` class: detect workflow patterns from runtime signals
  - Proposal queue with dedupe and ranking
  - Scaffold generation for skills/plugins (projection-safe)
  - Integration with `tools/skill_manager_tool.py` and `tools/plugin_guard.py`
- **Modify** `hermes_state.py`:
  - Add proposal CRUD methods
- **Create** `agent/model_ops.py`:
  - `ModelOpsService` class: sole mutation service for provider/model/base-URL/API-key
  - Mutation creation → approval → execution → rollback pipeline
  - Drift detection for direct `.env` changes at startup
- **Modify** `hermes_cli/model_switch.py`:
  - Route all model changes through `ModelOpsService`
- **Modify** `hermes_cli/web_server.py`:
  - Reject protected-key writes via generic `/api/env` without approved mutation context
- **Tests:**
  - `tests/agent/test_proposal_engine.py` — detection, dedupe, scaffold generation
  - `tests/agent/test_model_ops.py` — mutation CRUD, approval flow, rollback, drift detection

**Acceptance:**
- Proposals are generated-only by default (no auto-activation)
- Generated skills land quarantined until explicitly activated
- `ModelOpsService` is the only writable authority for model identity
- Generic config endpoints reject protected-key writes without mutation context

### Lane C3 — State Projections + Packaging (Gate 5, Gate 7)

**Goal:** Implement one-way projections and cloud/browser packaging.

**Files:**
- **Create** `agent/state_projections.py`:
  - `ProjectionService` class: one-way mirrors to FABRIC_DIR, Obsidian, mission bundles
  - Incremental replay using `runtime_signal_audit.audit_id`
  - Full delete-and-rebuild fallback on stale cursor
  - Idempotent, atomic writes
- **Modify** `hermes_constants.py`:
  - Add `FABRIC_DIR` and projection path helpers
- **Create** `packaging/fly/`:
  - `Dockerfile` — official Hermes runtime entrypoint
  - `docker/entrypoint.sh` — volume bootstrap + optional sidecar startup
  - `fly.toml` — Fly.io configuration
- **Modify** `hermes_cli/web_server.py`:
  - Auth boundary for browser terminal attach
  - Route provider switching to `ModelOpsService`
- **Tests:**
  - `tests/agent/test_state_projections.py` — incremental replay, rebuild, idempotency

**Acceptance:**
- Projections are one-way and rebuildable from canonical state
- No projection becomes an authoritative input path
- Browser terminal attaches through `web_server` → `tui_gateway` (no second PTY)
- Fly packaging starts official Hermes runtime

---

## Phase D — Integration + Todo Write-Through (Gate 3)

**Goal:** Wire mission graph todo semantics and integration tests.

**Files:**
- **Modify** `tools/todo_tool.py`:
  - Add write-through facade: when mission attached, `todo add/edit/done/delete` mutates `mission_nodes` via `agent/mission_state.py`
  - When no mission, use existing session-local behavior
- **Modify** `run_agent.py`:
  - Initialize `MissionState` service
  - Bridge `todo` tool calls to mission state when `_mission_service` is active
- **Tests:**
  - `tests/tools/test_todo_tool.py` — mission-attached write-through
  - `tests/agent/test_mission_state.py` — attach/detach, CRUD, lifecycle transitions

**Acceptance:**
- No dual writable representation for tasks
- Mission state is canonical across CLI/TUI/web
- Session-local todos resume when mission detached

---

## Phase E — QA Cycles (UltraQA)

**Goal:** All tests pass.

**Command:**
```bash
scripts/run_tests.sh tests/cron/ tests/agent/ tests/tools/ tests/hermes_cli/ -v --tb=short
```

**Cycles:** Up to 5. Stop if same error repeats 3 times.

**Acceptance:** Zero test failures across modified test suites.

---

## Phase F — Validation (Multi-Perspective Review)

**Parallel reviews:**
1. **Architect** — Functional completeness against PRD feature matrix
2. **Security-reviewer** — Trust boundary enforcement, auth checks, no bypass paths
3. **Code-reviewer** — Quality, idioms, maintainability

**Acceptance:** All reviewers approve. Rejected items fixed and re-validated (max 3 rounds).

---

## Phase G — Cleanup + Branch Protection

1. Final commit with all changes
2. Update `README.md` with new capabilities
3. Clear autopilot state
4. Present summary to user

---

## Verification Commands

```bash
# Schema
python -c "from hermes_state import SessionDB; db = SessionDB(); print(db.list_tables())"

# Cron health
scripts/run_tests.sh tests/cron/test_jobs.py tests/cron/test_scheduler.py -v

# Mission
scripts/run_tests.sh tests/agent/test_mission_state.py tests/tools/test_todo_tool.py -v

# Policy
scripts/run_tests.sh tests/agent/test_runtime_policy.py tests/agent/test_runtime_signals.py -v

# Full suite
scripts/run_tests.sh tests/ -v --tb=short
```

---

## Risks / Mitigation

| Risk | Mitigation |
|---|---|
| Large diff is fragile | Commit to feature branch immediately (Phase A) |
| Schema migration breaks existing sessions | Normalize missing fields on read; test migration path |
| Trigger loops in cron | Dedupe on `last_run_at`; restrict v1 to failure-trigger only |
| Policy enforcement too aggressive | Default to `monitor` mode; `enforce` is opt-in |
| Proposal generation unsafe | Scaffold-only by default; quarantine generated artifacts |
| Model mutation bypass | Reject generic endpoint writes; detect `.env` drift |

## Parallelization Map

**Sequential:** A → B → D → E → F → G
**Parallel within C:** C1, C2, C3 can run simultaneously (no shared files)
**Safe overlap:** D can start after B completes; C lanes don't block D

## Estimation

- Phase A: 5 min
- Phase B: 30 min
- Phase C (3 lanes): 2-3 hours
- Phase D: 45 min
- Phase E: 1-2 hours
- Phase F: 30 min
- Phase G: 15 min

Total: ~5-7 hours

---
Generated: 2026-04-20T17:45:00Z
Phase: Planning (Phase 1)
