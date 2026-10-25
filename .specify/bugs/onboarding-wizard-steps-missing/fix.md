# Bug Fix: Onboarding wizard calls endpoints that do not exist

- **Slug**: onboarding-wizard-steps-missing
- **Fixed**: 2026-10-25
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

The six wizard routes now exist on the onboarding router, on `TenantDB` behind `RequireAdmin`.
Each step writes through the same service as the settings screen it stands in for. A newly
verified tenant starts with the wizard open, a tenant from before the wizard counts as finished,
and the page always offers a way to the dashboard.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/app/services/onboarding_wizard.py` | added | progress in `tenant.settings["onboarding"]`; steps 1–3, finish, logo |
| `backend/app/api/v1/onboarding.py` | modified | `GET /wizard/status`, `PUT /wizard/step/{1..4}`, `POST /wizard/logo` |
| `backend/app/schemas/onboarding.py` | modified | status, step and logo schemas; step 3 validates the currency through `TenantUpdate` |
| `backend/app/services/onboarding_service.py` | modified | `verify_email` seeds `new_wizard_progress()` |
| `frontend/src/components/onboarding/Step2CraftType.tsx` | modified | sends `three_d_print`/`hand_knitting`/… (the backend values) |
| `frontend/src/components/onboarding/Step4FirstProduct.tsx` | modified | `symbolForCurrency(currency)` |
| `frontend/src/lib/api/onboarding.ts` | modified | `TenantType` from `@/types/modules`; step 3 carries `currency_symbol` |
| `frontend/src/pages/Onboarding.tsx` | modified | step 3 sends the symbol with the code; errors via `apiErrorDetail`; "Finish later" link |
| `backend/tests/api/test_onboarding_wizard.py` | added test | 17 tests |
| `backend/tests/integration/test_onboarding.py` | updated test | verification opens the wizard at step 1 |
| `frontend/src/components/onboarding/onboardingSteps.test.tsx` | added test | step 2 value, step 4 symbol |

## What each step writes

- **Step 1**: name and description via `TenantSettingsService.update_tenant`. A new slug is
  checked for uniqueness (409 if taken).
- **Step 2**: `tenant_type`, its default labels and features, and a module reset
  (`TenantModuleService.reset_to_defaults`). Allowed **only while the wizard is open**; 409 after.
- **Step 3**: books currency via `update_tenant`, with `record_operator_origins` first, exactly as
  `PUT /settings/tenant` does (T272). Also the shop name (`update_shop_settings`), brand colour
  (`update_branding_settings`) and timezone (`settings.localization.timezone`).
- **Step 4**: skip, or create the product by calling `products.create_product` itself, so there is
  no second implementation. A typed price becomes a list price on the tenant's first active sales
  channel via `products.add_product_pricing`.
- **Logo**: `ImageStorage.save_image`, then `update_branding_settings(logo_url=…)`.

## Tests Added or Updated

- `tests/api/test_onboarding_wizard.py`: status (pre-wizard tenant finished, fresh tenant at
  step 1, 401, member 403); step 1 success, 409 taken slug, 422; step 2 success, 409 after setup;
  step 3 writes all four settings and records currency provenance, 422 bad code, 422 JPY;
  404 unknown step; step 4 skip, 422 without a name, product and channel price created, price
  not stored without a channel.
- `tests/integration/test_onboarding.py::test_verify_email_creates_tenant_and_user`: the wizard
  starts at step 1.
- `frontend/.../onboardingSteps.test.tsx`: step 2 submits `hand_knitting`; step 4 labels GBP, CAD
  and AUD correctly.

## Local Verification

- On the test Postgres: `pytest tests/api/test_onboarding_wizard.py tests/integration/test_onboarding.py tests/unit/test_onboarding_service.py`: 55 passed.
- `vitest run src/components/onboarding`: 4 passed.
- Full CI-equivalent run: see `../FIX-RUN.md`.

## Deviations from Assessment

- **A second defect found and fixed: wrong business-type spelling.** Step 2 sent enum *names*
  (`THREED_PRINT`). The API and `useModules` use the *values* (`three_d_print`), so even with the
  routes in place, step 2 would have returned 422. Fixed on the frontend, so the API keeps one
  spelling.
- **Currencies without cents are refused in step 3 (422).** The settings path rejects JPY and
  similar (`TenantUpdate._books_currency`). The wizard validates through that same model rather
  than copying the rule. The wizard's currency list (GBP, USD, EUR, CAD, AUD) has none.
- **A price without a channel is not stored.** The assessment said the price becomes a channel
  list price. A brand-new tenant usually has no channel, and a price with no channel is not a
  figure the engine can read, so step 4 records `price_stored: false` in the step data instead of
  inventing a channel.
- **Pre-wizard tenants count as finished.** There is no migration: a tenant without the
  `onboarding` key reports `is_completed: true`, so existing users are never sent back through
  setup.
- **Also changed (in scope):** wizard errors now show the server's reason (`apiErrorDetail`)
  instead of "Request failed with status code 422".

## Follow-ups

- When step 4 stores no price, tell the user on the dashboard ("add a sales channel to price
  Ember Dragon"). Today it is recorded but not shown.
