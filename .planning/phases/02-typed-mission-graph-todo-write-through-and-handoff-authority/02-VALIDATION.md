---
phase: 02
slug: typed-mission-graph-todo-write-through-and-handoff-authority
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-20
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest via `scripts/run_tests.sh` |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `scripts/run_tests.sh tests/test_hermes_state.py tests/tools/test_todo_tool.py tests/tools/test_delegate.py tests/tools/test_checkpoint_manager.py tests/agent/test_mission_state.py tests/tools/test_mission_tool.py tests/agent/test_handoff_packets.py tests/agent/test_skill_commands.py -q` |
| **Full suite command** | `scripts/run_tests.sh tests/test_hermes_state.py tests/tools/test_todo_tool.py tests/tools/test_delegate.py tests/tools/test_checkpoint_manager.py tests/agent/test_mission_state.py tests/tools/test_mission_tool.py tests/agent/test_handoff_packets.py tests/agent/test_skill_commands.py -q` |
| **Estimated runtime** | ~90 seconds |

---

## Sampling Rate

- **After every task commit:** Run the task's `<automated>` command from its PLAN.md entry
- **After every plan wave:** Run `scripts/run_tests.sh tests/test_hermes_state.py tests/tools/test_todo_tool.py tests/tools/test_delegate.py tests/tools/test_checkpoint_manager.py tests/agent/test_mission_state.py tests/tools/test_mission_tool.py tests/agent/test_handoff_packets.py tests/agent/test_skill_commands.py -q`
- **Before `/gsd-verify-work`:** The focused Phase 2 suite above must be green
- **Max feedback latency:** 30 seconds per task-scoped command, 90 seconds per wave

---

## Per-task Verification Map

| task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | MISSION-01 | migration/unit | `scripts/run_tests.sh tests/test_hermes_state.py -q` | ✅ | ⬜ pending |
| 02-01-02 | 01 | 1 | MISSION-01 | service/tool integration | `scripts/run_tests.sh tests/agent/test_mission_state.py tests/tools/test_mission_tool.py -q` | ❌ created in task | ⬜ pending |
| 02-01-03 | 01 | 1 | MISSION-01 | regression contract + approval gate | `scripts/run_tests.sh tests/test_hermes_state.py tests/agent/test_mission_state.py tests/tools/test_mission_tool.py -q` | ✅ via 02-01-02 | ⬜ pending |
| 02-02-01 | 02 | 2 | MISSION-02 | tool-unit | `scripts/run_tests.sh tests/tools/test_todo_tool.py -q` | ✅ | ⬜ pending |
| 02-02-02 | 02 | 2 | MISSION-02 | hydration/integration | `scripts/run_tests.sh tests/tools/test_todo_tool.py tests/agent/test_mission_state.py -q` | ✅ via 02-01 | ⬜ pending |
| 02-02-03 | 02 | 2 | MISSION-02 | split-brain regression | `scripts/run_tests.sh tests/tools/test_todo_tool.py tests/agent/test_mission_state.py tests/test_hermes_state.py -q` | ✅ via 02-01 | ⬜ pending |
| 02-03-01 | 03 | 3 | MISSION-03 | delegation/handoff integration | `scripts/run_tests.sh tests/tools/test_delegate.py tests/agent/test_handoff_packets.py -q` | ❌ created in task | ⬜ pending |
| 02-03-02 | 03 | 3 | MISSION-03 | checkpoint separation regression | `scripts/run_tests.sh tests/tools/test_checkpoint_manager.py tests/agent/test_handoff_packets.py -q` | ✅ via 02-03-01 | ⬜ pending |
| 02-03-03 | 03 | 3 | MISSION-03 | read-surface/command regression | `scripts/run_tests.sh tests/agent/test_skill_commands.py tests/agent/test_handoff_packets.py -q` | ✅ via 02-03-01 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

No separate Wave 0 plan is required. New phase-specific tests (`tests/agent/test_mission_state.py`, `tests/tools/test_mission_tool.py`, and `tests/agent/test_handoff_packets.py`) are created inside their owning tasks before each task's `<automated>` command is run.
---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| No Phase 2 rollout beyond internal mission surfaces | MISSION-03 | Scope guard against accidental browser/dashboard rollout | Confirm Phase 2 execution touches no `web/`, `ui-tui/`, `tui_gateway/`, or `hermes_cli/web_server.py` files and limits exposure to internal/state/tool surfaces only. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] No `<automated>MISSING</automated>` references; new phase-specific tests are created within their owning tasks before execution
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter
- [x] Focused tests in 02-01-03 explicitly reject unauthorized mission activation without approval
- [x] Phase execution remains limited to internal CLI/TUI/tool/state surfaces; no browser/dashboard rollout files change

**Approval:** approved 2026-04-20 after checker loop and artifact-state sync