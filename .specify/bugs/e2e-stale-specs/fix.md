# Bug Fix: Playwright specs drifted from the current UI

- **Slug**: e2e-stale-specs
- **Fixed**: 2026-11-24
- **Assessment**: ./assessment.md
- **Status**: applied (Chromium green; WebKit and Firefox: see Local Verification)

## Summary

Every stale spec under `frontend/e2e/` (outside `pricing/`) was updated to the current UI while
keeping each test's intent. Specs now seed their own data per fresh tenant, assert saved values
through the API, and use role queries that survive the app's duplicated headings and lists. Six
tests that expose real app bugs are `test.fixme`'d with the reason. No app code changed.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `frontend/e2e/helpers.ts` | modified | exported `fetchVerificationToken`; added `apiAs(page)` (authorized JSON calls with the stored session), `getAccessToken`, `uniqueSuffix`; the session is read by polling `page.evaluate` (WebKit fix, below) |
| `frontend/e2e/tests/auth/login.spec.ts` | modified | uses the shared `createTestUser`/`isBackendAvailable`; login request held 1 s so the loading state is observable |
| `frontend/e2e/tests/auth/registration.spec.ts` | rewritten | business name, password rules, "Check your email", verification through the token hook; duplicate email uses a verified account; `/inventory` → `/filaments` |
| `frontend/e2e/categories.spec.ts` | rewritten | used a hard-coded production product; now seeds a product + category through the API |
| `frontend/e2e/tests/categories/category-management.spec.ts` | rewritten | real dialog labels, row-scoped locators, real assertions; 2 fixme |
| `frontend/e2e/tests/dashboard/dashboard-workflow.spec.ts` | modified | nav links by role `link`; mobile menu sheet; "Failed Today" no longer read as an error |
| `frontend/e2e/tests/printers/printer-fields.spec.ts` | modified | exact cell name (vs "Machine cost for …"); Model is a select; values checked through the API (the old check read a wrong storage key and silently skipped); 1 fixme |
| `frontend/e2e/tests/settings/settings-workflow.spec.ts` | modified | Settings link; "Credentials not configured" |
| `frontend/e2e/tests/inventory/{spool-fields,spools,consumable-fields}.spec.ts` | rewritten | new Filament Library flow ("Add Filament" → batch of identical spools, filament-type rows, read-only spool sheet, quick-update page); consumables list at `/consumables/types`, uppercase SKUs |
| `frontend/e2e/tests/products/{product-crud,product-fields,shop-visibility}.spec.ts` | rewritten | "Quick Create" link, TipTap description, labelled switches on the edit page, seeding via API; 1 fixme |
| `frontend/e2e/tests/models/model-fields.spec.ts` | modified | waits for the async SKU; category/designer/source/machine are selects; 1 fixme |
| `frontend/e2e/production-run-{auto-population,edit-flow,multi-model-materials}.spec.ts` | rewritten | spools/models/BOM/runs seeded via API; wizard comboboxes; placeholder tests now assert low-stock/inactive badges and per-model breakdowns |
| `frontend/e2e/tests/production/production-run.spec.ts` | modified | dialog labels, deduction checked via `GET /spools/{id}`; 1 fixme |
| `frontend/e2e/tests/orders/{order-create,order-flow}.spec.ts` | modified | real session instead of a fake token; money fields are decimal strings |
| `frontend/e2e/pricing/cost-and-margin.spec.ts` | modified | margin button scoped to the base (1+) row with `baseChannelRow` (scope added by the orchestrator) |

## Tests Added or Updated

All of the above. Added coverage while fixing: saved-value API checks for every printer, spool,
consumable, product and model field test; density/spool-type and auto-SKU tests (inventory); a
seeded-designer test (models); real assertions in the low-inventory, inactive-spool and per-model
breakdown production tests, which previously only clicked Next.

`test.fixme` (each is a real app bug, reported to the orchestrator):

| Test | App bug |
|---|---|
| categories › should list inactive categories under Show All | `CategoryList.tsx:92` sends `is_active`; `api/v1/categories.py:31` reads `include_inactive`, so inactive categories never list |
| categories › should reorder categories created from the dialog | new categories all get `display_order` 0; `handleMove` (`CategoryList.tsx:135`) swaps the two orders, which changes nothing |
| printers › should save serial_number correctly | the form has Serial Number (`PrinterFormDialog.tsx:247`) but the printer model/schemas have no `serial_number`: silently dropped |
| products › should toggle product active status | `GET /api/v1/products/{id}` filters `is_active` (`api/v1/products.py:650`): an inactive product's page is a 404 |
| models › should save a new designer typed in the form | `ModelForm.tsx:510-545`: the typed designer is not a Select option, so the Select resets on blur and the POST has no designer (same pattern for source and machine) |
| production › completes a run that has no estimated print time (America/New_York) | `CompleteRunDialog.tsx:149` writes UTC into a datetime-local field and `:265` parses it as local time; west of UTC `started_at` lands in the future, `production_run.py:674-685` stores a negative duration and the response 500s (`ge=0`), yet the run is completed |

## Local Verification

Stack: throwaway PostgreSQL 16 (5444, migrated to head), Redis (6390), backend on 8011 with
`E2E_TEST_HOOKS_ENABLED=true`, Vite on 5183. Shared ports 8000/5173/5433 untouched.

- Baseline on 35b7667: `npx playwright test --project=chromium --retries=0` → 107 failed, 106 passed.
- After the fix, on ab479f0 + changes: `npx playwright test --project=chromium --retries=0 --workers=3`
  → **208 passed, 6 skipped (the fixmes), 0 failed** (214 tests, 10.5 min).
- `npx eslint e2e` → clean.
- After syncing to aaaf05c (007 Ideas merged): same command → **210 passed, 6 skipped, 0 failed**.
- `pricing/cost-and-margin.spec.ts` on a fresh `seed_e2e.py` DB after the tier journey → 3/3.
- WebKit: about 40% failing on this host from page crashes, interrupted navigations and lost
  sessions, not from locators. See e2e.md.
- Firefox: cannot run on this machine. Playwright's `firefox.exe` is refused execution
  ("Permission denied" / `spawn UNKNOWN`), apparently by an OS execution policy. Not worked around.

## Deviations from Assessment

- Scope expansion: `pricing/cost-and-margin.spec.ts` (one locator), at the orchestrator's request.
- WebKit-only helper fix found while verifying: the app loads zone.js, which on WebKit turns
  `waitForFunction`'s result into a truthy promise object, so the wait resolved before the session
  was stored. The helper now polls `page.evaluate` from Node instead.
- Inventory: 5 tests were removed rather than fixme'd, because their UI is no longer routed (spool
  delete; storage location, empty spool weight, purchase price, purchase date on a spool). The new
  spool sheet is read-only by design ("per D-09").

## Follow-ups

- Fix the six app bugs above, then drop their `test.fixme`.
- `Button` ignores `asChild` (`src/components/ui/button.tsx:43`): every `asChild` link renders as
  `<button><a/></button>` (invalid nesting, two tab stops). Not fixme'd: no spec asserts it.
- Possible issues worth confirming with the owner (not fixme'd): Filament Library search filters by
  brand only, though the placeholder promises colour and material; `SpoolQuickUpdatePage` "Back to
  Inventory" goes to `/dashboard`; "1 spools" badge; `AuthContext` clears the session on any failed
  `/users/me` (a transient network error logs the user out).
- The e2e README's port/flag notes could mention `PYTHONUNBUFFERED=1` for readable backend logs.
