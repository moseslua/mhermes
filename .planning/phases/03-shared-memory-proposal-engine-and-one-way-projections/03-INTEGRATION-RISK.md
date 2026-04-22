# Phase 3 Integration Risk Summary

## Highest risks

### 1. Split-brain memory authority
If shared memory is assembled from prompt-time text instead of canonical sources, Phase 3 will create a second truth store.
- Mitigation: `P3-U1` must define a typed shared-memory read surface over canonical files/session history only.

### 2. Unsafe generated artifact activation
Direct skill/plugin generation without durable approval state would violate the rollout gate.
- Mitigation: `P3-U2` keeps proposal queue visible, auto-apply disabled, and requires `skills_guard`/`plugin_guard` before any activation path.

### 3. Derived outputs becoming inputs
Projection files becoming read sources would corrupt canonical-state guarantees.
- Mitigation: `P3-U3` must enforce one-way writers only and prove delete-and-rebuild from canonical state.

### 4. Provider invariant drift
Shared-memory features could accidentally activate more than one external provider or bypass current provider selection semantics.
- Mitigation: reuse existing `MemoryManager` and plugin/provider config seams instead of inventing a second selector.

## Verification gates
- Gate 4: proposal engine and generated artifacts
- Gate 5: shared memory, briefs, telemetry, and projections

## Recommended order
- Build `P3-U1` to lock shared-memory contracts.
- Build `P3-U2` with approval-gated proposal routing.
- Build `P3-U3` with projection cursoring and rebuild safety.

## Stop conditions
Do not advance beyond `P3-U1` if:
- canonical shared-memory sources are still ambiguous,
- provider exclusivity is not testable,
- or shared-memory reads still depend on derived outputs.
