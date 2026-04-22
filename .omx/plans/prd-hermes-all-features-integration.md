# PRD — Hermes All-Features Integration

## Status
Approved RALPLAN consensus plan.

## Objective
Integrate the full feature families represented by:
- `hermes-agent-camel`
- `hermes-alpha`
- `hermes-skill-factory`
- `maestro`
- `icarus-plugin`

into Hermes as one coherent product, while keeping:
- Hermes as the only runtime,
- `state.db` as the canonical durable authority,
- the existing Hermes plugin/provider contracts as the only long-term extension contracts,
- and all risky autonomy behind explicit approval and audit paths.

## Desired Outcome
Hermes gains all requested capabilities:
- CaMeL-style trust-boundary enforcement
- cloud/browser-terminal deployment packaging
- workflow observation and skill/plugin proposal generation
- long-running mission planning, approval, handoff, checkpoint, and mission-control flows
- shared-memory analytics, training export/eval, daily briefs, and model-ops

without creating:
- a second runtime,
- a second canonical store,
- a second plugin contract,
- or silent model/config mutation paths.

---

## Non-goals
- Do not vendor or preserve any external repo as a peer runtime.
- Do not introduce `.maestro/`, `FABRIC_DIR`, or any other second canonical source of truth.
- Do not support legacy single-file plugin drop formats as a first-class long-term contract.
- Do not promise exactly-once semantics the runtime cannot honestly guarantee.
- Do not ship writable mirrors, silent plugin generation, or silent model mutation in the first release.

---

## Principles
1. Hermes stays primary.
2. One durable authority per concept.
3. One plugin contract.
4. Risky autonomy is gated.
5. All persistence is profile-safe and workspace-aware.

---

## Decision Drivers
1. Preserve every requested feature family.
2. Replace vague architecture language with explicit write paths, signal semantics, and cutover rules.
3. Make security, orchestration, memory, deployment, and model-management auditable before enabling stronger autonomy.

---

## Options Considered

### Option A — Service-first runtime signals + typed control-plane state + opt-in projections
Pros
- Preserves all feature families without split-brain runtime/state.
- Keeps Hermes primary.
- Makes write ownership explicit.
- Gives a clean audit boundary.

Cons
- Requires core schema/service work up front.
- Needs performance discipline around SQLite/WAL behavior.

Status: Chosen.

### Option B — Plugin-first adapter layer
Pros
- Smaller early diffs.
- Faster for some narrow wins.

Cons
- Poor fit for Camel and Maestro-style runtime/state features.
- High risk of second truth stores and plugin-local drift.

Status: Rejected.

### Option C — External companion control plane
Pros
- Fastest path to a standalone cloud/mission demo.

Cons
- Violates Hermes-primary runtime requirement.
- Recreates the same fork/snapshot debt seen in Alpha/Maestro patterns.

Status: Rejected.

---

## Final Decision
Adopt a service-first Hermes-native cutover:
- small typed runtime signals,
- authoritative mission/proposal/model/projection services,
- typed mission schema in `state.db`,
- bounded audit tables,
- one-way projections,
- browser terminal built on `web_server` + `tui_gateway`,
- deployment packages wrapping official Hermes entrypoints.

This is the only option that preserves all requested features while keeping the harness coherent.

---

## Feature Preservation Matrix

| Source repo | Feature family | Hermes landing zone | Concrete touchpoints |
|---|---|---|---|
| `hermes-agent-camel` | Trusted/untrusted separation, per-turn security envelope, capability gating, `off/monitor/enforce` | Core runtime signal + policy layer | `run_agent.py`, `model_tools.py`, `tools/approval.py`, `hermes_cli/plugins.py`, `hermes_cli/config.py`, new `agent/runtime_signals.py`, new `agent/runtime_policy.py` |
| `hermes-alpha` | Cloud packaging, volume bootstrap, sidecar startup | Canonical packaging around Hermes entrypoints | `Dockerfile`, `docker/entrypoint.sh`, `packaging/`, new `packaging/fly/` |
| `hermes-alpha` | Browser terminal, provider switcher | First-party web surface using existing session engine | `hermes_cli/web_server.py`, `web/src/`, `tui_gateway/server.py`, new `agent/model_ops.py` |
| `hermes-skill-factory` | Passive observation, pattern detection, proposal/review workflow | Proposal engine over canonical state/signals | `run_agent.py`, new `agent/proposal_engine.py`, `hermes_state.py`, dashboard/TUI proposal UIs |
| `hermes-skill-factory` | Skill generation | Existing skill path + scan/approval | `tools/skill_manager_tool.py`, `tools/skills_guard.py` |
| `hermes-skill-factory` | Plugin generation | Hermes-packaged plugin scaffolds only | `hermes_cli/plugins.py`, `hermes_cli/plugins_cmd.py`, new `tools/plugin_guard.py` |
| `maestro` | Mission/milestone/feature/assertion model | Persistent mission graph | `hermes_state.py`, new `agent/mission_state.py`, new `tools/mission_tool.py`, `tools/todo_tool.py` bridge |
| `maestro` | Handoff packets, checkpoints, bundles | Delegate/checkpoint integration; bundles as exports | `tools/delegate_tool.py`, `tools/checkpoint_manager.py`, new `agent/handoff_packets.py`, new `agent/state_projections.py` |
| `maestro` | Mission Control dashboard | First-party web/TUI surfaces | `hermes_cli/web_server.py`, `web/src/`, `ui-tui/src/`, `tui_gateway/server.py` |
| `icarus-plugin` | Shared memory, pending work, briefs, telemetry, corpus report | Canonical memory/analytics service over existing memory callbacks and state | `agent/memory_manager.py`, `tools/memory_tool.py`, `tools/session_search_tool.py`, `cron/jobs.py`, `cron/scheduler.py`, `hermes_state.py` |
| `icarus-plugin` | Training export, eval, model registry, switch/rollback | Approval-gated model-ops + learning services | `hermes_cli/providers.py`, `hermes_cli/model_switch.py`, new `agent/model_ops.py`, `agent/trajectory.py`, `tools/rl_training_tool.py`, `hermes_cli/web_server.py` |
| `icarus-plugin` | Review/fix linkage, quality metadata | Mission relations + artifact metadata | `tools/delegate_tool.py`, mission store, proposal engine, export/eval artifacts |
| `icarus-plugin` | Obsidian/FABRIC mirroring | Opt-in one-way projections only | new `agent/state_projections.py`, `hermes_constants.py`, workspace `.hermes/` outputs |

---

## Canonical Contracts

### 1. Runtime signal contract
Internal coordination uses a typed `RuntimeSignal` envelope, not a generic free-form bus.

Required fields:
- `event_id`
- `idempotency_key`
- `event_type`
- `phase`
- `occurred_at`
- `publisher`
- `session_id`
- optional `mission_id`
- `correlation_id`
- `sequence_no` (per-session only)
- `actor`
- `subject`
- `provenance`
- bounded/redacted `payload`

Initial publishers:
- `run_agent.py` → `session.*`, `slash_command.*`, `llm.call.*`
- `model_tools.py` → `tool.call.*`
- `tools/approval.py` → `approval.*`
- `agent/mission_state.py` / `tools/mission_tool.py` → `mission.*`, `mission.node.*`, `mission.link.*`
- `tools/delegate_tool.py` / `agent/handoff_packets.py` / `tools/checkpoint_manager.py` → `handoff.*`, `checkpoint.*`
- `agent/model_ops.py` → `model.mutation.*`, `learning_export.*`, `eval_run.*`
- `agent/state_projections.py` → `projection.run.*`
- `cron/jobs.py` → `daily_brief.*`

Hook derivation direction:
- Runtime signals are canonical internally.
- Existing plugin hooks are derived from signals through a `PluginHookAdapter`.
- Add `on_slash_command` as a new public hook.
- Mission/handoff/projection/model-op signals remain internal unless a concrete plugin use case emerges.

Delivery semantics:
- In-process synchronous consumers observe publisher order.
- `sequence_no` is per-session only.
- Durable audit/projection consumers are at-least-once.
- Exactly-once is not part of the contract.
- All downstream consumers must be idempotent.
- Domain truth does not depend on replaying audit rows alone.

### 2. Authoritative domain state vs bounded audit
`state.db` is split by purpose.

Authoritative domain tables:
- `missions`
- `mission_nodes`
- `mission_links`
- `handoff_packets`
- `mission_checkpoints`
- `approvals`
- `proposals`
- `model_mutations`
- `learning_exports`
- `eval_runs`
- `projection_cursors`

Bounded operational tables:
- `runtime_signal_audit`
- `projection_runs`
- `analytics_rollups`

Write ownership:
- Mission/handoff state → `agent/mission_state.py` + `tools/mission_tool.py`
- Proposal/generation workflow → `agent/proposal_engine.py`
- Model ops/learning jobs → `agent/model_ops.py`
- Projections → `agent/state_projections.py`
- Runtime audit/analytics → `agent/runtime_signals.py` recorder

Retention and benchmark gate:
- `approval.*`, `mission.*`, `handoff.*`, `proposal.*`, `model.mutation.*`, `projection.run.*` persist by default.
- `tool.call.*`, `llm.call.*`, `api.request.*` are sampled/redacted and off-by-default for verbose payload capture.
- Add config knobs for retention, sampling, and payload budgets.
- Do not enable verbose runtime audit by default until benchmark shows:
  - p95 SQLite writer wait < 25ms
  - no visible `tui_gateway`/TUI stall > 250ms
  - sampled audit growth stays within retention budget

### 3. Mission schema and `todo` semantics
Mission schema is locked now.

`missions`
- `mission_id`, `title`, `status`, `created_by_session_id`, `owner_session_id`, `principles_json`, `outcomes_json`, `created_at`, `approved_at`, `closed_at`

`mission_nodes`
- `node_id`, `mission_id`, `parent_node_id`, `node_type`, `title`, `body`, `status`, `acceptance_json`, `assignee_session_id`, `sort_key`, `created_at`, `updated_at`

`mission_links`
- `link_id`, `mission_id`, `from_node_id`, `relation_type`, `to_kind`, `to_id`, `created_at`

Separate lifecycle tables remain separate:
- `handoff_packets`
- `mission_checkpoints`
- `approvals`
- `proposals`
- `model_mutations`
- `learning_exports`
- `eval_runs`

`todo` contract:
- No active mission → existing session-local behavior
- Active mission attached → write-through facade over `mission_nodes` where `node_type='task'`
- `todo add/edit/done/delete` mutate mission task rows through `agent/mission_state.py`
- Session-local todo items are suspended from default view while mission-attached
- No reverse sync path

### 4. Model-ops cutover rule
Model identity gets one write path.

- Add `agent/model_ops.py` as sole mutation service for provider/model/base-URL/API-key settings.
- `hermes_cli/model_switch.py` becomes the execution backend for `ModelOpsService`.
- CLI/TUI/browser/scheduler/web flows all call `ModelOpsService`.
- Generic `/api/env` and config-update endpoints must reject protected model-key writes unless carrying approved mutation context.
- Startup detects direct `.env` drift and surfaces it for reconciliation instead of silently backfilling history.

### 5. Projection contract
Mirrors are outputs, not collaboration surfaces.

- `agent/state_projections.py` is the only writer for `FABRIC_DIR`, Obsidian notes, mission bundles, and similar mirrors.
- `projection_cursors` store:
  - `last_applied_audit_id`
  - `last_snapshot_hash`
  - `last_projection_version`
  - `updated_at`
- Incremental replay uses globally ordered `runtime_signal_audit.audit_id` for projection-relevant families.
- Projections consume canonical domain tables + approved audit families only.
- Writes are idempotent and atomic.
- Missing/stale/invalid cursor → full delete-and-rebuild from canonical state.
- Direct mirror edits are out of scope for initial integration and may be overwritten.

### 6. Canonical browser-terminal transport
Pick one transport now.

- `hermes_cli/web_server.py` owns browser auth and public HTTP/WebSocket boundary.
- Browser terminal attaches to `tui_gateway/server.py` after auth.
- Deploy packages may start web server + gateway together, but do not introduce a second PTY supervisor or alternate agent runner.
- Browser provider switching is only a UI over `ModelOpsService`.

---

## Target Architecture

### Runtime signal and policy core
Use `agent/runtime_signals.py` + `agent/runtime_policy.py` to absorb Camel-style trust-boundary logic, capability gating, provider-metadata stripping, and unified hook derivation.

### Canonical domain state and bounded audit
Expand `state.db` to hold mission/proposal/model/projection state while keeping audit/analytics bounded and rebuildable.

### Mission and handoff layer
Port Maestro concepts into first-party Hermes mission state with typed nodes, links, handoffs, checkpoints, and exports.

### Knowledge, proposal, and projection layer
Implement Hermes shared-memory and Skill Factory proposal flows over canonical state; emit one-way FABRIC/Obsidian/bundle projections.

### Model ops and learning layer
Implement Icarus-style model switching, export, eval, registry, and brief generation through `ModelOpsService` and linked artifacts.

### Experience and deployment surfaces
Implement Mission Control, browser terminal, and Fly packaging as wrappers over Hermes runtime/state APIs.

---

## Cutover Rules
1. Runtime rule
   - Canonical runtime is Hermes only.
   - No second long-lived runner copied from Alpha or Maestro.

2. Write-path rule
   - Every concept has one authoritative writer.
   - Audit rows observe transitions; they do not become alternate write paths.

3. Mission rule
   - Persistent work state is `missions` / `mission_nodes` / `mission_links`.
   - `todo` is session-local when unattached and write-through when attached.

4. Model-mutation rule
   - All model mutations flow through `ModelOpsService`.
   - Generic env/config endpoints cannot bypass it.

5. Projection rule
   - Outputs are one-way delete-and-rebuild projections with global-audit-cursor replay for projection-relevant signals.

6. Browser transport rule
   - Browser sessions attach only through `web_server` → `tui_gateway`.
   - No second PTY/runtime stack ships.

---

## Implementation Phases

### Phase 1 — Runtime signals, hook completion, and bounded audit foundation
Goal: replace vague event-bus language with explicit runtime signals and complete missing observation seams.

Touchpoints
- `run_agent.py`
- `model_tools.py`
- `hermes_cli/plugins.py`
- `tools/approval.py`
- `tools/delegate_tool.py`
- `tools/checkpoint_manager.py`
- `hermes_cli/config.py`
- `hermes_state.py`
- `hermes_cli/plugins_cmd.py`
- new `agent/runtime_signals.py`
- new `agent/runtime_policy.py`
- new `tools/plugin_guard.py`

Key work
1. Add `RuntimeSignal` envelope and publisher helper.
2. Publish from concrete call sites.
3. Route hooks through signal publisher; wire missing `post_*` / `pre_api_request` / `post_api_request`; add `on_slash_command`.
4. Add bounded audit tables plus retention/sampling knobs.
5. Add plugin guard parity with skill scanning.
6. Run contention benchmark; keep verbose audit capture off until gate passes.

Rollout gate
- Policy ships in `monitor` mode only.
- Verbose runtime capture remains sampled/off until benchmark passes.

### Phase 2 — Typed mission graph, `todo` write-through, and handoff authority
Goal: port Maestro orchestration concepts without `.maestro/` or dual work representations.

Touchpoints
- `hermes_state.py`
- `tools/todo_tool.py`
- `tools/delegate_tool.py`
- `run_agent.py`
- `agent/skill_commands.py`
- `tools/checkpoint_manager.py`
- new `agent/mission_state.py`
- new `tools/mission_tool.py`
- new `agent/handoff_packets.py`

Key work
1. Add locked mission schema + service APIs.
2. Implement mission lifecycle commands.
3. Make `todo` write-through for active missions.
4. Persist handoff packets and checkpoints; generate bundles as projections only.
5. Expose mission-control read APIs for CLI/TUI/web.

Rollout gate
- Internal missions enabled for CLI/TUI first.
- Mission activation requires explicit approval.

### Phase 3 — Shared memory, proposal engine, and one-way projections
Goal: land Skill Factory + FABRIC-style knowledge features without violating provider constraints or projection rules.

Touchpoints
- `agent/memory_manager.py`
- `agent/memory_provider.py`
- `tools/memory_tool.py`
- `tools/session_search_tool.py`
- `run_agent.py`
- `tools/skill_manager_tool.py`
- `tools/skills_guard.py`
- `hermes_constants.py`
- new `agent/proposal_engine.py`
- new `agent/state_projections.py`

Key work
1. Build Hermes shared-memory service over canonical session/history data and memory-manager callbacks.
2. Build proposal engine on runtime signals + domain tables.
3. Route skill generation through `skill_manage`.
4. Route plugin generation through packaged scaffolds + `plugin_guard` quarantine.
5. Add FABRIC/Obsidian/mission-bundle projections with cursor tracking and idempotent replay.
6. Attach Icarus-style metadata fields to proposals, reviews/fixes, and export artifacts.

Rollout gate
- Proposal queue visible, auto-apply disabled.
- Projections opt-in only.

### Phase 4 — Model ops, learning exports, daily briefs, and analytics
Goal: absorb Icarus operational features into existing provider/model seams with a hard mutation boundary.

Touchpoints
- `hermes_cli/providers.py`
- `hermes_cli/model_switch.py`
- `run_agent.py`
- `agent/trajectory.py`
- `tools/rl_training_tool.py`
- `cron/jobs.py`
- `cron/scheduler.py`
- `hermes_cli/web_server.py`
- analytics pages
- new `agent/model_ops.py`

Key work
1. Add `ModelOpsService` as sole mutation path.
2. Persist `model_mutations`, `learning_exports`, and `eval_runs` with approval/rollback state.
3. Protect `/api/env` and config endpoints from model-key bypass.
4. Generate daily briefs and review/fix linkages from canonical state.
5. Extend analytics surfaces from bounded audit + domain state.

Rollout gate
- Manual approval only for model changes.
- Protected-key rejection, rollback, and audit visibility must be verified before browser provider switching is enabled.

### Phase 5 — Mission Control, browser terminal, and cloud packaging
Goal: expose the control plane in dashboard/TUI/browser surfaces without creating a second runtime or auth stack.

Touchpoints
- `hermes_cli/web_server.py`
- `web/src/App.tsx`
- `web/src/pages/*`
- `ui-tui/src/app/*`
- `tui_gateway/server.py`
- `Dockerfile`
- `docker/entrypoint.sh`
- new `packaging/fly/`

Key work
1. Add dashboard Mission Control pages for missions, approvals, proposals, telemetry, and model history.
2. Add TUI mission/status integration.
3. Implement browser terminal attach/input/resize/stream via `web_server` bridge to `tui_gateway`.
4. Package Fly deployment, volume bootstrap, and optional sidecar startup.
5. Reuse existing token-protected APIs and approval queue patterns.

Rollout gate
- No public/cloud deployment until auth hardening, gateway isolation, and browser transport tests pass.
- Browser provider switcher stays disabled until Phase 4 cutover is complete.

### Phase 6 — Rollout hardening, migration, and documentation
Goal: turn the architecture into a safe staged release.

Key work
1. Set conservative defaults.
2. Tune retention/sampling/contention from benchmark results.
3. Document mission lifecycle, projection overwrite semantics, model-op governance, and cloud/browser runbooks.
4. Add canary, rollback, and drift-reconciliation procedures.

---

## Rollout Ordering
1. Phase 1 with `monitor`-only policy, hook completion, plugin scanning, sampled audit.
2. Benchmark gate before any verbose runtime capture.
3. Phase 2 for canonical mission/handoff state + `todo` write-through.
4. Phase 3 for proposal queues and optional mirrors.
5. Phase 4 for manual model ops, exports/evals, daily briefs, analytics.
6. Phase 5 for browser/cloud UX only after auth and transport checks.
7. Phase 6 for hardening and controlled expansion.

---

## Risks and Mitigations
- Runtime-audit load overwhelms SQLite/WAL.
  - Mitigation: bounded audit, sampling/retention, benchmark gate.
- Mission state becomes a second planning stack beside `todo`.
  - Mitigation: lock `todo` write-through semantics under active mission.
- Browser/cloud packaging introduces second terminal runner or weak auth boundary.
  - Mitigation: require `web_server` auth + `tui_gateway` transport only.
- Model switches bypass approval via env/config writes.
  - Mitigation: `ModelOpsService` is sole writer; `/api/env` rejects protected-key bypass.
- At-least-once delivery causes duplicate work.
  - Mitigation: idempotency keys, deterministic overwrites, domain truth separate from audit replay.
- Skill/plugin generation self-amplifies.
  - Mitigation: proposal queue + approval + scan + quarantine.

---

## Available Agent Types Roster

| Role | Suggested reasoning | Use in this program |
|---|---|---|
| `planner` | medium | Phase planning, schema/rollout shaping, PR slicing |
| `architect` | high | Runtime contracts, schema shape, transport/auth boundaries |
| `executor` | high | Core implementation across runtime, state, UI, deploy surfaces |
| `debugger` | high | Replay, WAL contention, gateway/session bugs, drift issues |
| `verifier` | high | Final proof gathering, acceptance validation |
| `security-reviewer` | medium | Camel policy, browser/cloud auth, plugin guard, protected model keys |
| `test-engineer` | medium | Test-spec implementation and gate coverage |
| `code-reviewer` | high | Cross-cutting review before landing risky phases |
| `performance-reviewer` | medium | SQLite/WAL contention, audit sampling, UI latency |
| `qa-tester` | low | Browser/TUI/dashboard manual verification flows |
| `writer` | high | Operator docs, runbooks, migration notes |
| `explore` | low | Quick repo/file/symbol mapping when scope expands |

---

## Follow-up Staffing Guidance

### Ralph path
Use a single-owner sequential execution lane for the early core phases.

Recommended sequence
1. `architect` high — finalize Phase 1 contracts if implementation uncovers edge semantics.
2. `executor` high — implement Phase 1 and Phase 2 core changes.
3. `security-reviewer` medium — verify trust boundary, plugin guard, auth boundaries.
4. `test-engineer` medium — add/expand verification suite.
5. `verifier` high — prove rollout gates before moving to next phase.

Why Ralph first
- Phases 1 and 2 define contracts others depend on.
- Sequential ownership reduces schema and runtime drift.
- Easier to manage migrations and rollback.

### Team path
Use coordinated parallel execution after the substrate is locked.

Suggested lanes
- Lane A: Core runtime/policy/services — `executor` high
- Lane B: SQLite schema/migrations/analytics — `executor` high + `performance-reviewer` medium
- Lane C: Web/TUI/browser terminal UX — `executor` high + `qa-tester` low
- Lane D: Security/auth/plugin guard/model-op controls — `security-reviewer` medium + `executor` high
- Lane E: Test harness and rollout gates — `test-engineer` medium + `verifier` high
- Lane F: Docs/runbooks/migration guides — `writer` high

Why each lane exists
- Runtime and schema work are separable once contracts are fixed.
- UX work can proceed in parallel after APIs are stable.
- Security and verification need independent ownership to avoid self-approval.

---

## Launch Hints

### Ralph launch hint
Preferred when starting implementation from this plan:

```bash
$ralph ".omx/plans/prd-hermes-all-features-integration.md"
```

Suggested execution order under Ralph
- Phase 1 → verify gates
- Phase 2 → verify gates
- Phase 3 → verify gates
- Phase 4 → verify gates
- Phase 5 → verify gates
- Phase 6 → finalize rollout defaults/docs

### Team launch hint
Preferred after Phase 1 contracts are stable or when Phase 3+ is split into independent lanes:

```bash
$team ".omx/plans/prd-hermes-all-features-integration.md"
```

Optional explicit team prompt sketch

```bash
omx team --plan .omx/plans/prd-hermes-all-features-integration.md
```

Use the lane split listed in the staffing guidance section.

---

## Team Verification Path

What the team must prove before shutdown
- Runtime signal contract is implemented with documented publishers and hook derivation.
- Mission schema and `todo` write-through semantics are functioning.
- Model-op cutover blocks protected-key bypass.
- Browser terminal uses `web_server` → `tui_gateway` only.
- Projection replay and rebuild are idempotent.
- Benchmark gate results are recorded for verbose audit enablement.

What Ralph or final verifier must prove after handoff
- All phase gates in the test spec pass.
- No remaining parallel write paths exist for mission/model/projection state.
- Public/cloud deployment remains blocked until auth hardening checks are green.
- Docs match shipped behavior and default settings.

---

## ADR-001 — Service-first Hermes cutover for all requested feature families

Decision
- Integrate all five feature families through a small Hermes-core runtime-signal contract, explicit mission/proposal/model/projection services, typed mission schema in `state.db`, bounded audit tables, one-way projections, and a browser terminal that reuses `tui_gateway`.

Drivers
- Single runtime ownership.
- Single authoritative write path per concept.
- Approval/audit requirements for high-risk autonomy.
- Existing Hermes seams already cover plugins, memory providers, context engines, sessions, cron, gateway transport, and model switching.

Alternatives considered
- Plugin-first adapter layer.
- External companion control plane.
- Generic append-everything internal event bus.

Why chosen
- Preserves every requested feature family without retaining forked runtimes, writable mirrors, or untracked model/env mutation paths.
- Narrows the integration around explicit contracts the current Hermes seams can actually support.

Consequences
- More up-front service and migration work.
- Projections are not collaborative inputs in the initial release.
- Consumers must tolerate at-least-once delivery and implement idempotency.
- Generic env/config endpoints lose the ability to change model identity directly.

Follow-ups
- Build and run the benchmark harness before enabling verbose runtime capture.
- Document protected model-key list and startup drift reconciliation.
- Treat editable mirror import paths as a separate future ADR only if needed.

---

## Applied Improvement Changelog
- Replaced vague event-bus wording with explicit runtime-signal contract, publisher map, hook derivation direction, and honest at-least-once semantics.
- Locked mission schema and `todo` write-through semantics.
- Added explicit model-ops cutover and `/api/env` protected-key restriction rule.
- Split authoritative domain state from bounded audit/analytics tables and added a concrete benchmark gate.
- Chose `web_server` → `tui_gateway` as the only browser-terminal transport.
- Fixed projection replay contract to use global audit cursor, not per-session sequence.
- Added required agent roster, staffing guidance, launch hints, and team verification path.

---

## Success Criteria
- [ ] Every requested repo feature family has a named Hermes landing zone.
- [ ] Hermes remains the only runtime entrypoint.
- [ ] Runtime-signal envelope, publishers, hook derivation, and at-least-once semantics are implemented as specified.
- [ ] Mission schema is implemented as `missions` + `mission_nodes` + `mission_links` with separate lifecycle tables.
- [ ] `todo` semantics are explicit and enforced.
- [ ] `state.db` remains canonical for domain state; audit/analytics remain bounded and benchmark-gated.
- [ ] All model mutations flow through `ModelOpsService`; protected model keys cannot bypass it.
- [ ] Browser terminal transport is `web_server` auth + `tui_gateway` session engine only.
- [ ] FABRIC/Obsidian/bundle outputs are one-way projections with explicit idempotency and rebuild rules.
- [ ] Dashboard and TUI expose mission control, approvals, telemetry, and model history from canonical APIs.
- [ ] Public/cloud deployment remains blocked until auth hardening, gateway isolation, model-op cutover, and browser-terminal transport tests pass.
