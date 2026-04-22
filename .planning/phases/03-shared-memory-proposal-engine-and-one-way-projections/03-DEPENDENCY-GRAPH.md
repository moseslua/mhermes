# Phase 3 Dependency Graph

```text
P3-U1  Canonical shared-memory service and read APIs
  ├─> P3-U2  Proposal queue, guarded generation, and approval routing
  └─> P3-U3  One-way projections, cursoring, and rebuild flows
```

## Why this shape
- `P3-U1` is the contract setter. Both proposal detection and projections need one canonical shared-memory read surface.
- `P3-U2` depends on `P3-U1` because proposal ranking and approval routing should operate on canonical shared-memory/domain inputs rather than ad hoc tool text.
- `P3-U3` depends on `P3-U1` because projections must consume canonical sources only.
- `P3-U2` and `P3-U3` can proceed independently after `P3-U1` lands, then converge at final Phase 3 verification.

## Merge Queue
1. Merge `P3-U1`
2. Rebase `P3-U2` on latest integration branch and merge
3. Rebase `P3-U3` on latest integration branch and merge
4. Run final Phase 3 integration verification
