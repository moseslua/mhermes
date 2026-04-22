# Test Spec — Hermes All-Features Integration

## Scope
This test specification covers the phased implementation defined in:
- `.omx/plans/prd-hermes-all-features-integration.md`

The goal is to prove that Hermes absorbed all requested feature families while preserving:
- one runtime,
- one canonical domain store,
- one plugin contract,
- explicit approval and audit boundaries for risky autonomy.

---

## Gate 0 — Migration and baseline safety

### Assertions
- Existing Hermes sessions remain readable after schema migration.
- Existing plugin/provider loading still works before new features are enabled.
- No profile-unsafe path regression is introduced.

### Tests
- Migration tests for `hermes_state.py` from current schema to new schema.
- Plugin discovery/load regression tests using existing `tests/hermes_cli/test_plugins.py` patterns.
- Path resolution tests ensuring no hardcoded `~/.hermes` writes bypass `get_hermes_home()`.

Pass criteria
- Zero existing-session corruption.
- No plugin load regressions.
- No profile breakage.

---

## Gate 1 — Runtime signals and hook completion

### Unit tests
- `RuntimeSignal` envelope validation.
- `sequence_no` monotonicity per session.
- `idempotency_key` behavior for replayable events.
- Hook derivation from runtime signals.
- Presence of new `on_slash_command` hook.

### Integration tests
- `run_agent.py` emits `session.*`, `slash_command.*`, `llm.call.*`.
- `model_tools.py` emits `tool.call.*` for requested/completed/failed/blocked.
- `tools/approval.py` emits `approval.*`.
- Missing currently-declared hooks (`post_tool_call`, `post_llm_call`, `pre_api_request`, `post_api_request`) are wired and observed.

### Observability checks
- Audit retention/sampling knobs respected.
- Business-significant signals persist by default.
- Verbose `tool/llm/api` payload capture remains sampled/off until benchmark passes.

Pass criteria
- Hook/signal hierarchy is deterministic.
- No false exactly-once assumption in code or tests.
- All declared runtime hooks fire from canonical publishers.

---

## Gate 2 — Camel trust boundary

### Unit tests
- Trusted vs untrusted provenance tagging.
- Capability classification and policy evaluation for `off|monitor|enforce`.
- Provider metadata stripping before outbound calls.
- Blocking of unauthorized sensitive capabilities.

### Integration tests
- Tool output, file content, browser content, MCP data, and session recall enter the model as untrusted provenance.
- Trusted operator intent authorizes allowed side effects.
- Monitor mode records decisions without blocking.
- Enforce mode blocks unauthorized side effects.

### Adversarial tests
- Inject prompt-injection payloads in tool outputs and retrieved content.
- Verify unauthorized terminal, memory, plugin, messaging, scheduling, or browser actions are blocked.

Pass criteria
- Policy decisions are auditable.
- No unauthorized sensitive side effect is executed in enforce mode.

---

## Gate 3 — Mission graph and `todo` semantics

### Unit tests
- `missions`, `mission_nodes`, `mission_links` CRUD.
- Mission status lifecycle transitions.
- Write-through `todo` semantics under active mission.
- Session-local `todo` behavior when no mission is attached.

### Integration tests
- Delegation persists `handoff_packets` linked to missions.
- Mission checkpoints persist and restore correctly.
- Review/fix links resolve correctly.
- Mission nodes drive Mission Control views.

### Behavioral tests
- Attach a mission to a session.
- Add/edit/complete/remove `todo` items.
- Confirm these mutate mission task rows, not a second durable store.
- Detach mission and confirm session-local todo view resumes.

Pass criteria
- No dual writable representation exists for tasks.
- Mission state is canonical across CLI/TUI/web.

---

## Gate 4 — Proposal engine and generated artifacts

### Unit tests
- Workflow/proposal detection over runtime signals and domain state.
- Proposal queue dedupe and ranking.
- Projection-safe scaffold generation for skills/plugins.

### Integration tests
- Approved skill generation routes through `skill_manage`.
- Generated skills are scanned by `skills_guard`.
- Generated plugins are packaged and scanned/quarantined by `plugin_guard`.
- No auto-activation occurs without explicit approval.

### QA tests
- Observe repeatable workflow.
- Proposal appears in dashboard/TUI.
- Approve skill generation.
- Confirm generated artifact lands in proper Hermes-native location and remains disabled/quarantined until explicitly activated.

Pass criteria
- Proposal-only by default.
- No unsafe or unscanned generated artifact becomes active automatically.

---

## Gate 5 — Shared memory, briefs, telemetry, and projections

### Unit tests
- Shared-memory service composes canonical history plus memory callbacks.
- Projection cursor semantics use `last_applied_audit_id`.
- Projection replay is idempotent.
- Full delete-and-rebuild fallback works.

### Integration tests
- Shared-memory service respects the one-external-provider invariant.
- Daily brief generation reads canonical domain state.
- FABRIC/Obsidian/mission-bundle projections consume canonical sources only.

### End-to-end tests
- Enable FABRIC/Obsidian projections.
- Generate artifacts.
- Delete target output.
- Rebuild from canonical state.
- Verify regenerated output is correct and no source data was lost.

Pass criteria
- Projections are one-way, idempotent, and rebuildable.
- No projection becomes an authoritative input path.

---

## Gate 6 — ModelOpsService and protected mutation path

### Unit tests
- Protected model-key classification.
- `ModelOpsService` mutation creation, approval, execution, rollback.
- Drift detection for direct `.env` changes.

### Integration tests
- CLI/TUI/browser/scheduler/web requests all route through `ModelOpsService`.
- `hermes_cli/model_switch.py` acts as backend, not alternate mutation path.
- `/api/env` and generic config endpoints reject protected-key writes without approved mutation context.

### End-to-end tests
- Request model change in UI/CLI.
- Approve mutation.
- Verify runtime change occurs and is audited.
- Roll back.
- Verify rollback restores prior state.
- Attempt direct protected-key write via generic env endpoint and verify rejection.

Pass criteria
- One writable authority for model identity.
- No bypass path survives.

---

## Gate 7 — Browser terminal and cloud packaging

### Integration tests
- Browser terminal attaches only through `web_server` → `tui_gateway`.
- No second PTY/runtime stack is started.
- Browser provider switcher talks to `ModelOpsService` only.
- Fly packaging starts official Hermes runtime, not vendored snapshot logic.
- Volume bootstrap and optional sidecar startup operate correctly.

### Security tests
- Auth/token checks enforced before browser session attach.
- Public bind blocked until auth hardening gate is green.
- Plugin/dashboard/browser routes reject unauthenticated mutation.

### End-to-end tests
- Start deployed/browser package.
- Log in.
- Attach terminal.
- Use Mission Control.
- Attempt protected mutation without approval and verify block.

Pass criteria
- Browser/cloud surface is a wrapper over Hermes, not a second runtime.
- Auth boundary is enforced.

---

## Gate 8 — Performance and observability

### Benchmarks
Run representative 4-session mixed CLI/TUI/web load.

Measure:
- p95 SQLite writer wait
- TUI/gateway visible stall duration
- sampled audit growth rate
- proposal/mission-control latency

Required thresholds
- p95 SQLite writer wait < 25ms
- no visible `tui_gateway`/TUI stall > 250ms
- sampled audit growth remains within configured retention budget
- mission-control/dashboard interactions remain within agreed latency budget

### Observability tests
- Correlation IDs present across runtime signals, approvals, missions, handoffs, child sessions, exports/evals, and model mutations.
- Drift detection between canonical state and projections works.
- Protected model-key drift at startup is surfaced.
- Canary checks for public/cloud deployment health pass.

Pass criteria
- Benchmark gate passes before verbose runtime capture is enabled.
- Operators can diagnose failures from metrics/logs without consulting mirror outputs.

---

## Final acceptance checklist
- [ ] All requested repo feature families have working Hermes-native landing zones.
- [ ] Hermes remains the only runtime.
- [ ] `state.db` remains canonical for domain state.
- [ ] Hook/signal contract is complete and test-covered.
- [ ] Camel trust boundary works in monitor and enforce modes.
- [ ] Mission graph and `todo` semantics are canonical and unambiguous.
- [ ] Proposal engine is approval-gated and generated artifacts are scanned/quarantined.
- [ ] Shared memory and projections are one-way and rebuildable.
- [ ] Model mutation path is singular, approved, audited, and rollback-capable.
- [ ] Browser/cloud packaging wraps Hermes without introducing a second runtime.
- [ ] Benchmark and observability gates pass.
