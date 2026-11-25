# API Contracts: Packaging Page and Default Catalogue

All routes are under `/api/v1`, require a bearer token (401 otherwise), resolve the tenant with
`get_current_tenant` and use the tenant DB session. Writes require a member/admin/owner role (403
for viewers), as for consumables and postage today. Money and measures are decimal strings.

## Existing routes, extended

### GET /consumables/types

New query parameter `exclude_packaging: bool = false` → only rows with `packaging_kind IS NULL`.
Existing `packaging_kind` (comma list) unchanged. Response items gain:

```json
{ "from_catalogue": true, "catalogue_key": "box-s-150x100x50",
  "fits_services": ["canada_post:small_packet", "canada_post:expedited_parcel"] }
```

`fits_services` is `[]` for void fill/wrap and for a container without inner size.

### PUT /settings/tenant (existing `TenantUpdate`)

Accepts `country_code: "CA" | null` (ISO 3166-1 alpha-2; lower case is upper-cased; 422 on any
other shape). Tenant response includes `country_code`. Changing it re-seeds nothing.

### PUT /onboarding/wizard/step/3

Request gains `country: "FR" | null` (same rule). Step 5 then pre-selects the carrier from it.

### PUT /products/{id}

Accepts `postage_service: "<carrier>:<service>" | null`. 422 when no profile in force for the
tenant has that service. Product response includes `postage_service`.

### GET /modules

Module `consumables` declares two routes: `/consumables` ("Consumables", `wrench`) and
`/packaging` ("Packaging", `package-open`).

## New routes

### GET /packaging/catalogue → 200

```json
{ "version": 1, "as_of": "2026-11-01",
  "items": [ { "key": "box-s-150x100x50", "name": "Box S 150×100×50", "kind": "box",
               "inner_length_mm": "150", "inner_width_mm": "100", "inner_height_mm": "50",
               "wall_mm": "3", "empty_weight_grams": "60", "fill_volume_ml": null,
               "typical_cost": "0.95", "present": true, "present_as": "uuid-or-null",
               "previously_removed": false } ] }
```

`typical_cost` is for the tenant's currency or null. `previously_removed` is true when the key is in
`settings.catalogue_seed.packaging.added` but no row carries it any more (edge case: re-adding a
deleted item).

### POST /packaging/catalogue/apply → 200

Request `{ "keys": ["box-s-150x100x50", ...] }` (empty or absent = all). 422 on an unknown key.

```json
{ "added": [{"key": "...", "id": "uuid"}],
  "skipped": [{"key": "...", "reason": "already_present" | "name_in_use"}] }
```

### GET /catalogue-notice → 200

Returns `settings.catalogue_seed` with only unacknowledged parts (`{}` when none).

### POST /catalogue-notice/acknowledge → 204

Request `{ "part": "packaging" | "postage" }`. 422 on another value.

### GET /postage/carriers → 200

```json
{ "suggested_carrier": "canada_post", "chosen_from": "country" | "currency",
  "reason": null | "no_carrier_for_country" | "no_carrier_for_currency" | "carrier_currency_mismatch",
  "current": {"carrier": "canada_post", "default_service": "small_packet", "tariff_version": "2026-01-12"},
  "carriers": [ { "key": "canada_post", "name": "Canada Post", "currency": "CAD",
                  "usable": true, "latest_tariff": "2026-01-12", "source": "...",
                  "services": [{"key": "small_packet", "name": "Small Packet", "seeded": true}] } ] }
```

`usable` is false when the carrier's currency differs from the tenant's.

### POST /postage/carriers/apply → 200

Request `{ "carrier": "canada_post", "services": ["small_packet", "expedited_parcel"],
"tariff_version": "2026-01-12" | null }` (null = latest). 422: unknown carrier/service, carrier
currency ≠ tenant currency. 404: unknown tariff version. Effect: seeds the services (skipping
overlaps); when another carrier's seeded rows are in force, supersedes them; records
`settings.postage.carrier`.

```json
{ "added": 24, "superseded": 0,
  "skipped": [{"service": "small_packet", "zone": "domestic", "min_grams": "0", "reason": "overlaps_existing"}] }
```

### GET /postage/tariff-updates → 200

```json
{ "updates": [ { "carrier": "canada_post", "current": "2026-01-12", "latest": "2027-01-11",
                 "effective_from": "2027-01-11", "source": "..." } ] }
```

Accepting = `POST /postage/carriers/apply` with that `tariff_version` (supersede, D8).

### DELETE /postage/carriers/services/{service} → 204

Removes a seeded service (FR-018): sets `effective_to` on that service's seeded rows in force (never
deletes, never touches operator rows). 404 when no seeded row in force has that service; 403 viewers.
If it was the shop default, the default is cleared.

### PUT /settings/postage → 200

Request `{ "default_service": "canada_post:small_packet" | null }`. 422 when no profile in force
has that service. Response `{ "carrier": "...", "default_service": "..." }`.

### PUT /onboarding/wizard/step/5 → 200

Request:

```json
{ "packaging_keys": ["..."] | null, "carrier": "canada_post" | null,
  "services": ["small_packet"] | null, "default_service": "canada_post:small_packet" | null,
  "skip": false }
```

`skip=true` seeds nothing. Seeding failures do not fail the step: the response carries
`warnings` and the step completes (FR-015). Returns the standard `OnboardingStepResponse` plus
`seed: {packaging: {...}, postage: {...}}`.

## Error shape

Unchanged FastAPI `{"detail": "..."}` with operator-readable text (bug postage-error-raw-json).
