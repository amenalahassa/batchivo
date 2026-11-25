# Implementation Plan: Packaging Page and Default Packaging and Postage Catalogue

**Branch**: `006-packaging-catalogue` | **Date**: 2026-11-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/006-packaging-catalogue/spec.md`

## Summary

Give packaging its own page and seed every shop with a standard packaging catalogue and its
carrier's postage, so the packaging advisor and postage work on day one.

- **Packaging page** (US1): a `/packaging` route listing the consumables that have a
  `packaging_kind`, with add-by-kind dialogs that reuse the consumable form; the Consumables page
  excludes packaging. Navigation entry declared by the `consumables` module.
- **Packaging catalogue** (US2): a versioned data file of standard boxes, mailers, void fill and
  wrap with sizes, walls, empty weights and a typical cost per currency. One seeding service
  creates the missing items for a tenant (keyed by a `catalogue_key`), records every seeded figure
  as `assumed` in the existing provenance table, and stores a one-time "what was added/skipped"
  notice in the tenant's settings.
- **Postage catalogue** (US3): versioned tariff files per carrier (Canada Post, Royal Mail,
  La Poste, USPS) and effective date. The same seeding service creates `ShippingProfile` rows for
  the chosen services, tagged with service, source and tariff version, `assumed`, never
  overlapping existing rows. A newer tariff is offered and, when accepted, supersedes (closes
  `effective_to`, inserts new rows) rather than editing. A shop chooses a default service; a
  product may override it; `postage._price` prefers that service and falls back to the cheapest
  fitting one with a note.
- **Existing shops** (clarification Q3/Q4): seeded automatically at release by a CLI step run
  after `alembic upgrade` (k3s init container, VPS update command, dev deploy), carrier chosen
  by `carrier_for_tenant` — the tenant's country when recorded, else its currency (research D7).
- **Shop country** (clarification Q6): new optional `tenants.country_code`, set in general
  settings and onboarding step 3 like the currency; it only chooses the carrier. A dry-run of that step (savepoint, rolled back) produces the
  per-product postage delta report the constitution requires before the release is accepted.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 5.9 / React 19 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, PyYAML (already a
dependency, not needed: catalogue files are JSON); TanStack Router/Query, shadcn/ui, Zod

**Storage**: PostgreSQL 16 — columns added to `consumable_types`, `shipping_profiles`, `products`;
catalogue reference data as versioned JSON files shipped with the backend (`backend/app/data/`)

**Testing**: pytest (+ pytest-asyncio, the `client`/`db_session`/`test_tenant` fixtures), Vitest +
Testing Library, Playwright e2e for the onboarding step

**Target Platform**: k3s cluster (ArgoCD) and single-tenant VPS instances (spec 005)

**Project Type**: web application (backend + frontend)

**Performance Goals**: seeding one tenant < 2 s (≈ 20 consumables + ≈ 150 postage rows); Packaging
page list < 300 ms for 200 items; `fits_services` derived on read without N+1 queries

**Constraints**: Decimal end to end, decimal strings on the wire; tenant-scoped rows with RLS;
idempotent seeding safe to run on every deploy and under several replicas; no breaking change to
`/consumables` and `/shipping-profiles` APIs

**Scale/Scope**: 4 carriers, ~10 services, ~20 catalogue packaging items, 1–N tenants per instance

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How the design satisfies it |
|---|---|---|
| I. Multi-tenant isolation | PASS | Seeded rows carry `tenant_id`, RLS policies already cover `consumable_types`, `shipping_profiles`, `products`, `pricing_input_provenance`. Catalogue files are shared reference data, never tenant data. New endpoints use `get_current_tenant` + `get_tenant_db`. |
| II. Tests | PASS | Every new endpoint: 200/201, 401, 422, 404. Seeding service: idempotence, skip-on-name, currency without carrier, country before currency, country without carrier, supersede, overlap skip. Schema change: CRUD + unique constraint tests. Frontend: page, dialogs, notice, onboarding step. |
| III. One implementation | PASS | One seeding service (`catalogue_seed.py`) used by onboarding, the "add catalogue" endpoints and the release CLI. Service fit lives in `postage.py` (`services_fitting`) beside `_price`; the frontend never recomputes it. Postage preference is applied inside `_price`, not in routes. |
| IV. Money exact, settings honoured | PASS | Catalogue prices are decimal strings parsed to `Decimal`; the shop's chosen default service is honoured, fallback is reported (note), never silent. |
| V. Derived figures expire | PASS | `fits_services` and margins are computed on read; nothing derived is stored. |
| VI. History immutable, provenance visible | PASS | Seeded figures recorded `assumed` with `as_of` = catalogue/tariff date; a new tariff supersedes via `effective_to` + new rows; frozen order postage untouched. The seeding changes margins of products that had no postage → per-product delta report from the dry-run before release (FR-018a). |
| VII. Pipeline | PASS | Seeding runs from the image's own CLI in the init container (k3s) and the documented update command (VPS); no manual DB edits. |

No violations; Complexity Tracking is empty.

**Post-design re-check (after Phase 1)**: PASS — the data model adds only nullable columns and one
partial unique index; contracts reuse existing routers where they exist; no stored derived figure.

## Project Structure

### Documentation (this feature)

```text
specs/006-packaging-catalogue/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── api.md
│   └── catalogue-files.md
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── data/
│   │   ├── packaging_catalogue.json            # NEW versioned packaging catalogue
│   │   └── postage_tariffs/<carrier>/<date>.json  # NEW one file per carrier tariff
│   ├── models/
│   │   ├── consumable.py                       # + catalogue_key, catalogue_version
│   │   ├── shipping_profile.py                 # + service, source, catalogue_carrier, tariff_version
│   │   └── product.py                          # + postage_service
│   ├── services/
│   │   ├── catalogue_data.py                   # NEW load + validate catalogue/tariff files
│   │   ├── catalogue_seed.py                   # NEW the one seeding service (packaging + postage)
│   │   ├── postage.py                          # preferred service in _price; services_fitting()
│   │   ├── provenance.py                       # register fill_volume_ml
│   │   └── onboarding_wizard.py                # step 5: packaging & postage
│   ├── api/v1/
│   │   ├── packaging_catalogue.py              # NEW /packaging/catalogue, /catalogue-notice
│   │   ├── postage_catalogue.py                # NEW /postage/carriers, /postage/tariff-updates, /settings/postage
│   │   ├── consumables.py                      # exclude_packaging filter, fits_services in response
│   │   ├── products.py                         # postage_service on update/response
│   │   ├── modules.py                          # /packaging nav entry under consumables
│   │   └── onboarding.py                       # PUT /wizard/step/5
│   ├── schemas/                                # packaging_catalogue.py, postage_catalogue.py (NEW), consumable.py, product.py, onboarding.py
│   └── cli/seed_catalogues.py                  # NEW release step: --all-tenants [--dry-run --report]
├── alembic/versions/<rev>_catalogue_columns.py  # NEW schema migration
├── scripts/postage_delta_report.py             # + --after-seed mode (dry-run delta)
└── tests/
    ├── unit/test_catalogue_data.py, test_catalogue_seed.py, test_postage_preferred_service.py
    └── api/test_packaging_catalogue.py, test_postage_catalogue.py, test_consumables_packaging_filter.py, test_onboarding_step5.py

frontend/src/
├── pages/Packaging.tsx                         # NEW
├── components/packaging/
│   ├── PackagingList.tsx                       # NEW
│   ├── AddPackagingDialog.tsx                  # NEW (wraps the consumable form in packaging mode)
│   ├── CatalogueNotice.tsx                     # NEW one-time added/skipped banner
│   └── AddCatalogueDialog.tsx                  # NEW re-add catalogue items
├── components/inventory/ConsumableList.tsx     # exclude packaging
├── components/inventory/AddConsumableDialog.tsx # presetKind / packagingOnly props
├── components/settings/ShippingProfilesPanel.tsx # carrier, default service, tariff offer, seeded labels
├── components/products/ProductPackagingCard.tsx # link to /packaging; postage service override
├── components/onboarding/PackagingPostageStep.tsx # NEW step 5
├── components/layout/AppLayout.tsx             # icon + fallback nav
├── lib/api/packagingCatalogue.ts, postageCatalogue.ts  # NEW
├── hooks/usePackagingCatalogue.ts, usePostageCatalogue.ts # NEW
├── types/packagingCatalogue.ts, postageCatalogue.ts    # NEW
└── App.tsx                                     # /packaging route

infrastructure/k8s/backend/deployment.yaml      # init container: seed_catalogues after alembic
.claude/skills/deploy-dev/SKILL.md              # dev step: run seed_catalogues after migrate
```

**Structure Decision**: existing web-application layout (`backend/app`, `frontend/src`). Reference
data lives in `backend/app/data/` (new directory) because it ships with the image and is versioned
with the code that reads it.

## Complexity Tracking

None.
