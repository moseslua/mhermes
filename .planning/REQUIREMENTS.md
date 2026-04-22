# Requirements: Hermes all-features integration

**Defined:** 2026-04-20
**Core Value:** Hermes absorbs the requested feature families without creating a second runtime, a second canonical store, or unsafe autonomous write paths.

## v1 Requirements

Requirements for the approved integration program. Each maps to exactly one roadmap phase.

### Runtime Integrity

- [ ] **RUNTIME-01**: Hermes emits typed runtime signals from canonical publishers and derives declared plugin hooks from those signals.
- [ ] **RUNTIME-02**: Hermes enforces a Camel-style trust boundary that classifies provenance and blocks unauthorized sensitive side effects in enforce mode.
- [ ] **RUNTIME-03**: Hermes persists bounded audit data with explicit retention, sampling, and benchmark gates for verbose capture.

### Mission Control

- [ ] **MISSION-01**: Hermes persists missions, mission nodes, and mission links in canonical state with service APIs.
- [ ] **MISSION-02**: When a mission is active, `todo` operations write through to mission task rows instead of a second durable todo store.
- [ ] **MISSION-03**: Hermes persists handoff packets and checkpoints linked to missions and exposes read APIs usable by CLI, TUI, and web surfaces.

### Memory, Proposals, and Projections

- [ ] **MEMORY-01**: Hermes builds shared memory from canonical session/history data while preserving the one-external-provider invariant.
- [ ] **PROPOSAL-01**: Proposal generation for skills/plugins is approval-gated and generated artifacts are scanned or quarantined before activation.
- [ ] **PROJECTION-01**: Projections are one-way, idempotent, and rebuildable from canonical state.

### Model Operations and Analytics

- [ ] **MODELOPS-01**: `ModelOpsService` is the sole path for protected model mutations, approvals, rollback, and audit.
- [ ] **ANALYTICS-01**: Daily briefs, learning exports/evals, and analytics surfaces consume canonical state rather than ad hoc files or direct env mutation.

### Browser and Cloud Surfaces

- [ ] **SURFACE-01**: Mission Control and browser terminal surfaces wrap Hermes through existing web and TUI transports rather than a second runtime.
- [ ] **DEPLOY-01**: Cloud packaging boots official Hermes entrypoints with volume bootstrap and optional sidecar startup under hardened auth boundaries.

### Rollout Safety

- [ ] **ROLLOUT-01**: Rollout defaults, runbooks, canary checks, and rollback procedures make the integration safe to ship incrementally.

## v2 Requirements

Deferred to future release. Tracked but not in the current roadmap.

### Expansion Ideas

- **EXPAND-01**: Auto-apply approved proposals without a human checkpoint.
- **EXPAND-02**: Public/cloud deployment defaults enabled out of the box.
- **EXPAND-03**: Writable external mirrors or projections that feed back into canonical state.

## Out of Scope

| Feature | Reason |
|---------|--------|
| External companion control plane | Would violate Hermes-primary runtime ownership |
| Second canonical state store (`.maestro/`, `FABRIC_DIR`, similar) | Creates split-brain durable state |
| Silent model/config mutation | Violates approval and audit boundary |
| Auto-activating generated skills/plugins | Unsafe without review, scanning, and quarantine |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| RUNTIME-01 | Phase 1 | Pending |
| RUNTIME-02 | Phase 1 | Pending |
| RUNTIME-03 | Phase 1 | Pending |
| MISSION-01 | Phase 2 | Pending |
| MISSION-02 | Phase 2 | Pending |
| MISSION-03 | Phase 2 | Pending |
| MEMORY-01 | Phase 3 | Pending |
| PROPOSAL-01 | Phase 3 | Pending |
| PROJECTION-01 | Phase 3 | Pending |
| MODELOPS-01 | Phase 4 | Pending |
| ANALYTICS-01 | Phase 4 | Pending |
| SURFACE-01 | Phase 5 | Pending |
| DEPLOY-01 | Phase 5 | Pending |
| ROLLOUT-01 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 14 total
- Mapped to phases: 14
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-20*
*Last updated: 2026-04-20 after bootstrapping from the approved integration PRD and test spec*