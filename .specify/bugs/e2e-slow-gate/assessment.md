# Bug Assessment: the e2e gate takes 20–35 minutes

- **Slug**: e2e-slow-gate
- **Created**: 2026-11-24
- **Source**: pasted text (orchestrator brief)
- **Verdict**: valid
- **Severity**: medium (no user impact; it blocks every merge gate for 20–35 min on a 16 GB machine)

## Report (summarized)

`npm run test:e2e -- --project=chromium` and `--project=pricing` (from `frontend/`) take
~20–35 min. `playwright.config.ts` runs one worker, `fullyParallel: false`, one local retry.
Most specs call `registerAndLogin` in `beforeEach`, which walks the whole signup in the
browser for every test. Asked: reuse accounts, set data up through the API, run chromium on
3 workers, keep pricing serial, keep coverage identical.

## Symptom

Each chromium test pays for a full browser signup before doing its own work, and the tests run
one at a time.

## Reproduction

1. Start a stack with `E2E_TEST_HOOKS_ENABLED=true`, seed the e2e tenant.
2. `cd frontend; npx playwright test --project=chromium --project=pricing`.
3. Wall time ~20–35 min for ~240 tests.

## Suspected Code Paths

- `frontend/playwright.config.ts` — `workers: 1`, `fullyParallel: false`; the comment says
  "to prevent registration rate limiting", but `E2E_TEST_HOOKS_ENABLED` already switches the
  limiter off (`backend/app/core/rate_limit.py:rate_limiting_enabled`), so the reason is gone.
- `frontend/e2e/helpers.ts:registerAndLogin()` — per test: load `/signup` (a full SPA load from
  the Vite dev server), fill and submit the form, wait for "Check your email", read the token
  through the e2e hook, load `/verify-email?token=…` (second SPA load), poll storage, set the
  business type (wizard step 2), load `/dashboard` (third SPA load). The test then does its own
  `goto`. 3 extra cold page loads per test is most of the cost.
- 21 chromium spec files call it in `beforeEach` (about 190 tests).

## Root Cause Hypothesis

High confidence. The time goes to (a) the three browser page loads of the UI signup in every
test, and (b) running everything on one worker. The backend work behind a signup (two bcrypt
hashes, tenant creation) is small next to the page loads.

## Proposed Remediation

**Preferred**:

1. A fixture module `e2e/fixtures.ts` exporting `test`/`expect`. It overrides Playwright's
   `storageState` with the session of a ready account, created **through the API** (the same real
   endpoints the signup page calls: `POST /onboarding/register`, the e2e token hook,
   `POST /onboarding/verify-email`, `PUT /onboarding/wizard/step/2`), so the page opens already
   signed in. No signup page loads.
2. An option `account: 'fresh' | 'shared'`:
   - `'fresh'` (default): a new tenant per test, as today. The audit below shows most files
     depend on a brand-new tenant (empty states, "only category", row counts, module-level
     constant SKUs such as `WGT-A-001`, `DRAGON-001`, `Date.now()` taken once per file), so this
     keeps their isolation exactly as it is.
   - `'shared'`: one tenant per worker and spec file, reused by every test of that file in that
     worker (registered once, cached). For files whose tests only read or create uniquely named
     data: `tests/dashboard/dashboard-workflow.spec.ts`, `tests/settings/settings-workflow.spec.ts`.
3. Keep the real browser signup where it is the journey under test: `tests/auth/*` keep
   `registerAndLogin` / `createTestUser` unchanged.
4. `playwright.config.ts`: `workers: 3` overall (env override `PLAYWRIGHT_WORKERS`), the
   chromium project `fullyParallel: true`. Playwright 1.59 (installed) has a per-project
   `workers` limit: `pricing-setup` and `pricing` get `workers: 1` and `fullyParallel: false`,
   so the pricing journeys run one at a time, in file order, exactly as today, while chromium
   uses the other workers.
5. `ideas.spec.ts` signs in to the seeded owner through the login page per test; that tenant is
   shared with pricing, its data is uniquely titled, leave it.

**Alternatives**:
- One shared tenant for everything per worker (what the brief first suggested): would need every
  spec rewritten to stop assuming a new tenant (empty states, counts, constant SKUs); a larger
  change to assertions, against "same assertions". Rejected for the files listed above; adopted
  only where it is a no-op.
- A setup project that pre-registers a pool: equivalent to the worker cache but needs the pool
  size to match workers; the fixture is simpler.

**Files likely to change**:
- `frontend/e2e/fixtures.ts` (new), `frontend/e2e/helpers.ts`
- `frontend/playwright.config.ts`
- the 19 non-auth chromium spec files that call `registerAndLogin` in `beforeEach`
- `frontend/e2e/README.md`

**Tests to add or update**: none new; the suite itself is the test. Same test count, same
assertions, same 6 fixme skips. Before/after wall time recorded in `e2e.md`.

## Risks & Considerations

- Pricing journeys share one seeded tenant and change it; they must never overlap each other:
  covered by the project's `workers: 1`.
- `ideas.spec.ts` (chromium) signs in to the pricing tenant; running alongside pricing could
  overlap. Its data is uniquely named and it reads nothing pricing writes.
- Memory: 3 chromium workers + a Vite dev server + backend on a 16 GB machine.
- Session expiry: the stored `expiresAt` must stay ahead of the run so the app never refreshes
  (refresh rotation could invalidate a shared session). Access tokens live 24 h.
- `/logout` is client-side only (`POST /auth/logout` revokes nothing), so a test that signs out
  does not break a shared session.

## Open Questions

- None blocking.
