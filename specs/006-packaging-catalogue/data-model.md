# Data Model: Packaging Page and Default Packaging and Postage Catalogue

All new columns are nullable; existing rows are unaffected. One Alembic migration
(`<rev>_catalogue_columns.py`) adds them; downgrade drops them (lossless for operator data: the
dropped values only identify seeded rows).

## tenants (existing — `Tenant`)

| Column | Type | Rule |
|---|---|---|
| `country_code` | `VARCHAR(2)` NULL | ISO 3166-1 alpha-2, upper case; NULL = not recorded (every existing shop) |

- CHECK `ck_tenants_country_code`: `country_code IS NULL OR country_code ~ '^[A-Z]{2}$'`.
- Set through `TenantUpdate` (general settings) and onboarding step 3, like `currency_code`.
- Only chooses the carrier (research D7); it stores no derived figure.

## consumable_types (existing — `ConsumableType`)

| Column | Type | Rule |
|---|---|---|
| `catalogue_key` | `VARCHAR(64)` NULL | Key of the catalogue entry the row was seeded from; NULL for operator rows |
| `catalogue_version` | `INTEGER` NULL | Catalogue version that seeded it |

- Partial unique index `uq_consumable_types_tenant_catalogue_key` on `(tenant_id, catalogue_key)
  WHERE catalogue_key IS NOT NULL`.
- Existing packaging columns unchanged: `packaging_kind` (box, mailer, void_fill, wrap),
  `inner_length/width/height_mm`, `wall_mm`, `empty_weight_grams`, `fill_volume_ml`,
  `current_cost_per_unit`.
- Response-only (derived on read, not stored): `fits_services: list[str]` (container kinds),
  `from_catalogue: bool` (`catalogue_key is not null`).

## shipping_profiles (existing — `ShippingProfile`)

| Column | Type | Rule |
|---|---|---|
| `catalogue_carrier` | `VARCHAR(32)` NULL | `canada_post`, `royal_mail`, `la_poste`, `usps`; NULL for operator rows |
| `service` | `VARCHAR(64)` NULL | Service key within the carrier (`small_packet`, …); also settable on operator rows |
| `tariff_version` | `DATE` NULL | Effective date of the tariff file that seeded the row |
| `source` | `VARCHAR(255)` NULL | Human-readable source (document title and date/URL) |

- Index `ix_shipping_profiles_tenant_carrier` on `(tenant_id, catalogue_carrier, tariff_version)`.
- Supersede (D8): seeded rows get `effective_to`; new rows inserted. Never `UPDATE` of price,
  bracket or limits.
- CHECK: `catalogue_carrier IS NULL OR (service IS NOT NULL AND tariff_version IS NOT NULL)`.

## products (existing — `Product`)

| Column | Type | Rule |
|---|---|---|
| `postage_service` | `VARCHAR(100)` NULL | `"<carrier>:<service>"` override of the shop default; NULL = shop default |

Validated on write against the tenant's profiles in force (422 if no profile has that service).

## tenants.settings (JSONB, existing)

```json
{
  "postage": {"carrier": "canada_post", "default_service": "small_packet"},
  "catalogue_seed": {
    "packaging": {"version": 1, "applied_at": "2026-11-10",
                  "added": ["box-s-150x100x50", "..."],
                  "skipped": [{"key": "mailer-a5", "reason": "name_in_use"}],
                  "acknowledged": false},
    "postage": {"carrier": "canada_post", "tariff_version": "2026-01-12",
                "added": 42, "skipped": [{"service": "small_packet", "zone": "domestic", "reason": "overlaps_existing"}],
                "reason": null, "acknowledged": false}
  }
}
```

- `postage.reason` is set when nothing was seeded (`no_carrier_for_country`,
  `no_carrier_for_currency`, `carrier_currency_mismatch`); `postage.chosen_from` is `country` or
  `currency`.
- Written only through `TenantSettingsService`.

## pricing_input_provenance (existing)

- Registry gains `("consumable_type", "fill_volume_ml")`.
- Seeding writes one row per registered field of each seeded entity with `source='assumed'`,
  `as_of` = catalogue date (packaging) or tariff effective date (postage).

## Reference data (files, not tables)

### Packaging catalogue entry (`packaging_catalogue.json` → `items[]`)

| Field | Type | Rule |
|---|---|---|
| `key` | str | unique, kebab-case, ≤ 64 |
| `name` | str | display name |
| `kind` | `box`/`mailer`/`void_fill`/`wrap` | |
| `inner_length_mm`, `inner_width_mm`, `inner_height_mm` | decimal str | required for box/mailer, absent otherwise |
| `wall_mm` | decimal str | box/mailer |
| `empty_weight_grams` | decimal str | all kinds (void fill: per unit) |
| `fill_volume_ml` | decimal str | void_fill/wrap |
| `unit_of_measure` | str | `each`, `bag`, `m` |
| `typical_cost` | map currency→decimal str | optional per currency |
| `source` | str | supplier reference |

Top level: `version` (int), `as_of` (date). Minimums (FR-009): ≥ 8 boxes, ≥ 3 mailers, ≥ 3
void_fill/wrap.

### Carrier tariff (`postage_tariffs/<carrier>/<YYYY-MM-DD>.json`)

| Field | Type |
|---|---|
| `carrier`, `currency`, `effective_date`, `source` | str / date |
| `services[]` | `{key, name, volumetric_divisor?, max_length_mm?, max_width_mm?, max_height_mm?, zones[]}` |
| `zones[]` | `{zone, brackets[]: {min_grams, max_grams|null, price}}` |

Validation: currency matches carrier; brackets per zone non-overlapping and ascending; prices > 0;
size limits all-or-none (same rule as the `shipping_profiles` CHECK).

## State transitions

- Seeded item: `seeded (assumed)` → `edited (operator)` per field via provenance; never re-seeded
  over.
- Seeded profile: `in force` → `superseded` (effective_to set) when a new tariff or another
  carrier is accepted.
- Catalogue notice: `acknowledged=false` → `true` when the operator dismisses it.
