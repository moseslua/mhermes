# Phase 2: Typed mission graph, todo write-through, and handoff authority - Research

**Researched:** 2026-04-20
**Domain:** Hermes-internal mission orchestration, canonical SQLite state, delegation/handoff, and todo authority
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Persist missions, mission nodes, and mission links in Hermes-managed canonical state (`state.db`) with explicit service APIs.
- Do not create a second durable planner/task store or a `.maestro/` sidecar.
- Under an active mission, `todo` operations must write through to mission task rows.
- When no mission is attached, existing session-local todo behavior must remain available.
- Mission activation remains approval-gated.
- Persist handoff packets and checkpoints as mission-linked canonical records.
- Mission bundles/exports are projections only, not a writable source of truth.
- Expose mission-control read APIs that CLI, TUI, and web surfaces can consume later.
- Phase 2 itself does not need to ship the full browser/dashboard UX; it must provide the state and API substrate for those later surfaces.

### OpenCode's Discretion
- Exact schema/table names, migration layout, and service/helper decomposition.
- Exact command/API shapes for lifecycle, attach/detach, and mission lookup flows.
- Whether the phase is split around state/schema work vs todo/delegation/checkpoint integration, as long as canonical-write-path constraints remain intact.
- Test file organization and how verification is divided across unit, integration, and behavioral coverage.

### Deferred Ideas (OUT OF SCOPE)
- Proposal engine, generated skills/plugins, and one-way projections from Phase 3.
- ModelOpsService, learning exports, daily briefs, and analytics from Phase 4.
- Browser Mission Control, browser terminal, and cloud packaging from Phase 5.
- Rollout defaults, canary/rollback procedures, and migration runbooks from Phase 6.
</user_constraints>

<research_summary>
## Summary

The current Hermes codebase already contains most of the seams Phase 2 needs, but they are adapters and observations, not authoritative mission state. `tools/todo_tool.py:25-195` implements an in-memory `TodoStore` plus a fixed `todo` tool schema, while `run_agent.py:1273-1275`, `3789-3818`, and `7807-7841` attach that store to each `AIAgent`, rehydrate it from the most recent persisted tool response, and preserve only active items across compression by injecting a synthetic user message. This gives Phase 2 a clean place to preserve tool-call shape and compression behavior, but it also proves the current todo system is session-local and history-derived rather than canonical.

Durable mission-related storage is not present yet. `hermes_state.py:94-118` and `998-1097` persist runtime-signal audit rows with a nullable `mission_id`, and the v7 migration explicitly describes those rows as observational rather than authoritative domain truth (`hermes_state.py:360-365`). At the same time, `SessionDB` already owns WAL-mode SQLite lifecycle, migration/versioning patterns, retries, and indexing (`hermes_state.py:1-130`, `279-370`), making it the correct landing zone for canonical mission tables and mission-centric read/write APIs.

Delegation and checkpoints are likewise partially present but semantically different from the Phase 2 target. `tools/delegate_tool.py:321-425` and `680-860` already preserve parent/child session lineage, tool restrictions, activity propagation, and structured child outcomes, while `tools/checkpoint_manager.py:1-18` and `275-343` implement transparent filesystem safety checkpoints in shadow git repos under `~/.hermes/checkpoints`. The correct direction is to reuse delegation lineage and execution constraints, but keep workflow/mission checkpoints separate from filesystem rollback checkpoints.

**Primary recommendation:** Add authoritative mission persistence and service APIs inside `SessionDB`, then treat `todo`, delegation, and mission checkpoints as adapters that read/write canonical mission state while preserving existing tool schemas, compression continuity, and child-agent safety constraints.
</research_summary>

<standard_stack>
## Standard Stack

The established in-repo components for this phase:

### Core
| Component | Location | Purpose | Why Standard |
|-----------|----------|---------|--------------|
| `SessionDB` | `hermes_state.py` | Canonical SQLite durability, migrations, WAL behavior, query helpers | Existing durable authority already used by Hermes sessions |
| Runtime signal audit | `hermes_state.py`, `agent/runtime_signals.py`, `run_agent.py` | Observational event stream with `mission_id`, correlation, provenance | Already present and suitable as supporting audit, not canonical truth |
| `TodoStore` + `todo_tool()` | `tools/todo_tool.py` | Session-local task list and stable tool schema | Existing user/tool interface should be preserved while changing backing storage |
| Delegation pipeline | `tools/delegate_tool.py` | Parent/child agent construction, lineage, progress, restrictions | Existing handoff execution seam that Phase 2 must extend rather than replace |
| Shared slash/skill command helpers | `agent/skill_commands.py` | Shared command naming and prompt assembly across CLI/gateway | Existing registration/normalization surface for any mission-related command exposure |

### Supporting
| Component | Location | Purpose | When to Use |
|-----------|----------|---------|-------------|
| Filesystem checkpoint manager | `tools/checkpoint_manager.py` | Shadow-git rollback safety for file mutations | Preserve as separate safety infrastructure; do not use as mission state |
| Context compression todo injection | `run_agent.py`, `tools/todo_tool.py` | Preserve active task continuity across compression/session rotation | Keep for user/model continuity even after canonical mission state lands |
| Session lineage helpers | `hermes_state.py` | Parent-child session chains and title lineage | Reuse for mission lineage/handoff modeling where semantics align |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Canonical mission tables in `SessionDB` | Reconstruct from runtime audit rows only | Simpler upfront, but violates the requirement that audit is observational rather than authoritative |
| Mission-backed todo adapter | Keep history-scan hydration as truth | Less code immediately, but stale tool echoes remain authoritative and mission ownership cannot survive session rotation cleanly |
| Separate workflow checkpoint persistence | Reuse `CheckpointManager` shadow repos | Conflates rollback safety with semantic workflow state and stores mission data outside canonical session state |

**Installation:** No new external packages are required by the current research. Reuse Hermes' existing Python/SQLite surfaces unless planning uncovers a concrete missing dependency.
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Pattern 1: Authoritative service over adapter surfaces
**What:** Put canonical mission, task, handoff, and checkpoint state behind a dedicated service layer in `SessionDB`, then make `todo`, delegation, and UI/read surfaces adapters over that service.
**When to use:** Whenever an existing interface already exists but its backing store is currently session-local, prompt-local, or observational.
**Example:**
```text
canonical mission service -> todo tool adapter / delegation adapter / read APIs
runtime_signal_audit -> supporting telemetry only
```

### Pattern 2: Session lineage informs mission lineage, but does not replace it
**What:** Reuse `parent_session_id`, child-session registration, and delegated child completion metadata as provenance for mission handoffs, while storing mission authority explicitly in mission tables.
**When to use:** When a delegated child or resumed session participates in a mission but session parentage alone is not sufficient to define ownership or lifecycle.
**Example:**
```text
session parent/child chain = provenance
mission edge / handoff packet = authoritative workflow relationship
```

### Pattern 3: Keep workflow checkpoints separate from filesystem rollback checkpoints
**What:** Treat mission/workflow checkpoints as typed state in canonical storage, while preserving `CheckpointManager` solely for pre-edit filesystem safety.
**When to use:** Any time the same word "checkpoint" could refer to both workflow state and file rollback.
**Example:**
```text
workflow checkpoint -> SessionDB mission tables
filesystem checkpoint -> ~/.hermes/checkpoints shadow repo
```

### Anti-Patterns to Avoid
- **Audit-as-truth:** Do not treat `runtime_signal_audit` as the canonical mission graph; the v7 migration explicitly rejects that model.
- **Prompt-only handoffs:** Do not rely on loose goal/context strings as the only durable handoff representation; Phase 2 needs typed packets/records.
- **Checkpoint conflation:** Do not store mission semantics in shadow git checkpoints or expect `CheckpointManager` retention/dedupe rules to match workflow needs.
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Durable mission/task authority | A new sidecar store or `.maestro/`-style directory | Extend `SessionDB` with versioned mission tables and helpers | Keeps one durable authority and reuses proven WAL/migration behavior |
| Todo continuity | History-scan reconstruction as canonical truth | Mission-backed hydration plus current compression injection behavior | History replay is stale/ambiguous; compression continuity still matters |
| Workflow checkpoints | Mission state in shadow git repos | Separate mission checkpoint records, keep `CheckpointManager` for filesystem rollback only | Different retention, identity, and correctness requirements |
| Delegation lineage | Ad hoc parsing of child prompt text/results | Normalize delegation at `delegate_task()` / child build / child completion seams | Existing code already surfaces child lineage, restrictions, and results |

**Key insight:** The repo already has the right primitives; the phase should consolidate them behind a truthful authority boundary, not add new parallel representations.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Split-brain between todo state and mission state
**What goes wrong:** The `todo` tool updates one representation while mission state or UI surfaces read another.
**Why it happens:** Current todos are in-memory and history-derived, so it is tempting to leave them as-is and mirror later.
**How to avoid:** Make mission-backed writes authoritative first, then adapt `todo_tool()`/hydration to read that state.
**Warning signs:** Hydration still scans old tool responses, or mission/task views disagree after compression or session restart.

### Pitfall 2: Coupling mission authority to session cleanup
**What goes wrong:** Pruning or deleting a session destroys cross-session mission state or handoff authority.
**Why it happens:** Current durable state is session-centric and runtime audit queries are keyed mainly by session/correlation.
**How to avoid:** Give mission tables their own retention/ownership rules and explicitly define how mission records relate to session lineage.
**Warning signs:** Mission reads require replaying session audit history, or cleanup code can orphan active mission tasks silently.

### Pitfall 3: Confusing workflow checkpoints with filesystem rollback snapshots
**What goes wrong:** Mission resume data lives in shadow git repos or rollback tooling starts carrying workflow semantics.
**Why it happens:** `CheckpointManager` already exists and the word "checkpoint" overlaps conceptually.
**How to avoid:** Keep `CheckpointManager` untouched as safety infrastructure; introduce separately named, typed mission/workflow checkpoint records.
**Warning signs:** Mission code imports shadow-repo paths, or workflow restore logic depends on git commit hashes instead of typed state.
</common_pitfalls>

## Validation Architecture

Phase 2 should validate through the existing hermetic Python test wrapper, with the test strategy centered on Gate 3 from `.omx/plans/test-spec-hermes-all-features-integration.md`.

- **Primary framework:** `pytest` via `scripts/run_tests.sh`
- **Fast feedback path:** focused unit/integration targets for `hermes_state.py`, `tools/todo_tool.py`, `tools/delegate_tool.py`, and any new mission modules
- **Required layers:**
  - unit: schema helpers, lifecycle rules, todo write-through behavior, handoff/checkpoint normalization
  - integration: delegated child lineage + persisted handoff packets/checkpoints + canonical mission reads
  - behavioral: attach/detach mission, mutate todos, verify session-local fallback when no mission is attached
- **Sampling rule:** every plan task should have an automated verification command; missing coverage should create Wave 0 test scaffolding work rather than leaving manual-only checks behind

<open_questions>
## Open Questions

1. **What exact mission graph shape should Hermes store?**
   - What we know: The PRD requires missions, mission nodes, mission links, explicit lifecycle APIs, and no second writable task representation.
   - What's unclear: Exact table split, node/link typing, and whether some handoff/checkpoint payloads live inline or in sibling tables.
   - Recommendation: Resolve this in the first planning slice with a schema/service plan and migration tests before touching `todo` or delegation behavior.

2. **Where should mission lifecycle commands surface first?**
   - What we know: `agent/skill_commands.py` centralizes shared slash/skill command helpers, but no mission commands exist today.
   - What's unclear: Whether Phase 2 should add built-in mission commands immediately or only establish read/service APIs for later command surfaces.
   - Recommendation: Keep initial scope focused on state/service APIs plus any minimal command plumbing needed for CLI/TUI use; defer richer UX surface expansion to later phases.

3. **How much todo metadata must enter runtime-signal payloads?**
   - What we know: Current tool signals carry `tool_name`, `task_id`, result length, and `mission_id`, but not authoritative todo IDs or revisions.
   - What's unclear: Whether audit consumers need item-level diffs now or whether mission-table writes plus correlation IDs are enough initially.
   - Recommendation: Plan for stable mission/task identifiers now; make richer payload detail explicit only if a concrete consumer needs it.
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- `tools/todo_tool.py` - current todo storage, mutation semantics, and compression injection behavior
- `run_agent.py` - todo store ownership, hydration, compression/session rotation, and runtime-signal emission
- `hermes_state.py` - canonical SQLite patterns, runtime-signal audit schema, and migration style
- `tools/delegate_tool.py` - delegated child lineage, restrictions, and structured completion behavior
- `tools/checkpoint_manager.py` - filesystem checkpoint semantics and storage location
- `agent/skill_commands.py` - shared slash/skill command normalization surface
- `.omx/plans/prd-hermes-all-features-integration.md` - approved phase scope and target touchpoints
- `.omx/plans/test-spec-hermes-all-features-integration.md` - Gate 3 verification targets and rollout expectations

### Secondary (MEDIUM confidence)
- None required; phase research is fully grounded in repository artifacts.

### Tertiary (LOW confidence - needs validation)
- None.
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: Hermes SQLite/session state, todo tool behavior, delegation lineage, workflow checkpoints
- Ecosystem: existing in-repo mission-adjacent seams only
- Patterns: authoritative service over adapters, lineage-aware handoff authority, checkpoint separation
- Pitfalls: split-brain state, cleanup coupling, checkpoint conflation

**Confidence breakdown:**
- Standard stack: HIGH - all components exist in the repository today
- Architecture: HIGH - patterns align with both current repo seams and the approved PRD constraints
- Pitfalls: HIGH - directly observed mismatches between current behavior and target phase semantics
- Code examples: MEDIUM - no new implementation exists yet; examples are structural rather than concrete final APIs

**Research date:** 2026-04-20
**Valid until:** 2026-05-20
</metadata>

---

*Phase: 02-typed-mission-graph-todo-write-through-and-handoff-authority*
*Research completed: 2026-04-20*
*Ready for planning: yes*