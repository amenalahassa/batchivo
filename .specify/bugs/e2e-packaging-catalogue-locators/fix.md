# Bug Fix: Packaging catalogue journeys aim at the wrong elements

- **Slug**: e2e-packaging-catalogue-locators
- **Fixed**: 2026-11-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

The page heading is matched exactly. The carrier journey opens the Settings Pricing tab, where
the postage panel lives, and waits for loaded data (suggestion or services) before deciding to
click. Question A answered (a), test fix, by the user through the orchestrator.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `frontend/e2e/pricing/packaging-catalogue.spec.ts` | modified | `exact: true` on the heading; `openPricingSettings(page)`; `expect(suggestion.or(services)).toBeVisible()` before the branch |

## Tests Added or Updated

- Both journeys in `packaging-catalogue.spec.ts`.

## Local Verification

- Spec alone → 2/2. Full pricing project, runs 9 and 10 → 20/20 each.

## Deviations from Assessment

None.

## Follow-ups

- Spec 006 says "Settings → Postage"; the panel is the postage section of the Pricing tab. A
  wording touch-up in the spec would avoid the confusion.
