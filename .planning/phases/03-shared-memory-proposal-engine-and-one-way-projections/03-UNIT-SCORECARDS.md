# Phase 3 Unit Scorecards

## P3-U1 — Canonical shared-memory service and read APIs
- id: `P3-U1`
- depends_on: `[]`
- scope:
  - Introduce a canonical shared-memory service over file-backed curated memory plus canonical session/history data.
  - Preserve `MemoryManager`'s one-external-provider invariant.
  - Expose structured shared-memory reads for downstream proposal/projection consumers.
  - Keep frozen system-prompt snapshot behavior intact.
- acceptance_tests:
  - Shared-memory composition reads MEMORY.md/USER.md plus canonical session history without consulting derived outputs.
  - Service works with builtin memory only and with exactly one external provider.
  - Child-session lineage resolves back to parent session history where appropriate.
  - Prompt injection remains fenced/sanitized; persisted session messages are not mutated by prefetch.
- risk_level: `Tier 2`
- rollback_plan:
  - Remove the new shared-memory service wiring and fall back to current `memory_tool` + `session_search` split behavior.
  - Keep existing provider configuration paths untouched.
- status: `planned`
- notes:
  - Primary touchpoints: `agent/memory_manager.py`, `agent/memory_provider.py`, `tools/memory_tool.py`, `tools/session_search_tool.py`, `run_agent.py`

## P3-U2 — Proposal queue, guarded generation, and approval routing
- id: `P3-U2`
- depends_on: `[P3-U1]`
- scope:
  - Add a proposal engine over canonical memory/session/runtime inputs.
  - Deduplicate and rank proposals.
  - Route approved skill generation through `skill_manage`.
  - Route approved plugin generation through guarded scaffolds plus `plugin_guard` quarantine/disabled state.
  - Keep proposal queue visible while auto-apply remains disabled.
- acceptance_tests:
  - Proposal detection over runtime/domain/shared-memory inputs is deterministic and deduplicated.
  - Approved skill generation routes through `skill_manage` and remains scanned by `skills_guard`.
  - Approved plugin generation is scanned/quarantined by `plugin_guard` before activation.
  - No unsafe or unapproved generated artifact becomes active automatically.
- risk_level: `Tier 3`
- rollback_plan:
  - Disable proposal queue reads/writes and keep existing direct skill/plugin management paths only.
  - Leave generated artifact guards intact and block any pending proposal actions.
- status: `planned`
- notes:
  - Primary touchpoints: `tools/skill_manager_tool.py`, `tools/skills_guard.py`, `hermes_cli/plugins.py`, `hermes_cli/plugins_cmd.py`, new `agent/proposal_engine.py`, likely `tools/plugin_guard.py`

## P3-U3 — One-way projections, cursoring, and rebuild flows
- id: `P3-U3`
- depends_on: `[P3-U1]`
- scope:
  - Add a projection service for FABRIC/Obsidian/mission-bundle outputs.
  - Track projection cursor state, including `last_applied_audit_id`.
  - Make replay idempotent and rebuild delete-safe.
  - Use canonical state only; never read projection outputs back as source data.
- acceptance_tests:
  - Projection cursor semantics are explicit and monotonic.
  - Reapplying the same source state is idempotent.
  - Delete-and-rebuild from canonical state regenerates correct outputs.
  - Mission-bundle outputs derive from canonical mission/handoff/checkpoint state only.
- risk_level: `Tier 2`
- rollback_plan:
  - Disable projection writers and keep canonical state untouched.
  - Delete derived outputs and cursor metadata only.
- status: `planned`
- notes:
  - Primary touchpoints: `hermes_constants.py`, new `agent/state_projections.py`, `agent/mission_state.py`, `agent/handoff_packets.py`, `run_agent.py`
