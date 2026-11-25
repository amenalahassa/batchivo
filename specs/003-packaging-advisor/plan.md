# Implementation Plan: Packaging Advisor

**Branch**: `003-packaging-advisor` (work lands on `main`) | **Date**: 2026-10-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-packaging-advisor/spec.md`

## Summary

Operators choose boxes by eye and postage is priced on product weight alone,
although UK carriers price by size format first. This feature records each
item's dimensions (typed, or measured from its STL/3MF), gives consumables the
attributes of packaging, and adds a pure advisor that ranks the containers an
item fits in, with filler and wrap. Phase 2 feeds the packed parcel — weight
and outer size — into the existing postage engine, adds carrier size classes
and volumetric weight to shipping profiles, packs multi-item orders, records
the parcel confirmed at dispatch (deducting box stock), and reuses dimensions
for the printer-bed check and Etsy listings.

The approach is additive. Products already link a packaging consumable and
costing already prices it; postage already has one authority
(`app/services/postage.py`) with effective-dated profiles; 3MF files are
already opened on upload. The advisor never computes a cost, and postage
changes happen inside `postage.py`, so no second implementation appears.
Decisions and their alternatives: [research.md](./research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 5.9 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2;
React 19, TanStack Query/Router, shadcn/ui, Zod. **No new dependencies**: mesh
measurement uses `struct`, `zipfile` and `xml.etree` (research D3).

**Storage**: PostgreSQL 16 with RLS. Two new tables (`order_parcels`,
`order_parcel_items`), seven extended (`models`, `products`,
`product_variants`, `model_files`, `consumable_types`, `shipping_profiles`,
and `consumable_usage`, which gains one column). Tenant settings JSON gains a
`packaging` key.

**Testing**: pytest (unit for `mesh_bounds`, `packaging_advisor`, postage
parcel logic; API tests per endpoint; PostgreSQL migration/RLS suite); Vitest
for components.

**Target Platform**: k3s, Python 3.12-Alpine and Node-Alpine images, via
Woodpecker → ArgoCD.

**Project Type**: Multi-tenant web service (FastAPI + React SPA).

**Performance Goals**: Suggestions are an interactive read (catalogue of tens
of containers, 6 rotations each). SC-007: files up to 25 MB are measured in
the upload request with under 1 s added (timing test); 25–200 MB are measured
by a Celery task after the upload returns; over 200 MB are not measured and
say so.

**Constraints**: Decimal for every dimension, weight and volume; decimal
strings over the wire. Existing routes unchanged except for additive fields.
Migration chains on the head at implementation time (today
`rls_uncovered_tenant_tables_v1`, uncommitted on `main`).

**Scale/Scope**: Single-workshop tenants — hundreds of products, tens of
containers, orders of a few units. 39 FRs over 7 stories; ~4 new backend
modules, ~6 new frontend components.

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.0.0. Re-checked
after Phase 1 design — result unchanged.*

| Principle | Gate | Status |
|---|---|---|
| I. Multi-Tenant Isolation | Both new tables carry `tenant_id` with RLS policy in their creating migration; `test_every_tenant_table_has_rls.py` covers them automatically. Every endpoint uses `get_current_tenant` + `get_tenant_db`. | **PASS** |
| II. Tests Are Part of the Change | Each task ships its tests; endpoints cover 200/401/403/422/404; mesh fixtures assert to 0.1 mm; advisor edge cases (exact fit, zero clearance, incomplete box, out of stock) are unit tests. | **PASS** |
| III. One Authoritative Implementation | Advisor computes no cost; ranking ties use `consumable_unit_cost`, the function costing uses. Packed weight, size classes and volumetric weight are implemented inside `postage.py`; the parcel is assembled only by `postage.build_parcel`, which both the estimate and dispatch call (research D9/D10). Effective dimensions resolve in one helper. | **PASS** |
| IV. Money Exact, Settings Honoured | `Decimal` end to end; floats confined to mesh parsing (geometry, not money) and rounded once to 0.1 mm. Clearance is a tenant setting; the default is shown as a default and never shadows a configured value (D8). | **PASS** |
| V. Derived Figures Expire | Suggestions are computed on read, never stored. The stored file measurement is derived from immutable bytes; its invalidation is deletion of the file row (D4). | **PASS** |
| VI. History Immutable, Provenance Visible | Dimensions carry source, file and time. Container inner size, wall and empty weight join the pricing provenance registry in Phase 2, when they start deciding postage (FR-038). Order parcels and their stock usage are written once (409 on repeat). Size limits ride the existing effective-dated profile rows; settled orders' `postage_paid` is untouched (tested). | **PASS** |
| VII. Deployment Through Pipeline | Ordinary commits to `main`; no manifests change. | **PASS** |

Examined and found not to be violations:
- **Variant packaging override vs costing** (D11): costing has no variant
  path; the override affects packing and postage only, so no figure is
  computed twice, and the variant says its cost uses the product's packaging
  (FR-039). Recorded as a known limit, not a deviation.
- **Phase 2 changes computed postage**: the constitution requires the
  per-record difference to be reported before the change is accepted. The
  delta report runs before the Phase 2 release, not after it. Tenants with no
  size-limited profile see no change in profile choice (FR-026); the delta
  comes only from packaging weight.

## Project Structure

### Documentation (this feature)

```text
specs/003-packaging-advisor/
├── plan.md              # This file
├── research.md          # Phase 0: decisions D1–D13
├── data-model.md        # Phase 1: columns, tables, constraints
├── contracts/
│   └── packaging-api.md # Phase 1: REST contracts
├── quickstart.md        # Phase 1: validation guide
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/
├── alembic/versions/
│   ├── 20261026_packaging_advisor_v1.py     # NEW: MVP columns
│   └── 20261026_packaging_advisor_v2.py     # NEW: Phase 2 tables/columns + RLS
├── app/
│   ├── models/
│   │   ├── model.py, product.py, product_variant.py   # EXTEND: dimensions (+ fragile, variant packaging)
│   │   ├── model_file.py                              # EXTEND: measurement
│   │   ├── consumable.py                              # EXTEND: packaging attrs; usage.order_id
│   │   ├── shipping_profile.py                        # EXTEND: size limits, divisor, covers(parcel)
│   │   └── order_parcel.py                            # NEW: OrderParcel, OrderParcelItem
│   ├── schemas/
│   │   ├── dimensions.py                              # NEW: DimensionsIn/Out, PackagingSettings
│   │   ├── packaging.py                               # NEW: suggestion + parcel schemas
│   │   └── product.py, model.py, model_file.py, consumable.py, shipping_profile.py, order.py  # EXTEND
│   ├── services/
│   │   ├── dims.py                                    # NEW: Dims and Parcel value types (fit, rotations, volume)
│   │   ├── mesh_bounds.py                             # NEW: STL/3MF bounding boxes
│   │   ├── item_dimensions.py                         # NEW: effective dims/packaging, adopt measurement
│   │   ├── packaging_advisor.py                       # NEW: pure advisor + order packing
│   │   ├── order_parcel_service.py                    # NEW: confirm parcels, usage, postage
│   │   ├── model_file_service.py                      # EXTEND: measure on upload
│   │   ├── postage.py                                 # EXTEND: Parcel, packed weight, size classes
│   │   ├── provenance.py                              # EXTEND: register shipping profile limits
│   │   ├── print_queue_service.py                     # EXTEND: bed fit
│   │   └── etsy_sync.py                               # EXTEND: L×W×H
│   ├── tasks/
│   │   └── mesh_measure.py                            # NEW: Celery task for files > 25 MB
│   └── api/v1/
│       ├── packaging.py                               # NEW: suggestions, accept, dimensions PUTs
│       ├── settings.py                                # EXTEND: /settings/packaging
│       ├── orders.py                                  # EXTEND: suggestions, POST parcels
│       └── model_files.py, consumables.py, shipping_profiles.py  # EXTEND fields
├── scripts/postage_delta_report.py                    # NEW (Phase 2 release)
└── tests/
    ├── fixtures/meshes/                               # NEW: STL/3MF fixtures
    ├── unit/test_mesh_bounds.py, test_packaging_advisor.py, test_postage_parcel.py
    └── api/test_packaging_api.py, test_order_parcels_api.py

frontend/src/
├── types/packaging.ts                                 # NEW
├── lib/api/packaging.ts                               # NEW
├── hooks/usePackaging.ts                              # NEW
└── components/
    ├── products/DimensionsEditor.tsx                  # NEW (products, models, variants)
    ├── products/PackagingSuggestions.tsx              # NEW: ranked list + accept
    ├── products/ProductDetail.tsx                     # EXTEND
    ├── models/ModelDetail.tsx, ModelFilesEditor.tsx   # EXTEND: dims, measurement offer
    ├── inventory/AddConsumableDialog.tsx, EditConsumableDialog.tsx  # EXTEND: packaging fields
    ├── settings/PackagingSettings.tsx                 # NEW
    ├── settings/ShippingProfilesPanel.tsx             # EXTEND: size limits, divisor
    └── orders/OrderParcelDialog.tsx, OrderDetail.tsx  # NEW/EXTEND: suggest + confirm at dispatch
```

**Structure Decision**: Existing web-application layout (`backend/app`,
`frontend/src`). New logic goes in services; routes stay thin. A dedicated
`api/v1/packaging.py` router keeps the 3,000-line `products.py` from growing.

## Delivery Order

1. **MVP-A** — migration v1, models, `item_dimensions`, dimension endpoints and
   editor (Story 1).
2. **MVP-B** — consumable packaging attributes, settings, advisor, suggestions
   and accept (Stories 2, 4).
3. **MVP-C** — `mesh_bounds`, measure on upload, adopt (Story 3).
4. **Phase 2-A** — migration v2, `Parcel`/`build_parcel` in postage, size
   classes, volumetric, packed weight for single-unit orders, container
   provenance, delta report run before release (Story 5 minus dispatch).
   Multi-unit orders keep weight-only postage until 2-B.
5. **Phase 2-B** — order packing, parcel confirmation, stock usage (Story 6,
   FR-036/037).
6. **Phase 2-C** — bed fit, Etsy (Story 7).

Each step is releasable on its own.

## Complexity Tracking

No constitution violations to justify.
