# Bug Fix: Categories "Show All" never lists inactive categories

- **Slug**: category-show-all-param
- **Fixed**: 2026-11-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Rename the client parameter to `include_inactive` (sent only when true) and have "Show All" set it. The API stays as is. Callers that passed `is_active: true` drop it, since active-only is the default.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `frontend/src/lib/api/categories.ts` | modified | `CategoryListParams.is_active` -> `include_inactive`; sent only when true |
| `frontend/src/components/categories/CategoryList.tsx` | modified | "Show All" sets `include_inactive` |
| `frontend/src/components/products/ProductCategoriesEditor.tsx`, `ProductWizard/WizardCategorySelection.tsx` | modified | drop the ignored `is_active: true` |
| `frontend/src/lib/api/categories.test.ts` | added test | parameter name |
| `frontend/e2e/tests/categories/category-management.spec.ts` | modified | fixme removed |

## Tests Added or Updated

- `frontend/src/lib/api/categories.test.ts` > listCategories - sends `include_inactive`, never `is_active`
- `category-management.spec.ts` > should list inactive categories under Show All

## Local Verification

- New backend tests run against a throwaway PostgreSQL 16 (port 5467); new vitest files run on their own; all pass.
- e2e: `npx playwright test --project=chromium --retries=0 -g "should list inactive categories under Show All"` against a throwaway stack (backend 8033, Vite 5193) -> pass (see e2e.md).

## Deviations from Assessment

None.

## Follow-ups

None.
