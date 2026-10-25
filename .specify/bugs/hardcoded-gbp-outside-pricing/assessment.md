# Bug Assessment: Money outside the pricing screens is always shown in pounds

- **Slug**: hardcoded-gbp-outside-pricing
- **Created**: 2026-10-25
- **Source**: side finding from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 24 round
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

> Two screens outside the pricing feature format money with a hardcoded `£`.

## Symptom

`DesignerList.tsx` renders a designer's membership cost with `formatMoney(..., '£')`, and the
platform admin's `TenantDetailPage.tsx` renders a tenant's total revenue the same way. A tenant
keeping its books in another currency (settable since T242) sees pounds; the platform page also
labels revenue in pounds whatever the tenant's currency.

## Reproduction

1. Set the books currency to CAD in General settings.
2. Open Designers with a membership cost recorded. Observe `£`.

## Suspected Code Paths

- `frontend/src/components/designers/DesignerList.tsx:412`
- `frontend/src/pages/platform/TenantDetailPage.tsx:242`

## Root Cause Hypothesis

Written before the currency was configurable.

## Proposed Remediation

Use `useCurrency()` in the designer list; on the platform page, use the tenant's own
`currency_code` through `symbolForCurrency`. Test both with a non-GBP tenant.

## Risks & Considerations

None; display only.

## Open Questions

None.
