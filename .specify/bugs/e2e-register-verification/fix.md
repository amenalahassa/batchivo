# Bug Fix: e2e registerAndLogin broken by business name + email verification

- **Slug**: e2e-register-verification
- **Fixed**: 2026-11-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Option A (chosen by the user): a test-only backend hook returns the pending verification token,
and `registerAndLogin` now walks the real signup → `/verify-email` → `/dashboard` flow, filling the
business name, then picks 3D printing through setup step 2. The same flag switches off the API
rate limiter for a local e2e run. Both are off by default, refused in production, and the hook is
hidden from the API docs. `/verify-email` now spends its single-use token once under StrictMode.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/app/config.py` | modified | `e2e_test_hooks_enabled: bool = False` (env `E2E_TEST_HOOKS_ENABLED`) |
| `backend/app/api/v1/onboarding.py` | modified | `require_e2e_test_hooks` gate + `GET /onboarding/test/verification-token` (`include_in_schema=False`) |
| `backend/app/services/onboarding_service.py` | modified | `get_pending_verification_token(email)` (valid tokens only) |
| `backend/app/schemas/onboarding.py` | modified | `E2EVerificationTokenResponse` |
| `backend/app/core/rate_limit.py` | modified | `rate_limiting_enabled(settings)`: on unless the flag is set outside production |
| `backend/app/main.py` | modified | `limiter.enabled = rate_limiting_enabled(settings)` at startup |
| `backend/tests/api/test_onboarding_e2e_hooks.py` | added | 14 tests (hook + limiter gate) |
| `backend/tests/integration/test_rls_pricing.py` | modified | published-paths check skips routes with `include_in_schema=False` (they stay in the scoping population) |
| `frontend/src/pages/VerifyEmail.tsx` | modified | `useRef` guard: verify the token once per mount (StrictMode ran it twice → 500 on the second call) |
| `frontend/src/pages/VerifyEmail.test.tsx` | added | regression test under StrictMode |
| `frontend/e2e/helpers.ts` | modified | fills `#businessName`, waits on the register response (429 → backoff kept as fallback), reads token, opens `/verify-email`, sets business type via `PUT /onboarding/wizard/step/2`, then `/dashboard` |
| `frontend/e2e/README.md` | modified | how to start the local backend with the flag; what the flag does |

## Diff Highlights

```python
def require_e2e_test_hooks(settings: Settings = Depends(get_settings)) -> None:
    if not settings.e2e_test_hooks_enabled or settings.is_production:
        raise HTTPException(status_code=404, detail="Not Found")
```

## Tests Added or Updated

- `test_setting_is_off_by_default` — flag defaults to False.
- `test_hook_returns_404_by_default` — inert with default settings even with a pending token.
- `test_hook_refused_in_production_even_when_enabled` — production never exposes it.
- `test_hook_returns_pending_token_when_enabled` — returns the token (case-insensitive email).
- `test_hook_returns_404_for_unknown_email`, `test_hook_returns_404_for_used_token`, `test_hook_requires_email` (422).
- `test_hook_not_in_openapi_schema` — never listed in API docs.
- `test_rate_limiting_on_by_default`, `test_rate_limiting_on_in_test_and_dev_without_the_flag`, `test_rate_limiting_stays_on_in_production_even_with_the_flag`, `test_rate_limiting_off_for_a_local_e2e_run`, `test_app_limiter_is_enforcing_by_default`.
- `VerifyEmail.test.tsx` — one verify call under StrictMode (fails without the guard: "called 2 times"); no call without a token.
- `test_flag_absent_from_deployment_config` — `E2E_TEST_HOOKS_ENABLED` absent from `infrastructure/`, `docker-compose*.yml`, `deploy.sh`.

## Local Verification

- `ruff check` → pass; `ruff format --check` on changed files → pass (48 pre-existing unformatted test files elsewhere, untouched).
- Targeted pytest on 5433 (`test_onboarding_e2e_hooks.py`, `integration/test_onboarding.py`, `test_onboarding_wizard.py`, `test_onboarding_step5.py`) → 50 passed.
- Full backend suite on 5433 → 2997 passed, 1 failed (`test_every_derived_path_is_one_the_app_publishes`, caused by the hidden route; fixed), 68 skipped. After the fix and the limiter gate: `test_onboarding_e2e_hooks.py` + `test_rls_pricing.py` → 531 passed, 53 skipped.
- Running backend with the flag: 7 registrations in a row from one IP → all 201.
- Frontend `npm run lint`, `npm run typecheck`, `npm run test:run` (1393 passed, VerifyEmail tests included); `tsc --strict` on `e2e/helpers.ts` → pass.
- Full backend suite and e2e journeys: see `e2e.md` and the session report.

## Deviations from Assessment

- `.claude/launch.json` not changed: it is the shared dev launcher; enabling the hook there would turn it on for every dev backend. The flag is documented in `frontend/e2e/README.md` instead.
- Scope grew past the assessment, each step agreed with the orchestrator: the craft-type step (new signups are `generic`, so 3D-print screens showed "Module Not Available"), the StrictMode guard in `VerifyEmail.tsx`, and the rate-limiter gate (option A of a second design question).
- No VPS instance config exists in the repo at 31d7463, so the config guard test scans `infrastructure/`, `docker-compose*.yml` and `deploy.sh`.

## Follow-ups

- `POST /verify-email` answers 500 rather than 400 when a token was already used concurrently; the frontend guard removes the trigger, the backend error mapping could be tightened separately.
