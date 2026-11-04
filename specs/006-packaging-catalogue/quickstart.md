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
