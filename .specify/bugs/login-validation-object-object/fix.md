# Bug Fix: Login page shows "[object Object]" for a validation error

- **Slug**: login-validation-object-object
- **Fixed**: 2026-10-25
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

`apiError.ts` now exports `detailText(detail)`, the one reader of FastAPI's three `detail` shapes.
`apiErrorDetail`, `login`, `register` and `lib/api/models.ts` all use it, replacing three copies.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `frontend/src/lib/apiError.ts` | modified | `detailText` extracted; `apiErrorDetail` delegates to it |
| `frontend/src/lib/auth.ts` | modified | `detailText(error.detail) ?? 'Login failed'` (and the same for registration) |
| `frontend/src/lib/api/models.ts` | modified | `extractErrorMessage` delegates to `detailText` |
| `frontend/src/lib/apiError.test.ts` | added test | string, list, `{message}`, and empty shapes |
| `frontend/src/lib/auth.test.ts` | updated test | a 422 list reads as its message; an empty detail falls back |

## Tests Added or Updated

- `apiError.test.ts::detailText`: 4 cases.
- `auth.test.ts::login`: "reads a validation error list instead of showing [object Object]" and
  "falls back to a plain message when the detail says nothing".

## Local Verification

- `vitest run src/lib/apiError.test.ts src/lib/auth.test.ts src/lib/api`: 77 passed.
- Full CI-equivalent run: see `../FIX-RUN.md`.

## Deviations from Assessment

- None. One small behaviour change in `lib/api/models.ts`: a structured `{message}` detail now
  shows its message instead of the generic fallback.

## Follow-ups

- None.
