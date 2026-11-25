---
name: speckit-bug-e2e
description: Run the Playwright e2e suite (frontend/e2e) against a bug's reproduction scenario and record the result
compatibility: Requires spec-kit project structure with .specify/ directory and the Playwright scaffold (frontend/playwright.config.ts, frontend/e2e/)
metadata:
  author: batchivo
  source: "custom — extends the bug extension locally, not shipped by upstream spec-kit (not in .specify/extensions/bug/extension.yml's original upstream payload; a future `specify extension update bug` will not know about this file)"
user-invocable: true
disable-model-invocation: false
---

# Run E2E Tests for a Bug

Run the scripted Playwright suite (`frontend/e2e/`) to check whether the bug described by
`/speckit-bug-assess` reproduces, and whether the fix from `/speckit-bug-fix` holds — using
automated browser tests only, never a manual browse. The output is
`.specify/bugs/<slug>/e2e.md`. For the agent to drive a browser itself instead, use
`/speckit-browse`.

## User Input

```text
$ARGUMENTS
```

Same accepted forms as `/speckit-bug-test`: `slug=<bug-slug>`, `--slug <bug-slug>`, a bare
slug-like token, a path containing the slug, or nothing.

## Slug Resolution

Same resolution order as `/speckit-bug-test`:

1. Explicit user input.
2. Conversation context (slug from a just-run `/speckit-bug-assess` / `/speckit-bug-fix` /
   `/speckit-bug-test` in this session).
3. Single candidate on disk — list `.specify/bugs/*/assessment.md`. If exactly one bug
   directory exists, use it.
4. Disambiguate (ask interactively, or stop with a list in automated mode).

Once resolved, set `BUG_SLUG` and `BUG_DIR = .specify/bugs/<BUG_SLUG>`, and state which
resolution path was used.

## Prerequisites

- `BUG_DIR/assessment.md` MUST exist.
- `BUG_DIR/fix.md` is not required: running this before a fix exists is a legitimate way
  to prove the bug reproduces (pre-fix), not just that a fix holds (post-fix) — note which
  case applies in the report.
- The Playwright scaffold (`frontend/playwright.config.ts`, `frontend/e2e/`) must exist. If
  missing, stop and say so — do not scaffold it from inside a bug command.
- Servers, as `/speckit-e2e` describes them: the backend must already listen on
  `http://localhost:8000` (`.claude/launch.json` → `backend`, or `.\dev.ps1`); Playwright
  starts or reuses Vite on `http://localhost:5173`, and on Windows the frontend must be started
  first (`.claude/launch.json` → `frontend`) because the config's `VITE_API_URL=… npm run dev`
  does not run under `cmd.exe`. Specs under `e2e/pricing/` also need the tenant from
  `backend/scripts/seed_e2e.py`. Never set `PLAYWRIGHT_BASE_URL` / `PLAYWRIGHT_API_URL` to a
  non-local host.
- If `BUG_DIR/e2e.md` already exists, ask the user whether to overwrite it (interactive
  mode) or refuse (automated mode).

## Execution

1. **Find existing coverage.** Look for an e2e spec already written for this bug under
   `frontend/e2e/` (fuzzy match on the slug's words, on the bug title from `assessment.md`, or
   on the screen/route it names, e.g. `e2e/tests/<area>/`). This command never writes new spec
   files itself.
2. **No matching spec found (expected for most bugs today):**
   - By default, record the result as `not-run` with the reason "no dedicated e2e spec
     for this bug", and stop there. Do not run the full unrelated suite and claim it says
     anything about this bug.
   - Only run the full suite (`npm run test:e2e -- --reporter=list` from `frontend/`) if
     `$ARGUMENTS` explicitly asks for it (e.g. `full`, `all`) — and even then, report it as a
     regression check, not as reproduction evidence for this specific bug.
3. **Matching spec found:** run it from `frontend/` with
   `npm run test:e2e -- <matched-file> --project=chromium --reporter=list`
   (`--project=pricing` for a file under `e2e/pricing/`). `--reporter=list` keeps the
   configured `html` reporter from blocking on failure. Capture exit status, passed / failed /
   skipped counts and, on failure, a short excerpt of the first failing assertion (not the
   full trace). A spec that **skipped** (backend unreachable) proves nothing: treat it as
   `not-run` and say why.
4. **Judge the outcome:**
   - **verified** — the matching spec passes and the context is post-fix (fix.md exists).
   - **reproduced** — the matching spec fails and the context is pre-fix (fix.md does not
     exist yet) — this confirms the bug, it is not itself a failure of this command.
   - **failed** — the matching spec fails and the context is post-fix (fix.md exists) —
     the fix did not hold.
   - **not-run** — no matching spec exists, it skipped, or browsers/scaffold/servers are missing.
5. **Write the report** to `BUG_DIR/e2e.md`:

   ```markdown
   # Bug E2E Run: <short title>

   - **Slug**: <BUG_SLUG>
   - **Run**: <ISO 8601 date>
   - **Assessment**: ./assessment.md
   - **Fix**: ./fix.md (if present)
   - **Result**: verified | reproduced | failed | not-run

   ## Summary

   <One or two sentences.>

   ## Checks Performed

   | Spec file | Command | Result | Notes |
   |-----------|---------|--------|-------|
   | <path or "none"> | `<command>` | pass / fail / skipped / not-run | <short note> |

   ## Output Excerpt

   <Short snippet — failing assertion or final summary line. No full logs.>

   ## Recommendation

   <One paragraph, e.g. "No dedicated e2e coverage exists for this bug — consider adding
   frontend/e2e/tests/<area>/<slug>.spec.ts" or "Fix confirmed by
   frontend/e2e/tests/<area>/<slug>.spec.ts; close the bug.">
   ```

6. **Report back** with the slug, the `e2e.md` path, and the result. If `not-run`, suggest
   either writing a spec for this bug or using `/speckit-browse` to reproduce it manually
   in the meantime.

## Guardrails

- CLI only. This command never takes over the browser to click around manually — point to
  `/speckit-browse` for that.
- Never writes or edits e2e spec files, and never modifies source code.
- Never overwrite an existing `e2e.md` without confirmation.
- Never mark `verified` when no spec exists for this bug, or when it skipped — that is
  `not-run`, not a free pass borrowed from an unrelated passing suite.
