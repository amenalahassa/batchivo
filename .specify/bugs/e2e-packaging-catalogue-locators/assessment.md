# Bug Assessment: Packaging catalogue journeys aim at the wrong elements

- **Slug**: e2e-packaging-catalogue-locators
- **Created**: 2026-11-24
- **Source**: pasted text (orchestrator: the two packaging-catalogue journeys fail on clean main 31d7463)
- **Verdict**: valid (test defect, not an app defect)
- **Severity**: medium (blocks the green e2e gate before every merge, no user impact)

## Report (verbatim or summarized)

The two journeys in `frontend/e2e/pricing/packaging-catalogue.spec.ts` (spec 006, T060)
fail every run on clean main. Reproduced on an isolated stack (backend 8010, Vite 5183,
scratch database seeded by `backend/scripts/seed_e2e.py`):

```
1) the standard catalogue is added and listed as defaults
   Error: strict mode violation: getByRole('heading', { name: 'Packaging' }) resolved to 2 elements:
       1) <h1 ...>Packaging</h1>
       2) <h3 ...>Your packaging</h3>
2) the suggested carrier is added and a default service chosen
   Error: locator.scrollIntoViewIfNeeded: Test timeout of 30000ms exceeded.
   - waiting for getByTestId('shipping-profiles-panel')
```

## Symptom

Journey 1 stops at its first assertion because the heading name matches by substring.
Journey 2 waits forever for the postage panel on `/settings`, which only renders inside the
**Pricing** tab; the test never opens that tab.

## Reproduction

1. Seed the e2e tenant, start the backend and Vite.
2. `npx playwright test e2e/pricing/packaging-catalogue.spec.ts --project=pricing --retries=0`
3. Both tests fail as above.

## Suspected Code Paths

- `frontend/e2e/pricing/packaging-catalogue.spec.ts:23`: `getByRole('heading', { name: 'Packaging' })`
  is a case-insensitive substring match, so it also matches the list card's "Your packaging" title
  (`frontend/src/components/packaging/PackagingList.tsx`).
- `frontend/e2e/pricing/packaging-catalogue.spec.ts:48-58`: goes to `/settings` and looks for
  `shipping-profiles-panel`. `frontend/src/pages/Settings.tsx` renders `ShippingProfilesPanel`
  (which holds `CarrierPostageSection`) only in `<TabsContent value="pricing">`, and the default
  tab is General. The helper `openPricingSettings` in `pricing-helpers.ts` already does that.
- Same test: `if (await suggestion.isVisible())` is read once, immediately. While the carrier
  query is still loading, it is false, the click is skipped, and `carrier-services` never
  appears on a shop with no carrier yet (the seeded tenant). This is a race.

## Root Cause Hypothesis

The journey was written against a layout it never ran on: the postage panel has sat in the
Pricing tab since T245, before spec 006. The spec's "Settings → Postage" names the postage
section of Settings, not a tab (there is none). The app behaves as specs 006 and T245 describe.
Confidence: high (reproduced, DOM snapshot confirms both elements).

## Proposed Remediation

**Preferred**: fix the test only.
- Journey 1: `getByRole('heading', { name: 'Packaging', exact: true })`.
- Journey 2: open the tab with `openPricingSettings(page)`. Then wait until either the
  suggestion button or the carrier services list is visible (`expect(a.or(b)).toBeVisible()`)
  before deciding whether to click, so the decision is made on loaded data.

**Alternatives**:
- Add a "Postage" tab to Settings: changes the UI the shop uses, not justified by the spec's
  wording. Rejected (pending the orchestrator's answer, question A).

**Files likely to change**:
- `frontend/e2e/pricing/packaging-catalogue.spec.ts`

**Tests to add or update**:
- The journey itself is the regression test: two green runs in a row.

## Risks & Considerations

- None for the app. The rerun branches of both journeys (already-added catalogue, carrier
  already chosen) must keep passing on a second run against the same database.

## Open Questions

- Question A to the orchestrator: test fix (recommended) or a Postage tab.
