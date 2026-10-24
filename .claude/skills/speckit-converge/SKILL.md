---
name: "speckit-converge"
description: "Assess the current codebase against the feature's spec, plan, and tasks, then append any remaining unbuilt work as new tasks to tasks.md so implement can complete it."
compatibility: "Requires spec-kit project structure with .specify/ directory"
metadata:
  author: "github-spec-kit"
  source: "templates/commands/converge.md"
user-invocable: true
disable-model-invocation: false
---


## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Pre-Execution Checks

**Check for extension hooks (before convergence)**:

- Check if `.specify/extensions.yml` exists in the project root.
- If it exists, read it and look for entries under the `hooks.before_converge` key
- If the YAML cannot be parsed or is invalid, do not skip silently: tell the user that `.specify/extensions.yml` could not be read (include the parser error) and that no hooks were checked, including any mandatory (`optional: false`) hooks registered there, then continue normally
- Filter out hooks where `enabled` is explicitly `false`. Treat hooks without an `enabled` field as enabled by default.
- For each remaining hook, do **not** attempt to interpret or evaluate hook `condition` expressions:
  - If the hook has no `condition` field, or it is null/empty, treat the hook as executable
  - If the hook defines a non-empty `condition`, skip the hook and leave condition evaluation to the HookExecutor implementation
- When constructing command invocations from hook command names, replace dots (`.`) with hyphens (`-`). For example, `speckit.git.commit` → `/speckit-git-commit`.
- For each executable hook, output the following based on its `optional` flag:
  - **Optional hook** (`optional: true`):

    ```text
    ## Extension Hooks

    **Optional Pre-Hook**: {extension}
    Command: `/{command}`
    Description: {description}

    Prompt: {prompt}
    To execute: `/{command}`
    ```

  - **Mandatory hook** (`optional: false`):

    ```text
    ## Extension Hooks

    **Automatic Pre-Hook**: {extension}
    Executing: `/{command}`
    EXECUTE_COMMAND: {command}

    Wait for the result of the hook command before proceeding to the Goal.
    ```
    After emitting the block above you MUST actually invoke the hook and wait for it to finish before continuing. Run it the same way you would run the command yourself in this agent/session (the invocation may differ from the literal `{command}` id shown above, e.g. a skills-mode agent runs it as `/skill:speckit-...` or `$speckit-...`). Emitting the block alone does not run the hook.

- If no hooks are registered or `.specify/extensions.yml` does not exist, skip silently

## Goal

Close the gap between what a feature's specification, plan, and tasks call for and what the
codebase currently implements. Read `spec.md`, `plan.md`, and `tasks.md` as the **sole
source of intent** (with the constitution as governing constraints), assess the current
state of the code, determine which requirements, acceptance criteria, plan decisions, and
existing tasks are unmet, incomplete, or only partially satisfied, and **append each piece
of remaining work as a new, traceable task** at the bottom of `tasks.md` so that
`/speckit-implement` can complete it. This command MUST run only after
`/speckit-implement` has run on the current `tasks.md`, and after `/speckit-tasks` has produced a complete `tasks.md`.

This is **not** a diff tool and does **not** track changes. It assesses the present state
of the code relative to the feature's artifacts — no git, no branch comparison, no history.

## Operating Constraints

**APPEND-ONLY, NEVER REWRITE**: The command's **only** write is appending a new
`## Phase N: Convergence` section to `tasks.md`. It MUST NOT:

- modify `spec.md` or `plan.md` in any way;
- rewrite, renumber, reorder, or delete any existing task (including tasks from a prior
  Convergence phase);
- modify, create, or delete any application code — completing the appended tasks is the
  job of `/speckit-implement`.

When the codebase already satisfies everything, the command MUST leave `tasks.md`
**byte-for-byte unchanged** (no empty Convergence header) and report a clean result.

**COMPLETE IN ONE ROUND, NEVER DEFER**: A round's output is the *whole* remaining work, not
the part this round happened to reach. Every round MUST:

- walk **every** item in the intent inventory individually against code — every FR, every
  buildable SC, every acceptance scenario, every edge case, every contract endpoint, every
  research decision and every data-model constraint (Step 4c). A requirement covered only by
  a pattern sweep has not been walked;
- run **every** pattern sweep to completion over the whole repository. A sweep too broad for
  one command is split into several commands, never sampled;
- run every check the project's CI runs (Step 4d), and treat a failing one as a finding;
- turn every gap it sees into a task, including one that looks "pre-existing", "out of this
  round's focus" or "already known". Nothing observed is left to "the next round".

A summary that names areas "left for later", "sampled", "remaining" or "to start from next
time" is a failed round, not a partial success: go back and finish them before appending.
The only legitimate reason to stop short is a hard blocker the user must resolve (a missing
credential, an artifact that cannot be read), and that is reported as a blocker, not as
deferred work.

**Constitution Authority**: The project constitution (`.specify/memory/constitution.md`) is
**non-negotiable**. Code that violates a MUST principle is the highest-severity finding and
produces a corresponding remediation task. If the constitution is an unfilled template,
skip constitution checks gracefully rather than failing.

## Execution Steps

### 1. Initialize Convergence Context

Run `.specify/scripts/powershell/check-prerequisites.ps1 -Json -RequireSpec -RequireTasks -IncludeTasks` once from repo root and parse JSON for FEATURE_DIR and AVAILABLE_DOCS. Derive absolute paths:

- SPEC = FEATURE_DIR/spec.md
- PLAN = FEATURE_DIR/plan.md
- TASKS = FEATURE_DIR/tasks.md
- CONSTITUTION = `.specify/memory/constitution.md` (if present)
If `spec.md`, `plan.md`, or `tasks.md` is missing, STOP with a clear, actionable message naming the
prerequisite command to run (`/speckit-specify` for a missing spec, `/speckit-plan` for a missing plan,
`/speckit-tasks` for missing tasks). Do not produce partial output.
For single quotes in args like "I'm Groot", use escape syntax: e.g 'I'\''m Groot' (or double-quote if possible: "I'm Groot").

### 2. Load Artifacts

Load the minimum from each artifact that still lets you *falsify* a claim. Progressive
disclosure governs how much of a file you read, never whether you open it: an artifact
left unopened is an artifact whose claims you are accepting on trust, and this command
exists to stop doing that.

**From spec.md:**

- Functional Requirements (FR-###)
- Success Criteria (SC-###) — include only items requiring buildable work; exclude
  post-launch outcome metrics and business KPIs
- User Stories and their Acceptance Scenarios
- Edge Cases (if present)

**From plan.md:**

- Architecture/stack choices and technical decisions
- Data Model references
- Phases and named touch-points (files/components the plan says will be created or edited)
- Technical constraints

**From tasks.md:**

- Task IDs (to compute the next ID and next phase number)
- Descriptions, phase grouping, and referenced file paths

**From constitution (if not an unfilled template):**

- Principle names and MUST/SHOULD normative statements

**From every other doc `AVAILABLE_DOCS` reports — `data-model.md`, `contracts/`,
`research.md`, `quickstart.md` — when it exists.** These are not background reading; they
are the artifacts that state design decisions in *checkable* form, which `plan.md` only
summarises. Each one listed and not opened MUST be named as such in the Step 6 summary.

- `data-model.md`: every declared table, its columns and constraints, its tenant scoping
  and RLS policy, and any table documented as a deliberate exception to a constitution
  principle. Verify each against the models and the migrations — a declared RLS policy or
  a documented exception is a claim with a right answer, and a model that silently
  contradicts a recorded decision is a `contradicts` finding against the plan.
- `contracts/`: every declared endpoint, with its method, path, auth tier and error codes.
  Check each against the routers. Compare on path *structure*, normalising parameter names
  and honouring optional-segment notation such as `[/{id}]`, so a notation artefact is not
  reported as a missing route.
- `research.md`: the numbered design decisions. Each is a constraint the code must still
  satisfy, and a decision reversed in the code without the document changing is a finding.
- `quickstart.md`: the per-tier validation steps. Where one is mechanically checkable, run
  it rather than inferring the outcome.

### 3. Build the Intent Inventory

Create an internal model (do not echo raw artifacts):

- **Requirements inventory**: one stable key per FR-### / SC-### / user-story acceptance
  scenario (e.g. `US1/AC2`), plus the plan decisions and constitution principles that
  impose buildable obligations.
- **Code-scope map**: from the file paths named in `plan.md` and `tasks.md`, plus a keyword
  search for the concepts each requirement describes, derive the set of source files and
  components in scope for assessment.

  **Derive it from the repository, not from the plan's file tree.** `plan.md` lists the
  files somebody expected to touch when the plan was written; the feature's figures reach
  further. Take every concept a requirement names — the figure, the table, the record, the
  policy lever — and enumerate *every* file that reads or writes it, with a search over the
  whole repository. A surface that handles a figure in scope is in scope whether or not the
  plan predicted it: exports, dashboards, queues, admin screens and CSV writers all touch
  money and are rarely in anybody's tree.

  The map bounds which **requirements** are traced to which code. It does **not** bound
  where a constitution MUST principle may be found, and it does not license skipping a file
  because the plan failed to mention it. If a file holding a figure in scope is absent from
  the plan, note that too — the plan's tree being incomplete is itself worth one line in
  the summary.

### 4. Assess the Codebase and Classify Findings

Include every existing task in the intent inventory, regardless of checkbox state or
Convergence phase: completion claims are not evidence. Verify current behavior against
the spec, plan, tasks, and constitution; for corrective task chains, assess the resulting
behavior, not superseded implementation details. Check both unmet obligations and
implementation that contradicts, exceeds, or falls outside the stated intent.

For each item in the intent inventory, inspect the current code in scope and produce a
`Finding` only where there is a gap. Classify every finding by **gap type**:

- **`missing`**: the required work is absent from the code entirely.
- **`partial`**: the work exists but does not yet fully satisfy the requirement /
  acceptance criterion / plan decision.
- **`contradicts`**: the code does something that conflicts with stated intent or a
  constitution MUST principle.
- **`unrequested`**: the code contains work not called for by the spec, plan, or tasks
  (surfaced for awareness — converge does **not** delete code, it only appends a task to
  review/justify or remove it).

Each `Finding` records: a stable id, the `source-ref` it traces to, the `gap-type`, a
severity, and a short human-readable description with the evidence (the file/area observed).

#### 4a. Generalise every finding into a pattern, then sweep for it

A finding is rarely unique. Code is written by copying a neighbour, so a defect on one
surface almost always has twins on the surfaces that were written beside it — and the
twin is usually on the surface the *previous* convergence round did not happen to open.
A round that fixes one copy and reports `tasks_appended` leaves the rest, and the next
round rediscovers them as "new".

So for each finding, before moving on:

1. State the defect as a **mechanical pattern** — not "this route is on `get_db`" but
   "a route that writes a tenant-scoped figure on a session without RLS".
2. **Sweep the whole repository for that pattern**, not the file the finding came from and
   not only the paths in the code-scope map. The map bounds which *requirements* are in
   scope; it does not bound where a constitution violation may be found, because a MUST
   principle applies everywhere.
3. Treat each additional hit as its own finding, and **rule hits out explicitly**. A hit on
   a path where the pattern is legitimate — money as a `float` in a Prometheus counter or
   an OpenTelemetry span attribute, a grams or percentage field whose name merely looks
   monetary — is a decision to record in the summary, not a silent omission.
4. Complete every sweep. If one is too broad for a single command, split it by directory or
   by pattern and run all the parts. A sampled sweep is not an acceptable outcome.

**Run the sweep as one command over the repository, before reading any file.** A sweep
performed by following findings one surface at a time is not a sweep; it reaches exactly
the files the previous round's findings pointed at, which is how a pattern survives six
rounds. One `grep -rn` over `app/`, `src/` and the equivalents costs a single call and
returns the whole population at once — including the routers, services and components
nobody has opened yet. Do that first, then read.

Patterns worth sweeping on any feature that touches money, tenancy or persisted history,
each of which has produced a CRITICAL finding on a surface an earlier round had missed:

- every path that constructs the record a requirement says must be snapshotted, against
  the set of paths that actually write the snapshot;
- every route that reads or writes a figure in scope, against the RLS session dependency;
- every arithmetic or conversion step on a monetary value, in **both** the backend and the
  frontend — including integer division such as pence `/ 100`, which yields a binary float
  in Python and in JavaScript alike;
- every figure the engine already owns, against the places that recompute it.

#### 4a-i. Never trust a guardrail test that is a curated list

A test that enumerates the surfaces it checks — a `ROUTES` list parametrised over, an
allow-list of permitted exceptions, a dict of expected counts — guards the entries somebody
remembered to add and nothing else. It passes because the list is short, not because the
code is clean, and a new surface is covered by *absence*. Worse, it reads like a sweep in
the summary: "142 routes asserted to use the tenant session" sounds exhaustive and means
"142 routes are on a list".

So for every guardrail test that defends a requirement in scope:

1. Open it and decide whether its population is **enumerated by hand** or **derived from
   the application** (`app.routes`, a module walk, a glob over the source tree).
2. Where it is enumerated, **diff the list against the real population yourself** — all
   routes the app mounts, all modules in the package, all components in the directory. Every
   item in the real population and not in the list is a candidate finding, not a pass.
3. Treat the test's own self-checks with suspicion. `test_the_list_is_not_empty` and
   `test_every_entry_names_its_task` verify the list's internal consistency, never its
   coverage. A list-coverage test must compare against the application.
4. Where a guard is enumerated and could be derived, that is a finding in its own right —
   the guard will go on passing as the code grows past it.

The same applies to an allow-list of excused violations. An entry excused by name was a
deliberate deferral once; it is also a hole that no longer fails. Check every entry still
has a live reason, and report any that are simply unfinished work — pinned is not fixed.

#### 4a-ii. Walk every requirement that enumerates a list, item by item

Where a requirement names a set — the policy levers that need a role, the bases a fee may
be charged on, the roles and what each may edit, the fee categories, the order states — the
set is a checklist with a right answer per item, and a sweep for a *pattern* will not find
the one item nobody implemented. Patterns find a defect repeated across surfaces; lists find
a surface that was never built.

So for each such requirement, write the set out and name the code that owns each element.
An element with no owner is a finding. This is how a lever like "discount policy" sits in a
requirement's list of ten for six rounds while nine of its siblings are guarded: every round
checked the mechanism on the surfaces it already knew, and none laid the list beside the
routers.

Give the **permission and role dimension** its own pass, because it has no arithmetic to
leave a trace: enumerate every write endpoint that touches a figure or a lever in scope and
record the role guard on each. A missing guard looks exactly like a correct one in a diff,
and no test fails for its absence unless somebody wrote that test.

#### 4b. Inspect in-scope code that has no test before code that has one

Prioritise by where defects actually are, which is not where the requirements are hardest.
A module carrying a test that asserts its **own completeness** — a set equality against the
enum of cases, a cross-check that a second expression of a calculation equals the first —
is close to self-defending, and inspecting it tends to confirm rather than find. A file
with no test at all has nothing defending it and no reason for anyone to have looked.

So enumerate the in-scope source files with no corresponding test file, ordered by size,
and inspect those first. Count a file as tested when a sibling's test exercises it; check
before reporting an absent test file as an absent test. Where the plan names a surface as
created or updated and it has no test, that is a finding against the constitution's
testing principle in its own right, independent of whether its behaviour is correct.

**A test file is not coverage. Grep the test for the behaviour, not the module.** The
presence of `tests/.../test_<module>.py` says somebody tested *something* in that module,
which is routinely its two pure string helpers while every figure it writes goes unasserted.
A 674-line service with a 60-line test file of helper assertions ranks as "tested" under a
file-counting heuristic and is as undefended as one with no test at all — and it will not
appear in the untested list, so nothing brings you back to it.

So for each in-scope module, grep its test file for the **names of the things the
requirements care about** — the figure, the column, the field, the state — and treat a test
file that never mentions them as an absent test for that behaviour. Rank by the ratio of
test size to module size as well as by absence: a large module with a small test is the
same signal as a large module with none, and it hides better.

#### 4c. Walk every item in the inventory, every round

Sweeps find a defect repeated across surfaces; they never show that a requirement was
built. So every round walks the whole inventory one item at a time — not a share of it,
and not only the items earlier rounds did not reach:

1. **Map first.** Grep the tests and the source for each item's id (`FR-031d`, `US3/AC5`)
   and for the concepts it names. Items with no test citation, or whose tests never mention
   the figure the item is about, are walked first — they are where unbuilt work hides.
2. **Walk each item** to the code that owns it and the test that asserts it, and record a
   verdict: `holds` (name the owning code and the asserting test), or a finding. A verdict
   resting on a test means the test was opened and asserts the behaviour, not that a test
   file exists.
3. **Check reachability, not just existence.** A service function no route calls, a route
   no client calls, and a hook no component calls are `missing` for any requirement that
   says the operator can see or do the thing. Grep for the callers of every function an
   item depends on.
4. **Walk every edge case and acceptance scenario** as its own item, with the same verdicts.
   An edge case is usually a branch nobody wrote.
5. **Walk every write path for a figure in scope**, not only the one the plan names: each
   must honour the same rules (role, provenance, observed-is-read-only, effective dating,
   exact money). A rule enforced on one route and absent from its siblings is a finding per
   sibling.
6. **Walk every external entry point** that creates a record in scope — imports, webhooks,
   bridges, storefront, scripts — against the same rules as the console path.

The Step 6 count of items verified individually MUST equal the size of the inventory.

#### 4d. Run the project's CI gates

Read the CI configuration (`.woodpecker/`, `.github/workflows/`, and so on) and run every
check it runs for the code in scope — lint, format, type checking, unit tests, build. A
gate that fails is a CRITICAL finding, because nothing reaches production through a red
pipeline, whatever the cause and whoever introduced it. "The errors were already there"
is not a reason to leave them out.

**Edge cases:**

- **Little or no code yet**: treat the entire specified scope as `missing` remaining work
  rather than failing.
- **Nothing remains**: produce zero findings and follow the converged branch in Step 7.

### 5. Assign Severity

- **CRITICAL**: violates a constitution MUST principle, or a `missing`/`contradicts` gap
  that blocks baseline functionality of a P1 user story.
- **HIGH**: a `missing` or `partial` gap on a core functional requirement or acceptance
  criterion.
- **MEDIUM**: a `partial` gap on a secondary requirement, or an `unrequested` addition with
  unclear justification.
- **LOW**: minor partial gaps, polish, or low-risk `unrequested` additions.

### 6. Present the In-Session Findings Summary

Before appending anything, output a compact, severity-graded summary (no file writes yet):

## Convergence Findings

| ID | Gap Type | Severity | Source | Evidence | Remaining Work |
|----|----------|----------|--------|----------|----------------|
| F1 | missing  | HIGH     | FR-008 | Example: no append-only guard detected in path/to/module.py when writing tasks.md | Add append-only enforcement |

**Summary metrics:**

- Inventory size, and items verified individually (Step 4c) — the two numbers MUST match;
  if they do not, the round is not finished
- Plan decisions checked
- Artifacts loaded — every `AVAILABLE_DOCS` entry MUST be opened
- Pattern sweeps run (Step 4a), each complete
- CI gates run (Step 4d), each with its result
- Enumerated requirements walked item by item (Step 4a-ii), each with its unowned elements
- Guardrail tests examined (Step 4a-i), split into **derived from the application** and
  **enumerated by hand**, the latter with the diff against the real population stated
- Constitution principles checked (or "skipped — template")
- Findings by gap type (missing / partial / contradicts / unrequested)
- Findings by severity

For each finding, say **why it was not found before**, in a clause: a surface outside the
plan's file tree, a pattern swept only within known paths, a dimension never swept, a
guardrail whose list did not cover it, a behaviour its module's test never mentions, or —
honestly, where it applies — *not missed at all*: a figure that only became a contradiction
because an earlier round built the authority it now disagrees with, or one found earlier and
deliberately deferred. Rounds get cheaper only if each one says which blind spot it is
closing, and a finding created by the previous round's own work is not evidence of a blind
spot. Do not let the count of findings stand in for that distinction.

**Report these honestly; a number here is a claim about work done.** "103 requirements
checked" means 103 were walked one by one against code. Never inflate the count. If the
walk is not complete, the answer is to finish it in this round, not to report a smaller
number and move on.

Alongside the findings, list what was **checked and ruled out**: a sweep hit that is
legitimate, a component whose test lives in a sibling file, a skip guarded by a genuine
environment gate. A reader cannot tell a question you answered from one you never asked
unless you say.

### 7. Append Convergence Tasks (or report converged)

**If there are one or more actionable findings** (`tasks_appended` outcome):

Append to the **end** of `tasks.md`, per the append contract:

1. Scan all existing task IDs; let `M` be the maximum. Determine the next phase number `N`
   (highest existing phase + 1).
2. Write a single new section header `## Phase N: Convergence`.
3. Emit one checklist item per actionable finding, ordered CRITICAL/HIGH first, assigning
   zero-padded IDs `T{M+1:03d}, T{M+2:03d}, …`:

   ```markdown
   - [ ] T042 <imperative description> per <source-ref> (<gap-type>)
   ```

   `<source-ref>` traces the task to its origin: e.g. `FR-003`, `SC-002`,
   `US1/AC2`, `plan: storage decision`, `Constitution II`.

   `<gap-type>` is one of `missing`, `partial`, `contradicts`, `unrequested`.

   Constitution-violation tasks MUST be emitted first and described as
   `CRITICAL`.
4. Never reuse or renumber existing IDs. If a prior Convergence phase exists, add a new,
   separately-numbered one below it — do not touch the old one.

**If there are no actionable findings** (`converged` outcome):

- Do **not** modify `tasks.md` at all — no empty phase header.
- Report: **"✅ Converged — the implementation satisfies the spec, plan, and tasks."**
- Include the summary counts of what was checked.

### 8. Provide Next Actions (Handoff)

- On `tasks_appended`: state how many tasks were appended under which phase, and recommend
  running `/speckit-implement` to complete them. The appended list is the whole remaining
  work as of this round; the handoff names no "remaining", "sampled" or "next time" areas,
  because the round does not end while any exist.
- The only thing a follow-up converge run should find is what the implement pass itself
  introduced. Say so, and recommend running converge once more after implement to check
  exactly that.
- A check may wait for the fixes only if it *depends* on them — for example, verifying a
  fix's own behaviour. Every other check runs in this round.
- On `converged`: recommend proceeding to review / opening a PR. No further implement pass
  is needed for this feature's specified scope.

### 9. Check for extension hooks

After producing the result, check if `.specify/extensions.yml` exists in the project root.

- If it exists, read it and look for entries under the `hooks.after_converge` key
- If the YAML cannot be parsed or is invalid, do not skip silently: tell the user that `.specify/extensions.yml` could not be read (include the parser error) and that no hooks were checked, including any mandatory (`optional: false`) hooks registered there, then continue normally
- Filter out hooks where `enabled` is explicitly `false`. Treat hooks without an `enabled` field as enabled by default.
- For each remaining hook, do **not** attempt to interpret or evaluate hook `condition` expressions:
  - If the hook has no `condition` field, or it is null/empty, treat the hook as executable
  - If the hook defines a non-empty `condition`, skip the hook and leave condition evaluation to the HookExecutor implementation
- Report the convergence outcome (`converged` or `tasks_appended`) in-session before listing
  any hooks, so users can decide whether to run optional follow-up commands.
- When constructing command invocations from hook command names, replace dots (`.`) with hyphens (`-`). For example, `speckit.git.commit` → `/speckit-git-commit`.
- For each executable hook, output the following based on its `optional` flag:
  - **Optional hook** (`optional: true`):

    ```text
    ## Extension Hooks

    **Optional Hook**: {extension}
    Command: `/{command}`
    Description: {description}

    Prompt: {prompt}
    To execute: `/{command}`
    ```

  - **Mandatory hook** (`optional: false`):

    ```text
    ## Extension Hooks

    **Automatic Hook**: {extension}
    Executing: `/{command}`
    EXECUTE_COMMAND: {command}
    ```
    After emitting the block above you MUST actually invoke the hook and wait for it to finish before continuing. Run it the same way you would run the command yourself in this agent/session (the invocation may differ from the literal `{command}` id shown above, e.g. a skills-mode agent runs it as `/skill:speckit-...` or `$speckit-...`). Emitting the block alone does not run the hook.

- If no hooks are registered or `.specify/extensions.yml` does not exist, skip silently
