# Context Snapshot — aeon-automation-skill-healing

## Task statement
Integrate the Aeon/Talon automation capabilities that are better than Hermes into Hermes, especially automation orchestration and self-healing / skill-health behavior.

## Desired outcome
Add concrete Hermes features that close the gap with Aeon in unattended automation, run health visibility, and self-healing workflows, while fitting Hermes's existing cron, skill, and gateway architecture.

## Known facts / evidence
- Hermes already supports unattended automation through cron jobs, webhook subscriptions, and API-triggered flows (`hermes-already-has-routines.md`).
- Hermes cron already supports:
  - recurring and one-shot schedules (`cron/jobs.py`)
  - multi-skill job loading (`cron/jobs.py`, `tools/cronjob_tools.py`)
  - optional pre-run scripts with injected stdout and wake gating (`cron/scheduler.py:_run_job_script`, `_parse_wake_gate`, `_build_job_prompt`)
  - delivery routing across platforms (`cron/scheduler.py`)
- Hermes skills infrastructure already supports agent-managed creation/editing (`tools/skill_manager_tool.py`) and bundled skill syncing (`tools/skills_sync.py`).
- Hermes does not appear to have an Aeon-style self-healing loop with persistent per-job quality history, reactive follow-up jobs, or built-in heartbeat / health / repair automation.
- From the earlier Aeon analysis in `talon/`, Aeon’s differentiators over Hermes are primarily:
  - a self-healing loop: heartbeat → skill-health → skill-evals → skill-repair → self-improve
  - per-skill health tracking in persistent state
  - reactive triggers based on failure conditions
  - scheduled meta-skills dedicated to keeping the system healthy

## Constraints
- Work inside the existing Hermes architecture; avoid bolting on a separate daemon or database unless clearly necessary.
- Preserve prompt-caching design — avoid stuffing volatile policy into stable prompt layers.
- Keep changes reviewable and testable.
- Current workspace already has uncommitted AI-first workflow/doc changes; do not overwrite them.

## Unknowns / open questions
- Whether to implement reactive triggers as a generic cron capability or as a narrower self-healing mechanism.
- Whether self-healing should operate on cron jobs only, skills only, or both.
- How far to go in this pass: infrastructure only vs infrastructure plus bundled meta-skills/templates.

## Likely codebase touchpoints
- `cron/jobs.py`
- `cron/scheduler.py`
- `tools/cronjob_tools.py`
- `hermes_cli/commands.py` / cron-related CLI surfaces
- `tools/skill_manager_tool.py`
- `tools/skills_sync.py`
- `skills/` (new bundled automation/self-healing skills)
- `tests/cron/*`
- `tests/tools/test_cronjob_tools.py`
- `tests/hermes_cli/test_cron.py`
- `README.md` / docs for automation usage
