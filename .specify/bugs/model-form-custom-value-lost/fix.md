# Bug Fix: A designer typed in ModelForm is lost on blur (same for source and machine)

- **Slug**: model-form-custom-value-lost
- **Fixed**: 2026-11-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Offer the typed value as a `SelectItem` while "+ Add new" is open (and the current value whenever it is not in the list, e.g. an inactive designer on edit), so the option already exists when blur sets the field.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `frontend/src/components/models/ModelForm.tsx` | modified | `withCurrentValue()` adds the typed/current value to each of the three option lists |
| `frontend/src/components/models/ModelForm.test.tsx` | added tests | three cases (`it.each`) |
| `frontend/e2e/tests/models/model-fields.spec.ts` | modified | fixme removed |

## Tests Added or Updated

- `ModelForm.test.tsx` > values typed with "+ Add new" > keeps a new {Designer,Source,Machine} after blur and saves it (failed before the fix)
- `model-fields.spec.ts` > should save a new designer typed in the form

## Local Verification

- New backend tests run against a throwaway PostgreSQL 16 (port 5467); new vitest files run on their own; all pass.
- e2e: `npx playwright test --project=chromium --retries=0 -g "should save a new designer typed in the form"` against a throwaway stack (backend 8033, Vite 5193) -> pass (see e2e.md).

## Deviations from Assessment

First attempt added the item only once the field held the typed value; the vitest still failed (the option registered after Radix's change event). The item is now offered from the typed text before blur.

## Follow-ups

None.
