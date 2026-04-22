# Roadmap: Hermes all-features integration

## Overview

This roadmap turns the approved Hermes all-features integration PRD into staged, verifiable delivery. Each phase preserves Hermes as the primary runtime while progressively adding runtime policy, mission orchestration, proposal and memory features, model operations, browser/cloud surfaces, and rollout hardening behind explicit gates.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [ ] **Phase 1: Runtime signals, hook completion, and bounded audit foundation** - Make runtime publishers, hooks, trust-boundary policy, and audit ownership explicit.
- [ ] **Phase 2: Typed mission graph, todo write-through, and handoff authority** - Port Maestro-style mission orchestration into canonical Hermes state.
- [ ] **Phase 3: Shared memory, proposal engine, and one-way projections** - Land Skill Factory and FABRIC-style knowledge features on top of canonical state only.
- [ ] **Phase 4: Model ops, learning exports, daily briefs, and analytics** - Route risky model mutation and learning workflows through a single governed service.
- [ ] **Phase 5: Mission Control, browser terminal, and cloud packaging** - Expose the control plane in product surfaces without creating a second runtime or auth stack.
- [ ] **Phase 6: Rollout hardening, migration, and documentation** - Ship the program safely with conservative defaults, migration coverage, and operator runbooks.

## Phase Details

### Phase 1: Runtime signals, hook completion, and bounded audit foundation
**Goal:** Replace vague event-bus language with explicit runtime signals, complete missing observation seams, and establish audit/policy infrastructure without breaking existing Hermes flows.
**Depends on:** Nothing (first phase)
**Requirements**: [RUNTIME-01, RUNTIME-02, RUNTIME-03]
**Success Criteria** (what must be TRUE):
  1. Canonical publishers emit typed runtime signals and every declared runtime hook is derived from those signals.
  2. Trusted vs untrusted provenance is enforced in monitor and enforce modes for sensitive side effects.
  3. Audit retention and sampling controls exist, with verbose capture still gated by benchmark results.
**Plans**: TBD

Plans:
- [ ] 01-01: TBD
- [ ] 01-02: TBD
- [ ] 01-03: TBD

### Phase 2: Typed mission graph, todo write-through, and handoff authority
**Goal:** Port Maestro orchestration concepts into Hermes without `.maestro/` sidecars or dual work representations.
**Depends on:** Phase 1
**Requirements**: [MISSION-01, MISSION-02, MISSION-03]
**Success Criteria** (what must be TRUE):
  1. Missions, mission nodes, and mission links persist in canonical state with explicit service APIs.
  2. Under an active mission, `todo` mutations write through to mission task rows, while session-local todo behavior resumes when no mission is attached.
  3. Handoff packets and checkpoints persist against missions and can be read consistently by CLI, TUI, and web surfaces.
  4. Mission activation remains approval-gated and no second writable task representation survives.
**Plans**: Canonical mission schema, lifecycle, and read APIs; mission-backed todo write-through and session fallback; mission-linked handoff packets, checkpoints, and read models

Plans:
- [ ] 02-01: Canonical mission schema, lifecycle, and read APIs
- [ ] 02-02: Mission-backed todo write-through and session fallback
- [ ] 02-03: Mission-linked handoff packets, checkpoints, and read models

### Phase 3: Shared memory, proposal engine, and one-way projections
**Goal:** Land Skill Factory and FABRIC-style knowledge features without violating provider constraints or projection rules.
**Depends on:** Phase 2
**Requirements**: [MEMORY-01, PROPOSAL-01, PROJECTION-01]
**Success Criteria** (what must be TRUE):
  1. Shared memory composes canonical session/history data with memory callbacks while preserving the one-external-provider invariant.
  2. Proposal generation is approval-gated and generated skills/plugins are scanned or quarantined before activation.
  3. Projections are one-way, idempotent, and rebuildable from canonical state.
**Plans**: Canonical shared-memory service and read APIs; proposal queue, guarded generation, and approval routing; one-way projections, cursoring, and rebuild flows

Plans:
- [ ] 03-01: Canonical shared-memory service and read APIs
- [ ] 03-02: Proposal queue, guarded generation, and approval routing
- [ ] 03-03: One-way projections, cursoring, and rebuild flows

### Phase 4: Model ops, learning exports, daily briefs, and analytics
**Goal:** Absorb Icarus operational features into existing provider/model seams with a hard mutation boundary.
**Depends on:** Phase 3
**Requirements**: [MODELOPS-01, ANALYTICS-01]
**Success Criteria** (what must be TRUE):
  1. `ModelOpsService` becomes the sole writable path for protected model mutation, approval, rollback, and audit.
  2. Learning exports, eval runs, daily briefs, and analytics surfaces consume canonical state and mutation history.
  3. Generic env/config endpoints cannot bypass protected-key governance.
**Plans**: TBD

Plans:
- [ ] 04-01: TBD
- [ ] 04-02: TBD

### Phase 5: Mission Control, browser terminal, and cloud packaging
**Goal:** Expose the control plane in dashboard, TUI, browser, and deployment surfaces without creating a second runtime or auth stack.
**Depends on:** Phase 4
**Requirements**: [SURFACE-01, DEPLOY-01]
**Success Criteria** (what must be TRUE):
  1. Mission Control surfaces and browser terminal run through `web_server` -> `tui_gateway` only.
  2. Cloud packaging launches official Hermes entrypoints with required bootstrap and optional sidecar support.
  3. Auth hardening blocks public/browser mutation paths until the security gate is green.
**Plans**: TBD

Plans:
- [ ] 05-01: TBD
- [ ] 05-02: TBD

### Phase 6: Rollout hardening, migration, and documentation
**Goal:** Turn the architecture into a safe staged release with explicit defaults, migration coverage, and operator guidance.
**Depends on:** Phase 5
**Requirements**: [ROLLOUT-01]
**Success Criteria** (what must be TRUE):
  1. Conservative defaults, retention/sampling knobs, and drift/canary procedures are documented and enforced.
  2. Migration, rollback, and recovery procedures exist for mission, projection, and model-op state.
  3. Docs and runbooks match shipped behavior and rollout policy.
**Plans**: TBD

Plans:
- [ ] 06-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Runtime signals, hook completion, and bounded audit foundation | 0/3 | Not started | - |
| 2. Typed mission graph, todo write-through, and handoff authority | 0/3 | Not started | - |
| 3. Shared memory, proposal engine, and one-way projections | 0/3 | Not started | - |
| 4. Model ops, learning exports, daily briefs, and analytics | 0/2 | Not started | - |
| 5. Mission Control, browser terminal, and cloud packaging | 0/2 | Not started | - |
| 6. Rollout hardening, migration, and documentation | 0/1 | Not started | - |