# Autopilot Spec — Hermes All-Features Integration

## Source
Derived from `.omx/plans/prd-hermes-all-features-integration.md` (approved RALPLAN consensus plan).

## Objective
Absorb hermes-agent-camel, hermes-alpha, hermes-skill-factory, maestro, and icarus-plugin feature families into Hermes as one coherent product.

## Principles
1. Hermes stays primary runtime.
2. One durable authority per concept (`state.db`).
3. One plugin contract.
4. Risky autonomy is gated.
5. All persistence is profile-safe.

## Feature Preservation Matrix

| Source | Feature Family | Status | Hermes Landing Zone |
|---|---|---|---|
| hermes-agent-camel | CaMeL trust boundary, capability gating | Partial | `agent/runtime_signals.py` exists; `agent/runtime_policy.py` missing |
| hermes-alpha | Cloud packaging, browser terminal | Not started | `packaging/fly/`, `hermes_cli/web_server.py` |
| hermes-skill-factory | Passive observation, proposal engine | Partial | `agent/proposal_engine.py` missing; proposal schema missing |
| hermes-skill-factory | Skill/plugin generation | Partial | `tools/plugin_guard.py` exists; generation workflow incomplete |
| maestro | Mission graph, handoffs, checkpoints | Partial | `agent/mission_state.py`, `tools/mission_tool.py` exist; `agent/handoff_packets.py` exists |
| maestro | Mission Control dashboard | Not started | Web/TUI surfaces |
| icarus-plugin | Shared memory, briefs, telemetry | Partial | `agent/memory_manager.py` modified; projection layer missing |
| icarus-plugin | Training export, eval, model registry | Not started | `agent/model_ops.py`, `tools/rl_training_tool.py` exists but not wired |
| icarus-plugin | Obsidian/FABRIC mirroring | Not started | `agent/state_projections.py` missing |

## Gate Status

| Gate | Description | Status | Blockers |
|---|---|---|---|
| Gate 0 | Migration + baseline safety | Partial | Need migration test for new tables |
| Gate 1 | Runtime signals + hooks | Partial | `runtime_signals.py` exists; missing `runtime_policy.py`, hook adapter |
| Gate 2 | CaMeL trust boundary | Not started | `runtime_policy.py` missing; no provenance tagging in diff |
| Gate 3 | Mission graph + todo semantics | Partial | Schema exists; need integration tests for write-through |
| Gate 4 | Proposal engine + artifacts | Not started | Schema missing; `proposal_engine.py` missing |
| Gate 5 | Shared memory + projections | Partial | Memory manager modified; `state_projections.py` missing |
| Gate 6 | ModelOps + protected mutation | Not started | `model_ops.py` missing; schema missing |
| Gate 7 | Browser terminal + cloud packaging | Not started | No packaging dir; web_server.py has some changes |
| Gate 8 | Performance + observability | Not started | No benchmark harness in diff |

## Critical Path
1. **Schema completion** — add missing tables (approvals, proposals, model_mutations, learning_exports, eval_runs, projection_cursors, analytics_rollups)
2. **Runtime policy layer** — `agent/runtime_policy.py` with CaMeL provenance + capability gating
3. **Proposal engine** — `agent/proposal_engine.py` with approval-gated generation
4. **Model ops service** — `agent/model_ops.py` with protected mutation path
5. **State projections** — `agent/state_projections.py` with one-way mirrors
6. **Integration tests** — all gates
7. **Commit + branch** — protect the 8k-line diff

## Risks
- Trigger loops in cron health (mitigated: dedupe on `last_run_at`)
- Backward compatibility (mitigated: normalize missing fields on read)
- Second runtime/store creep (mitigated: PRD explicitly rejects)
- Large uncommitted diff (risk: loss on checkout/reset)

## Out of Scope
- External companion control plane (rejected in PRD)
- Legacy single-file plugin drop formats (rejected in PRD)
- Exactly-once semantics (not promised)
- Silent plugin generation or model mutation (gated)

## Acceptance Criteria
- All 8 gates have passing tests
- `state.db` is canonical; no second truth stores
- No profile-unsafe path regressions
- Benchmark gate passes before verbose audit enabled
- All reviewers approve in Phase 4

## Context
- 79 files modified, ~8,000 insertions on `main` (uncommitted)
- Prior session: Phase 1 (runtime signals, mission state), Phase 2 (shared memory, proposal scaffolding)
- Test spec: `.omx/plans/test-spec-hermes-all-features-integration.md`
- Context snapshot: `.omx/context/hermes-all-features-20260420T174500Z.md`

---
Generated: 2026-04-20T17:45:00Z
Phase: Expansion (Phase 0)
