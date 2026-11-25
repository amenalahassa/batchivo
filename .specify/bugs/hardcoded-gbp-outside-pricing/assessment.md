# Bug Assessment: Money outside the pricing screens is always shown in pounds

- **Slug**: hardcoded-gbp-outside-pricing
- **Created**: 2026-10-25
- **Re-assessed**: 2026-10-25 (against `7a2776e`)
- **Source**: side finding from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 24 round
- **Verdict**: valid (still open)
- **Severity**: low

## Report (verbatim or summarized)

> Two screens outside the pricing feature format money with a hardcoded `£`.

## Re-assessment changes

- **Both sites are unchanged**, and a sweep of `frontend/src` for `£` finds no others that
  render. The remaining hits are `'£'` fallbacks for an absent currency (`useCurrency.ts:33`,
  `GeneralSettings.tsx:69,80`, the sales-channel component defaults), comments, guide copy, and
  `Step4FirstProduct.tsx:79`, which is tracked under `onboarding-wizard-steps-missing`.
- **The platform fix needs a backend change.** `TenantDetailResponse` (`app/schemas/platform_admin.py`)
  does not expose the tenant's currency. `Tenant.currency_code` exists (`app/models/tenant.py:96`)
  but is not serialised, so the frontend has nothing to pass to `symbolForCurrency`.

## Symptom

`DesignerList.tsx` renders a designer's membership cost with `formatMoney(..., '£')`. The
platform admin's `TenantDetailPage.tsx` renders a tenant's total revenue the same way. A tenant
that keeps its books in another currency (settable since T242) sees pounds. The platform page
labels every tenant's revenue in pounds.

## Reproduction

1. Set the books currency to CAD in General settings.
2. Open Designers with a membership cost recorded. Observe `£`.
3. As a platform admin, open that tenant's detail page. The revenue shows `£`.

## Suspected Code Paths

- `frontend/src/components/designers/DesignerList.tsx:412`
- `frontend/src/pages/platform/TenantDetailPage.tsx:242`
- `backend/app/schemas/platform_admin.py`: `TenantDetailResponse` / `TenantResponse` have no `currency_code`.

## Root Cause Hypothesis

Both were written before the currency was configurable. Confidence: high.

## Proposed Remediation

**Preferred**:

- Designer list: take the symbol from `useCurrency()`.
- Platform page: add `currency_code: str` to `TenantResponse` (it is read from the model, so
  nothing is stored), add it to the frontend platform tenant type, and render with
  `formatMoney(tenant.total_revenue, symbolForCurrency(tenant.currency_code))`.

**Files likely to change**:
- `frontend/src/components/designers/DesignerList.tsx`
- `frontend/src/pages/platform/TenantDetailPage.tsx` and its platform tenant type
- `backend/app/schemas/platform_admin.py`
- tests for both components and for the platform tenant detail endpoint

**Tests to add or update**:
- DesignerList renders `$` (or `C$`, whatever `symbolForCurrency` returns) for a CAD tenant.
- The platform tenant detail response includes `currency_code`, and the page renders its symbol.

## Risks & Considerations

- `total_revenue` sums order totals as stored. If a tenant ever took orders in more than one
  currency, the sum is meaningless whatever the symbol. That is out of scope here.
- Display only: no stored figure changes.

## Open Questions

None.
