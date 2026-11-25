---
name: "speckit-design"
description: "Design a feature in one go: run plan, then tasks, then analyze, fix what analyze finds in plan.md and tasks.md, and stop with a design ready for /speckit-build."
argument-hint: "Optional guidance for planning and task generation"
compatibility: "Requires spec-kit project structure with .specify/ directory and an existing spec.md"
metadata:
  author: "batchivo"
  source: "local composite of speckit-plan, speckit-tasks, speckit-analyze"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty). Pass it on as the
arguments of `/speckit-plan` and `/speckit-tasks`.

## Goal

Take a feature from `spec.md` to a checked, implementable design without stopping between
steps: `plan.md` (+ `research.md`, `data-model.md`, `contracts/`, `quickstart.md`), then
`tasks.md`, then a consistency analysis whose findings are fixed in the design artifacts.
The command ends when the design is ready for `/speckit-build`, or when only a decision the
user must make is left.

This command writes **no application code**.

## Operating Rules

- Run each step by invoking its skill (`speckit-plan`, `speckit-tasks`, `speckit-analyze`)
  with the Skill tool and follow that skill's instructions in full, including its extension
  hooks. Do not re-implement a step from memory.
- Do not stop between steps to ask whether to continue. The user asked for all of them.
  Stop only for a hard blocker (below).
- Never weaken the spec to make the analysis pass. `spec.md` is the user's intent.

## Execution Steps

### 1. Preconditions

Run `.specify/scripts/powershell/check-prerequisites.ps1 -Json -PathsOnly` from the repo
root and parse FEATURE_DIR. If `FEATURE_DIR/spec.md` does not exist, STOP and tell the
user to run `/speckit-specify` first.

If `spec.md` still contains `[NEEDS CLARIFICATION]` markers, STOP and recommend
`/speckit-clarify`: planning on an open question produces a plan that converge will later
contradict.

### 2. Plan

Invoke `speckit-plan` with the user input. When it finishes, confirm `plan.md` exists in
FEATURE_DIR and that its Constitution Check has no unresolved violation. A gate failure the
plan itself cannot justify is a hard blocker.

### 3. Tasks

Invoke `speckit-tasks` with the user input. Confirm `tasks.md` exists and every task has an
ID and a file path.

### 4. Analyze and remediate (loop, at most 3 passes)

1. Invoke `speckit-analyze`. It is read-only and ends by offering remediation; **do not wait
   for an answer to that offer** — this command already has the user's go-ahead to remediate
   the design artifacts.
2. For every CRITICAL and HIGH finding, and every MEDIUM finding that is a coverage gap
   (a requirement, success criterion or edge case with no task), apply the fix:
   - in `tasks.md`: add missing tasks, fix ordering/dependencies, correct file paths, split
     vague tasks. Keep IDs unique and sequential; renumbering is allowed here because no
     task has been implemented yet;
   - in `plan.md` / `data-model.md` / `contracts/` / `research.md`: resolve contradictions,
     terminology drift and constitution conflicts.
3. A finding whose only fix is a change to `spec.md` (a contradictory or untestable
   requirement, an ambiguity in user intent) is **not** fixed silently: record it as an
   open question for the user.
4. Re-run `speckit-analyze`. Repeat until it reports no CRITICAL or HIGH finding that can be
   fixed in plan/tasks, or 3 passes have run. If CRITICAL findings remain after 3 passes,
   report them as blockers with what was tried.

LOW and remaining MEDIUM findings are listed in the report, not fixed.

### 5. Report

Output:

```text
## Design Ready: <feature>

| Step    | Result |
|---------|--------|
| plan    | plan.md + <artifacts generated> |
| tasks   | <N> tasks in <P> phases (<K> parallel) |
| analyze | <passes> pass(es); fixed <n> (C/H/M); left <n> LOW/MEDIUM |

Coverage: <x>% of requirements have ≥1 task
Open questions for the user (spec-level): <list or "none">
Blockers: <list or "none">
```

Next action: `/speckit-build` when there are no blockers or open questions; otherwise
`/speckit-clarify` (spec questions) or the specific fix needed.

## Hard Blockers (the only reasons to stop early)

- `spec.md` missing or carrying `[NEEDS CLARIFICATION]`.
- A constitution gate violation the plan cannot justify.
- A CRITICAL analyze finding that needs a spec change, or survives 3 remediation passes.
- A mandatory extension hook that fails.
