---

description: "Task list for the Packaging page and default packaging and postage catalogue"
---

# Tasks: Packaging Page and Default Packaging and Postage Catalogue

**Input**: Design documents from `specs/006-packaging-catalogue/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, contracts/catalogue-files.md, quickstart.md

**Tests**: Required. The constitution (II) makes tests part of every change: each endpoint covers 200/201, 401, 422, 404; business logic covers success, edge and error paths; schema changes cover CRUD and constraints.

**Organization**: Tasks are grouped by user story (spec.md US1 P1, US2 P2, US3 P3).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1, US2, US3
- Paths are relative to the repository root (`backend/app`, `frontend/src`)

---

## Phase 1: Setup

**Purpose**: Directories and the reference-data loader every story reads

- [ ] T001 Create `backend/app/data/__init__.py`, `backend/app/data/postage_tariffs/` and `backend/app/cli/__init__.py`; make sure `backend/Dockerfile` copies `app/data/**` into the image (it copies `app/` already — verify JSON files are not excluded by `.dockerignore`)
- [ ] T002 [P] Add Pydantic models and loaders in `backend/app/services/catalogue_data.py`: `PackagingCatalogue` (`version: int`, `as_of: date`, `items`), `PackagingCatalogueItem` (`key` unique kebab-case "≤ 64", `kind` in box/mailer/void_fill/wrap, decimal-string figures "> 0", box/mailer require `inner_length_mm`, `inner_width_mm`, `inner_height_mm`, `wall_mm`, `empty_weight_grams`; void_fill/wrap require `fill_volume_ml` and forbid inner sizes, `typical_cost` keys limited to CAD/GBP/USD/EUR), `CarrierTariff` (`carrier`, `currency` fixed per carrier CAD/GBP/EUR/USD, `effective_date` equal to the file name, `services[].zones[].brackets[]` ascending and non-overlapping, last bracket may have `max_grams: null`, size limits all-or-none), `load_packaging_catalogue()`, `load_tariffs(carrier=None)`, `latest_tariff(carrier)`, `CARRIER_FOR_COUNTRY = {"CA": "canada_post", "GB": "royal_mail", "US": "usps", "FR": "la_poste"}`, `CARRIER_FOR_CURRENCY = {"CAD": "canada_post", "GBP": "royal_mail", "USD": "usps", "EUR": "la_poste"}` and the single resolver `carrier_for(country_code, currency_code) -> CarrierChoice(carrier | None, chosen_from, reason)` per research D7 (country first, no currency fallback when a country is set; `carrier_currency_mismatch` when the carrier's currency ≠ books currency); cache with `functools.lru_cache`
- [ ] T003 [P] Unit tests for the loader in `backend/tests/unit/test_catalogue_data.py`: every shipped file loads; FR-009 minimums (≥ 8 boxes, ≥ 3 mailers, ≥ 3 void_fill/wrap); each invalid case (duplicate key, box without wall, void fill with inner size, overlapping brackets, wrong currency for carrier, file name ≠ `effective_date`, placeholder price such as `"..."`) raises; `carrier_for` cases: FR+EUR → la_poste/country, None+EUR → la_poste/currency, BE+EUR → none/`no_carrier_for_country`, CA+USD → none/`carrier_currency_mismatch`, None+AUD → none/`no_carrier_for_currency`

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: Schema, provenance registry and the seeding service shared by US2 and US3

- [ ] T004 Add columns to models: `country_code: VARCHAR(2) NULL` on `Tenant` in `backend/app/models/tenant.py` with CHECK `ck_tenants_country_code` `country_code IS NULL OR country_code ~ '^[A-Z]{2}$'`; `catalogue_key: VARCHAR(64) NULL`, `catalogue_version: INTEGER NULL` on `ConsumableType` in `backend/app/models/consumable.py` with partial unique index `uq_consumable_types_tenant_catalogue_key` on `(tenant_id, catalogue_key) WHERE catalogue_key IS NOT NULL`; `catalogue_carrier: VARCHAR(32) NULL`, `service: VARCHAR(64) NULL`, `tariff_version: DATE NULL`, `source: VARCHAR(255) NULL` on `ShippingProfile` in `backend/app/models/shipping_profile.py` with index `ix_shipping_profiles_tenant_carrier (tenant_id, catalogue_carrier, tariff_version)` and CHECK `catalogue_carrier IS NULL OR (service IS NOT NULL AND tariff_version IS NOT NULL)`; `postage_service: VARCHAR(100) NULL` on `Product` in `backend/app/models/product.py`
- [ ] T005 Alembic migration `backend/alembic/versions/<rev>_catalogue_columns.py` for T004 (upgrade adds, downgrade drops; `down_revision` = the single head reported by `poetry run alembic heads` at implementation time — today `model_file_versions_v1`, from the uncommitted model-file-versions work; never fork a second head); verify a fresh database reaches head
- [ ] T006 [P] Schema tests in `backend/tests/unit/test_catalogue_columns.py`: CRUD of the new columns, the partial unique index (two NULL keys allowed, duplicate key per tenant refused, same key in two tenants allowed), the shipping profile CHECK, the tenant `country_code` CHECK (NULL and `FR` accepted, `fr`/`FRA` refused)
- [ ] T007 [P] Register `("consumable_type", "fill_volume_ml", "Volume one unit of void fill or wrap fills")` in `backend/app/services/provenance.py` and add a test in `backend/tests/unit/test_provenance_registry.py` (or the existing registry test file)
- [ ] T008 Create the seeding service `backend/app/services/catalogue_seed.py` skeleton: `SeedResult` dataclasses (`added`, `skipped` with `reason`), tenant notice writer `record_notice(db, tenant, part, result)` storing `settings.catalogue_seed.<part>` through `TenantSettingsService` with `acknowledged: false`, and `acknowledge(db, tenant, part)`; unit tests in `backend/tests/unit/test_catalogue_seed.py` for the notice round trip

**Checkpoint**: schema migrated, loader validated, seeding service shell in place.

---

## Phase 3: User Story 1 — Packaging page (Priority: P1) 🎯 MVP

**Goal**: operators find and manage boxes, mailers and void fill on their own page; Consumables keeps hardware.

**Independent Test**: open Packaging from the navigation, add a box, see it suggested for a product that fits; Consumables does not list it.

### Tests for User Story 1

- [ ] T009 [P] [US1] API tests in `backend/tests/api/test_consumables_packaging_filter.py`: `GET /api/v1/consumables/types?exclude_packaging=true` returns only rows with `packaging_kind IS NULL`; `packaging_kind=box,mailer,void_fill,wrap` returns only packaging; response carries `from_catalogue` and `catalogue_key`; an existing packaging row created before this feature (no `catalogue_key`) is listed unchanged (FR-025); 401 without token; 422 on `exclude_packaging=maybe`
- [ ] T010 [P] [US1] Module nav test in `backend/tests/api/test_modules_consumables_route.py`: `/packaging` declared with label "Packaging" and icon `package-open` by the `consumables` module
- [ ] T011 [P] [US1] Frontend tests `frontend/src/pages/Packaging.test.tsx` and `frontend/src/components/packaging/PackagingList.test.tsx`: lists only packaging; box shows inner size, wall, empty weight, stock, cost, used-by products; void fill shows fill volume; a box without inner size shows "incomplete" with the reason; "Add box" opens the form in Box mode; viewer sees no add/edit/delete
- [ ] T012 [P] [US1] Frontend test `frontend/src/components/inventory/ConsumableList.test.tsx`: the list requests `exclude_packaging=true` and shows no box

### Implementation for User Story 1

- [ ] T013 [US1] Add `exclude_packaging: bool = Query(False)` to `list_consumable_types` and `from_catalogue`/`catalogue_key` to `consumable_type_to_response` in `backend/app/api/v1/consumables.py`; add the fields to `ConsumableTypeResponse` in `backend/app/schemas/consumable.py`
- [ ] T014 [US1] Declare `{"path": "/packaging", "label": "Packaging", "icon": "package-open"}` under `MODULE_NAVIGATION["consumables"]` in `backend/app/api/v1/modules.py`
- [ ] T015 [P] [US1] Frontend API/types: add `exclude_packaging` to the consumables list params and `from_catalogue`, `catalogue_key`, `fits_services?` to the consumable type in `frontend/src/types/consumable.ts` and `frontend/src/lib/api/consumables.ts`
- [ ] T016 [US1] `AddConsumableDialog` packaging mode in `frontend/src/components/inventory/AddConsumableDialog.tsx`: props `presetKind?: PackagingKind` and `packagingOnly?: boolean` — preset the kind, show name, `PackagingFieldsSection`, cost, stock, unit, supplier; hide hardware-only fields; title "Add box/mailer/void fill/wrap"
- [ ] T017 [US1] `PackagingList` in `frontend/src/components/packaging/PackagingList.tsx`: table of packaging consumables (`packaging_kind=box,mailer,void_fill,wrap`), columns per kind (FR-003), "default" badge per figure whose provenance is `assumed` (from `packaging_provenance`), "incomplete" badge from `packaging_incomplete`, used-by products, edit/delete via existing `EditConsumableDialog`/`DeleteConsumableDialog`; add buttons per kind opening `AddConsumableDialog` in packaging mode; read-only for viewers (`canEditOperationalFigures`)
- [ ] T018 [US1] Page and route: `frontend/src/pages/Packaging.tsx` (AppLayout + PackagingList), `/packaging` route in `frontend/src/App.tsx` wrapped in `ProtectedRoute` + `ModuleGuard`; `package-open` icon in the icon map and `/packaging` in the fallback nav of `frontend/src/components/layout/AppLayout.tsx`
- [ ] T019 [US1] Consumables page excludes packaging: request `exclude_packaging: true` in `frontend/src/components/inventory/ConsumableList.tsx`; keep the subtitle "magnets, inserts, hardware"; add a one-line link "Boxes and mailers are on the Packaging page"
- [ ] T020 [US1] Link from `frontend/src/components/products/ProductPackagingCard.tsx` (and `PackagingSuggestions.tsx` when no container fits) to `/packaging` (FR-007); test in `frontend/src/components/products/ProductPackagingCard.test.tsx`
- [ ] T021 [US1] Ensure the packaging advisor ignores a box/mailer without inner dimensions (FR-006): add a regression test in `backend/tests/unit/test_packaging_advisor.py` (implementation change in `backend/app/services/packaging_advisor.py` only if the test fails)

**Checkpoint**: US1 deliverable on its own (operators add their own boxes).

---

## Phase 4: User Story 2 — Standard packaging catalogue (Priority: P2)

**Goal**: every shop starts with standard boxes, mailers and void fill, labelled as defaults, with a typical cost.

**Independent Test**: a new shop keeping defaults has the catalogue on Packaging, labelled "default"; a product with dimensions gets a catalogue box suggested.

### Tests for User Story 2

- [ ] T022 [P] [US2] Service tests in `backend/tests/unit/test_catalogue_seed.py`: seeds all items with `catalogue_key`/`catalogue_version`; every registered field recorded `assumed` with `as_of` = catalogue date; cost from the tenant currency, none when the currency has no `typical_cost` (FR-014); second run adds nothing (`already_present`); an active operator item with the same kind and name → `name_in_use`, untouched; a deleted seeded item is not re-created by the release step once the tenant is at the current version, but is re-created by an explicit apply; seeding never changes a product's accepted packaging (edge case); selection by keys; unknown key → error; failure leaves no partial rows (FR-015)
- [ ] T023 [P] [US2] API tests in `backend/tests/api/test_packaging_catalogue.py`: `GET /api/v1/packaging/catalogue` (200 with `present`, `previously_removed` true for a key seeded earlier and since deleted, `typical_cost` in tenant currency; 401); tenant isolation: tenant B never sees tenant A's seeded rows or notice (FR-024), `POST /api/v1/packaging/catalogue/apply` (200 added/skipped; 401; 403 viewer; 422 unknown key), `GET /api/v1/catalogue-notice` and `POST /api/v1/catalogue-notice/acknowledge` (204; 422 bad part; 401)
- [ ] T024 [P] [US2] Onboarding tests in `backend/tests/api/test_onboarding_step5.py`: step 5 with default selection seeds packaging (and postage, see US3); `skip=true` seeds nothing; a seeding error returns `warnings` and still completes the step; 401; 422 on an unknown key
- [ ] T025 [P] [US2] Frontend tests `frontend/src/components/packaging/CatalogueNotice.test.tsx` and `frontend/src/components/packaging/AddCatalogueDialog.test.tsx`: banner lists added/skipped with reasons and dismisses; dialog lists catalogue items with present ones disabled, marks previously removed ones "previously removed" so the operator can deselect them, and applies the selection

### Implementation for User Story 2

- [ ] T026 [US2] Write `backend/app/data/packaging_catalogue.json` (version 1, as_of): at least 8 corrugated boxes (cube and flat, small to large, sized for 3D-printed items), 3 mailers (padded and cardboard), 3 void fill/wrap (kraft paper, air pillows, bubble wrap), each with inner size, wall, empty weight or fill volume and `typical_cost` in CAD, GBP, USD, EUR transcribed from supplier list prices, `source` recorded per item; the T003 test must pass
- [ ] T027 [US2] Implement `seed_packaging(db, tenant, keys=None, *, release=False) -> SeedResult` in `backend/app/services/catalogue_seed.py` per research D3–D5: insert-only, identity by `catalogue_key` or active same kind+name, provenance via `provenance.record_origin(source="assumed")` for each registered field, cost from `typical_cost[tenant.currency_code]`, savepoint per call so a failure leaves nothing; `release=True` skips a tenant whose `settings.catalogue_seed.packaging.version` ≥ catalogue version and records the version
- [ ] T028 [US2] Schemas `backend/app/schemas/packaging_catalogue.py` and router `backend/app/api/v1/packaging_catalogue.py` (`GET /packaging/catalogue`, `POST /packaging/catalogue/apply`, `GET /catalogue-notice`, `POST /catalogue-notice/acknowledge`) per contracts/api.md; register in `backend/app/main.py` (and the consumables module routes in `backend/app/modules/threed_print/consumables.py` if routes are module-registered)
- [ ] T029 [US2] Onboarding step 5 in `backend/app/services/onboarding_wizard.py` (`LAST_STEP = 5`, `save_step5`), `backend/app/schemas/onboarding.py` (`OnboardingStep5Request`), `backend/app/api/v1/onboarding.py` (`PUT /wizard/step/5`); calls `seed_packaging` (and `seed_postage` once US3 lands); errors become `warnings`
- [ ] T030 [P] [US2] Frontend data layer: `frontend/src/types/packagingCatalogue.ts`, `frontend/src/lib/api/packagingCatalogue.ts`, `frontend/src/hooks/usePackagingCatalogue.ts` (catalogue, apply, notice, acknowledge; invalidate `consumables` queries after apply)
- [ ] T031 [US2] `frontend/src/components/packaging/CatalogueNotice.tsx` (one-time banner on Packaging) and `frontend/src/components/packaging/AddCatalogueDialog.tsx` ("Add standard packaging" button on Packaging); wire into `PackagingList.tsx`
- [ ] T032 [US2] Onboarding UI step 5 (packaging part) in `frontend/src/components/onboarding/PackagingPostageStep.tsx` and `frontend/src/pages/Onboarding.tsx`: catalogue list all selected, deselect, skip; test in `frontend/src/components/onboarding/PackagingPostageStep.test.tsx`
- [ ] T033 [US2] Margin shows an assumed or missing packaging cost (FR-014, US2 scenario 6): verify the product margin breakdown flags the packaging line's `assumed` source through the existing observed-share display, and that a seeded item without a cost (currency with no `typical_cost`) makes the margin say the packaging cost is missing; tests in `backend/tests/unit/test_costing_packaging_provenance.py` (and a frontend assertion in the product margin breakdown test if either flag is not shown)

**Checkpoint**: US1 + US2 deliverable (catalogue seeded via onboarding and the Packaging page).

---

## Phase 5: User Story 3 — Postage for the shop's carrier (Priority: P3)

**Goal**: every shop starts with dated postage for its carrier's services; a default service, overridable per product, drives the margin; new tariffs supersede.

**Independent Test**: choose services in onboarding (or run the release step for a CAD shop), see dated profiles in Settings → Postage, and a product margin using the default service, then the product override.

### Tests for User Story 3

- [ ] T034 [P] [US3] Service tests in `backend/tests/unit/test_catalogue_seed.py` (postage part): seeds one profile per service × zone × bracket with `catalogue_carrier`, `service`, `tariff_version`, `source`, fields recorded `assumed` with `as_of` = tariff date; skips brackets overlapping an existing in-force profile of the same zone and dates (`overlaps_existing`); currency without carrier → nothing, `reason = no_carrier_for_currency` (FR-022); switching carrier supersedes the previous carrier's seeded rows (`effective_to` set) and never touches operator rows; newer tariff supersedes (D8); release mode chooses the carrier with `carrier_for` (country first, else currency — D7; a country without carrier seeds nothing with `no_carrier_for_country`) and skips a tenant already at the latest tariff
- [ ] T035 [P] [US3] Postage preference tests in `backend/tests/unit/test_postage_preferred_service.py`: product override used when it fits; shop default used otherwise; preferred service not fitting → cheapest fitting with note `preferred_service_does_not_fit`; no preference → unchanged behaviour (existing tests still pass); multi-product order uses the shop default; `services_fitting` excludes services whose size limits the container's outer size exceeds
- [ ] T036 [P] [US3] API tests in `backend/tests/api/test_postage_catalogue.py`: `GET /api/v1/postage/carriers` (200, `suggested_carrier` + `chosen_from` + `reason` from `carrier_for` — country when set, else currency; `usable` false on currency mismatch; 401), `POST /api/v1/postage/carriers/apply` (200; 401; 403 viewer; 422 unknown service, currency mismatch; 404 unknown tariff version), `GET /api/v1/postage/tariff-updates` (200 with an update when a newer file exists — use a test tariff directory override; 401), `PUT /api/v1/settings/postage` (200; 422 service with no profile; 401); `DELETE /api/v1/postage/carriers/services/{service}` (204 supersedes that service's seeded rows, operator rows untouched; 401; 403 viewer; 404 service not seeded); tenant isolation: applying for tenant A creates nothing visible to tenant B (FR-024); `PUT /api/v1/products/{id}` with `postage_service` (200; 422 unknown service; 404 product)
- [ ] T037 [P] [US3] Frozen order postage unchanged after a tariff supersede (FR-021) in `backend/tests/unit/test_catalogue_seed.py`: an order with `freeze_order_postage` keeps its figure
- [ ] T038 [P] [US3] Frontend tests `frontend/src/components/settings/ShippingProfilesPanel.test.tsx` (carrier section, default service select, seeded rows labelled default with source and tariff date, tariff update offer, switch carrier, remove a service, notice naming the carrier and whether it came from the country or the currency, and for a currency without carrier the notice explaining why and linking to manual profile entry — FR-022) and `frontend/src/components/products/ProductPackagingCard.test.tsx` (postage service override select lists only fitting services)

### Implementation for User Story 3

- [ ] T039 [US3] Shop country backend (FR-017a): `country_code` on `TenantUpdate` and `TenantResponse` in `backend/app/schemas/tenant_settings.py` ("ISO 3166-1 alpha-2", upper-cased, `^[A-Z]{2}$`, nullable to clear) through the existing `PUT /api/v1/settings/tenant`; `country` on `OnboardingStep3Request` in `backend/app/schemas/onboarding.py` saved by `save_step3` in `backend/app/services/onboarding_wizard.py`; tests in `backend/tests/api/test_settings_country.py` (200 set and clear; 401; 422 `FRA`; onboarding step 3 stores it; changing it creates or supersedes no shipping profile)
- [ ] T040 [P] [US3] Shop country frontend: country select (searchable, optional, "Used to choose your postage carrier") next to the currency in `frontend/src/components/settings/GeneralSettings.tsx` and `frontend/src/components/onboarding/Step3ShopSetup.tsx`; `country_code` in the tenant type; tests in `frontend/src/components/settings/GeneralSettings.test.tsx` and `frontend/src/components/onboarding/onboardingSteps.test.tsx`
- [ ] T041 [P] [US3] Tariff file `backend/app/data/postage_tariffs/canada_post/<effective_date>.json` — services `lettermail`, `small_packet`, `expedited_parcel`; zones `domestic`, `us`, `international`; brackets, size limits and prices transcribed from the Canada Post "Postage rates and prices" guide in force, `source` naming the document and date
- [ ] T042 [P] [US3] Tariff file `backend/app/data/postage_tariffs/royal_mail/<effective_date>.json` — services `large_letter`, `small_parcel`, `medium_parcel`; zones `domestic`, `europe`, `world_1`, `world_2`; from Royal Mail "Our prices"
- [ ] T043 [P] [US3] Tariff file `backend/app/data/postage_tariffs/la_poste/<effective_date>.json` — services `lettre_suivie`, `colissimo`; zones `domestic`, `europe`, `world`; from La Poste "Tarifs" in force
- [ ] T044 [P] [US3] Tariff file `backend/app/data/postage_tariffs/usps/<effective_date>.json` — services `ground_advantage`, `priority_mail`; zones `domestic` (zone-averaged or zone 1–4 retail price, stated in `source`), `international`; from USPS Notice 123
- [ ] T045 [US3] Implement `seed_postage(db, tenant, carrier=None, services=None, tariff_version=None, *, release=False) -> SeedResult` , `remove_postage_service(db, tenant, service)` (supersedes that service's seeded rows via `effective_to`, FR-018) and `pending_tariff_updates(db, tenant)` in `backend/app/services/catalogue_seed.py` per research D6–D8 (overlap rule shared with `backend/app/api/v1/shipping_profiles.py`: move its overlap check into a service function and call it from both, Constitution III); store `settings.postage.carrier` and the notice
- [ ] T046 [US3] Preferred service in `backend/app/services/postage.py`: `preferred_service` parameter on `_price`, resolution in `postage_for_order`/`postage_for_product` (product `postage_service`, else `tenant.settings.postage.default_service`), note `preferred_service_does_not_fit`; new `services_fitting(container, profiles, as_of)` using `build_parcel`'s outer size
- [ ] T047 [US3] `fits_services` in `ConsumableTypeResponse` filled by `list_consumable_types`/`get_consumable_type` in `backend/app/api/v1/consumables.py` with one profile query per request (D11)
- [ ] T048 [US3] Schemas `backend/app/schemas/postage_catalogue.py` and router `backend/app/api/v1/postage_catalogue.py` (`GET /postage/carriers`, `POST /postage/carriers/apply`, `GET /postage/tariff-updates`, `PUT /settings/postage`, `DELETE /postage/carriers/services/{service}`) per contracts/api.md; register in `backend/app/main.py`; include `service`, `source`, `tariff_version`, `catalogue_carrier` in the shipping profile response schema (`backend/app/schemas/shipping_profile.py` or equivalent)
- [ ] T049 [US3] `postage_service` on products: `backend/app/schemas/product.py` (update + response), validation in `backend/app/api/v1/products.py` (422 when no profile in force has that service)
- [ ] T050 [US3] Onboarding step 5 postage part: `seed_postage` with the chosen carrier/services and default service in `backend/app/services/onboarding_wizard.py`; carrier pre-selected by `carrier_for` (country from step 3, else currency) in `frontend/src/components/onboarding/PackagingPostageStep.tsx`
- [ ] T051 [P] [US3] Frontend data layer `frontend/src/types/postageCatalogue.ts`, `frontend/src/lib/api/postageCatalogue.ts`, `frontend/src/hooks/usePostageCatalogue.ts`
- [ ] T052 [US3] `frontend/src/components/settings/ShippingProfilesPanel.tsx`: carrier section (current carrier, services, switch carrier, add/remove services), default service select, "default" badge + source + tariff date on seeded rows, tariff update offer with accept, one-time postage notice (reuse `CatalogueNotice`) naming the carrier and whether it came from the country or the currency, or, when `reason` is set (`no_carrier_for_country`, `no_carrier_for_currency`, `carrier_currency_mismatch`), saying why nothing was added and pointing to "Add profile" (FR-022)
- [ ] T053 [US3] Product override: postage service select (only services in `fits_services` of the product's container) in `frontend/src/components/products/ProductPackagingCard.tsx`; margin note when the preferred service does not fit; Packaging list shows `fits_services` per container (`PackagingList.tsx`)

**Checkpoint**: all three stories functional.

---

## Phase 6: Release step for existing shops (FR-011, FR-018, FR-018a)

- [ ] T054 Release CLI `backend/app/cli/seed_catalogues.py` (`python -m app.cli.seed_catalogues --all-tenants [--tenant SLUG] [--dry-run --report PATH]`): PostgreSQL advisory lock; per tenant, own transaction, `seed_packaging(release=True)` and `seed_postage(release=True)` (carrier from `carrier_for`, D7); one tenant's failure logged and skipped; summary printed; `--dry-run` runs inside a savepoint always rolled back
- [ ] T055 Dry-run delta report: extend `backend/scripts/postage_delta_report.py` with an `--after-seed` mode (or have the CLI call its row builder) that writes per product × zone the postage before and after seeding, as the constitution requires before the release is accepted (FR-018a)
- [ ] T056 Tests in `backend/tests/unit/test_seed_catalogues_cli.py`: all tenants seeded once; second run no-op; dry-run writes nothing and produces the report; a failing tenant does not stop the others; advisory lock prevents concurrent runs
- [ ] T057 Run the CLI after migrations: second command in the backend init container of `infrastructure/k8s/backend/deployment.yaml` (after `alembic upgrade heads`); dev step in `.claude/skills/deploy-dev/SKILL.md` (after step 6); note for the VPS update command of spec 005 in `specs/005-single-tenant-vps/` (cross-reference only)
- [ ] T058 Produce `specs/006-packaging-catalogue/delta-postage.md` with the dry-run against a copy of production data before release (FR-018a, Constitution: Additional Constraints)

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T059 [P] Operator docs `docs-site/docs/packaging.md` (Packaging page, catalogue defaults, carriers, default service, tariff updates) and a link from `docs-site/docs/pricing-model.md`
- [ ] T060 [P] E2E journey `frontend/src/test/e2e/packaging-catalogue.spec.ts`: onboarding step 5 → Packaging lists catalogue → product suggests a box → margin uses default service
- [ ] T061 Full verification: `cd backend && poetry run pytest && poetry run ruff check && poetry run ruff format --check`; `cd frontend && npm test && npm run lint && npm run typecheck`
- [ ] T062 Run quickstart.md on the dev stack and record the outcome in `specs/006-packaging-catalogue/quickstart.md` (results section)

---

## Dependencies & Execution Order

- Phase 1 → Phase 2 → stories. T002 before T026/T041–T044 (files validated by the loader).
- **US1** depends only on Phase 2 (T004–T005 for `catalogue_key` in responses).
- **US2** depends on Phase 2; its UI hooks into US1's `PackagingList` (T017) and onboarding.
- **US3** depends on Phase 2; T047/T053 hook into US1's list; T050 extends US2's step 5 and reads the country saved by T039; T002's `carrier_for` is used by T045, T048, T050 and T054.
- **Phase 6** depends on T027 and T045.
- **Phase 7** last.

### Parallel opportunities

- Phase 1: T002 ∥ T003 (after T001).
- Phase 2: T006 ∥ T007 after T004–T005.
- US1: tests T009–T012 ∥; T015 ∥ backend T013–T014.
- US2: tests T022–T025 ∥; T030 ∥ backend T027–T029.
- US3: T040 ∥ T039 (after the API shape is agreed); tariff files T041–T044 ∥ each other and with tests T034–T038; T051 ∥ backend T045–T049.

### Parallel example: User Story 3

```text
T041 Canada Post tariff file   T042 Royal Mail tariff file
T043 La Poste tariff file      T044 USPS tariff file
T035 postage preference tests  T036 postage catalogue API tests
```

## Implementation Strategy

1. **MVP = Phase 1 + Phase 2 + US1**: the Packaging page alone fixes "where do I add my boxes" (bugcap #44/#59).
2. **+ US2**: catalogue via onboarding and the Packaging page.
3. **+ US3**: postage catalogue, default service, tariffs.
4. **+ Phase 6**: release step seeds existing shops automatically, after the delta report is reviewed.
5. Each increment ships through `main` → CI → ArgoCD and stays independently testable.
