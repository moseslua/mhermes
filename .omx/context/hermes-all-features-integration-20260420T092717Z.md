# Context Snapshot — Hermes all-features integration

- Timestamp: 2026-04-20T09:27:17Z
- Task slug: hermes-all-features-integration

## Task statement
Turn the prior repo scan into a full-scale RALPLAN-style plan markdown artifact for integrating all requested features from five external repositories into the Hermes harness.

## Desired outcome
Produce an execution-ready consensus plan that preserves every feature family from:
- hermes-agent-camel
- hermes-alpha
- hermes-skill-factory
- maestro
- icarus-plugin

The plan must keep Hermes as the primary runtime and identify concrete implementation phases, files/subsystems, risks, verification strategy, and execution staffing guidance.

## Known facts / evidence
### Hermes extension seams
- General plugins are directory-based (`plugin.yaml` + `__init__.py` + `register(ctx)`) via `hermes_cli/plugins.py`.
- Memory providers are pluggable but only one external provider is allowed at a time via `agent/memory_provider.py` and `agent/memory_manager.py`.
- Context engines are pluggable and selected by config via `agent/context_engine.py` and `run_agent.py`.
- Durable session history is canonical in SQLite `state.db` with FTS5 via `hermes_state.py`.
- Skill creation/editing already goes through `skill_manage` and generated skills are scanned by `tools/skills_guard.py` from `tools/skill_manager_tool.py`.
- Plugin toolsets already participate in tool configuration UI via `hermes_cli/tools_config.py`.
- Only part of the declared plugin hook surface is currently wired. `pre_tool_call` and `pre_llm_call` are active in `run_agent.py`; declared hooks like `post_tool_call`, `post_llm_call`, `pre_api_request`, and `post_api_request` were not observed invoked in current runtime inspection.
- Plugin installation currently clones and installs repos but does not run a plugin security scanner analogous to `skills_guard`.

### External repo findings
#### hermes-agent-camel
- This is a Hermes fork, not a plugin.
- It adds trusted/untrusted separation, per-turn security envelope, capability gating for sensitive tools, and monitor/enforce/off runtime modes.
- Its value is architectural and belongs in core runtime.

#### hermes-alpha
- This is an experimental Fly.io/browser-PTY deployment wrapper around a vendored Hermes snapshot.
- It contributes cloud packaging, a browser terminal, volume bootstrap, and optional messaging-sidecar startup.
- It should not become the canonical runtime.

#### hermes-skill-factory
- This is a prototype meta-skill plus old-style plugin that observes workflows and proposes skill/plugin generation.
- Its best ideas are passive observation, pattern detection, proposal/review, and generation.
- Its implementation assumes old plugin APIs, single-file plugin drops, hardcoded `~/.hermes`, and generated plugin stubs.

#### maestro
- This is a standalone Bun-based local-first conductor with `.maestro/` state.
- It contributes plan/approve/execute, mission/milestone/feature/assertion modeling, handoff packets, checkpoints, principles/outcomes, and a mission-control dashboard.
- It overlaps heavily with Hermes state/task/orchestration and should be concept-ported rather than adopted wholesale.

#### icarus-plugin
- This is the closest fit to Hermes’ current plugin model: `plugin.yaml`, `ctx.register_tool`, and `ctx.register_hook`.
- It contributes shared memory, telemetry, training export, fine-tune/eval/model switching, review/fix linkage, daily briefs, and Obsidian/FABRIC mirroring.
- It introduces a second file-backed truth store (`FABRIC_DIR`) and can rewrite `.env` to switch models.

## Constraints
- Preserve all requested feature families.
- Do not create multiple competing runtimes or canonical state stores.
- Keep Hermes profile-safe; no hardcoded `~/.hermes` paths.
- Prefer Hermes-native extension seams over long-term dependence on external forks.
- Plan should be deliberate/high-rigor because it spans security, memory, orchestration, deployment, and model-management concerns.

## Unknowns / open questions
- Whether plugin hook wiring should be expanded directly in core or normalized through an internal event bus.
- How much of mission state should live in SQLite versus workspace-local markdown/json projections.
- Whether FABRIC/Obsidian mirroring should be bundled by default or remain opt-in.
- How aggressive the initial scope should be for model-switching automation versus manual approval-only.
- Whether Alpha-style browser terminal should extend existing Hermes web surfaces or remain a separate package.

## Likely codebase touchpoints
- `run_agent.py`
- `model_tools.py`
- `hermes_state.py`
- `agent/context_engine.py`
- `agent/memory_provider.py`
- `agent/memory_manager.py`
- `hermes_cli/plugins.py`
- `hermes_cli/plugins_cmd.py`
- `hermes_cli/config.py`
- `agent/skill_commands.py`
- `tools/skill_manager_tool.py`
- `tools/skills_guard.py`
- `hermes_cli/web_server.py`
- `ui-tui/`
- `tui_gateway/`
