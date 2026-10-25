---

description: "Task list for the Packaging Advisor feature"
---

# Tasks: Packaging Advisor

**Input**: Design documents from `/specs/003-packaging-advisor/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/packaging-api.md](./contracts/packaging-api.md), [quickstart.md](./quickstart.md)

**Tests**: REQUIRED. Constitution II: every change ships its tests. Endpoints
cover 200/201, 401, 403 (viewer, writes), 422 and 404. Tests are written first
in each story and must fail before the implementation lands.

**Organization**: Tasks are grouped by user story (US1–US7 from spec.md).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to
- Paths are from the repository root (`backend/`, `frontend/`)

## Conventions for every task

- Lengths `Numeric(7,1)` mm, weights `Numeric(8,1)` g, volumes `Numeric(10,1)` ml; `Decimal` in Python; decimal **strings** in JSON and TypeScript (never `number`).
- Every endpoint: `get_current_tenant` + `get_tenant_db` (`TenantDB`); writes use `RequireMember`.
- Services under `backend/app/services/`; routes stay thin.
- Commit style `type: description`; before each commit `cd backend && poetry run pytest && poetry run ruff check`, and for frontend `cd frontend && npm test && npm run lint && npm run typecheck`.

---

## Phase 1: Setup

**Purpose**: Fixtures used across stories

- [ ] T001 [P] Create mesh fixtures in `backend/tests/fixtures/meshes/`: `block_binary.stl` and `block_ascii.stl` (40 × 30 × 20 mm block; the binary one's 80-byte header starts with `solid` to exercise detection), `block.3mf` (plain), `block_rotated_scaled.3mf` (build item transform rotating 90° about Z and scaling 2× → expected 60.0 × 80.0 × 40.0), `block_inches.3mf` (`unit="inch"`, block of 1 × 1 × 1 in → 25.4 mm), `two_objects.3mf` (two objects, 40×30×20 and 10×10×10, separate build items), `bambu_objects.3mf` (mesh in `/3D/Objects/object_1.model` referenced by component from `3D/3dmodel.model`), and `not_a_mesh.stl` (random bytes). Add `backend/tests/fixtures/meshes/make_fixtures.py` that generates them deterministically so they can be regenerated.
- [ ] T002 [P] Add shared test factories in `backend/tests/utils/packaging.py` (existing `tests/utils/` package): `make_box(db, tenant, name, inner=(l,w,h), weight=Decimal, on_hand=int, cost=Decimal|None, kind="box", wall=None)`, `make_void_fill(db, tenant, fill_volume_ml, on_hand)`, `make_wrap(db, tenant)`, `set_dims(product_or_model, l, w, h, source="entered")`.

---

## Phase 2: Foundational (blocks every story)

**Purpose**: MVP schema, ORM fields and the shared dimension value type

- [ ] T003 Write migration `backend/alembic/versions/20261026_packaging_advisor_v1.py` (revision `packaging_advisor_v1`, `down_revision` = current head — today `rls_uncovered_tenant_tables_v1`; confirm with `poetry run alembic heads` first). Add to `models`, `products` and `product_variants`: `length_mm`, `width_mm`, `height_mm` `Numeric(7,1)` nullable; `dimensions_source` `String(10)` nullable; `dimensions_source_file_id` UUID FK `model_files.id` `ON DELETE SET NULL` nullable; `dimensions_set_at` `DateTime(timezone=True)` nullable; constraints `ck_<table>_dims_all_or_none` ("all three null, or all three > 0") and `ck_<table>_dims_source` ("dimensions_source IS NULL iff dimensions null; value in ('entered','measured')"). Add to `products`: `is_fragile` Boolean not null `server_default false`. Add to `product_variants`: `packaging_consumable_id` UUID FK `consumable_types.id` `ON DELETE SET NULL` nullable, `packaging_quantity` Integer nullable with check `> 0` when set. Add to `model_files`: `measured_length_mm`, `measured_width_mm`, `measured_height_mm` `Numeric(7,1)`, `measured_objects` JSONB (JSON on SQLite via `with_variant`), `measured_at` timestamptz, `measurement_note` `String(255)`, `measurement_status` `String(10)` check in ('done','pending','skipped','failed'), all nullable. Add to `consumable_types`: `packaging_kind` `String(12)` nullable check in ('box','mailer','void_fill','wrap'); `inner_length_mm`, `inner_width_mm`, `inner_height_mm` `Numeric(7,1)` (all-null or all > 0); `wall_mm` `Numeric(5,1)`, `empty_weight_grams` `Numeric(8,1)`, `fill_volume_ml` `Numeric(10,1)` (each nullable, `>= 0`). Downgrade drops all of it. No data backfill.
- [ ] T004 [P] Extend `backend/app/models/model.py` with the six dimension columns and their check constraints (column comments as in data-model.md).
- [ ] T005 [P] Extend `backend/app/models/product.py` with the six dimension columns, `is_fragile`, and constraints; leave `size_cm` untouched (FR-005).
- [ ] T006 [P] Extend `backend/app/models/product_variant.py` with the six dimension columns, `packaging_consumable_id`, `packaging_quantity`, a `packaging_consumable` relationship, and constraints.
- [ ] T007 [P] Extend `backend/app/models/model_file.py` with the seven measurement columns (incl. `measurement_status`).
- [ ] T008 [P] Extend `backend/app/models/consumable.py` (`ConsumableType`) with `packaging_kind`, the three inner dims, `wall_mm`, `empty_weight_grams`, `fill_volume_ml`, and constraints; add `PACKAGING_KINDS = ("box", "mailer", "void_fill", "wrap")`.
- [ ] T009 Update `backend/tests/unit/pricing/test_provenance_registry.py` `NOT_A_COST_INPUT`: `model` and `product` → `length_mm`, `width_mm`, `height_mm`: "a dimension"; `consumable_type` → `inner_length_mm`, `inner_width_mm`, `inner_height_mm`, `wall_mm`: "a dimension until Phase 2 prices postage from it", `empty_weight_grams`: "a weight until Phase 2 prices postage from it", `fill_volume_ml`: "a volume, not money". (Phase 2 task T051 moves the first five into the registry — FR-038.) Run it and confirm it passes.
- [ ] T010 Create `backend/app/services/dims.py` with frozen dataclass `Dims(length: Decimal, width: Decimal, height: Decimal)`: `sorted_desc()`, `volume_ml` (mm³ / 1000), `plus(clearance)` (adds `2 × clearance` per axis), `fits_in(other) -> Optional[tuple[str,str,str]]` (tries all 6 permutations, returns the orientation or None; equality fits), `quantize()` to 0.1 mm `ROUND_HALF_UP`; `Dims.from_row(obj, prefix="")` returning None unless all three set. In the same module, frozen dataclass `Parcel(grams: Optional[Decimal], outer: Optional[Dims], reasons: tuple[str, ...] = ())` (plain value; assembled only by `postage.build_parcel`, T052). Unit tests in `backend/tests/unit/test_dims.py`: exact fit, 0.1 mm over fails, rotation needed, zero clearance, volume.
- [ ] T011 Create `backend/app/schemas/dimensions.py`: `DimensionsIn` (three `Optional[Decimal]` fields `gt=0`, max one decimal place, all-or-none validator; optional `adopt_file_id: UUID`), `DimensionsOut` (`length_mm`, `width_mm`, `height_mm` as decimal strings, `source`, `source_file_id`, `set_at`, `inherited: bool = False`), `PackagingSettings` (`clearance_mm`, `fragile_clearance_mm` `Decimal ge=0`, one decimal place; `configured: bool`). Serialize Decimals as strings, matching existing money schemas.
- [ ] T012 Create `backend/app/services/item_dimensions.py`: `effective_dimensions(product, variant=None) -> tuple[Optional[Dims], DimensionsOut | None]` (variant's if set, else product's, with `inherited=True`), `effective_packaging(product, variant=None) -> (consumable, quantity)`, `set_dimensions(db, tenant, target, dims_in, user)` (writes source `'entered'`, `dimensions_set_at=now(UTC)`, clears source when all null), and `variant_for_order_line(product, sku)` (variant whose `sku` equals the line's `product_sku`, else None — research D11). Unit tests in `backend/tests/unit/test_item_dimensions.py`.

**Checkpoint**: `poetry run alembic upgrade head` from an empty DB and `poetry run pytest tests/unit/pricing/test_provenance_registry.py tests/unit/test_dims.py tests/unit/test_item_dimensions.py` pass.

---

## Phase 3: User Story 1 — Record a product's dimensions (P1) 🎯 MVP

**Goal**: Operators enter L × W × H on products, models and variants; source and time are shown; entered values are never overwritten.

**Independent Test**: Quickstart scenario 1 and 10 (viewer).

### Tests for User Story 1

- [ ] T013 [P] [US1] API tests in `backend/tests/api/test_packaging_api.py::TestDimensions`: `PUT /api/v1/products/{id}/dimensions` 200 (returns `source="entered"`, `set_at`), clear with all-null 200, 401 no token, 403 viewer, 422 for `0`, `-1`, `"abc"`, `12.34` (two decimals) and only two of three, 404 unknown product and product of another tenant; same matrix for `PUT /api/v1/models/{id}/dimensions` and `PUT /api/v1/products/{id}/variants/{variant_id}/dimensions` (variant 404 when it belongs to another product); `GET /api/v1/products/{id}` shows `dimensions` and `is_fragile`; a variant without dims returns the product's with `inherited=true`. FR-005: a product with `size_cm` set returns the same `size_cm` before and after dimensions are saved, and saving dimensions never writes `size_cm`.

### Implementation for User Story 1

- [ ] T014 [US1] Create router `backend/app/api/v1/packaging.py` with the three `PUT …/dimensions` endpoints delegating to `item_dimensions.set_dimensions`; register it in `backend/app/main.py` under `/api/v1`.
- [ ] T015 [P] [US1] Add `dimensions: Optional[DimensionsOut]` and `is_fragile` to product responses in `backend/app/schemas/product.py` and the response builders in `backend/app/api/v1/products.py` (both list and detail dict builders around the existing `size_cm` keys); add `dimensions`, `packaging_consumable_id`, `packaging_quantity`, `effective_packaging` to `ProductVariantResponse`; accept `is_fragile` in `ProductUpdate`.
- [ ] T016 [P] [US1] Add `dimensions` to model responses in `backend/app/schemas/model.py` and `backend/app/api/v1/models.py`.
- [ ] T017 [P] [US1] Frontend types and client: `frontend/src/types/packaging.ts` (`Dimensions` with string fields, `DimensionsInput`), `frontend/src/lib/api/packaging.ts` (`setProductDimensions`, `setModelDimensions`, `setVariantDimensions`), `frontend/src/hooks/usePackaging.ts` (mutations invalidating the product/model queries); extend `frontend/src/types/product.ts` and model types.
- [ ] T018 [US1] Create `frontend/src/components/products/DimensionsEditor.tsx`: three inputs (mm, one decimal, validated with Zod as strings), Save/Clear, a source badge ("Entered · date" / "Measured from <file> · date" / "Inherited from product"), hidden actions for viewers. Test in `DimensionsEditor.test.tsx` (validation messages name the field; viewer sees no Save).
- [ ] T019 [US1] Mount `DimensionsEditor` in `frontend/src/components/products/ProductDetail.tsx` (product + per-variant rows) and `frontend/src/components/models/ModelDetail.tsx`; add a "Fragile" toggle on the product. Extend `ProductDetail.test.tsx` and `ModelDetail.test.tsx`.

**Checkpoint**: US1 independently usable; existing `size_cm` displays unchanged.

---

## Phase 4: User Story 2 — Get a box suggestion and accept it (P1) 🎯 MVP

**Goal**: Packaging catalogue, clearance settings, ranked suggestions, accept, drift warning.

**Independent Test**: Quickstart scenarios 4, 5, 6, 8, 9.

### Tests for User Story 2

- [ ] T020 [P] [US2] Unit tests `backend/tests/unit/test_packaging_advisor.py::TestSuggest`: spec Story 2 scenario 1 (boxes 100×100×50, 150×100×60, 200×150×100; item 120×70×30; clearance 10 → order [150×100×60, 200×150×100], 100×100×50 absent); orientation reported when only a rotated fit works; nothing fits → `minimum_inner` = sorted item + 2×clearance (300³ → 320³); incomplete box (missing an inner dim) never suggested and listed in warnings; out-of-stock ranked after in-stock; equal volume tie broken by lower `consumable_unit_cost`, `None` cost last, then name; mailer treated like a box with height = max thickness; clearance 0 fits an exact-size box; no item dims → warning `dimensions_required`; `room_mm` and `empty_volume_ml` values (150×100×60 vs 120×70×30 → room 10/10/10, empty 648.0 ml).
- [ ] T021 [P] [US2] API tests `backend/tests/api/test_packaging_api.py::TestSuggestions` and `::TestAccept` and `::TestPackagingSettings`: `GET /products/{id}/packaging-suggestions` 200/401/404 (other tenant), `?variant_id=` uses the variant's effective dims, 404 foreign variant; response has no cost field; `is_current` true for the accepted container; FR-022: requesting suggestions writes nothing (row counts of every table and the product's `updated_at` unchanged after the GET). `POST /products/{id}/packaging` 200 sets product packaging; with `variant_id` sets the variant only; 403 viewer; 422 when consumable is not box/mailer or quantity < 1; 404 unknown consumable or one from another tenant. After changing dims so the accepted box no longer fits, `GET /products/{id}` returns `packaging_warnings: ["accepted_packaging_does_not_fit"]`. `GET/PUT /settings/packaging`: defaults with `configured=false`, PUT persists and returns `configured=true`, 422 negative, 403 viewer, 401. Consumables: create/patch with packaging fields 201/200, 422 on bad `packaging_kind` or `inner_length_mm=0`, `packaging_incomplete` flag, `?packaging_kind=box,mailer` filter.
- [ ] T022 [P] [US2] Assert cost authority: test in `backend/tests/unit/test_packaging_advisor.py::TestNoCostPath` that accepting a box makes the product's cost breakdown packaging line equal `consumable_unit_cost(box) × quantity` via `app/services/costing.py` (no figure produced by the advisor).

### Implementation for User Story 2

- [ ] T023 [P] [US2] Extend `backend/app/schemas/consumable.py` and `backend/app/api/v1/consumables.py` with the packaging fields (validation as T003 constraints), `packaging_incomplete` computed in the response, and the `packaging_kind` comma-separated filter.
- [ ] T024 [P] [US2] Add `GET/PUT /settings/packaging` to `backend/app/api/v1/settings.py` storing `tenant.settings["packaging"] = {"clearance_mm": "10.0", "fragile_clearance_mm": "20.0"}` as decimal strings; GET returns defaults with `configured=false` when the key is absent (research D8). Add `get_packaging_settings(tenant) -> (Decimal, Decimal, bool)` in `backend/app/services/packaging_advisor.py` as the only reader.
- [ ] T025 [US2] Implement pure functions in `backend/app/services/packaging_advisor.py`: `Container`, `Suggestion`, `Advice` dataclasses (data-model.md "Value objects"); `suggest(item: Dims | None, containers, *, clearance: Decimal, fragile: bool=False, fillers=(), wraps=()) -> Advice` per research D6 (fit with `Dims.fits_in`, ranking in-stock → volume → unit-cost key → name, `minimum_inner`, warnings `dimensions_required` / `nothing_fits` / `incomplete_container:<name>`). No database access, no cost output.
- [ ] T026 [US2] Add `async load_packaging_context(db, tenant) -> (containers, fillers, wraps, clearance, fragile_clearance)` in `backend/app/services/packaging_advisor.py`, building `Container` from `ConsumableType` rows where `packaging_kind` is set and `is_active`, using `consumable_unit_cost` from the costing module only as the tie-break key.
- [ ] T027 [US2] Add `GET /products/{id}/packaging-suggestions` and `POST /products/{id}/packaging` to `backend/app/api/v1/packaging.py` (response shape per contracts; accept writes product or variant `packaging_consumable_id`/`packaging_quantity`, rejects non box/mailer with 422, does not require fit).
- [ ] T028 [US2] Add `packaging_warnings: list[str]` to product (and variant) responses in `backend/app/api/v1/products.py`, computed on read with `Dims.fits_in` against the effective accepted container and the clearance in force (FR-024); never stored.
- [ ] T029 [P] [US2] Extend `frontend/src/components/inventory/AddConsumableDialog.tsx` and `EditConsumableDialog.tsx` with a "Packaging" section (kind select; inner L/W/H; wall; empty weight; fill volume shown only for void fill), plus an "incomplete" badge in `ConsumableList.tsx`. Update their tests.
- [ ] T030 [P] [US2] Create `frontend/src/components/settings/PackagingSettings.tsx` (two fields, "default" hint while `configured=false`) and add it to the settings page; test file alongside.
- [ ] T031 [US2] Create `frontend/src/components/products/PackagingSuggestions.tsx`: "Suggest packaging" button → ranked list (name, inner size, orientation, room per axis, empty volume, in-stock badge, "current" badge), Accept per row (hidden for viewers), states for `dimensions_required` (link to the editor) and `nothing_fits` (shows minimum inner size). Packaging cost shown is the product's existing cost-breakdown line, not a new figure. Mount in `ProductDetail.tsx` for the product and each variant; show `packaging_warnings` as an alert. Tests in `PackagingSuggestions.test.tsx`.
- [ ] T032 [US2] FR-039: add `packaging_notes` to `ProductVariantResponse` in `backend/app/schemas/product.py` / `backend/app/api/v1/products.py` — `["variant_packaging_not_costed"]` when the variant's effective packaging (consumable or quantity) differs from the product's; computed on read. In `frontend/src/components/products/ProductDetail.tsx` the variant row shows "Cost breakdown uses the product's packaging" for that note and shows no packaging cost of its own. API test in `backend/tests/api/test_packaging_api.py::TestVariantPackagingNote` (note present after accepting a different box for a variant, absent when inherited or identical) and a case in `ProductDetail.test.tsx`.

**Checkpoint**: MVP (US1 + US2) shippable.

---

## Phase 5: User Story 3 — Measure dimensions from an uploaded file (P2)

**Goal**: STL/3MF uploads produce a bounding box, auto-applied only where no dimensions exist.

**Independent Test**: Quickstart scenarios 2 and 3; SC-003 (0.1 mm).

### Tests for User Story 3

- [ ] T033 [P] [US3] Unit tests `backend/tests/unit/test_mesh_bounds.py` against every T001 fixture: binary and ASCII block → 40.0 × 30.0 × 20.0; binary with `solid` header still read as binary; rotated/scaled 3MF → 60.0 × 80.0 × 40.0; inch 3MF → 25.4 mm; two-object 3MF → two objects listed, overall build size, note about assembled size; Bambu component file read; random bytes → `None` with a note (status `failed`); a file over `MAX_MEASURE_BYTES` → status `skipped`, note says why (patch the limit low in the test). SC-007 timing test (`@pytest.mark.slow` allowed): a generated 25 MB binary STL is measured in under 1.0 s.
- [ ] T034 [P] [US3] API tests `backend/tests/api/test_packaging_api.py::TestMeasureOnUpload`: upload STL to a model with no dims → model dims set with `source="measured"` and `source_file_id`; `measurement.applied_to == ["model"]`; upload again to a model with entered dims → dims unchanged, `applied_to == []`; product with exactly one model at quantity 1 and no dims → product receives it; product with two models → not touched; G-code upload → `measurement: null`, 201; unreadable STL → 201 with `status: "failed"`; a file above `INLINE_MEASURE_BYTES` (patched low) → 201 with `status: "pending"` and the Celery task enqueued (mock `delay`), no sizes; `POST /files/parse-3mf` returns `measurement`; `PUT /products/{id}/dimensions` with `adopt_file_id` → `source="measured"`, 404 for a file of another model/tenant.

### Implementation for User Story 3

- [ ] T035 [US3] Create `backend/app/services/mesh_bounds.py` per research D3: `measure(file_bytes: bytes, extension: str) -> Optional[Measurement]` (`Measurement(overall: Dims, objects: list[(name, Dims)], note: Optional[str])`); binary STL via length check `84 + 50·n` and `struct.iter_unpack('<12fH')`; ASCII STL streaming `vertex` lines; 3MF via `zipfile` + `xml.etree.ElementTree.iterparse`, following `<component objectid path>` into `/3D/Objects/*.model`, composing `transform` matrices (3×4, row-major as the 3MF spec defines), applying the `unit` attribute (micron 0.001, millimeter 1, centimeter 10, inch 25.4, foot 304.8, meter 1000); `INLINE_MEASURE_BYTES = 25 * 1024 * 1024`, `MAX_MEASURE_BYTES = 200 * 1024 * 1024` (research D3, SC-007); floats only inside parsing, results quantized to 0.1 mm. Catch all parse errors and return a note rather than raising.
- [ ] T036 [US3] Call `mesh_bounds.measure` in `backend/app/services/model_file_service.py` `upload_file` and `create_local_reference` for `.stl`/`.3mf` up to `INLINE_MEASURE_BYTES` (larger files: set `measurement_status='pending'` and enqueue T037; over `MAX_MEASURE_BYTES`: `'skipped'`); store the `measured_*` fields and status on the `ModelFile`; then `item_dimensions.apply_measurement(db, tenant, model, model_file)` which sets the model's dims only when it has none (`source='measured'`, file id) and the same for a product whose BOM is exactly that one model at quantity 1 (FR-009), returning `applied_to`. Extend `parse_3mf_metadata` / the parse endpoint to include `measurement` without persisting.
- [ ] T037 [US3] Create Celery task `backend/app/tasks/mesh_measure.py` `measure_model_file(tenant_id, model_file_id)` (name `mesh_measure.measure_model_file`, registered like `app/tasks/margin_alerts.py`): opens its own session with the tenant RLS context set, loads the file bytes via `ModelFileService.get_file_content`, runs `mesh_bounds.measure`, stores results and `measurement_status` (`done`/`failed`), then calls `item_dimensions.apply_measurement` (entered dims still win, FR-003). Idempotent: does nothing if status is no longer `pending`. Tests in `backend/tests/unit/test_mesh_measure_task.py` (eager mode): pending → done with dims applied; entered dims untouched; unreadable → failed; second run no-op; another tenant's file id → nothing written.
- [ ] T038 [US3] Extend `backend/app/schemas/model_file.py` (`ModelFileUploadResponse`, `ThreeMFParseResponse`, file list item) with `measurement` per contracts; support `adopt_file_id` in `item_dimensions.set_dimensions` (file must belong to the model or the product's single model; 404 otherwise).
- [ ] T039 [US3] Frontend: in `frontend/src/components/models/ModelFilesEditor.tsx` show each file's measurement (overall + objects, note; "Measuring…" while `pending`, refetching the file list every 5 s until it is not); in `DimensionsEditor.tsx` show "Measured X × Y × Z from <file> — Use these" when a measurement differs from the current dims, calling the adopt endpoint. Tests updated.

**Checkpoint**: US3 works with US1 alone (no advisor needed).

---

## Phase 6: User Story 4 — Filler and protection (P2)

**Goal**: Void-fill quantity and fragile handling in suggestions.

**Independent Test**: Quickstart scenario 5 (void fill) and 7 (fragile).

### Tests for User Story 4

- [ ] T040 [P] [US4] Unit tests `backend/tests/unit/test_packaging_advisor.py::TestFiller`: 1000 ml/unit fill with 1600 ml empty → 2 units; picks the in-stock filler with the largest `fill_volume_ml`; no filler stocked → empty volume reported, `void_fill=None`; fragile uses fragile clearance (120×70×30 with 20 → 150×100×60 rejected); fragile + stocked wrap → `wrap` set; fragile without wrap → no wrap, no error.
- [ ] T041 [P] [US4] API test: `PATCH /products/{id}` `is_fragile=true` then suggestions show `fragile: true` and `clearance_mm` = fragile clearance.

### Implementation for User Story 4

- [ ] T042 [US4] Extend `suggest()` in `backend/app/services/packaging_advisor.py` with void fill (`ceil(empty_ml / fill_volume_ml)`, `Decimal` with `ROUND_CEILING`) and fragile handling (clearance swap, wrap suggestion) per research D6; pass `product.is_fragile` from the suggestions endpoint in `backend/app/api/v1/packaging.py`.
- [ ] T043 [US4] Show void fill quantity and wrap in `PackagingSuggestions.tsx`; "Fragile" badge when applied. Tests updated.

**Checkpoint**: MVP complete (US1–US4). Release before Phase 2.

---

## Phase 7: User Story 5 — Postage uses the packed parcel (P3, Phase 2)

**Goal**: Packed weight, size classes and volumetric weight inside `postage.py`.

**Independent Test**: Quickstart scenarios 11, 12, 13, 16.

### Tests for User Story 5

- [ ] T044 [P] [US5] Unit tests `backend/tests/unit/test_postage_parcel.py`: `build_parcel` is the only assembler — sums item weights × quantity plus each packing item's `empty_weight_grams × quantity`, outer = container inner + `2 × wall_mm`, unknown packing weight → `grams=None` with reason; single-unit order: product 180 g + 40 g box → 220 g bracket chosen; **H2**: one line of quantity 3 never uses the product's single-unit box (until US6 it gets weight-only postage with reason `order_packing_unavailable`, identical to today's figure); two lines likewise; **H1**: two weight-only profiles covering the same weight in a zone → the same profile as today's ordering picks (by `weight_bracket_min_grams`), even when the other is cheaper; with a size-limited profile present, size-limited profiles are tried first, cheapest first; box without `empty_weight_grams` → postage unknown with reason (not zero); large-letter profile (353×250×25) rejected for a 160×110×70 parcel and small-parcel chosen; parcel 30 mm deep rejected by large letter; sorted-dimension comparison (a 250×353×20 parcel fits a 353×250×25 limit); divisor 5000 with 400×300×200 at 1 kg → chargeable 4800 g; profile without limits matches by weight exactly as before; size-limited profile never matches unknown size; `wall_mm` 3 → outer = inner + 6 per axis; product without accepted packaging → weight-only as today, with reason `no_packaging_recorded` exposed.
- [ ] T045 [P] [US5] Regression test `backend/tests/unit/test_postage_parcel.py::TestHistory`: an order with `postage_paid` set before the change keeps it after profiles gain limits and packaging changes; `freeze_order_postage` on a new order uses the packed parcel; existing `tests/` postage tests still pass unchanged where no packaging/limits exist.
- [ ] T046 [P] [US5] API tests for `/api/v1/shipping-profiles` with `max_length_mm`, `max_width_mm`, `max_height_mm` (all-or-none, `> 0`) and `volumetric_divisor` (`> 0`): 201/200/422/403/401/404; editing a profile in force supersedes it (existing T233 behaviour preserved).

### Implementation for User Story 5

- [ ] T047 [US5] Write migration `backend/alembic/versions/20261026_packaging_advisor_v2.py` (revision `packaging_advisor_v2`, down `packaging_advisor_v1`): `shipping_profiles` add `max_length_mm`, `max_width_mm`, `max_height_mm` `Numeric(7,1)` (all-null or all > 0) and `volumetric_divisor` `Numeric(8,1)` (`> 0`); create `order_parcels` (`id`, `tenant_id` FK tenants CASCADE, `order_id` FK orders CASCADE, `sequence` Integer, unique `(order_id, sequence)`, `outer_length_mm`/`outer_width_mm`/`outer_height_mm` `Numeric(7,1)` null, `packed_weight_grams` `Numeric(10,1)` null, `confirmed_by_user_id` FK users SET NULL, `confirmed_at` timestamptz not null, timestamps) and `order_parcel_items` (`id`, `tenant_id`, `order_parcel_id` FK CASCADE, `consumable_type_id` FK RESTRICT, `quantity` Integer `> 0`); `consumable_usage` add `order_id` FK orders SET NULL nullable, indexed. `ENABLE ROW LEVEL SECURITY` and `CREATE POLICY tenant_isolation_policy … USING (tenant_id = current_setting('app.current_tenant_id')::uuid)` on both new tables, in this migration.
- [ ] T048 [P] [US5] Extend `backend/app/models/shipping_profile.py` with the four columns and replace `covers(grams)` by `covers(parcel: Parcel) -> bool`, importing `Parcel` from `app/services/dims.py` (T010) — never from `postage.py` (chargeable weight = `max(actual, L·W·H mm³ / 1000 / divisor × 1000)` g when divisor set; sorted dims ≤ sorted limits when limits set; limits set and outer unknown → False). Its only caller is `postage._price`; update that call in T052 and leave no grams-based variant behind.
- [ ] T049 [P] [US5] Create `backend/app/models/order_parcel.py` (`OrderParcel`, `OrderParcelItem`) and register in `backend/app/models/__init__.py`; add `order_id` to `ConsumableUsage` in `backend/app/models/consumable.py` with comment noting `usage_type='shipping'`.
- [ ] T050 [US5] Register the four new `shipping_profile` fields in `backend/app/services/provenance.py` (`default_source="policy"`), add them to `PROVENANCE_ENTITY_TYPES` coverage if needed, and run `tests/unit/pricing/test_provenance_registry.py`.
- [ ] T051 [US5] FR-038 / Constitution VI: register `consumable_type` `inner_length_mm`, `inner_width_mm`, `inner_height_mm`, `wall_mm`, `empty_weight_grams` in `backend/app/services/provenance.py` (`default_source="assumed"`) and remove them from `NOT_A_COST_INPUT` in `backend/tests/unit/pricing/test_provenance_registry.py` (`fill_volume_ml` stays excluded). In `backend/app/api/v1/consumables.py` write their provenance through the existing provenance service whenever any of them is saved, from the request's `packaging_provenance.source` (`measured` | `assumed`, default `assumed`; never `observed`), and return it. Frontend: "How do you know these figures?" (Measured / Estimated) select in the packaging section of `AddConsumableDialog.tsx` / `EditConsumableDialog.tsx`, and the source badge next to the figures. Tests: registry test passes; API test that saving a box writes provenance rows with the chosen source and that 422 is returned for `observed`; dialog test.
- [ ] T052 [US5] Refactor `backend/app/services/postage.py` (research D9): import `Parcel` from `app/services/dims.py` and add **`build_parcel(contents: list[tuple[Optional[Decimal], int]], packing: list[tuple[ConsumableType, int]]) -> Parcel`** — the single place that sums item weights × quantity plus each packing item's `empty_weight_grams × quantity` and derives outer size (container inner + `2 × wall_mm`; absent wall = 0, stated in reasons); any unknown weight → `grams=None` with reason (FR-025, FR-030). `_price(profiles, parcel, zone, as_of)` tries, among profiles in force for the zone, size-limited profiles first ordered by `postage_cost` ascending, then profiles without limits in today's order (`weight_bracket_min_grams`) — FR-026, so tenants without size-limited profiles see no change — and uses `covers(parcel)`. `postage_for_order`: when the order is exactly one unit, build the parcel from that unit's effective packaging (`item_dimensions.effective_packaging`, variant resolved via `variant_for_order_line`); when it is more than one unit (several lines, or one line with quantity > 1 — H2), keep today's weight-only parcel with reason `order_packing_unavailable` until T060 lands. `postage_for_grams` keeps working (weight-only parcel). No postage or packed-weight logic outside this module (Constitution III).
- [ ] T053 [P] [US5] Extend `backend/app/schemas/shipping_profile.py` and `backend/app/api/v1/shipping_profiles.py` with the four fields.
- [ ] T054 [P] [US5] Extend `frontend/src/components/settings/ShippingProfilesPanel.tsx` with "Size limits (mm)" and "Volumetric divisor" inputs (decimal strings); test updated.
- [ ] T055 [US5] Create `backend/scripts/postage_delta_report.py`: for every product of a tenant, indicative postage weight-only (old) vs packed parcel (new) for each zone, printed as CSV with per-product difference — the constitution's per-record diff for a change to computed values. Smoke test in `backend/tests/unit/test_postage_delta_report.py`.
- [ ] T056 [US5] Before the Phase 2 release is accepted (constitution: report the per-record difference first), run `backend/scripts/postage_delta_report.py` against a copy of production data, review it with the operator, and attach the output to the release note.

**Checkpoint**: Postage reflects packed parcels; settled orders untouched.

---

## Phase 8: User Story 6 — One box for a multi-item order (P3, Phase 2)

**Goal**: Order-level packing suggestion.

**Independent Test**: Quickstart scenario 14.

### Tests for User Story 6

- [ ] T057 [P] [US6] Unit tests `backend/tests/unit/test_packaging_advisor.py::TestOrderPacking`: two items fitting together → one parcel with both and arrangement; three where none fits all → fewest-container split listing contents; quantity 3 of one product expands to 3 units; line without dims → warning naming the SKU, no parcels; deterministic output for the same input; clearance applied around the group.
- [ ] T058 [P] [US6] API tests `backend/tests/api/test_order_parcels_api.py::TestOrderSuggestions`: `GET /orders/{id}/packaging-suggestions` 200 (parcels, `estimated_postage.is_estimate=true`), 401, 404 other tenant; variant SKU lines use the variant's dims.

### Implementation for User Story 6

- [ ] T059 [US6] Implement `suggest_for_order(items: list[tuple[str, Dims]], containers, *, clearance) -> OrderAdvice` in `backend/app/services/packaging_advisor.py` per research D7 (first-fit-decreasing, extreme-point placement, 6 rotations, deterministic tie-breaks; split into fewest containers when none holds all).
- [ ] T060 [US6] In `backend/app/services/postage.py` `postage_for_order`, replace the `order_packing_unavailable` path for multi-unit orders with `packaging_advisor.suggest_for_order`: one `build_parcel` per suggested parcel, postage summed; an order the advisor cannot pack (missing dimensions) stays weight-only with the advisor's reason. Extend `backend/tests/unit/test_postage_parcel.py`: quantity-3 line and two-line orders now priced from the suggested parcel(s); a split order sums two parcels' postage.
- [ ] T061 [US6] Add `GET /orders/{id}/packaging-suggestions` in `backend/app/api/v1/orders.py` (thin: load lines, resolve variants, call advisor and postage), schema in `backend/app/schemas/packaging.py`.

**Checkpoint**: Order suggestions available; dispatch confirmation next.

---

## Phase 9: User Story 5 (cont.) — Confirm the parcel at dispatch (FR-036, FR-037)

**Goal**: Confirmed parcel recorded once; postage from it; box and filler stock deducted.

**Independent Test**: Quickstart scenario 15; spec Story 5 scenarios 6 and 7.

### Tests

- [ ] T062 [P] [US5] API tests `backend/tests/api/test_order_parcels_api.py::TestConfirmParcels`: `POST /orders/{id}/parcels` 201 stores parcels and items, sets `postage_paid` from the confirmed box with `actuals_source="derived"`; an order whose `postage_paid` was `entered` keeps it; box stock 12 → 11 and void fill −2 with `consumable_usage` rows (`usage_type="shipping"`, `order_id`); second POST → 409 and stock unchanged; stock reaching −1 → 201 with `stock_below_zero` warning; 422 empty parcels / quantity 0 / non-packaging consumable; 403 viewer; 401; 404 order of another tenant; works for an order that `ship_order` routes through `dispatch_native_commerce` (separate endpoint). `GET /orders/{id}` exposes `parcels` and `postage_is_estimate`.

### Implementation

- [ ] T063 [US5] Create `backend/app/services/order_parcel_service.py` `OrderParcelService(db, tenant, user).confirm(order, parcels_in)`: refuse if parcels exist (409); assemble each parcel with `postage.build_parcel` from the order's line weights and the confirmed items (no weight or size arithmetic in this service — FR-030); write `OrderParcel`/`OrderParcelItem`; write one `ConsumableUsage` per item (`usage_type="shipping"`, `order_id`, `cost_at_use` from `consumable_unit_cost`) and decrement `quantity_on_hand` (allowed below zero, collect warnings); compute postage through `postage.py` from the confirmed parcels and set `orders.postage_paid` with `actuals_source="derived"` unless `actuals_source == "entered"`. Single transaction; log with `logger.info`.
- [ ] T064 [US5] Add `POST /orders/{id}/parcels` in `backend/app/api/v1/orders.py` (thin) and `parcels` + `postage_is_estimate` to `OrderResponse` in `backend/app/schemas/order.py` / the response builders.
- [ ] T065 [US5] Create `frontend/src/components/orders/OrderParcelDialog.tsx`: pre-filled from `GET /orders/{id}/packaging-suggestions`, editable containers and quantities, shows estimated postage marked "estimate", confirm → `POST /parcels`; open it from the ship action in `OrderDetail.tsx` before calling ship; show confirmed parcels afterwards (read-only) and stock warnings. Tests in `OrderParcelDialog.test.tsx`.

---

## Phase 10: User Story 7 — Dimensions reused elsewhere (P3, Phase 2)

**Goal**: Printer-bed fit check and Etsy dimensions.

**Independent Test**: Quickstart scenarios 17 and 18.

### Tests for User Story 7

- [ ] T066 [P] [US7] Tests in `backend/tests/unit/test_print_queue_bed_fit.py`: model 300 mm long vs 256³ bed → printer excluded; footprint fitting only when rotated 90° → included; height over `bed_size_z_mm` → excluded; model without dims or printer without all bed sizes → behaves as before; explicit per-printer config still matches first.
- [ ] T067 [P] [US7] Create `backend/tests/unit/test_etsy_sync_specs.py` (no Etsy unit test exists yet), testing the description specifications block: product with dims → `Size: 120.0 × 80.0 × 45.0 mm`; without dims → existing `Size: Ncm` line.

### Implementation for User Story 7

- [ ] T068 [P] [US7] Implement the bed check in `PrintQueueService._is_printer_compatible` in `backend/app/services/print_queue_service.py` (replace the "would require model dimensions" comment) per research D12; log the exclusion reason.
- [ ] T069 [P] [US7] Update specifications block in `backend/app/services/etsy_sync.py` to use `item_dimensions.effective_dimensions(product)` when set.

---

## Phase 11: Polish & Cross-Cutting

- [ ] T070 [P] Document the advisor, dimensions, size classes and dispatch confirmation for operators in `docs-site/docs/pricing-model.md` (postage section) and a new `docs-site/docs/packaging.md`.
- [ ] T071 Run the PostgreSQL suites (`docker-compose.test.yml`): `tests/integration/test_every_tenant_table_has_rls.py` covers `order_parcels` and `order_parcel_items`; fresh DB reaches head; downgrade v2 → v1 → previous head works.
- [ ] T072 Full gates: `cd backend && poetry run pytest --cov=app --cov-report=term-missing && poetry run ruff check && poetry run ruff format --check`; `cd frontend && npm test && npm run lint && npm run typecheck`.
- [ ] T073 Walk every quickstart.md scenario (1–18) in the running app and tick them off.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (1)** → **Foundational (2)** → stories.
- **US1 (3)** depends on Foundational.
- **US2 (4)** depends on Foundational; uses US1's endpoints to set dims in tests via factories, so it can run alongside US1 after T012.
- **US3 (5)** depends on Foundational (+ T014 router for `adopt_file_id`).
- **US4 (6)** depends on US2 (extends `suggest`).
- **US5 (7)** depends on US2 (accepted packaging, container weights).
- **US6 (8)** depends on US2 and US5 (T060 replaces T052's weight-only path for multi-unit orders).
- **US5 dispatch (9)** depends on US6 (suggestions pre-fill the dialog) and T047 tables.
- **US7 (10)** depends on Foundational only.
- **Polish (11)** last.

### Within Each Story

Tests first (must fail) → models/migrations → services → endpoints → frontend.

### Parallel Opportunities

- T001, T002 together. T004–T008 together after T003.
- US1 backend T015/T016 with frontend T017.
- US2: T020, T021, T022 together; T023, T024, T029, T030 together.
- US3 tests T033, T034 together; US3 can run in parallel with US2.
- US7 (T066–T069) can run any time after Foundational.
- Phase 2 (US5): T048, T049, T053, T054 together after T047.

## Parallel Example: User Story 2

```text
T020 advisor unit tests        | T021 API tests        | T022 cost-authority test
T023 consumable packaging API  | T024 settings endpoint | T029 consumable dialogs | T030 settings UI
→ T025 suggest() → T026 loader → T027 endpoints → T028 warnings → T031 suggestions UI → T032 variant note
```

## Implementation Strategy

### MVP First

1. Phases 1–2 → 3 (US1) → 4 (US2): the operator records sizes and gets a box. **Release.**
2. Phase 5 (US3) and 6 (US4): measurement and filler. **Release MVP complete.**

### Incremental Delivery (Phase 2)

3. Phase 7 (US5 postage) with the delta report. **Release.**
4. Phases 8–9 (US6 + dispatch). **Release.**
5. Phase 10 (US7) whenever convenient.

## Notes

- [P] tasks touch different files and have no unmet dependency.
- Commit after each task or logical group, `feat:` / `test:` prefixes, no AI markers (CLAUDE.md).
- Never recompute a cost in the advisor or the frontend; never store a suggestion.
