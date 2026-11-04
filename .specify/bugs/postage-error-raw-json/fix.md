# Bug Fix: Postage save errors do not show the server's explanation

- **Slug**: postage-error-raw-json
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

The postage panel's "Not saved" alert now renders `apiErrorDetail(error)`, the API's own `detail`, instead of axios' "Request failed with status code 422". The backend overlap refusal is reworded for the operator. The same `apiErrorDetail` swap was applied to the other mutation alerts that showed `error.message`.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `frontend/src/components/settings/ShippingProfilesPanel.tsx` | modified | `apiErrorDetail(saveError)`; `onSubmit` catches the rejected `mutateAsync` so the form stays open |
| `backend/app/api/v1/shipping_profiles.py` | modified | overlap message: `"Canada colis" already covers 0 g to any weight in zone CA. Change this profile's weight range…`; `_grams`/`_upper_limit` helpers |
| 15 other components (`FilamentPurchaseForm`, `ModelCostProfileForm`, `ProvenanceFieldsPanel`, `PrinterCostPolicyForm`, `PricingPolicySettings`, `FeeRuleEditor`, `FeePreviewPanel`, `AddConsumableDialog`, `AddPurchaseDialog`, `DeleteSpoolDialog`, `UpdateWeightDialog`, `OrderParcelDialog`, `PrinterFormDialog`, `PlateActionsDialog`, `PlateFormDialog`) | modified | mutation alerts render `apiErrorDetail(...)` |
| `frontend/src/components/settings/ShippingProfilesPanel.test.tsx` | added test | |
| `backend/tests/api/test_shipping_profiles.py` | added test | |

## Tests Added or Updated

- `ShippingProfilesPanel.test.tsx::shows the server's reason when postage is not saved` — fails without the fix (verified by stashing the panel).
- `test_shipping_profiles.py::TestValidation::test_the_overlap_refusal_is_worded_for_the_operator` — exact wording.

## Local Verification

- `npx vitest run src/components/settings/ShippingProfilesPanel.test.tsx` → 11 passed; with the panel stashed → 1 failed.
- `poetry run pytest tests/api/test_shipping_profiles.py` → 44 passed (+1 new).

## Deviations from Assessment

- Scope expanded (one line): `onSubmit` let the rejected `mutateAsync` escape as an unhandled promise rejection; it is now caught and the form stays open with the alert.
- The open question "panel only or sweep?" was answered by doing the sweep: `apiErrorDetail` falls back to `error.message`, so every swapped alert shows the same or more.
- The axios-interceptor alternative was not used.

## Follow-ups

- Remaining `error.message` renders not tied to a mutation alert (e.g. `ErrorBoundary`, `TeamSettings` invite, `DeleteConsumableDialog`, `DeletePrinterDialog`, `ProductWizard`) could get the same treatment.
