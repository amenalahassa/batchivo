# Quickstart: validating the Packaging page and default catalogue

## Prerequisites

- Local stack (`dev.ps1`, or `docker compose up -d postgres redis` + backend + frontend).
- Database migrated: `cd backend && poetry run alembic upgrade head`.

## 1. Release step on an existing shop (US2, US3, FR-011, FR-018)

```bash
cd backend
poetry run python -m app.cli.seed_catalogues --all-tenants --dry-run --report ../specs/006-packaging-catalogue/delta-postage.md
poetry run python -m app.cli.seed_catalogues --all-tenants
poetry run python -m app.cli.seed_catalogues --all-tenants   # second run: "nothing to do"
```

Expected: the dry-run writes a per-product postage before/after table and changes nothing; the
first run reports, per tenant, packaging added/skipped and, for a CAD shop, Canada Post profiles
added; the second run adds nothing.

## 2. Packaging page (US1)

1. Open the console, reload: "Packaging" is in the navigation.
2. Packaging lists the catalogue boxes, mailers and void fill, each labelled "default"; a banner
   says what was added and skipped; dismiss it.
3. "Add box" → form already in Box mode → save `Test box 200×150×100`, wall 3, 120 g.
4. Consumables lists only hardware (no boxes).
5. Edit a catalogue box's inner height → that figure no longer shows "default".

## 3. Postage (US3)

1. Settings → Postage: seeded Canada Post profiles with source and tariff date, labelled default.
2. Choose default service Small Packet.
3. Open a product with dimensions and weight → margin uses Small Packet; set the product's
   postage service to Expedited Parcel → margin uses Expedited Parcel.
4. A box larger than Small Packet's limits shows only the services it fits on the Packaging page.

## 4. New shop onboarding

1. Create a shop (EUR) and run the wizard to step 5: catalogue items all selected, La Poste
   proposed; keep defaults; finish.
2. Packaging and Postage are populated; margins mark packaging cost as assumed.

## 5. Automated checks

```bash
cd backend && poetry run pytest tests/unit/test_catalogue_data.py tests/unit/test_catalogue_seed.py tests/unit/test_postage_preferred_service.py tests/api/test_packaging_catalogue.py tests/api/test_postage_catalogue.py tests/api/test_consumables_packaging_filter.py tests/api/test_onboarding_step5.py
cd frontend && npx vitest run src/components/packaging src/pages/Packaging.test.tsx src/components/settings/ShippingProfilesPanel.test.tsx
```

## Results (2026-11-04, round 1)

Run on a scratch copy of the local dev database (`batchivo_spec006`, made with
`pg_dump batchivo`, migrated to `catalogue_columns_v1`), with a backend on
:8006 and the frontend on :5174 so the dev stack itself was not touched.
Signed in with throwaway local owners created for the walkthrough.

| Scenario | Outcome |
|---|---|
| 1. Release step | Pass. Dry run wrote the report (no product's postage changes; see `delta-postage.md`). First run: e2e-pricing (GBP) 16 packaging + 8 Royal Mail profiles; handy (CAD) 16 packaging + 39 Canada Post profiles. Second run: "nothing to do" for both. |
| 2.1 Navigation | Pass. "Packaging" is in the sidebar beside Consumables. |
| 2.2 Catalogue listed | Pass. 16 items, every assumed figure badged "default", fitting services listed per box; the notice said 16 added and dismissed. |
| 2.3 Add box | Pass. "Add box" opens titled "Add box", kind preset, no category or description; the box saved and listed. **Found:** an operator's own estimate was badged "default" like a catalogue item — now "estimated" (fixed, test added). |
| 2.4 Consumables | Pass. No packaging listed; the line pointing to the Packaging page is shown. |
| 2.5 Edit a catalogue box | Pass after a fix. **Found:** opening a consumable for the first time rendered the edit form before the record filled it, and Radix's hidden selects wrote their fallbacks ("hardware", not packaging) back over the loaded values, so saving would strip a catalogue box's kind (pre-existing in `EditConsumableDialog`, exposed by this feature). Fixed: the form renders once filled; regression test proves the failure before the fix. After the fix, marking the new height as measured left the other two sides assumed, and the size cell now says "partly default" (test added). |
| 3.1 Seeded profiles | Pass. Badged "default" with the price list and tariff date; the postage notice named Canada Post, chosen from the books currency. |
| 3.2 Default service | Pass. Small Packet saved as `canada_post:small_packet`. |
| 3.3 Margin by service | Not walked through: the copy's only CAD product has no weight. Covered by `tests/unit/test_postage_preferred_service.py` and the product override API tests. |
| 3.4 Fits per box | Pass. The 200 mm cube lists only Expedited Parcel; smaller boxes also list Small Packet. |
| 4. New EUR shop | Pass. Step 5 listed all 16 items (all selected, priced in €), proposed La Poste "from your shop's country"; Finish led to the dashboard with 16 packaging items, 39 La Poste profiles and the notice. Step 3 was submitted through the API: the browser pane was hidden, so its dropdowns could not be opened. |
| 4.2 Assumed packaging cost | Covered by `tests/unit/test_costing_packaging_provenance.py`. |
| 5. Automated checks | Pass (see the CI gates in the build report). |
