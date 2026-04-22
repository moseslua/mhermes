## What does this PR do?

<!-- Describe the change clearly. What problem does it solve? Why is this approach the right one? -->



## Related Issue

<!-- Link the issue this PR addresses. If no issue exists, consider creating one first. -->

Fixes #

## Type of Change

<!-- Check the one that applies. -->

- [ ] 🐛 Bug fix (non-breaking change that fixes an issue)
- [ ] ✨ New feature (non-breaking change that adds functionality)
- [ ] 🔒 Security fix
- [ ] 📝 Documentation update
- [ ] ✅ Tests (adding or improving test coverage)
- [ ] ♻️ Refactor (no behavior change)
- [ ] 🎯 New skill (bundled or hub)

## Changes Made

<!-- List the specific changes. Include file paths for code changes. -->

- 

## Behavior Contract

<!-- Describe the behavior change in reviewable terms. What should users, operators, or other modules observe after this PR? -->

- **Changes:** 
- **Must remain unchanged:** 

## Acceptance Criteria

<!-- Make these concrete and testable. Prefer observable outcomes over implementation details. -->

- [ ] 
- [ ] 

## Verification Evidence

<!-- Replace the placeholders with the exact commands, evals, or artifacts you used. -->

| Claim | Command / Eval | Result | Notes |
|------|----------------|--------|-------|
| | | | |

## AI-First Review Risks

<!-- Reviewers should focus here before style issues. Use N/A only when truly not applicable. -->

- **Behavior regressions:** 
- **Security assumptions:** 
- **Data integrity risks:** 
- **Failure handling / degraded mode:** 
- **Rollout / rollback safety:** 

## Interface Boundaries Touched

<!-- Check all that apply. -->

- [ ] None
- [ ] Tool schema / registry contract
- [ ] Slash command / CLI surface
- [ ] Gateway / TUI event contract
- [ ] Prompt assembly / caching
- [ ] Memory / session storage
- [ ] Benchmark / eval harness

## Checklist

<!-- Complete these before requesting review. -->

### Code

- [ ] I've read the [Contributing Guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md)
- [ ] My commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`fix(scope):`, `feat(scope):`, etc.)
- [ ] I searched for [existing PRs](https://github.com/NousResearch/hermes-agent/pulls) to make sure this isn't a duplicate
- [ ] My PR contains **only** changes related to this fix/feature (no unrelated commits)
- [ ] I've run `scripts/run_tests.sh` or a narrower command that I documented above — or this PR is docs/process-only and I documented why no code-path verification was needed
- [ ] I've added or updated regression coverage for changed behavior (required for bug fixes, strongly encouraged for features)
- [ ] I've added explicit edge-case assertions and focused integration checks when this PR crosses a module boundary — or N/A
- [ ] I've tested on my platform: <!-- e.g. Ubuntu 24.04, macOS 15.2, Windows 11 -->

### Documentation & Housekeeping

<!-- Check all that apply. It's OK to check "N/A" if a category doesn't apply to your change. -->

- [ ] I've updated relevant documentation (README, `docs/`, docstrings) — or N/A
- [ ] I've updated `cli-config.yaml.example` if I added/changed config keys — or N/A
- [ ] I've updated `CONTRIBUTING.md` or `AGENTS.md` if I changed architecture or workflows — or N/A
- [ ] I've considered cross-platform impact (Windows, macOS) per the [compatibility guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md#cross-platform-compatibility) — or N/A
- [ ] I've updated tool descriptions/schemas if I changed tool behavior — or N/A

## For New Skills

<!-- Only fill this out if you're adding a skill. Delete this section otherwise. -->

- [ ] This skill is **broadly useful** to most users (if bundled) — see [Contributing Guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md#should-the-skill-be-bundled)
- [ ] SKILL.md follows the [standard format](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md#skillmd-format) (frontmatter, trigger conditions, steps, pitfalls)
- [ ] No external dependencies that aren't already available (prefer stdlib, curl, existing Hermes tools)
- [ ] I've tested the skill end-to-end: `hermes --toolsets skills -q "Use the X skill to do Y"`

## Screenshots / Logs

<!-- If applicable, add screenshots or log output showing the fix/feature in action. -->

