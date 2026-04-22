# Hermes all-features integration

## What This Is

Hermes Agent is a brownfield AI-agent runtime with CLI, TUI, gateway, tool, memory, and plugin surfaces already in production use. This planning track captures the approved integration program for absorbing the feature families researched from `hermes-agent-camel`, `hermes-alpha`, `hermes-skill-factory`, `maestro`, and `icarus-plugin` into Hermes as one coherent product.

## Core Value

Hermes absorbs the requested feature families without creating a second runtime, a second canonical store, or unsafe autonomous write paths.

## Requirements

### Validated

- ✓ Hermes runs as a single runtime across CLI, TUI, web, and messaging entry points.
- ✓ Durable session history is canonical in `state.db` via `hermes_state.py`.
- ✓ Hermes already supports plugin/provider/context-engine seams that new work must extend rather than bypass.

### Active

- [ ] Typed runtime signals, explicit trust-boundary policy, and bounded audit capture land in Hermes core.
- [ ] Mission graph, `todo` write-through semantics, handoff packets, and checkpoints become canonical mission state.
- [ ] Shared memory, proposal generation, and one-way projections operate from canonical state only.
- [ ] Model operations, learning exports, daily briefs, and analytics route through a single approval-gated mutation service.
- [ ] Mission Control, browser terminal, and cloud packaging wrap the official Hermes runtime rather than introducing a parallel stack.
- [ ] Rollout defaults, migration procedures, and operator docs make the cutover safe to ship.

### Out of Scope

- A second runtime or companion control plane — violates Hermes-primary runtime ownership.
- `.maestro/`, `FABRIC_DIR`, or any other second canonical durable store — state must remain authoritative in Hermes-managed storage.
- Silent model/config mutation or auto-activating generated skills/plugins — all risky autonomy remains approval-gated and auditable.
- Public/cloud deployment before auth hardening and browser transport verification — security gate comes first.

## Context

- Hermes already has mature CLI, gateway, TUI, tool, memory, cron, and plugin systems that must stay profile-safe and remain the long-term extension seams.
- The approved source artifact for this program is `.omx/plans/prd-hermes-all-features-integration.md`, with verification guidance in `.omx/plans/test-spec-hermes-all-features-integration.md`.
- The integration must preserve every requested feature family while tightening ambiguous architecture boundaries into explicit services, write paths, and rollout gates.

## Constraints

- **Architecture**: Hermes remains the only runtime and `state.db` remains the canonical durable authority.
- **Safety**: Risky autonomy, model mutation, plugin generation, and browser/cloud mutation paths require explicit approval and auditability.
- **Profiles**: All persistence stays profile-safe; no hardcoded `~/.hermes` paths.
- **Compatibility**: Existing CLI, gateway, plugin, and provider behaviors must keep working through the migration.
- **Verification**: Each phase must prove its rollout gate before later phases depend on it.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Service-first Hermes-native cutover | Preserves all requested feature families without split-brain runtime/state | ✓ Good |
| Runtime signals are canonical internally | Makes publishers, audit, and hook derivation explicit | ✓ Good |
| Mission, proposal, model-op, and projection state use singular authoritative services | Prevents dual writable representations | ✓ Good |
| Browser terminal must reuse `web_server` -> `tui_gateway` | Avoids a second PTY/runtime stack | — Pending |

---
*Last updated: 2026-04-20 after bootstrapping GSD planning artifacts from the approved integration PRD*