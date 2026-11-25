# Bug Fix: An inactive product's detail page is a 404

- **Slug**: product-inactive-detail-404
- **Fixed**: 2026-11-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Drop the `is_active` filter from `GET /products/{id}` only (tenant scope kept). Cost, margin and pricing endpoints keep it: an inactive product is not for sale. The list endpoint already filters by default.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/app/api/v1/products.py` | modified | `get_product` no longer filters `is_active` |
| `backend/tests/integration/test_products_api.py` | modified / added test | `test_delete_product` updated, `test_get_inactive_product_detail` added |
| `frontend/e2e/tests/products/product-crud.spec.ts` | modified | fixme removed |

## Tests Added or Updated

- `test_products_api.py::TestProductsEndpoints::test_get_inactive_product_detail`
- `test_products_api.py::TestProductsEndpoints::test_delete_product` (soft delete -> 200 inactive, purge -> 404)
- `product-crud.spec.ts` > should toggle product active status

## Local Verification

- New backend tests run against a throwaway PostgreSQL 16 (port 5467); new vitest files run on their own; all pass.
- e2e: `npx playwright test --project=chromium --retries=0 -g "should toggle product active status"` against a throwaway stack (backend 8033, Vite 5193) -> pass (see e2e.md).

## Deviations from Assessment

`test_delete_product` asserted a 404 after a soft delete. That assertion encoded the bug, so it now expects 200 with `is_active` false, and 404 only after a purge.

## Follow-ups

None.
