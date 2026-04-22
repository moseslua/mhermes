# Phase 2: Typed mission graph, todo write-through, and handoff authority - Context

**Gathered:** 2026-04-20
**Status:** Ready for planning
**Source:** PRD Express Path (`.omx/plans/prd-hermes-all-features-integration.md`)

<domain>
## Phase Boundary

Phase 2 delivers canonical mission orchestration inside Hermes itself: mission schema and service APIs in durable Hermes state, lifecycle commands, `todo` write-through semantics under an active mission, handoff packets and checkpoints linked to missions, and read APIs that later CLI/TUI/web surfaces can consume.

This phase does not introduce a `.maestro/` sidecar, a second writable todo representation, proposal generation, shared-memory projections, browser Mission Control surfaces, or model-ops/browser deployment work from later phases.

</domain>

<decisions>
## Implementation Decisions

### Canonical mission state
- Persist missions, mission nodes, and mission links in Hermes-managed canonical state (`state.db`) with explicit service APIs.
- Do not create a second durable planner/task store or a `.maestro/` sidecar.

### Todo integration
- Under an active mission, `todo` operations must write through to mission task rows.
- When no mission is attached, existing session-local todo behavior must remain available.
- Mission activation remains approval-gated.

### Handoff and checkpoints
- Persist handoff packets and checkpoints as mission-linked canonical records.
- Mission bundles/exports are projections only, not a writable source of truth.

### Surface contract
- Expose mission-control read APIs that CLI, TUI, and web surfaces can consume later.
- Phase 2 itself does not need to ship the full browser/dashboard UX; it must provide the state and API substrate for those later surfaces.

### OpenCode's Discretion
- Exact schema/table names, migration layout, and service/helper decomposition.
- Exact command/API shapes for lifecycle, attach/detach, and mission lookup flows.
- Whether the phase is split around state/schema work vs todo/delegation/checkpoint integration, as long as canonical-write-path constraints remain intact.
- Test file organization and how verification is divided across unit, integration, and behavioral coverage.

</decisions>

<specifics>
## Specific Ideas

- Use the Gate 3 checks in `.omx/plans/test-spec-hermes-all-features-integration.md` as the verification north star for this phase.
- Ensure the planner accounts for `hermes_state.py`, `tools/todo_tool.py`, `tools/delegate_tool.py`, `run_agent.py`, `agent/skill_commands.py`, `tools/checkpoint_manager.py`, and new mission/handoff modules called out in the PRD.
- Preserve the service-first cutover decision already approved in the PRD.

</specifics>

<deferred>
## Deferred Ideas

- Proposal engine, generated skills/plugins, and one-way projections from Phase 3.
- ModelOpsService, learning exports, daily briefs, and analytics from Phase 4.
- Browser Mission Control, browser terminal, and cloud packaging from Phase 5.
- Rollout defaults, canary/rollback procedures, and migration runbooks from Phase 6.

</deferred>

---

*Phase: 02-typed-mission-graph-todo-write-through-and-handoff-authority*
*Context gathered: 2026-04-20 via PRD Express Path*