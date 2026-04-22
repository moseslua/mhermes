# Context Snapshot — Hermes All-Features Integration

## Task Statement
Integrate the full feature families from hermes-agent-camel, hermes-alpha, hermes-skill-factory, maestro, and icarus-plugin into Hermes as one coherent product.

## Desired Outcome
Hermes gains: CaMeL trust-boundary enforcement, cloud/browser-terminal packaging, workflow observation/skill proposal generation, mission planning/handoff/checkpoint/control flows, shared-memory analytics/briefs/model-ops — without creating a second runtime, canonical store, plugin contract, or silent mutation paths.

## Known Facts
- PRD approved and exists at `.omx/plans/prd-hermes-all-features-integration.md`
- Test spec exists at `.omx/plans/test-spec-hermes-all-features-integration.md`
- 79 files modified, ~8,000 insertions, ~1,675 deletions on `main` (uncommitted)
- Prior session implemented Phase 1 (runtime signals, mission state) and Phase 2 (shared memory, proposal engine scaffolding)
- Brainstack repo review completed as side task
- Autopilot impl plan for cron health exists at `.omx/plans/autopilot-impl.md`

## Constraints
- Hermes stays primary runtime
- `state.db` remains canonical
- One plugin contract only
- Risky autonomy behind explicit approval/audit
- Profile-safe paths only (no hardcoded `~/.hermes`)

## Unknowns / Open Questions
- Which of the 8 PRD gates are functionally complete vs need tests vs not started
- Whether cron health/trigger implementation in the diff is complete and passing
- Whether mission graph todo write-through is wired
- Whether proposal engine generates scaffolds correctly

## Likely Touchpoints
- `cron/jobs.py`, `cron/scheduler.py` — health metrics, reactive triggers
- `agent/mission_state.py`, `tools/mission_tool.py`, `tools/todo_tool.py` — mission graph
- `agent/proposal_engine.py` — proposal workflow
- `agent/runtime_signals.py`, `agent/runtime_policy.py` — Camel trust boundary
- `agent/model_ops.py` — model mutation path
- `agent/state_projections.py` — one-way projections
- `hermes_state.py` — schema migrations
- `hermes_cli/web_server.py` — browser terminal
- `run_agent.py`, `model_tools.py` — signal emission

## Existing Artifacts
- `.omx/plans/prd-hermes-all-features-integration.md` (658 lines)
- `.omx/plans/test-spec-hermes-all-features-integration.md` (256 lines)
- `.omx/plans/autopilot-impl.md` (117 lines, cron-focused)
- `docs/specs/ai-first-engineering-workflow.md` (192 lines, new)

## Branch State
- On `main`, all changes unstaged/uncommitted
- No feature branch created yet

## Test Status
- `tests/cron/test_jobs.py` — exit code 33 on last run (failure suspected)
- Other modified test areas unverified

## Next Critical Actions
1. Commit current work to a feature branch
2. Establish test baseline
3. Complete remaining PRD gates
4. Run full test suite
5. Validate with multi-perspective review

---
Snapshot generated: 2026-04-20T17:45:00Z
Session: omp-session-2026-04-20T17-45-07-918Z_14c24d1313974c0c.html
