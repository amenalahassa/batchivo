# Bug Fix: A deleted model stays in the model list

- **Slug**: model-soft-delete-listed
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Kept the soft delete (archive). The model list now asks for active models by default (`is_active=true`), "Clear filters" returns to that default, and the model pickers (plates, product models, product wizard) no longer offer archived models. The delete confirmation explains that the model is archived and how to see it again.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `frontend/src/components/models/ModelList.tsx` | modified | `isActive` starts `true`; clear → `true`; "filters active" badge relative to that default |
| `frontend/src/components/models/ModelDetail.tsx` | modified | confirmation text explains archiving |
| `frontend/src/components/production-runs/PlateFormDialog.tsx` | modified | `is_active: true` |
| `frontend/src/components/products/ProductModelsEditor.tsx` | modified | `is_active: true` |
| `frontend/src/components/products/ProductWizard/WizardModelSelection.tsx` | modified | `is_active: true` |
| `frontend/src/components/models/ModelList.test.tsx` | added test | |

## Tests Added or Updated

- `ModelList.test.tsx::asks for active models by default, so an archived (deleted) one is not listed` — fails without the fix (verified by stashing `ModelList.tsx`).
- `ModelList.test.tsx::still reaches archived models through the Inactive filter`.

## Local Verification

- `npx vitest run src/components/models` → 6 files, 45 tests passed.
- With `ModelList.tsx` stashed → 1 of the 2 new tests fails (regression proven).

## Deviations from Assessment

- The backend default of `list_models` was not changed (preferred remediation is frontend-only; avoids an API behaviour change).
- `ModelForm.tsx:146` still lists all models: it only harvests existing sources/machines for autocomplete, not a picker.
- The dialog title/button still say "Delete" (the user's word for it); only the description changed. No "Restore" action added.

## Follow-ups

- A "Restore" action on an inactive model's detail page.
- Decide whether an unreferenced model should be hard-deleted.
