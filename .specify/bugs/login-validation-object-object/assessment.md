# Bug Assessment: Login page shows "[object Object]" for a validation error

- **Slug**: login-validation-object-object
- **Created**: 2026-10-25
- **Re-assessed**: 2026-10-25 (against `7a2776e`)
- **Source**: side finding from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 22 round (seen while building the e2e journeys)
- **Verdict**: valid (still open)
- **Severity**: low

## Report (verbatim or summarized)

> A 422 from the login endpoint (an email on a reserved domain) renders as "[object Object]".

## Re-assessment changes

- The code is unchanged: `frontend/src/lib/auth.ts:71` (register) and `:94` (login) still
  `throw new Error(error.detail || '...')`.
- **Reuse, do not add.** `frontend/src/lib/apiError.ts` already has `apiErrorDetail`, which turns
  all three FastAPI `detail` shapes (string, `{message}`, list of `{msg}`) into text. It only
  accepts axios errors, and `auth.ts` uses `fetch`. The earlier proposal of a new helper in
  `auth.ts` would have been a second copy. `lib/api/models.ts:44` already has a third.

## Symptom

When `/api/v1/auth/login` returns 422 (`EmailStr` rejects a reserved TLD), FastAPI's `detail` is
an array of error objects. `new Error(array)` stringifies it, and the form shows
"[object Object]". Expected: the field's message, or "Check your email and password".

## Reproduction

1. Open `/login`.
2. Sign in with an address on a reserved TLD, such as `someone@example.test`.
3. Observe "[object Object]" under the form.

## Suspected Code Paths

- `frontend/src/lib/auth.ts:71,94`: `detail` passed straight into `Error`.
- `frontend/src/pages/Login.tsx:41`: renders `err.message`.
- `frontend/src/lib/apiError.ts:12-27`: the existing detail-to-text logic, axios-only.
- `frontend/src/lib/api/models.ts:44`: a duplicate of the same logic.

## Root Cause Hypothesis

`detail` is passed straight into `Error`, which stringifies an array of objects. Confidence: high.

## Proposed Remediation

**Preferred**: Split the body of `apiErrorDetail` into an exported `detailText(detail: unknown):
string | undefined` in `apiError.ts`. Keep `apiErrorDetail` as a thin axios wrapper over it. Use
`detailText(error.detail) || 'Login failed'` (and `'Registration failed'`) in `auth.ts`, and make
`lib/api/models.ts` call it too, so one implementation remains.

**Files likely to change**:
- `frontend/src/lib/apiError.ts`, `frontend/src/lib/auth.ts`, `frontend/src/lib/api/models.ts`
- `frontend/src/lib/apiError.test.ts`, `frontend/src/lib/auth.test.ts`

**Tests to add or update**:
- `detailText` handles a string, a `{message}` object, a list of `{msg}`, and `undefined`.
- `login` and `register` throw a readable message for a 422 list body.

## Risks & Considerations

- Display only.

## Open Questions

None.
