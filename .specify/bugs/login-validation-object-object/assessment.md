# Bug Assessment: Login page shows "[object Object]" for a validation error

- **Slug**: login-validation-object-object
- **Created**: 2026-10-25
- **Source**: side finding from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 22 round (seen while building the e2e journeys)
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

> A 422 from the login endpoint (an email on a reserved domain) renders as "[object Object]".

## Symptom

When `/api/v1/auth/login` returns 422, FastAPI's `detail` is an array of error objects. The login
form shows "[object Object]" instead of a readable message. Expected: the field's message, or a
generic "Check your email and password".

## Reproduction

1. Open `/login`.
2. Sign in with an address on a reserved TLD such as `someone@example.test`.
3. Observe "[object Object]" under the form.

## Suspected Code Paths

- `frontend/src/lib/auth.ts:94` — `throw new Error(error.detail || 'Login failed')`; the same at `:71` for registration.
- `frontend/src/pages/Login.tsx:41-42` — renders `err.message`.

## Root Cause Hypothesis

`detail` is passed straight into `Error`, which stringifies an array of objects.

## Proposed Remediation

Add a small `detailMessage(detail)` helper in `lib/auth.ts` that returns a string detail as is and
joins `msg` fields for an array, used by both login and registration. Test both shapes in
`auth.test.ts`.

## Risks & Considerations

None; display only.

## Open Questions

None.
