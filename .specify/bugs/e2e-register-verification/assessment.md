# Bug Assessment: e2e registerAndLogin broken by business name + email verification

- **Slug**: e2e-register-verification
- **Created**: 2026-11-24
- **Source**: pasted text (orchestrator session brief)
- **Verdict**: valid
- **Severity**: high

## Report (summarized)

`registerAndLogin` (`frontend/e2e/helpers.ts:35`) no longer works, so every e2e that creates its
throwaway user fails with "Registration failed after 3 retries". Two causes: the signup page now
requires "Business Name *" (`#businessName`), and signup now requires email verification — the account
only exists once the emailed link is opened, and locally the token only appears in the backend log.

## Symptom

Observed: the helper fills email/password only; client-side validation blocks on the empty business
name, and even with it, registration ends on "Check your email" instead of `/dashboard`, so the helper
times out. Expected: the helper creates a disposable, logged-in user on `/dashboard` against a local
backend.

## Reproduction

1. Start backend on 8000 and Vite on 5173.
2. Run any spec that calls `registerAndLogin`, e.g. `npx playwright test e2e/tests/models --project=chromium`.
3. Helper submits `/signup` without a business name → "Business name is required" (no URL change) → timeout → throws.
4. With a business name filled: `POST /api/v1/onboarding/register` → 201 → "Check your email"; still no `/dashboard`.

## Suspected Code Paths

- `frontend/e2e/helpers.ts:35` `registerAndLogin` — never fills `#businessName`; waits for `/dashboard`, which the new flow never reaches.
- `frontend/src/pages/Signup.tsx:158` — business name required; `:202` "Check your email" state after register.
- `backend/app/services/onboarding_service.py:75` `register_tenant` — stores registration data in an `EmailVerificationToken`; tenant/user only created in `verify_email` (`:145`).
- `backend/app/services/onboarding_service.py:395` — with no email provider configured, token is only logged.
- `frontend/src/pages/VerifyEmail.tsx:45` — `/verify-email?token=` calls verify, stores JWTs, redirects to `/onboarding` (no forced wizard redirect elsewhere, so `/dashboard` is reachable afterwards).

## Root Cause Hypothesis

High confidence. The signup flow moved to tenant onboarding (business name + email verification,
`/api/v1/onboarding/*`) and the e2e helper was never updated. The helper has no way to obtain the
verification token: no email sink locally and no test hook.

## Proposed Remediation

**Preferred (needs orchestrator sign-off)**: a test-only endpoint that returns the pending
verification token for an email, e.g. `GET /api/v1/onboarding/test/verification-token?email=…`,
gated by a new setting `e2e_test_hooks_enabled: bool = False` (env `E2E_TEST_HOOKS_ENABLED`) and
additionally refused when `environment == "production"`. When off, the route answers 404 (as if it
did not exist). The helper then: fills business name + email + password, submits, waits for "Check your
email", fetches the token from the API, opens `/verify-email?token=…` (the real verification path, so
the real `verify_email` runs), then goes to `/dashboard`.

**Alternatives**:
- Setting that auto-verifies on register in e2e mode (register returns tokens / creates tenant directly) — fewer moving parts in the helper, but changes the semantics of the production `register` code path and skips the real verify flow.
- Helper reads the token straight from PostgreSQL (`email_verification_tokens`) with a `pg` client — zero backend change, but adds a DB dependency + DB URL to the frontend e2e, couples e2e to schema.
- Capture outgoing mail (file/mailpit sink) and parse the link — most realistic, heaviest infra.

**Files likely to change**:
- `backend/app/config.py` (new setting)
- `backend/app/api/v1/onboarding.py` (test-only route)
- `backend/tests/api/test_onboarding_test_hooks.py` (new)
- `frontend/e2e/helpers.ts`
- `.claude/launch.json` / e2e README (enable the flag for the local e2e backend)

**Tests to add or update**:
- Backend: route returns 404 with default settings; 404 when flag on but `environment=production`; returns the pending token when enabled; 404 for unknown email.
- E2E: a couple of `registerAndLogin` journeys (`e2e/tests/models/`, `e2e/tests/products/`).

## Risks & Considerations

- Security: the endpoint leaks verification tokens — must be off by default and impossible in production; covered by tests.
- Rate limit `5/minute` on register still applies; the existing retry/backoff stays.
- Ports/DB are shared with parallel sessions; run e2e only with the orchestrator's go-ahead.

## Open Questions

- [NEEDS CLARIFICATION: design choice — test endpoint vs auto-verify vs DB read vs mail capture] → asked to orchestrator.
