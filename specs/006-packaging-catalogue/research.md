# Research: Packaging Page and Default Packaging and Postage Catalogue

## D1. Where packaging lives

- **Decision**: packaging stays a `ConsumableType` with a `packaging_kind`. The Packaging page is a
  filtered view (`GET /consumables/types?packaging_kind=box,mailer,void_fill,wrap`); the
  Consumables page asks `exclude_packaging=true`.
- **Rationale**: the packaging advisor, `build_parcel`, purchases, stock and usage already read
  `ConsumableType`; a parallel table would duplicate all of it (Constitution III).
- **Alternatives**: a `PackagingItem` table (rejected: duplicates stock/purchases); a category
  string "packaging" (rejected: `packaging_kind` is already the authoritative marker).

## D2. Catalogue format and location

- **Decision**: JSON files in `backend/app/data/`: `packaging_catalogue.json` (one version number,
  a list of items) and `postage_tariffs/<carrier>/<effective_date>.json`. Loaded and validated by
  Pydantic models in `services/catalogue_data.py` at first use; invalid data raises at load time
  and is caught by a unit test that loads every file.
- **Rationale**: versioned with the code, reviewable in diffs, no DB reference tables to migrate,
  identical for every tenant, works on VPS installs offline.
- **Alternatives**: DB reference tables (rejected: one more migration per tariff); YAML (rejected:
  JSON keeps numbers as strings explicitly, no implicit typing).

## D3. Identity of a seeded item (idempotence)

- **Decision**: `consumable_types.catalogue_key` (e.g. `box-s-150x100x50`), unique per tenant when
  not null. An item is present if a row has that key, or if an active row has the same
  `packaging_kind` and the same name (case-insensitive) → skipped with reason `name_in_use`.
  Seeding only inserts; it never updates an existing row, so operator edits are never touched.
  A tenant-level record `settings.catalogue_seed.packaging.version` stores the last version
  applied; the release step skips a tenant already at the current version, so an item the operator
  deleted is not re-created automatically (re-adding stays possible from the page).
- **Shipping profiles**: `shipping_profiles.catalogue_carrier` + `service` + `tariff_version`
  identify seeded rows. A profile is skipped when an existing profile in force for the same zone
  overlaps its weight bracket and dates (the same rule `shipping_profiles.py` already enforces).

## D4. Provenance of seeded figures

- **Decision**: after inserting, call `provenance.record_origin(..., source="assumed",
  as_of=<catalogue or tariff date>)` for every registered field. Register `fill_volume_ml` for
  `consumable_type`. Shipping profile fields are recorded `assumed` explicitly (their registry
  default is `policy`, which would claim the operator decided them).
- **Rationale**: FR-013/FR-019; reuses `pricing_input_provenance`, which the margin breakdown's
  observed share already reads, so "assumed packaging cost" surfaces in the margin with no new
  code path (FR-014).
- An operator edit goes through `record_operator_write`, which relabels only the edited fields.

## D5. Typical cost per currency

- **Decision**: each catalogue item carries `typical_cost: {"CAD": "1.10", "GBP": "0.65",
  "USD": "0.85", "EUR": "0.75"}`; the seeding uses the tenant's `currency_code`; no entry → item
  seeded without cost (margin reports packaging cost missing, existing behaviour).
- **Source**: supplier list prices (e.g. Uline/ULINE.ca, Packaging Express, Raja, Instapak) at the
  catalogue date, recorded per item in `source`. Figures are transcribed during implementation
  (task) and reviewed; they are assumptions by definition.

## D6. Carrier, services and tariffs

- **Decision**: four carriers, services per clarification Q2:
  - `canada_post` (CAD): `lettermail`, `small_packet`, `expedited_parcel`
  - `royal_mail` (GBP): `large_letter`, `small_parcel`, `medium_parcel`
  - `la_poste` (EUR): `lettre_suivie`, `colissimo`
  - `usps` (USD): `ground_advantage`, `priority_mail`
- Each tariff file: carrier, currency, effective_date, source (document title + URL), and per
  service: zones (`domestic` + the carrier's main international groups, e.g. `us`, `international`
  for Canada Post; `europe`, `world_1`, `world_2` for Royal Mail), weight brackets (grams),
  `max_length/width/height_mm`, `volumetric_divisor` where the carrier applies one, price per
  bracket as a decimal string.
- **Sources** (to transcribe in the implementation task, recording the exact document):
  Canada Post "Postage rates and prices" guide; Royal Mail "Our prices" (online/retail price
  list); La Poste "Tarifs des envois" (Lettre suivie, Colissimo); USPS Notice 123 price list.
- **Rationale**: tariffs change yearly; files are versioned by effective date so a new file is a
  new offer (D8), never an edit.
- **Zone naming**: zones keep the profile's existing free-text `destination_zone`, seeded with the
  stable keys above so `zone_for_destination` keeps matching by exact name.

## D7. Carrier for a shop (country first, then currency)

- **Decision** (clarifications Q5, Q6): one resolver `carrier_for_tenant(tenant) ->
  CarrierChoice(carrier | None, chosen_from: "country" | "currency", reason | None)` in
  `services/catalogue_data.py`, used by onboarding, the release step and `GET /postage/carriers`
  (Constitution III: one implementation). With `tenants.country_code` set:
  `CA→canada_post`, `GB→royal_mail`, `US→usps`, `FR→la_poste`; any other country → none,
  `reason = no_carrier_for_country` (the currency is NOT used as a fallback: a Belgian EUR shop
  would otherwise get La Poste domestic rates for Belgium). Without a country:
  `CAD→canada_post`, `GBP→royal_mail`, `USD→usps`, `EUR→la_poste`; other currencies → none,
  `reason = no_carrier_for_currency`. A carrier whose currency differs from the books currency →
  none, `reason = carrier_currency_mismatch`. Changing the country re-seeds nothing; the panel
  then suggests the new carrier and the operator switches (supersede).
- **Alternatives**: country with currency fallback (rejected: wrong domestic zone for a country
  the carrier does not serve); derive country from timezone (rejected: unreliable). All services of the carrier
  are seeded at release; the operator can remove services or switch carrier later
  (`POST /postage/carriers/apply`), which supersedes the seeded rows of the previous carrier.
  New shops pick the carrier/services in onboarding step 5 (pre-selected by `carrier_for_tenant`).

## D8. New tariff (supersede)

- **Decision**: `GET /postage/tariff-updates` compares the tenant's seeded `tariff_version` per
  carrier with the newest file; the panel offers it. Accepting sets `effective_to = new
  effective_date - 1 day` on the tenant's current seeded rows of that carrier still in force and
  inserts the new rows `effective_from = new effective_date` (or today if already past). Operator
  rows (no `catalogue_carrier`) are never touched. Orders keep `freeze_order_postage` snapshots.

## D9. Default service and product override

- **Decision**: `tenant.settings["postage"] = {"carrier": str, "default_service": str|null}`;
  `products.postage_service` (nullable, `"<carrier>:<service>"`). `postage._price` gains
  `preferred_service`; candidates of that service that cover the parcel are tried first, else the
  existing order (sized cheapest, then weight-only) and the result carries note
  `preferred_service_does_not_fit`. `postage_for_order`/`postage_for_product` resolve the
  preference (single-product order: product override, else tenant default; multi-product order:
  tenant default). No preference → behaviour unchanged.
- **Alternatives**: always cheapest (rejected in Q2).

## D10. Automatic seeding at release

- **Decision**: `python -m app.cli.seed_catalogues --all-tenants` runs after `alembic upgrade
  heads` in the backend init container (k3s), in the VPS update command (spec 005) and in the
  deploy-dev skill. It takes a PostgreSQL advisory lock, processes each tenant in its own
  transaction, is idempotent (D3), and only seeds tenants whose recorded catalogue/tariff version is
  older than the shipped one. Failure of one tenant is logged and does not block others or startup.
- `--dry-run --report <path>` runs the same seeding inside a savepoint that is always rolled back
  (pattern of `scenario_service.py`) and writes the per-product postage before/after for every
  zone (reusing `postage_delta_report.py`'s columns) — the constitution's delta report, produced
  against a production copy before the release is accepted (FR-018a).
- **Alternatives**: Alembic data migration (rejected: migrations must not import evolving app
  code, and a frozen SQL copy of the seeding would be a second implementation); seeding on app
  startup (rejected: runs in every replica and on every restart).

## D11. Service fit shown on the Packaging page

- **Decision**: `postage.services_fitting(container, profiles)` returns the services whose size
  limits accept the container's outer size (inner + 2×wall), computed on read; `ConsumableTypeResponse`
  gains `fits_services: list[str]` for container kinds, filled by the list endpoint from one
  profile query per request.

## D12. Units

- **Decision**: catalogue and API stay in mm and g (existing convention). Displaying inches/oz for
  USPS shops is out of scope (deferred in clarification).
