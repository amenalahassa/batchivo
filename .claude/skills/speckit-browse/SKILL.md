---
name: "speckit-browse"
description: "Have the agent itself drive a browser to manually explore, test, or reproduce a feature or a bug in the local Batchivo app — the one command that authorizes the agent to click around in the running app on request."
argument-hint: "A feature slug (specs/<slug>), a bug slug (.specify/bugs/<slug>), or free text describing what to check/reproduce"
compatibility: "Requires the built-in browser tool and the local dev servers (.claude/launch.json: backend on 8000, frontend on 5173)"
metadata:
  author: "batchivo"
  source: "custom — not part of upstream spec-kit"
user-invocable: true
disable-model-invocation: false
---

This is the one command where the agent is explicitly allowed to take the browser's wheel
itself. Manual, click-by-click browser testing is otherwise left to the user unless they ask
first — **invoking this command is that ask**. Once called, proceed with the browser
exploration below without re-confirming permission for it. Every other safety rule still
applies as normal (no real credentials, no destructive or paid actions, consent popups
declined by default, etc.).

## User Input

```text
$ARGUMENTS
```

Accept any of:

- A **feature slug** matching `specs/<slug>/` — read `spec.md` (and `quickstart.md` if
  present) for the acceptance criteria / manual steps to exercise.
- A **bug slug** matching `.specify/bugs/<slug>/` — read `assessment.md`'s reproduction
  steps (and `fix.md` if present, to know the expected outcome should now be "does not
  reproduce" rather than "reproduces").
- **Free text** describing what to check (e.g. "the packaging page lists the default boxes")
  — treat it directly as the thing to verify, no file lookup.
- **Nothing** — ask what to check (interactive mode), or stop and ask for a target
  (automated mode). Never invent a target.

## Resolution

1. If the input matches a `.specify/bugs/<slug>` directory → **BUG mode**.
2. Else if it matches `specs/<slug>` (disambiguate from a short list if ambiguous) →
   **FEATURE mode**.
3. Else → **FREEFORM mode**: the input itself is the instructions.

State which mode was used before proceeding.

## Prerequisites

- Load the `anthropic-skills:built-in-browser` skill first if it has not been loaded yet
  this session.
- Use the **built-in browser** (`mcp__Claude_Browser__*` / `preview_start`), never Claude in
  Chrome / the user's real Chrome — this is the user's own dev app, not a signed-in external
  site, and the built-in browser's isolated tabs are the right tool for it.
- The local stack must be reachable:
  - Postgres and Redis: `docker compose up -d postgres redis` (the dev containers
    `batchivo-postgres`, `batchivo-redis`). If migrations are pending, `/deploy-dev` brings the
    dev database up to date (it backs it up first).
  - Backend: check `http://localhost:8000/health`; if down, `preview_start` with the `backend`
    entry of `.claude/launch.json` (uvicorn `--reload` on 8000).
  - Frontend: check `http://localhost:5173`; if down, `preview_start` with the `frontend` entry
    (Vite on 5173), and wait for it to be ready.
  - Alternative: the user's `.\dev.ps1` runs all of these in one console — do not start it
    yourself on top of servers that are already running.
- Test data only: the local dev database, accounts registered on `localhost` in this session
  with a throwaway `@example.com` address, or the seeded e2e tenant (`backend/scripts/seed_e2e.py`,
  credentials in `frontend/e2e/config.ts`) when it exists in the database you are pointed at.
  Never www.batchivo.com / api.batchivo.com, a staging host, the shop
  (test.mystmereforge.co.uk) or a customer VPS; never a real Square payment or a real email
  sent through Resend — this stays inside the same "testing the user's own application"
  exception that governs test credentials elsewhere.

## Execution

1. **Plan the walkthrough** as a short ordered list of concrete actions:
   - FEATURE mode: turn the spec's acceptance criteria / quickstart steps into check items.
   - BUG mode: turn the assessment's reproduction steps into check items; if `fix.md`
     exists, the expected result on each step flips from "bug happens" to "bug does not
     happen".
   - FREEFORM mode: turn the free text into the shortest list of actions that answers it.
2. **Drive the browser.** Prefer `read_page` / `get_page_text` over screenshots for reading
   content and structure; use `computer` / `form_input` to act; take a `computer screenshot`
   at points worth showing in the report. Check `read_console_messages` /
   `read_network_requests` for errors along the way (failed `/api/v1/...` calls, 401/403 from
   tenant scoping, 422 validation errors), per the built-in-browser skill's verification
   workflow.
3. **Judge each step** `pass` / `fail` / `inconclusive` — same discipline as
   `/speckit-bug-test`: never claim a step passed if it was not actually exercised, and
   never claim a reproduction happened if the server/page never actually loaded.
4. **If something is broken and the fix is a small, obvious source change** squarely within
   what brought you here, you may fix it and re-check — but say explicitly that you did, and
   do not expand scope beyond that. The fix still needs its test (constitution II) and the
   project's gates before any commit. A non-trivial fix gets reported, not improvised.
5. **Report:**
   - **FEATURE mode**: reply in chat with the steps checked, pass/fail per step, and any
     issue found. This command does not replace `specs/<slug>/quickstart.md` — it is one
     run against it.
   - **BUG mode**: write `.specify/bugs/<slug>/browse.md`, mirroring the per-bug report
     convention (`assessment.md` / `fix.md` / `test.md` / `e2e.md`), using the same
     `verified` / `partial` / `failed` / `not-run` vocabulary as `/speckit-bug-test`,
     and also reply with a short summary in chat.
   - **FREEFORM mode**: reply in chat only.

## Guardrails

- Runs only because it was explicitly invoked. Never take the browser's wheel on your own
  initiative outside this command — if you are tempted to "just go check" mid-task, stop
  and ask first instead.
- Stays inside the "testing the user's own application" exception at all times: localhost
  only, test credentials/seed data only, never production/staging/VPS, never a real purchase.
- Does not create automated coverage. If the same check would make a good Playwright spec,
  say so in the report (e.g. "worth adding `frontend/e2e/tests/<area>/<slug>.spec.ts`") — but
  writing one is a separate, explicit task; use `/speckit-e2e` or `/speckit-bug-e2e` to run
  existing specs instead of writing new ones from inside this command.
- Leave running servers as you found them: stop only what this command started, and only if
  the user wants it stopped.
- Every other platform safety rule still applies while driving the browser (no prohibited
  actions, no entering real credentials, consent/cookie popups declined by default, etc.).
