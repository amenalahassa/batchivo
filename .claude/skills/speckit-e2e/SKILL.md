---
name: "speckit-e2e"
description: "Run the Playwright end-to-end suite (frontend/e2e — whole suite, or scoped to one feature) and report pass/fail. Executes scripted tests only — never drives a browser manually itself."
argument-hint: "Optional: a feature slug (specs/<slug>), `full`, or a path/grep pattern forwarded to `playwright test`"
compatibility: "Requires the Playwright scaffold (frontend/playwright.config.ts, frontend/e2e/) and Chromium installed (`cd frontend && npx playwright install chromium`)"
metadata:
  author: "batchivo"
  source: "custom — not part of upstream spec-kit"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

Accept any of:

- **Nothing** — ask nothing, but do **not** run the whole suite from a feature session: run the
  targeted scope below for the active feature (`.specify/feature.json` → `feature_directory`).
  The whole suite runs **once per merge** by the orchestrator (`/speckit-orchestrate` § 5), or
  when the user explicitly asks for it.
- `full` — the whole suite: `npm run test:e2e -- --reporter=list` (every project: chromium,
  firefox and webkit over `e2e/` minus `e2e/pricing/`, plus the `pricing` project).
- A feature slug matching `specs/<slug>/` — look for e2e spec files under `frontend/e2e/`
  whose name or content references that slug, its feature number or the screens/routes it
  touches; if none match, say so and offer to run the full suite instead.
- A bare path or grep-style pattern — forward it to `playwright test` as-is (see Execution).

## Prerequisites

All commands run from `frontend/`.

- `frontend/playwright.config.ts` and `frontend/e2e/` must exist. If not, stop and say the
  Playwright scaffold needs to be set up first — do not improvise a config here.
- Chromium must be installed. If the run fails with a "browser not found" / "executable
  doesn't exist" error, stop and tell the user to run `npx playwright install chromium`
  (in `frontend/`) — don't silently trigger a large download on their behalf.
- **Servers** (read from `playwright.config.ts`):
  - Base URL is `PLAYWRIGHT_BASE_URL`, default `http://localhost:5173`; the API is
    `PLAYWRIGHT_API_URL`, default `http://localhost:8000` (`e2e/config.ts`). Every default
    is local: never point either variable at www.batchivo.com, api.batchivo.com, staging or
    a customer VPS.
  - For the default base URL only, Playwright starts (or, locally, reuses) the Vite dev server
    on 5173 with `VITE_API_URL=<api url> npm run dev`. That command uses a POSIX env prefix,
    which `cmd.exe` (Playwright's shell on Windows) rejects: on Windows, start the frontend
    first (`preview_start` with the `frontend` entry of `.claude/launch.json`, or `.\dev.ps1`)
    so Playwright reuses it. A Vite already on 5173 from another worktree would be reused too —
    check which checkout it serves.
  - Playwright never starts the backend. It must be listening on 8000 (`backend` entry of
    `.claude/launch.json`, or `.\dev.ps1`, which also brings up Postgres and Redis). Most specs
    **skip themselves** when `/health` is unreachable — a skipped run is not a pass.
  - The `pricing` project (`e2e/pricing/`, with `pricing-setup` signing in first) needs the
    tenant seeded by `backend/scripts/seed_e2e.py` (`DATABASE_URL=<scratch db> poetry run python
    scripts/seed_e2e.py`) — a scratch database, not the dev one, unless the user says so. CI runs
    only this project (`.woodpecker/test-e2e.yml`) against a built frontend on port 4173.

## Execution

1. Resolve the scope from `$ARGUMENTS` per **User Input** above.
2. If scoped with zero matching spec files: do not fabricate a result. Report
   "no e2e coverage for this scope yet" and stop — optionally point at `/speckit-browse`
   for a manual check in the meantime, or note that a spec could be added for this feature
   (writing one is a separate, explicit task; this command never authors test files).
3. Otherwise run, from `frontend/`:
   - targeted: `npm run test:e2e -- <paths> --project=chromium --reporter=list`
     (`--project=pricing` for files under `e2e/pricing/`);
   - full: `npm run test:e2e -- --reporter=list`.
   Always pass `--reporter=list`: the configured `html` reporter opens a report server on
   failure and blocks the command. Targeted scope of a feature: the specs covering its screens,
   the specs of areas whose files it modified (`e2e/tests/<area>/`, `e2e/pricing/` for pricing
   work), every spec importing a modified `e2e/helpers.ts`, `e2e/config.ts` or
   `e2e/pricing/pricing-helpers.ts`, and the unstable specs it ran into. Capture exit status,
   passed / failed / **skipped** / flaky counts (retries are 1 locally, so a pass on retry shows
   as flaky), and — on failure — a short excerpt of the first failing assertion. Never paste
   full logs.
4. Report the result inline in chat: files and project run, counts, and any failure excerpts;
   say why tests were skipped (usually: backend not running). This command does not write its
   own Markdown report; when run as part of a feature's "done" check, fold the result into
   `/speckit-converge`'s own assessment, and when run for a bug, prefer `/speckit-bug-e2e`
   instead (it records `.specify/bugs/<slug>/e2e.md`).

## Guardrails

- CLI only — this command never takes over the browser to click around manually. If a
  genuine manual reproduction or exploration is needed, say so explicitly and point at
  `/speckit-browse` rather than improvising with a browser tool mid-command.
- Never writes or edits e2e spec files itself.
- Test accounts only: throwaway `@example.com` users registered by `registerAndLogin`
  (`e2e/helpers.ts`), or the seeded pricing tenant (`E2E_OWNER_EMAIL` / `E2E_VIEWER_EMAIL` /
  `E2E_PASSWORD` in `e2e/config.ts`). If a spec appears to take a real Square payment, send a
  real email through Resend, or use any non-test credential or a non-local host, stop and flag
  it instead of running it.
