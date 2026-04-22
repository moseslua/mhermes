---
name: writing-plans
description: Use when you have a spec or requirements for a multi-step task. Creates comprehensive implementation plans with bite-sized tasks, exact file paths, and complete code examples.
version: 1.1.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
metadata:
  hermes:
    tags: [planning, design, implementation, workflow, documentation]
    related_skills: [subagent-driven-development, test-driven-development, requesting-code-review]
---

# Writing Implementation Plans

## Overview

Write comprehensive implementation plans assuming the implementer has little context for the codebase and needs explicit verification guidance. Document what they need to touch, why the change is scoped the way it is, which interfaces must remain stable, how to verify the change, and which risks matter. Give them bite-sized tasks. DRY. YAGNI. TDD. Evidence first.

Assume the implementer is a skilled developer but may not understand the repo's hidden invariants, interface boundaries, or the right level of test rigor without help.

**Core principle:** A good plan makes implementation and verification obvious. If someone has to guess about scope, contracts, or proof, the plan is incomplete.

## When to Use

**Always use before:**
- Implementing multi-step features
- Breaking down complex requirements
- Delegating to subagents via subagent-driven-development

**Don't skip when:**
- Feature seems simple (assumptions cause bugs)
- You plan to implement it yourself (future you needs guidance)
- Working alone (documentation matters)

## Bite-Sized Task Granularity

Each task should be small enough to verify independently and large enough to matter. Aim for one coherent change slice per task, not a fixed time budget.

Every task should answer one question clearly: what gets added, changed, or verified in this step?

**Too big:**
```markdown
### Task 1: Build authentication system
[50 lines of code across 5 files]
```

**Right size:**
```markdown
### Task 1: Add the failing regression test for empty passwords
[1 file, 1 behavior]

### Task 2: Update the auth validator to reject empty and null passwords
[1-2 files, same contract]

### Task 3: Add boundary tests for the CLI/auth integration path
[1-2 files, integration proof]
```

Prefer grouping work by behavior boundary, not by arbitrary minute counts or commit cadence.
## Plan Document Structure

### Header (Required)

Every plan MUST start with:

```markdown
# [Feature Name] Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

### Contract block (Required for non-trivial code changes)

Every substantial plan should include a dedicated contract/evidence block near the top:

```markdown
## Contract and Evidence
- In scope:
- Out of scope:
- Stable interfaces touched:
- Acceptance criteria:
- Deterministic tests:
- Edge cases / degraded mode:
- Data integrity assumptions:
- Rollout / rollback:
- Eval tier: none | targeted tests | focused integration checks | repo-specific benchmark/eval, if any
```

This is more important than including large code dumps. Prefer exact file paths, verification steps, and risk notes over speculative implementation detail.

### Task Structure

Each task follows this format:

````markdown
### Task N: [Descriptive Name]

**Objective:** What this task accomplishes (one sentence)

**Files:**
- Create: `exact/path/to/new_file.ext`
- Modify: `exact/path/to/existing.ext:Lx-Ly`
- Verify: `tests/or/checks/that/prove/this`

**Acceptance criteria:**
- Observable outcome 1
- Observable outcome 2

**Step 1: Add or update the verification first**

Describe the deterministic test, assertion, or check that should fail before the change.

**Step 2: Make the minimal implementation change**

Describe the smallest code/config/doc change that satisfies the contract.

**Step 3: Re-run verification**

Run: `<project test command or verification step>`
Expected: PASS / expected output / expected observable behavior

**Step 4: Note boundary or rollback concerns**

Call out compatibility, degraded-mode behavior, or rollback notes when relevant.
````

## Writing Process

### Step 1: Understand Requirements

Read and understand:
- Feature requirements
- Design documents or user description
- Acceptance criteria
- Constraints

### Step 2: Explore the Codebase

Use Hermes tools to understand the project:

```text
# Understand project structure
search_files("*", target="files", path="src/")

# Look at similar features
search_files("similar_pattern", path="src/")

# Check existing tests or verification surfaces
search_files("test_", target="files", path="tests/")

# Read key files
read_file("path/to/key/file")
```

### Step 3: Design Approach

Decide:
- Architecture pattern
- File organization
- Dependencies needed
- Testing strategy

### Step 4: Write Tasks

Create tasks in order:
1. Setup/infrastructure
2. Core functionality (TDD for each)
3. Edge cases
4. Integration
5. Cleanup/documentation

### Step 5: Add Complete Details

For each task, include:
- **Exact file paths** (not "the config file" but `src/config/settings.py`)
- **Acceptance criteria** that a reviewer can check
- **Exact commands** with expected output when verification is straightforward
- **Deterministic tests and integration checks** that prove the changed behavior
- **Edge cases / degraded-mode expectations** when the task crosses a boundary or touches error handling
- **Interface or compatibility notes** when old callers or external consumers might break

### Step 6: Review the Plan

Check:
- [ ] Tasks are sequential and logical
- [ ] File paths are exact
- [ ] Acceptance criteria are testable
- [ ] Verification steps prove the claimed behavior
- [ ] Edge cases and degraded modes are called out where relevant
- [ ] Stable interfaces / compatibility boundaries are named
- [ ] No missing context
- [ ] DRY, YAGNI, TDD principles applied

### Step 7: Save the Plan

Use the workspace plan path that matches the request:

```bash
# Default working plan artifact
mkdir -p .hermes/plans

# Shared repo documentation only when the plan itself is meant to land in version control
mkdir -p docs/plans
```

Prefer `.hermes/plans/` for normal execution handoffs. Use `docs/plans/` only when the user explicitly wants the plan committed as project documentation.

## Principles

### DRY (Don't Repeat Yourself)

**Bad:** Copy-paste validation in 3 places
**Good:** Extract validation function, use everywhere

### YAGNI (You Aren't Gonna Need It)

**Bad:** Add "flexibility" for future requirements
**Good:** Implement only what's needed now

```python
# Bad — YAGNI violation
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
        self.preferences = {}  # Not needed yet!
        self.metadata = {}     # Not needed yet!

# Good — YAGNI
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
```

### TDD (Test-Driven Development)

Every task that produces code should include the full TDD cycle:
1. Write failing test
2. Run to verify failure
3. Write minimal code
4. Run to verify pass

See `test-driven-development` skill for details.

### Commit Strategy

Commit at natural reviewable boundaries when the plan is intended for execution. Do not force a commit after every tiny step if it would create noise or split one behavior change across multiple commits.

Use commit guidance to improve reversibility, not to satisfy a rigid cadence.

## Common Mistakes

### Vague Tasks

**Bad:** "Add authentication"
**Good:** "Create User model with email and password_hash fields"

### Missing Contract Detail

**Bad:** "Step 1: Add validation"
**Good:** "Step 1: Add validation for empty and malformed inputs in `src/auth/validator.ext`, and verify it fails before the implementation change"

### Missing Verification

**Bad:** "Step 3: Test it works"
**Good:** "Step 3: Run the project's canonical test or verification command and record the expected passing outcome"

### Missing File Paths

**Bad:** "Create the model file"
**Good:** "Create: `src/models/user.py`"

## Execution Handoff

After saving the plan, offer the execution approach:

**"Plan complete and saved. Ready to execute using subagent-driven-development — I'll dispatch a fresh subagent per task with two-stage review (spec compliance then code quality). Shall I proceed?"**

When executing, use the `subagent-driven-development` skill:
- Fresh `delegate_task` per task with full context
- Spec compliance review after each task
- Code quality review after spec passes
- Proceed only when both reviews approve

## Remember

```
Behavior-scoped tasks
Exact file paths
Acceptance criteria
Deterministic verification
Edge cases and degraded-mode expectations
Interface / compatibility notes
DRY, YAGNI, TDD
```

**A good plan makes implementation obvious.**
