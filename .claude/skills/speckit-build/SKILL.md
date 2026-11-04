---
name: "speckit-build"
description: "Build a designed feature to convergence: run implement, then converge, and keep looping implement → converge until converge reports the feature converged."
argument-hint: "Optional implementation guidance"
compatibility: "Requires spec-kit project structure with .specify/ directory, plus spec.md, plan.md and tasks.md"
metadata:
  author: "batchivo"
  source: "local composite of speckit-implement, speckit-converge"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty). Pass it on as the
arguments of every `/speckit-implement` run.

## Goal

Drive a feature from `tasks.md` to a codebase that satisfies its spec, plan and tasks:

```text
implement → converge ─┬─ converged       → done ✅
                      └─ tasks_appended  → implement → converge → …
```

The loop ends **only** on a `converged` outcome from `speckit-converge`, or on a hard
blocker. It does not end because a round count was reached, because the remaining work
looks small, or because the session has run long.

## Operating Rules

- Run each step by invoking its skill (`speckit-implement`, `speckit-converge`) with the
  Skill tool and follow that skill's instructions in full — including converge's "complete
  in one round, never defer" rules and both skills' extension hooks. Do not shortcut a
  converge round because the previous one was recent.
- Do not stop between iterations to ask whether to continue. The user asked for the loop.
- Each `speckit-implement` run after the first works only on the unchecked tasks — in
  practice the latest `## Phase N: Convergence` section. Completed `[X]` tasks are not redone.
- Every task implemented gets its tests (project rule: all code MUST have tests), and the
  project's CI gates must be green before a converge round can report `converged`:
  `cd backend && poetry run pytest && poetry run ruff check && poetry run ruff format --check`,
  `cd frontend && npm test && npm run lint && npm run typecheck`.
- **Side findings** from converge (outside the feature) never block the loop. Collect them
  across rounds; do not run `/speckit-bug-assess` for them without the user's yes.
- Do not commit or push. Committing is the user's call after the loop ends.

## Execution Steps

### 1. Preconditions

Run `.specify/scripts/powershell/check-prerequisites.ps1 -Json -RequireTasks -IncludeTasks`
from the repo root and parse FEATURE_DIR. If `spec.md`, `plan.md` or `tasks.md` is missing,
STOP and recommend `/speckit-design` (or `/speckit-specify` when the spec is missing).

### 2. Iteration loop

Set `round = 1`. Then repeat:

1. **Implement.** Invoke `speckit-implement` with the user input.
   - Its checklist gate may ask whether to proceed with unchecked checklists. Ask that once,
     on round 1 only; the answer stands for every later round.
   - A failing non-parallel task halts implement. Diagnose and fix it within this round
     (it is part of the work), then continue implement. Only a failure that needs the user
     (missing credential, external service down, a decision outside the spec) is a blocker.
2. **Converge.** Invoke `speckit-converge`.
3. **Decide.**
   - `converged` → leave the loop (step 3).
   - `tasks_appended` → record the round (tasks appended, by severity, and the finding IDs
     with their source refs), increment `round`, and go back to 1.

**Stall guard.** Before starting another round, compare the new Convergence tasks with
those of the previous two rounds. If the same finding (same source ref and gap, on the same
surface) has been appended and "implemented" in two consecutive rounds and is back a third
time, the loop is not making progress on it: stop it as a blocker and report the finding,
what each round changed, and why it did not hold. Findings that are new — introduced by the
previous implement pass — are progress, not a stall.

Print one line per round as it ends, so progress is visible:

```text
Round <n>: implemented <k> tasks · converge → <converged | +<m> tasks (C<c>/H<h>/M<m>/L<l>)>
```

### 3. Final report

```text
## Build Converged ✅  (or: ## Build Stopped — Blocker)

| Round | Tasks implemented | Converge outcome |
|-------|-------------------|------------------|
| 1     | T001–T045         | +6 tasks (Phase 8) |
| 2     | T046–T051         | converged |

CI gates: <each gate and its result in the final round>
Final converge metrics: inventory <n> / verified <n>, sweeps <n>, gates <n>
Side findings (outside the feature): <ID, severity, suggested /speckit-bug-assess slug,
  before-merge or any-time> — or "none"
Blocker (if stopped): <what, evidence, what the user must do>
```

Next actions: on `converged`, review the diff and commit/open a PR (the user's call); offer
to run `/speckit-bug-assess` for any side finding flagged *before merging*. On a blocker,
state the one thing needed to resume, then `/speckit-build` again picks up where it left off.

## Hard Blockers (the only reasons to leave the loop without converging)

- A missing artifact (`spec.md`, `plan.md`, `tasks.md`).
- A failure that needs the user: credential, unavailable service, a requirement that
  contradicts itself or the constitution and needs a spec decision.
- The stall guard firing.
- A mandatory extension hook that fails.
