# Data Model: Packaging Advisor

**Feature**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

All lengths are millimetres as `Numeric(7,1)`, weights grams as `Numeric(8,1)`,
volumes millilitres as `Numeric(10,1)`. Python side is `Decimal` throughout.
Every table already carries `tenant_id` under RLS unless marked **new**.

## MVP (migration `packaging_advisor_v1`)

### `models` — EXTEND

| Column | Type | Null | Notes |
|---|---|---|---|
| `length_mm`, `width_mm`, `height_mm` | Numeric(7,1) | yes | outer size of the printed model |
| `dimensions_source` | String(10) | yes | `'entered'` \| `'measured'` |
| `dimensions_source_file_id` | UUID FK `model_files.id` | yes | `ON DELETE SET NULL`; set when `'measured'` |
| `dimensions_set_at` | timestamptz | yes | when the dimensions were set |

Constraints (same on `products` and `product_variants`):
- `ck_<table>_dims_all_or_none`: all three null, or all three `> 0`.
- `ck_<table>_dims_source`: `dimensions_source IS NULL` iff dimensions null;
  value in (`'entered'`, `'measured'`).

### `products` — EXTEND

Same five dimension columns as `models`, plus:

| Column | Type | Null | Notes |
|---|---|---|---|
| `is_fragile` | Boolean | no | default `false`; selects the fragile clearance (FR-020) |

`size_cm` is kept unchanged (FR-005).

### `product_variants` — EXTEND (clarification Q1)

Same five dimension columns (null = inherit the product's), plus:

| Column | Type | Null | Notes |
|---|---|---|---|
| `packaging_consumable_id` | UUID FK `consumable_types.id` | yes | `ON DELETE SET NULL`; null = inherit |
| `packaging_quantity` | Integer | yes | `> 0` when set; null = inherit |

Resolution: `effective_dimensions(variant)` = variant's if set, else the
product's. `effective_packaging(variant)` likewise. One helper in
`app/services/item_dimensions.py`, used by every reader.

### `model_files` — EXTEND (measurement, research D4)

| Column | Type | Null | Notes |
|---|---|---|---|
| `measured_length_mm`, `measured_width_mm`, `measured_height_mm` | Numeric(7,1) | yes | bounding box of the whole build |
| `measured_objects` | JSONB | yes | `[{"name": str, "length_mm": "40.0", ...}]`, decimal strings |
| `measured_at` | timestamptz | yes | |
| `measurement_note` | String(255) | yes | why not measured, or the multi-object warning |
| `measurement_status` | String(10) | yes | `'done'` \| `'pending'` (queued, file > 25 MB) \| `'skipped'` (> 200 MB, not a mesh) \| `'failed'` |

### `consumable_types` — EXTEND (research D5)

| Column | Type | Null | Notes |
|---|---|---|---|
| `packaging_kind` | String(12) | yes | `'box'` \| `'mailer'` \| `'void_fill'` \| `'wrap'` |
| `inner_length_mm`, `inner_width_mm`, `inner_height_mm` | Numeric(7,1) | yes | mailer height = max thickness |
| `wall_mm` | Numeric(5,1) | yes | wall thickness for outer size (Phase 2 postage) |
| `empty_weight_grams` | Numeric(8,1) | yes | |
| `fill_volume_ml` | Numeric(10,1) | yes | void fill only: volume one unit fills |

Constraints: kind in set; inner dims all-null or all `> 0`; `wall_mm`,
`empty_weight_grams`, `fill_volume_ml` `>= 0`. A box/mailer without all three
inner dimensions is "incomplete" and never suggested.

### Tenant settings (no schema change)

`tenants.settings["packaging"]`:
`{"clearance_mm": "10.0", "fragile_clearance_mm": "20.0"}` — decimal strings,
each `>= 0`, validated by `PackagingSettings` schema.

### Provenance registry

Two vocabularies, not to be confused: an item's `dimensions_source`
(`entered` / `measured`) describes dimensions, which are not cost inputs; the
pricing provenance (`observed` / `measured` / `policy` / `assumed`, side table
`pricing_input_provenance`) describes cost inputs.

MVP — add to `NOT_A_COST_INPUT` in `tests/unit/pricing/test_provenance_registry.py`:
- `model`: `length_mm`, `width_mm`, `height_mm` — "a dimension".
- `product`: same three — "a dimension".
- `consumable_type`: the three inner dims, `wall_mm` — "a dimension until
  Phase 2 prices postage from it"; `empty_weight_grams` — "a weight until
  Phase 2 prices postage from it"; `fill_volume_ml` — "a volume, not money".

Phase 2 — FR-038: move `inner_length_mm`, `inner_width_mm`,
`inner_height_mm`, `wall_mm`, `empty_weight_grams` out of `NOT_A_COST_INPUT`
into `app/services/provenance.py` (`consumable_type`,
`default_source="assumed"`). The consumables API writes their provenance on
save (`measured` or `assumed`, chosen by the operator). `fill_volume_ml`
stays excluded.

## Phase 2 (migration `packaging_advisor_v2`)

### `shipping_profiles` — EXTEND (research D9)

| Column | Type | Null | Notes |
|---|---|---|---|
| `max_length_mm`, `max_width_mm`, `max_height_mm` | Numeric(7,1) | yes | all-null or all `> 0`; compared sorted |
| `volumetric_divisor` | Numeric(8,1) | yes | `> 0`; cm³ ÷ divisor = kg |

Registered in `app/services/provenance.py` under `shipping_profile` with
`default_source="policy"`. Effective-dated with the existing row
(`effective_from`/`effective_to`).

### `order_parcels` — **NEW**

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID PK | no | |
| `tenant_id` | UUID FK `tenants.id` | no | RLS `tenant_isolation_policy` |
| `order_id` | UUID FK `orders.id` | no | `ON DELETE CASCADE` |
| `sequence` | Integer | no | 1..n within the order; unique `(order_id, sequence)` |
| `outer_length_mm`, `outer_width_mm`, `outer_height_mm` | Numeric(7,1) | yes | as confirmed |
| `packed_weight_grams` | Numeric(10,1) | yes | null when any weight unknown |
| `confirmed_by_user_id` | UUID FK `users.id` | yes | `SET NULL` |
| `confirmed_at` | timestamptz | no | |

Written once (FR-036). No update endpoint.

### `order_parcel_items` — **NEW**

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID PK | no | |
| `tenant_id` | UUID FK | no | RLS |
| `order_parcel_id` | UUID FK `order_parcels.id` | no | `CASCADE` |
| `consumable_type_id` | UUID FK `consumable_types.id` | no | `RESTRICT` (history) |
| `quantity` | Integer | no | `> 0` |

### `consumable_usage` — EXTEND

| Column | Type | Null | Notes |
|---|---|---|---|
| `order_id` | UUID FK `orders.id` | yes | `SET NULL`; set for `usage_type='shipping'` |

`usage_type` gains the value `'shipping'` (documented in the column comment;
no check constraint exists today).

## Value objects (not stored)

- `Dims(length, width, height)` — `Decimal`, with `sorted()` and `volume_ml`.
- `Container(id, name, kind, inner: Dims, wall, empty_weight, in_stock, unit_cost_key)`.
- `Suggestion(container, orientation, room: Dims, empty_volume_ml, void_fill, wrap, warnings)`.
- `Advice(suggestions, minimum_inner: Dims | None, warnings)`.
- `OrderAdvice(parcels: [ (container, contents) ], warnings)`.
- `Parcel(grams | None, outer: Dims | None, reasons)` — postage input, defined
  with `Dims` in `app/services/dims.py`, built only by `postage.build_parcel`
  (estimate and dispatch alike).

## Shipping profile selection order (Phase 2)

Within the zone and date in force: size-limited profiles first, by
`postage_cost` ascending; then unlimited profiles by
`weight_bracket_min_grams` (today's order). First profile that `covers`
the parcel wins.

## State

```text
Product dimensions:  none ──operator saves──▶ entered
                     none ──upload measured──▶ measured
                     measured ──operator saves/adopts──▶ entered | measured
                     entered ──upload──▶ entered (offer only)

Order parcel:        none ──POST /parcels──▶ confirmed (immutable)
```
