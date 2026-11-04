# Bug Assessment: A deleted model stays in the model list

- **Slug**: model-soft-delete-listed
- **Created**: 2026-11-03
- **Source**: pasted text (local bugcap #56; user report bugcap #41)
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

bugcap #41 (user): "Delete action/btn is not working — it ask for confirmation, then route back to the model list, but the item still in the list."

bugcap #56 (code review): delete is a soft delete; the list does not filter inactive models by default.

## Symptom

After confirming "Delete Model", the app returns to `/models` and the model is still listed (now badged "Inactive"). Expected: a deleted model no longer appears in the list or in model pickers.

## Reproduction

1. Models → open a model → Delete → confirm.
2. The app navigates to `/models`.
3. The model is still in the list, with an "Inactive" badge; it is also still offered when adding a model to a product or a plate.

## Suspected Code Paths

- `backend/app/api/v1/models.py:777-799` — `DELETE /models/{id}` sets `is_active = False` (soft delete, deliberate: products, plates and runs reference models).
- `backend/app/api/v1/models.py:204,233-234` — `list_models` filters on `is_active` only when the query parameter is given; default returns active and inactive.
- `frontend/src/components/models/ModelList.tsx:54,63-68` — `isActive` starts `undefined`, so no filter is sent; the "Active" chip (`:289-300`) is opt-in.
- `frontend/src/components/models/ModelDetail.tsx:200-210` — the dialog says "delete" ("This will set is_active to false"), so the user expects removal.
- Pickers that also show inactive models: `ModelForm.tsx:146`, `production-runs/PlateFormDialog.tsx:59`, `products/ProductModelsEditor.tsx:103`, `products/ProductWizard/WizardModelSelection.tsx:35` (only `CreateRunWizard.tsx:156` passes `is_active: true`).

## Root Cause Hypothesis

The backend implements delete as archive, but the list and the pickers default to "all", so an archived model looks undeleted. Confidence: **high**.

## Proposed Remediation

**Preferred**: keep the soft delete and make "inactive" hidden by default. In `ModelList`, initialise the status filter to active and add an explicit "Archived/Inactive" chip to see the rest; pass `is_active: true` in the four pickers. Reword the dialog to "Archive model" with a plain-language explanation (it stays on existing products and runs), and offer "Restore" on an inactive model.

**Alternatives**:
- Change the backend default of `list_models` to `is_active=True` when the parameter is omitted. One place fixes every caller, but it is an API behaviour change for anything that relied on "all" (check the shop/integrations first).
- Hard delete when the model has no references. More faithful to "delete", but needs reference checks across products, plates, runs and files.

**Files likely to change**:
- `frontend/src/components/models/ModelList.tsx`, `ModelDetail.tsx`, `ModelForm.tsx`
- `frontend/src/components/production-runs/PlateFormDialog.tsx`, `products/ProductModelsEditor.tsx`, `products/ProductWizard/WizardModelSelection.tsx`
- `frontend/src/components/models/ModelList.test.tsx` (new)
- `backend/tests/api/test_models.py` (if the backend default changes)

**Tests to add or update**:
- ModelList requests `is_active=true` by default and shows an archived model only under the archived filter.
- After a delete mutation, the list query is invalidated and the model is gone from the default view.
- Pickers do not offer an inactive model.

## Risks & Considerations

- Products that already reference an inactive model must still display it (detail views must not filter it out).
- If the backend default changes, the storefront/shop and Shopify/Etsy sync paths must be checked for reliance on inactive models.

## Open Questions

- [NEEDS CLARIFICATION: should "Delete" stay an archive (recommended, keeps history) or become a real delete when unreferenced?]
