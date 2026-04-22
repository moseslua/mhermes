# Revised RALPLAN Draft — Hermes integration of camel, alpha, skill-factory, maestro, and icarus

## RALPLAN-DR Summary

### Principles
1. Hermes stays primary. `run_agent.py`, CLI, gateway, TUI, and dashboard remain the only live execution/runtime surfaces.
2. One durable authority per concept. `state.db` remains canonical for domain state; audit and analytics tables are bounded operational records, not alternate truth.
3. One plugin contract. General plugins keep `plugin.yaml` + `register(ctx)`; provider plugins stay single-select through existing `MemoryProvider` / `ContextEngine` seams.
4. Risky autonomy is gated. Security envelope, model ops, skill/plugin generation, and review/fix loops start in observe/propose/manual-approval mode.
5. Profile-safe paths only. All new persistence resolves through Hermes-managed paths and workspace `.hermes/` outputs; no hardcoded `~/.hermes` paths ship.

### Decision Drivers
- Preserve every requested feature family without creating a second runtime or second canonical state store.
- Replace vague platform language with explicit write paths, event semantics, and cutover rules.
- Keep security, orchestration, memory, deployment, and model-management behavior auditable before enabling stronger autonomy.

### Viable Options
1. Service-first runtime signals + typed control-plane state + opt-in projections
   - Pros: keeps Hermes primary, makes write ownership explicit, preserves all feature families without a peer runtime, and limits SQLite growth to bounded audit records.
   - Cons: requires early service/schema work and benchmark discipline before verbose audit capture.
2. Plugin-first adapter layer
   - Pros: narrower initial diffs, some fast wins.
   - Cons: weak fit for runtime/state features, high split-brain risk, and no clean answer for Camel or Maestro concepts.
3. External companion control plane
   - Pros: fastest way to demo missions/cloud UX.
   - Cons: violates Hermes-primary requirement and recreates fork debt around runtime, auth, and state.

### Recommendation
Choose Option 1. The cutover stays Hermes-core, but it is narrowed to explicit runtime signals, typed mission/model/projection services, and bounded audit persistence instead of a generic “event bus + append-everything control plane”.

### Pre-mortem
1. Split-brain state — mirrors or browser/cloud surfaces become writable and drift from canonical mission/model state.
2. Runtime contention — verbose tool/LLM event persistence regresses WAL behavior and freezes TUI/browser sessions.
3. Mutation bypass — browser provider switcher or `/api/env` changes model identity without approval, rollback, or audit.

### Expanded Test Plan
- Unit: runtime signal envelope validation, per-session sequencing, Camel policy evaluation, mission schema migration, `todo` write-through semantics, projection cursor replay, protected model-key enforcement.
- Integration: publisher→hook→audit propagation, mission/handoff persistence, proposal generation, mirror rebuild idempotency, model-op approval and rollback, browser terminal bridge to `tui_gateway`.
- E2E: mission lifecycle across CLI/TUI/web, browser provider switch through approved model ops, cloud package startup without alternate runtime, delete-and-rebuild projection flows.
- Observability: correlation IDs, audit retention/sampling metrics, lock-contention benchmark gate, drift detection, and canary checks for public/cloud deployment.

---

## Overview
Integrate requested feature families from `hermes-agent-camel`, `hermes-alpha`, `hermes-skill-factory`, `maestro`, and `icarus-plugin` by extending Hermes seams that already exist: runtime orchestration in `run_agent.py`, tool dispatch in `model_tools.py`, canonical session history in `hermes_state.py`, plugin/provider contracts in `hermes_cli/plugins.py`, `agent/memory_manager.py`, and `agent/context_engine.py`, plus current dashboard/TUI surfaces in `hermes_cli/web_server.py`, `web/`, `ui-tui/`, and `tui_gateway/`.

The target architecture is not a federation of imported repos. It is a Hermes-native service cutover with: a small typed runtime-signal contract, authoritative mission/model/proposal state in `state.db`, bounded audit and analytics tables, approval-gated model/learning services, one-way projections for FABRIC/Obsidian/bundles, and browser/cloud surfaces that wrap the official Hermes runtime instead of vendoring it.

## Non-goals
- Do not import or preserve any external repo as a peer runtime.
- Do not introduce `.maestro/`, `FABRIC_DIR`, or any other second canonical store.
- Do not support old single-file plugin drop formats long-term.
- Do not promise exactly-once delivery semantics the runtime cannot honestly provide.
- Do not ship automatic model/env rewrites, writable mirrors, or silent plugin generation on day one.

## Capability Mapping by Source Repo

| Source | Feature family | Hermes-native landing zone | Concrete touchpoints |
|---|---|---|---|
| `hermes-agent-camel` | Trusted/untrusted separation, per-turn security envelope, capability gating, `off/monitor/enforce` modes | Core runtime signal + policy layer | `run_agent.py`, `model_tools.py`, `tools/approval.py`, `hermes_cli/plugins.py`, `hermes_cli/config.py`, new `agent/runtime_signals.py`, new `agent/runtime_policy.py` |
| `hermes-alpha` | Cloud packaging, volume bootstrap, optional sidecar startup | Canonical packaging around Hermes entrypoints | `Dockerfile`, `docker/entrypoint.sh`, `packaging/`, new `packaging/fly/` |
| `hermes-alpha` | Browser terminal, provider switcher, cloud operator entrypoint | First-party web surface that authenticates in `hermes_cli/web_server.py` and attaches to the existing `tui_gateway/server.py` session engine | `hermes_cli/web_server.py`, `web/src/App.tsx`, new terminal page/components, `tui_gateway/server.py`, new `agent/model_ops.py` |
| `hermes-skill-factory` | Passive observation, pattern detection, proposal/review workflow | Proposal engine over canonical runtime/domain state | `run_agent.py`, new `agent/proposal_engine.py`, `hermes_state.py`, dashboard/TUI proposal UIs |
| `hermes-skill-factory` | Skill generation | Existing skill path with guardrails | `tools/skill_manager_tool.py`, `tools/skills_guard.py`, `skills/`, approval flow |
| `hermes-skill-factory` | Plugin generation from learned patterns | Hermes-packaged plugin scaffolds only | `hermes_cli/plugins.py`, `hermes_cli/plugins_cmd.py`, new `tools/plugin_guard.py`, generated `plugin.yaml` packages |
| `maestro` | Mission / milestone / feature / assertion model, task queue, principles/outcomes | Persistent mission graph in canonical state | `hermes_state.py`, new `agent/mission_state.py`, new `tools/mission_tool.py`, `tools/todo_tool.py` bridge |
| `maestro` | Handoff packets, checkpoints, portable bundles | Delegate-task and checkpoint integration; bundles remain exports | `tools/delegate_tool.py`, `tools/checkpoint_manager.py`, new `agent/handoff_packets.py`, new `agent/state_projections.py` |
| `maestro` | Mission-control dashboard | First-party web/TUI surfaces backed by canonical mission APIs | `hermes_cli/web_server.py`, `web/src/`, `ui-tui/src/`, `tui_gateway/server.py` |
| `icarus-plugin` | Shared memory, pending work, daily brief, telemetry, corpus report | Canonical memory/analytics service over existing memory callbacks and state | `agent/memory_manager.py`, `tools/memory_tool.py`, `tools/session_search_tool.py`, `cron/jobs.py`, `cron/scheduler.py`, `hermes_state.py`, analytics endpoints |
| `icarus-plugin` | Training export, fine-tune/eval linkage, model registry, switch/rollback | Approval-gated model-ops and learning services over existing provider/model stack | `hermes_cli/providers.py`, `hermes_cli/model_switch.py`, new `agent/model_ops.py`, `agent/trajectory.py`, `tools/rl_training_tool.py`, `hermes_cli/web_server.py` |
| `icarus-plugin` | Review/fix linkage and work-quality metadata | Mission relations plus artifact metadata on proposals, reviews, and exports | `tools/delegate_tool.py`, mission store, proposal engine, export/eval artifacts |
| `icarus-plugin` | Obsidian/FABRIC mirroring | Opt-in one-way projections only | new `agent/state_projections.py`, `hermes_constants.py`, workspace `.hermes/` outputs |

## Canonical Contracts

### 1. Runtime signal contract
The internal coordination primitive is a typed runtime signal, not a generic free-form bus.

**Canonical envelope**

| Field | Meaning |
|---|---|
| `event_id` | Unique emission identifier for this signal instance |
| `idempotency_key` | Stable dedupe key when retries can replay the same logical event |
| `event_type` | Stable family, e.g. `tool.call`, `llm.call`, `api.request`, `mission.node`, `approval`, `handoff`, `model.mutation`, `projection.run` |
| `phase` | `requested`, `started`, `completed`, `failed`, `blocked`, `approved`, `rejected`, `rolled_back`, or `ended` |
| `occurred_at` | UTC timestamp |
| `publisher` | Module/function that emitted the signal |
| `session_id` / `mission_id` | Correlation scopes; `mission_id` is nullable |
| `correlation_id` | Ties multi-step flows such as delegation, approvals, or model changes |
| `sequence_no` | Monotonic per `session_id`; used for session-scoped ordering and replay within one session |
| `actor` | `{ kind, id }` for user/assistant/plugin/system/scheduler |
| `subject` | `{ kind, id }` for tool/model/node/projection/etc. |
| `provenance` | `trusted`, `untrusted`, `derived`, or `system`; feeds Camel policy decisions |
| `payload` | Bounded, redacted JSON payload; never the full durable truth for domain objects |

**Initial publishers and call sites**

| Call site | Published signal families |
|---|---|
| `run_agent.py` | `session.*`, `slash_command.*`, `llm.call.*`, session lifecycle and delegated-run context changes |
| `model_tools.py` | `tool.call.*` including requested/completed/failed/blocked |
| `tools/approval.py` | `approval.*` |
| `agent/mission_state.py` / `tools/mission_tool.py` | `mission.*`, `mission.node.*`, `mission.link.*` |
| `tools/delegate_tool.py` / `agent/handoff_packets.py` / `tools/checkpoint_manager.py` | `handoff.*`, `checkpoint.*` |
| `agent/model_ops.py` wrapping `hermes_cli/model_switch.py` | `model.mutation.*`, `learning_export.*`, `eval_run.*` |
| `agent/state_projections.py` | `projection.run.*` |
| `cron/jobs.py` | `daily_brief.*` and scheduled summary/export completion signals |

**Derivation direction**
- Runtime signals are canonical internally.
- Existing plugin hooks are derived from those signals inline through a `PluginHookAdapter`; hooks remain the public extension API.
- `pre_tool_call`, `post_tool_call`, `pre_llm_call`, `post_llm_call`, `pre_api_request`, `post_api_request`, and session hooks are all emitted from the same publisher helper instead of scattered direct calls.
- Add one new public hook, `on_slash_command`, because slash-command observation is required by Skill Factory and is not represented by the current hook set.
- Mission, handoff, projection, and model-op signals remain internal unless a concrete plugin use case proves a public hook is needed.

**Ordering and delivery semantics**
- Synchronous consumers inside one process observe publish order exactly as emitted by the calling path.
- `sequence_no` gives a per-session ordering guarantee; there is no cross-session or cross-process total order.
- Durable audit persistence and projection workers are **at-least-once** consumers. Retries or crash recovery may replay a signal with the same `idempotency_key`.
- Exactly-once is not part of the contract. All downstream consumers, especially projections and analytics, must be idempotent.
- Domain truth never depends on replaying audit rows alone; authoritative services write domain tables directly and emit signals around those transitions.

### 2. Authoritative domain state vs bounded audit
`state.db` is split by purpose, not by file.

**Authoritative domain tables in the initial cutover**
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

**Bounded operational tables**
- `runtime_signal_audit`
- `projection_runs`
- `analytics_rollups`

**Write ownership**

| Concept | Authoritative writer | Rebuildable or bounded outputs |
|---|---|---|
| Mission and handoff state | `agent/mission_state.py` + `tools/mission_tool.py` | mission-control views, portable bundles |
| Proposal and generation workflow | `agent/proposal_engine.py` | draft skills/plugins, proposal dashboards |
| Model ops and learning jobs | `agent/model_ops.py` | provider switcher UI, training/eval artifacts |
| Projections | `agent/state_projections.py` | `FABRIC_DIR`, Obsidian notes, mission bundles |
| Runtime audit and analytics | `agent/runtime_signals.py` recorder | analytics pages and learning heuristics |

**Retention and benchmark gate**
- `approval.*`, `mission.*`, `handoff.*`, `proposal.*`, `model.mutation.*`, and `projection.run.*` persist by default because they describe business-significant state transitions.
- `tool.call.*`, `llm.call.*`, and `api.request.*` are sampled, redacted, and off-by-default for verbose payload capture until the benchmark gate passes.
- Add explicit knobs in config for `audit_retention_days`, per-family sampling rates, and `max_audit_payload_bytes`.
- Do not enable verbose runtime-audit persistence by default until a benchmark harness proves all three under a representative 4-session mixed CLI/TUI/web load: p95 SQLite writer wait under 25ms, no visible `tui_gateway` or TUI stall above 250ms, and projected sampled-audit growth within the configured retention budget.

### 3. Mission schema and `todo` semantics
Lock the mission model now.

**Schema**
- `missions`
  - `mission_id`, `title`, `status` (`draft|approved|active|paused|completed|canceled`), `created_by_session_id`, `owner_session_id`, `principles_json`, `outcomes_json`, `created_at`, `approved_at`, `closed_at`
- `mission_nodes`
  - `node_id`, `mission_id`, `parent_node_id`, `node_type` (`milestone|feature|assertion|task`), `title`, `body`, `status` (`pending|ready|in_progress|blocked|done|dropped`), `acceptance_json`, `assignee_session_id`, `sort_key`, `created_at`, `updated_at`
- `mission_links`
  - `link_id`, `mission_id`, `from_node_id`, `relation_type` (`depends_on|blocks|verifies|review_of|revises|assigned_to`), `to_kind`, `to_id`, `created_at`
- Separate lifecycle tables stay separate instead of being overloaded into generic node JSON: `handoff_packets`, `mission_checkpoints`, `approvals`, `proposals`, `model_mutations`, `learning_exports`, and `eval_runs`.

**`todo` rule under an active mission**
- No active mission: `todo` keeps its existing session-local behavior.
- Active mission attached to the session: `todo` becomes a write-through facade over `mission_nodes` rows where `node_type = 'task'` for that mission.
- `todo add/edit/done/delete` mutate mission task rows through `agent/mission_state.py`; they do not write to a second todo store.
- While a mission is active, session-local `todo` items are suspended from the default view rather than merged. Detaching the mission restores the session-local view.
- Mission Control, delegation, and daily briefs read the mission task rows directly; no reverse sync path exists.

### 4. Model-ops cutover rule
Model identity gets one write path.

- Add `agent/model_ops.py` as the sole mutation service for provider/model/base-URL/API-key settings used by `hermes_cli/providers.py` and `hermes_cli/model_switch.py`.
- `hermes_cli/model_switch.py` becomes the execution backend for `ModelOpsService`, not an alternate control path.
- CLI, TUI, browser provider switcher, scheduled jobs, and web APIs all call `ModelOpsService` and receive a `model_mutation_id` tied to approval and rollback state.
- Generic `/api/env` or config-update endpoints must reject writes to protected model-related keys unless the request is carrying an approved `model_mutation_id` issued by `ModelOpsService`.
- Any direct `.env` drift discovered at startup is surfaced as configuration drift to reconcile; it is not silently backfilled into mutation history and does not bypass approval.

### 5. Projection contract
Mirrors are outputs, not collaboration surfaces.

- `agent/state_projections.py` is the only writer for `FABRIC_DIR`, Obsidian notes, mission bundles, and any other file-based mirror.
- `projection_cursors` are keyed by `(projection_name, target_root)` and store `last_applied_audit_id`, `last_snapshot_hash`, `last_projection_version`, and `updated_at`.
- Projections consume authoritative domain tables plus approved audit families; they never read another projection as input.
- Incremental replay is driven only by the globally ordered `runtime_signal_audit.audit_id` for projection-relevant signal families, never by per-session `sequence_no`.
- Replaying the same audit window into the same target root must be idempotent: identical object IDs map to identical paths, and writes happen via atomic overwrite/rename.
- If a cursor is missing, stale, or hash validation fails, the projection does a full delete-and-rebuild from canonical state.
- Direct edits to projection outputs are out of scope for the initial integration and may be overwritten on the next run.

### 6. Canonical browser-terminal transport
Pick one transport now: browser terminal traffic goes through the existing gateway session engine.

- `hermes_cli/web_server.py` owns browser auth, token checks, and the public HTTP/WebSocket boundary.
- After auth, the browser terminal attaches to the session engine in `tui_gateway/server.py`; spawn, attach, resize, input, and output all flow through that gateway.
- The deploy package may start the gateway and web server together, but it does not introduce a second PTY supervisor or alternate agent runner.
- Browser provider switching is just a UI over `ModelOpsService`; it does not mutate environment or runtime state directly.

## Target Architecture

### 1. Runtime signal and policy core
`run_agent.py`, `model_tools.py`, approval flows, mission services, projections, and model ops all publish the same runtime-signal envelope through `agent/runtime_signals.py`. `agent/runtime_policy.py` consumes that envelope to apply Camel trust-boundary rules, capability gating, and provider-metadata stripping before outbound calls. Plugin hooks are derived from the same signals inline, so the runtime no longer has parallel ad hoc hook and event abstractions.

### 2. Canonical domain state and bounded audit
`state.db` expands from session/message history into a broader but explicit control-plane store. Domain tables hold missions, mission nodes/links, handoff packets, checkpoints, approvals, proposals, model mutations, exports/evals, and projection cursors. Audit and analytics tables stay retention-bound and rebuildable.

### 3. Mission and handoff layer
Maestro concepts land as first-party Hermes mission state. `missions` hold approve/activate/close lifecycle, `mission_nodes` hold milestone/feature/assertion/task structure, `mission_links` encode dependency and review relations, and `handoff_packets` persist delegate-ready context. Portable bundles remain exports generated from canonical mission state.

### 4. Knowledge, proposal, and projection layer
Shared memory is implemented as a Hermes service over canonical state plus existing memory callbacks, not as a second external provider. Skill-factory ideas land as proposal queues and approved scaffold generation. Icarus-style work-quality metadata (`training_value`, `verified`, `evidence`, `review_of`, `revises`, `assigned_to`, `artifact_paths`) become structured metadata on proposals, mission relations, and export artifacts. FABRIC/Obsidian outputs are one-way projections.

### 5. Model ops and learning layer
Icarus model switching, export, fine-tune/eval linkage, daily briefs, and registry ideas land behind `ModelOpsService` and the existing provider/model stack. All model mutations are approval-gated, rollback-capable, and recorded in `model_mutations`; exports and evals are linked artifacts, not hidden file rewrites.

### 6. Experience and deployment surfaces
Dashboard, TUI, and browser/cloud packaging remain wrappers over official Hermes runtime/state APIs. The Alpha browser terminal becomes a first-party web feature using `web_server` auth plus `tui_gateway` transport. Fly packaging and sidecar startup remain deployment targets around Hermes packaging, never a vendored runtime snapshot.

## Cutover Rules
1. **Runtime rule**
   - Canonical runtime: `run_agent.py` plus existing CLI/gateway/TUI/web orchestration.
   - Disallowed: a second long-lived runner copied from Alpha or Maestro.

2. **Write-path rule**
   - Every concept has one authoritative writer: mission service, proposal engine, model-ops service, or projection service.
   - Audit rows observe those transitions; they do not become an alternate write path.

3. **Mission rule**
   - Canonical persistent work state lives in `missions` / `mission_nodes` / `mission_links`.
   - `todo` is session-local when no mission is attached and write-through mission tasks when one is attached.

4. **Model-mutation rule**
   - All provider/model/base-URL/API-key mutations flow through `ModelOpsService`.
   - Generic env/config mutation endpoints are not allowed to bypass that path.

5. **Projection rule**
   - FABRIC/Obsidian/bundle outputs are one-way projections with global-audit-cursor replay for projection-relevant signals and delete-and-rebuild fallback from canonical state.
   - Deleting a projection never loses authoritative state.

6. **Browser transport rule**
   - Browser terminal sessions attach only through `hermes_cli/web_server.py` → `tui_gateway/server.py`.
   - No dedicated browser-only PTY/runtime stack ships.

## Implementation Phases

### Phase 1 — Runtime signals, hook completion, and bounded audit foundation
Goal: replace vague event-bus language with an explicit signal contract and finish the missing observation seams.

**Touchpoints**
- Existing: `run_agent.py`, `model_tools.py`, `hermes_cli/plugins.py`, `tools/approval.py`, `tools/delegate_tool.py`, `tools/checkpoint_manager.py`, `hermes_cli/config.py`, `hermes_state.py`, `hermes_cli/plugins_cmd.py`
- New: `agent/runtime_signals.py`, `agent/runtime_policy.py`, `tools/plugin_guard.py`

**Work**
1. Add the `RuntimeSignal` envelope, publisher helper, per-session sequencing, and idempotency-key support.
2. Publish from the concrete call sites listed in the runtime-signal contract.
3. Route existing plugin hooks through the signal publisher, wire missing `post_tool_call`, `post_llm_call`, `pre_api_request`, and `post_api_request`, and add `on_slash_command`.
4. Add bounded audit tables plus retention/sampling config knobs instead of a full append-everything journal.
5. Add `plugin_guard` so plugin install/update/load has parity with skill scanning.
6. Run the contention benchmark harness and keep verbose `tool/llm/api` audit capture off until the benchmark gate passes.

**Rollout gate**
- Ship policy in `monitor` mode only.
- Persist business-significant signals by default; verbose runtime capture remains sampled/off until the benchmark gate is green.

### Phase 2 — Typed mission graph, `todo` write-through, and handoff authority
Goal: port Maestro orchestration concepts into Hermes without a `.maestro/` sidecar or dual work representations.

**Touchpoints**
- Existing: `hermes_state.py`, `tools/todo_tool.py`, `tools/delegate_tool.py`, `run_agent.py`, `agent/skill_commands.py`, `tools/checkpoint_manager.py`
- New: `agent/mission_state.py`, `tools/mission_tool.py`, `agent/handoff_packets.py`

**Work**
1. Add the locked `missions`, `mission_nodes`, and `mission_links` schema with migrations and service APIs.
2. Implement mission lifecycle commands: draft, approve, attach, pause, resume, complete, cancel.
3. Make `todo` a write-through facade over mission task nodes when a mission is active.
4. Persist `handoff_packets` and `mission_checkpoints`; generate portable bundles as projection outputs only.
5. Expose mission-control read APIs for CLI/TUI/web without introducing a second orchestrator.

**Rollout gate**
- Internal missions enabled for CLI/TUI first.
- Mission activation requires explicit approval; browser/cloud surfaces are still out of scope.

### Phase 3 — Shared memory, proposal engine, and one-way projections
Goal: land Skill Factory and FABRIC-style knowledge features without violating provider constraints or projection rules.

**Touchpoints**
- Existing: `agent/memory_manager.py`, `agent/memory_provider.py`, `tools/memory_tool.py`, `tools/session_search_tool.py`, `run_agent.py`, `tools/skill_manager_tool.py`, `tools/skills_guard.py`, `hermes_constants.py`
- New: `agent/proposal_engine.py`, `agent/state_projections.py`, optional plugin-scaffold generator module

**Work**
1. Implement a Hermes shared-memory service over canonical session/history data plus existing memory-manager callbacks.
2. Build the proposal engine on runtime signals and domain tables, not on ad hoc in-memory observation.
3. Route skill generation through `skill_manage`; route plugin generation through packaged scaffolds and `plugin_guard` quarantine.
4. Add FABRIC/Obsidian/mission-bundle projections with cursor tracking, idempotent overwrite rules, and full rebuild fallback.
5. Attach Icarus-style metadata fields to proposals, review/fix links, and export artifacts.

**Rollout gate**
- Proposal queue visible, but auto-apply remains disabled.
- Projections are opt-in only and direct projection edits are explicitly unsupported.

### Phase 4 — Model ops, learning exports, daily briefs, and analytics
Goal: absorb Icarus operational features into existing provider/model seams with a hard mutation boundary.

**Touchpoints**
- Existing: `hermes_cli/providers.py`, `hermes_cli/model_switch.py`, `run_agent.py`, `agent/trajectory.py`, `tools/rl_training_tool.py`, `cron/jobs.py`, `cron/scheduler.py`, `hermes_cli/web_server.py`, analytics pages
- New: `agent/model_ops.py`, export/eval linkage helpers

**Work**
1. Add `ModelOpsService` and make it the only mutation path for provider/model/base-URL/API-key settings.
2. Persist `model_mutations`, `learning_exports`, and `eval_runs` as first-class artifacts with approval and rollback state.
3. Update `/api/env` and any generic config mutation endpoints to reject protected model-key writes unless they carry an approved `model_mutation_id`.
4. Generate daily briefs and review/fix linkages from canonical mission/proposal/export state.
5. Extend analytics surfaces from bounded audit rows and authoritative domain tables instead of a full raw event journal.

**Rollout gate**
- Manual approval only for model changes.
- `/api/env` protected-key rejection, rollback, and audit visibility must be verified before browser provider switching is enabled.

### Phase 5 — Mission Control, browser terminal, and cloud packaging
Goal: expose the new control plane in dashboard/TUI/browser surfaces without creating a second runtime or auth stack.

**Touchpoints**
- Existing: `hermes_cli/web_server.py`, `web/src/App.tsx`, `web/src/pages/*`, `ui-tui/src/app/*`, `tui_gateway/server.py`, `Dockerfile`, `docker/entrypoint.sh`
- New: mission/control pages, browser terminal routes/components, `packaging/fly/`

**Work**
1. Add dashboard Mission Control pages for missions, approvals, proposals, telemetry, and model history.
2. Add TUI mission/status integration over the same mission and approval APIs.
3. Implement browser terminal attach/input/resize/stream flows as a `web_server` bridge to `tui_gateway`.
4. Package Fly deployment, volume bootstrap, and optional sidecar startup around Hermes packaging.
5. Reuse existing token-protected web APIs and approval queue patterns rather than inventing a second cloud auth model.

**Rollout gate**
- No public/cloud deployment until auth hardening, gateway isolation, and browser-terminal transport tests pass.
- Browser provider switcher remains disabled until Phase 4 model-op cutover is complete.

### Phase 6 — Rollout hardening, migration, and documentation
Goal: turn the architecture into a safe staged release with explicit defaults and rollback.

**Touchpoints**
- Existing: `hermes_cli/config.py`, `README.md`, `website/docs/*`, `tests/*`, canary/deploy docs`

**Work**
1. Set conservative defaults for policy mode, projection opt-in, generation quarantine, and model-op approvals.
2. Tune retention, sampling, and contention settings from real benchmark results.
3. Document mission lifecycle, projection overwrite semantics, model-op governance, and cloud/browser operational runbooks.
4. Add canary, rollback, and drift-reconciliation procedures.

## Rollout Ordering
1. Phase 1 lands first with `monitor`-only policy, hook completion, plugin scanning, and sampled bounded audit.
2. Run the benchmark gate; keep verbose `tool/llm/api` audit persistence off until it passes.
3. Phase 2 enables canonical mission/handoff state and `todo` write-through for internal flows.
4. Phase 3 enables proposal queues and optional mirrors, but not auto-apply or writable projections.
5. Phase 4 enables manual model ops, exports/evals, daily briefs, and analytics on top of the protected mutation path.
6. Phase 5 adds browser/cloud UX only after auth and gateway transport checks are green.
7. Phase 6 decides where `enforce` mode, broader audit sampling, and public deployment can safely be enabled.

## Verification Strategy

### Unit
- Runtime-signal envelope validation, per-session `sequence_no`, hook derivation, and idempotency-key handling.
- Camel policy behavior for `off|monitor|enforce` across normal tools, dangerous commands, model ops, and generated artifacts.
- Schema migration coverage for `missions`, `mission_nodes`, `mission_links`, lifecycle artifact tables, and projection cursors.
- `todo` write-through behavior under active mission versus session-local mode when detached.
- Projection cursor replay, full rebuild fallback, and path determinism.
- Protected model-key rejection in `/api/env` and rollback behavior in `ModelOpsService`.

### Integration
- Publisher→hook→audit propagation from `run_agent.py`, `model_tools.py`, approval flows, mission services, and model ops.
- Delegation persists `handoff_packets`, checkpoints, and review→fix links with the correct `child_session_id` / artifact linkage.
- Plugin install/update/load is blocked or quarantined by `plugin_guard` for unsafe packages.
- Shared-memory service respects the one-external-provider invariant while exposing FABRIC-style recall/search/brief flows.
- Projection runs are idempotent across duplicate signal delivery and cursor replay.
- Browser provider switching reaches `ModelOpsService` rather than mutating env/config directly.

### E2E
- CLI mission lifecycle across create/approve/attach/todo/delegate/checkpoint/export.
- TUI mission resume plus mission/approval/proposal visibility over canonical APIs.
- Dashboard Mission Control and analytics with token-protected APIs.
- Browser terminal startup and interaction through `web_server` → `tui_gateway` with no alternate runtime snapshot.
- Delete-and-rebuild of FABRIC/Obsidian/mission-bundle projections proving mirrors are not canonical.

### Observability
- Correlation IDs across runtime signals, approvals, missions, handoffs, child sessions, exports/evals, and model mutations.
- Metrics for approval latency, policy blocks, mission state transitions, proposal backlog, projection lag, audit retention, and export/eval outcomes.
- Lock-contention benchmark output for the verbose-audit gate.
- Drift detection between canonical state and generated projections, plus startup detection of protected model-key drift.
- Canary checks for public/cloud deployment security and runtime health.

## Risks & Mitigations
- **Risk:** sampled runtime audit still overwhelms SQLite under multi-surface load.
  - **Mitigation:** persist domain state separately from audit, keep verbose capture off until the benchmark gate passes, and retain explicit sampling/retention knobs.
- **Risk:** mission state becomes a second planning stack beside `todo`.
  - **Mitigation:** lock `todo` to write-through mission tasks when a mission is active and suspend session-local todo from the default view during that attachment.
- **Risk:** browser/cloud packaging introduces a second terminal runner or weak auth boundary.
  - **Mitigation:** require `web_server` auth + `tui_gateway` transport only, and block public bind until transport and auth tests pass.
- **Risk:** model switches silently alter runtime identity or bypass approval through generic env/config mutation paths.
  - **Mitigation:** `ModelOpsService` is the only writer for protected model keys; `/api/env` rejects bypass writes and runtime drift is surfaced for reconciliation.
- **Risk:** at-least-once delivery causes duplicate downstream work.
  - **Mitigation:** require idempotency keys for replayable signals, make projections overwrite deterministically, and keep domain truth out of audit replay.
- **Risk:** skill/plugin generation becomes self-amplifying.
  - **Mitigation:** proposal queue + approval + guard scan + quarantine before activation.

## ADR-001 — Service-first Hermes cutover for all requested feature families
- **Decision**
  - Integrate all five feature families by adding a small Hermes-core runtime-signal contract, explicit mission/proposal/model/projection services, typed mission schema in `state.db`, bounded audit tables, one-way projections, and a browser terminal that reuses `tui_gateway`.
- **Drivers**
  - Single runtime ownership.
  - Single authoritative write path per concept.
  - Approval/audit requirements for high-risk autonomy.
  - Existing Hermes seams already cover plugins, memory providers, context engines, sessions, cron, gateway transport, and model switching.
- **Alternatives considered**
  - Plugin-first adapter layer.
  - External companion control plane.
  - Generic append-everything internal event bus.
- **Why chosen**
  - It preserves every requested feature family without retaining forked runtimes, writable mirror stores, or untracked model/env mutation paths.
  - It narrows the integration around explicit contracts the current Hermes seams can actually support: typed signals, typed mission rows, bounded audit, a single gateway transport, and one mutation service for models.
- **Consequences**
  - More up-front service and migration work.
  - Projections are explicitly not collaborative inputs in the initial release.
  - Consumers must tolerate at-least-once delivery and implement idempotency.
  - Generic env/config mutation endpoints lose the ability to change model identity directly.
- **Follow-ups**
  - Implement the benchmark harness and lock default audit-retention/sampling values before enabling verbose runtime capture.
  - Document the protected model-key list and operator reconcile flow for startup drift.
  - Consider editable mirror import paths only as a later, separate ADR if real demand appears.

## Success Criteria
- [ ] Every requested repo feature family has a named Hermes landing zone; nothing is deferred as vague future work.
- [ ] Hermes remains the only runtime entrypoint; no peer runtime or vendored snapshot ships.
- [ ] The plan defines a canonical runtime-signal envelope, publisher call sites, hook derivation direction, and at-least-once/idempotent delivery semantics.
- [ ] The mission schema is locked to `missions` + `mission_nodes` + `mission_links`, with separate lifecycle tables for handoffs, checkpoints, approvals, proposals, and model mutations/exports/evals.
- [ ] `todo` semantics are explicit: session-local without a mission, write-through mission tasks with one active mission attached.
- [ ] `state.db` remains canonical for domain state, while audit/analytics persistence is bounded and gated by benchmark results before verbose capture becomes default.
- [ ] All model mutations flow through `ModelOpsService`, and `/api/env` or generic config updates cannot bypass that path for protected model keys.
- [ ] Browser terminal transport is explicitly `web_server` auth + `tui_gateway` session engine; no second PTY/runtime stack ships.
- [ ] FABRIC/Obsidian/bundle outputs are one-way, cursor-driven, delete-and-rebuild projections with explicit idempotency rules.
- [ ] Dashboard and TUI expose mission control, approvals, telemetry, and model history from canonical APIs.
- [ ] Public/cloud deployment is blocked until auth hardening, gateway isolation, model-op cutover, and browser-terminal transport tests are verified.
