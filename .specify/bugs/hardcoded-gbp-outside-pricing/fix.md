# Bug Fix: Money outside the pricing screens is always shown in pounds

- **Slug**: hardcoded-gbp-outside-pricing
- **Fixed**: 2026-10-25
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

The designer list formats membership costs with the books currency from `useCurrency()`. The
platform tenant page formats revenue in the tenant's own currency, which the platform API now
returns.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/app/schemas/platform_admin.py` | modified | `currency_code` on `TenantResponse` (inherited by `TenantDetailResponse`) |
| `backend/app/api/v1/platform.py` | modified | detail response passes `currency_code` (the list uses `model_validate`, so it needs no change) |
| `frontend/src/lib/api/platform.ts` | modified | `currency_code` on `Tenant` |
| `frontend/src/pages/platform/TenantDetailPage.tsx` | modified | `symbolForCurrency(tenant.currency_code)` |
| `frontend/src/components/designers/DesignerList.tsx` | modified | `useCurrency().currency.symbol` |
| `backend/tests/api/test_platform_admin.py` | updated test | detail and list carry `currency_code` |
| `frontend/src/components/designers/DesignerList.test.tsx` | added test | CAD tenant sees `CA$12.00`, no `£` |
| `frontend/src/pages/platform/TenantDetailPage.test.tsx` | added test | CAD tenant's revenue labelled `CA$` |

## Tests Added or Updated

- `test_platform_admin.py::test_get_tenant_detail` asserts `currency_code`;
  `test_tenant_list_carries_each_tenants_currency` is new.
- `DesignerList.test.tsx`, `TenantDetailPage.test.tsx` as above.

## Local Verification

- `pytest tests/api/test_platform_admin.py`: 22 passed.
- `vitest run` on both new frontend tests: 2 passed.
- Full CI-equivalent run: see `../FIX-RUN.md`.

## Deviations from Assessment

- None.

## Follow-ups

- `total_revenue` sums order totals as stored. For a tenant that sold in several currencies, the
  sum is not meaningful whatever its symbol. That is out of scope here.
