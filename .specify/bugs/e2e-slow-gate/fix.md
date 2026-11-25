# Bug Fix: the e2e gate takes 20–35 minutes

- **Slug**: e2e-slow-gate
- **Fixed**: 2026-11-24
- **Assessment**: ./assessment.md
- **Status**: applied (verified: 238/238, 9.7 min at 3 workers, see ./e2e.md)

## Summary

Chromium specs no longer sign up through the browser before every test: a fixture makes the
owner account through the API and opens the page already signed in. Chromium runs on 3
workers in parallel; the pricing projects keep one worker of their own.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `frontend/e2e/fixtures.ts` | added | `test`/`expect` with `account: 'fresh' \| 'shared'`; `createAccountViaApi()` (register → token hook → verify-email → setup step 2); overrides `storageState` with the session (expiry 20 h ahead so the app never refreshes) |
| `frontend/e2e/helpers.ts` | modified | `E2EAccount`, `rememberAccount()`; `getAccessToken()` falls back to the context's account before the page opens the app; `openDashboard()` |
| `frontend/playwright.config.ts` | modified | `fullyParallel: true`, `workers: PLAYWRIGHT_WORKERS \|\| 3`; `pricing-setup`/`pricing`: `fullyParallel: false`, `workers: 1` |
| 19 chromium spec files | modified | import `test`/`expect` from fixtures; `registerAndLogin(page)` removed where the next step opens a page, else `openDashboard(page)` (where the old helper left the page) |
| `tests/dashboard/dashboard-workflow.spec.ts`, `tests/settings/settings-workflow.spec.ts` | modified | `test.use({ account: 'shared' })` |
| `frontend/e2e/README.md` | modified | fixtures, workers |

Untouched: `tests/auth/*` (UI signup/login are the journeys under test), `tests/ideas/ideas.spec.ts`
(seeded owner), `pricing/*`.

## Tests Added or Updated

None added. Same 238 tests listed; no `test(`, `test.fixme`, `test.skip` or `expect(` line
changed (`git diff -U0 e2e | grep` on those patterns is empty).

## Local Verification

- `npx tsc --noEmit --strict … e2e/**/*.ts playwright.config.ts` → clean
- `npx eslint e2e playwright.config.ts` → clean
- `npx playwright test --list --project=chromium --project=pricing` → 238 tests in 33 files
- Full e2e (chromium + pricing, 3 workers, own stack): 238 passed, 1 of them flaky (ECONNRESET,
  passed on retry), 9.7 min — see ./e2e.md.

## Baseline ("before", from the orchestrator's merge gates, 1 worker, fresh seed, same machine)

| Commit | Run | Result | Wall time |
|--------|-----|--------|-----------|
| main 134d821 | chromium + pricing | 230 passed / 6 skipped | 27.3 min |
| main a32b6e0 | chromium + pricing | 231 passed / 6 skipped | 20.3 min |
| app-bugs merge (pre-main) | pricing alone | 20 passed | 1.5 min |
| app-bugs merge (pre-main) | chromium alone | 218 passed | 21.3 min |

## Deviations from Assessment

None.

## Follow-ups

- More files could opt into `account: 'shared'` once their names are made unique per test
  (module-level `Date.now()` constants, fixed SKUs such as `WGT-A-001`, `DRAGON-001`) and their
  empty-state checks are kept on a fresh tenant.
