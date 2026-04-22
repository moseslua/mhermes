# Phase 3 RFC Execution Log

## Phase
Phase 3 — Shared memory, proposal engine, and one-way projections

## Goal
Land Skill Factory and FABRIC-style knowledge features without violating provider constraints or projection rules.

## Inputs
- `.planning/ROADMAP.md` Phase 3
- `.omx/plans/prd-hermes-all-features-integration.md`
- `.omx/plans/test-spec-hermes-all-features-integration.md`
- Current repo seams in memory/session recall, skill/plugin generation, and mission bundle reads

## RFC Intake Summary
Phase 3 is too large for a single implementation pass. It spans:
- canonical memory composition,
- proposal detection and approval-gated generation,
- guarded skill/plugin materialization,
- projection cursoring and rebuild semantics.

The right cut is three independently verifiable work units with one explicit dependency chain and one parallelizable tail.

## Dependency Graph Snapshot
- `P3-U1` → `P3-U2`
- `P3-U1` → `P3-U3`
- `P3-U2` and `P3-U3` integrate at Phase 3 verification

Execution intent:
1. Build canonical shared-memory substrate first.
2. Add proposal queue and guarded generation over that substrate.
3. Add one-way projections consuming canonical state only.

## Unit Assignment
### P3-U1
Canonical shared-memory service and read APIs

### P3-U2
Proposal queue, guarded generation, and approval routing

### P3-U3
One-way projections, cursoring, and rebuild flows

## Integration Notes
- Phase 3 must preserve the one-external-provider invariant already enforced by `MemoryManager`.
- No generated skill or plugin becomes active automatically.
- Projection outputs are derived only; they never become canonical inputs.
- Mission bundles should reuse `MissionService.build_bundle()` as the canonical mission-shaped export source.

## Merge Queue Rules for This Phase
- Land `P3-U1` first.
- Rebase `P3-U2` and `P3-U3` onto the `P3-U1` result before merge.
- Re-run focused Phase 3 tests after each merge candidate.
- Do not merge proposal/projection units if shared-memory source contracts drift.

## Recovery Plan
If a unit stalls:
1. Snapshot findings in the unit scorecard.
2. Narrow scope around the failing seam only.
3. Retry with updated constraints.
4. Keep later units blocked until upstream contracts are stable.

## Output Contract
This RFC decomposition produces:
- `03-UNIT-SCORECARDS.md`
- `03-DEPENDENCY-GRAPH.md`
- `03-INTEGRATION-RISK.md`
