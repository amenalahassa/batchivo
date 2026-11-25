# Bug Fix: Reordering newly created categories does nothing

- **Slug**: category-reorder-noop
- **Fixed**: 2026-11-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Backend: a category created without an explicit `display_order` goes after the tenant's existing ones (max + 1, or 0 for the first). Frontend: a move renumbers the shown list 0..n-1 in its new order and patches only the categories whose order changes, so tenants whose categories already share 0 can reorder too.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/app/api/v1/categories.py` | modified | append new categories when no order is given |
| `backend/tests/integration/test_categories_api.py` | added tests | `test_create_category_without_order_goes_last`, `test_create_first_category_without_order_is_zero` |
| `frontend/src/lib/api/categories.ts` | modified | `displayOrderUpdatesForMove` (pure) |
| `frontend/src/components/categories/CategoryList.tsx` | modified | `handleMove` uses it with `reorderCategories` |
| `frontend/src/lib/api/categories.test.ts` | added tests | three move cases |
| `frontend/e2e/tests/categories/category-management.spec.ts` | modified | fixme removed |

## Tests Added or Updated

- `test_categories_api.py::TestCategoryCRUD::test_create_category_without_order_goes_last`
- `test_categories_api.py::TestCategoryCRUD::test_create_first_category_without_order_is_zero`
- `categories.test.ts` > displayOrderUpdatesForMove
- `category-management.spec.ts` > should reorder categories created from the dialog

## Local Verification

- New backend tests run against a throwaway PostgreSQL 16 (port 5467); new vitest files run on their own; all pass.
- e2e: `npx playwright test --project=chromium --retries=0 -g "should reorder categories created from the dialog"` against a throwaway stack (backend 8033, Vite 5193) -> pass (see e2e.md).

## Deviations from Assessment

None.

## Follow-ups

None.
