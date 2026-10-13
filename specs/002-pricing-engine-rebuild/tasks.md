---

description: "Task list for Pricing Engine Rebuild — Margins That Match Reality"
---

# Tasks: Pricing Engine Rebuild — Margins That Match Reality

**Input**: Design documents from `/specs/002-pricing-engine-rebuild/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md, `.specify/memory/constitution.md` v1.0.0

**Tests**: Test tasks are included and non-optional. Constitution principle II makes tests part of every change, and principle II plus the Development Workflow section state that a suite turning green by restoring a defect is a failed change.

**Organization**: Tasks are grouped by user story. Unlike a typical feature, the first three stories form a chain — a margin cannot be right before costs are — so US2 → US3 → US4 is a genuine ordering, not a staffing preference. This is stated explicitly under Dependencies rather than pretended away.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US7)
- Exact file paths are included in every task

## Path Conventions

Web application layout per plan.md: `backend/app/` and `backend/tests/` for the FastAPI service, `frontend/src/` for the React SPA, `backend/alembic/versions/` for migrations, `infrastructure/k8s/` for deployment manifests.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: scaffolding and tooling that every later phase uses. No behaviour change.

- [X] T001 Create the pricing test package with `__init__.py` at `backend/tests/unit/pricing/__init__.py`
- [X] T002 [P] Add per-module mypy overrides tightening `app.services.costing`, `landed_cost`, `fee_engine`, `pricing_solver`, `channel_pnl` in `backend/pyproject.toml` under `[tool.mypy]` (research D8)
- [X] T003 [P] Write the AST-based float ban as a test in `backend/tests/unit/pricing/test_no_float_in_money_paths.py` — it parses the five modules above and fails on any `float` annotation or `float(...)` call (research D8)
- [X] T004 Create the golden fixture at `backend/tests/fixtures/golden_case.py` holding **inputs only** — 142 g part, 3 g purge, CA$31.00 per 1000 g landed with 25 g unusable, 9.5 h print, printer at CA$1,100 over 6,000 h with CA$220 reserve and 95 W at CA$0.13/kWh, 15 min at-risk labor and 5 min packing at CA$25/h, CA$180/month over 600 machine-hours, CA$0.92 packaging, 92% yield, one print per plate. No expected values live here
- [X] T005 [P] Create the per-product cost delta report script at `backend/scripts/cost_delta_report.py`, taking a `--before-ref` and a `--cause` label, emitting one row per product with its before and after cost and the attributed cause, and exiting non-zero when any change is unattributed
- [X] T006 [P] Create the frontend pricing surface skeleton: `frontend/src/components/pricing/` directory and `frontend/src/types/pricing.ts` mirroring the breakdown schema

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: contracts and guardrails every story depends on. Deliberately contains **no migration**, so that US1 can ship without one.

**⚠️ CRITICAL**: no user story work begins until this phase is complete

- [X] T007 Define the `CostBreakdown` and `CostLine` schemas in `backend/app/schemas/model.py` per the Cost breakdown shape in data-model.md — `lines[]` each with `key`, `label`, `amount`, `risk_class` (`at_risk` | `not_at_risk`), `source`, `as_of`; plus `at_risk_subtotal`, `not_at_risk_subtotal`, `yield_applied`, `failure_mode`, `failure_premium`, `total_make_cost`, `observed_share`, `assumed_share`, `incomplete_reasons[]`
- [X] T008 [P] Write the property-test harness in `backend/tests/unit/pricing/test_properties.py`: margin monotonic in price, cost monotonic in weight and in hours, a yield of 1.0 is a no-op, bundle cost equals the sum of its children
- [X] T009 [P] Write the graph-coherence test in `backend/tests/integration/test_cost_graph_coherence.py`: build a randomised bill-of-materials graph, mutate a leaf spool price, assert no stale figure is served through any transitive ancestor (Constitution V)
- [X] T010 [P] Write the RLS harness for new pricing endpoints in `backend/tests/integration/test_rls_pricing.py`, asserting a second tenant's rows are invisible through every route added by this feature (Constitution I)
- [X] T011 [P] Write the migration-head test in `backend/tests/integration/test_migration_head.py` asserting `alembic upgrade head` succeeds on an empty database and that exactly one head exists
- [X] T012 [P] Assert monetary JSON serialisation in `backend/tests/unit/pricing/test_money_serialisation.py` — every money field crosses the wire as a decimal string, never a JSON number

**Checkpoint**: guardrails in place; the float ban, the property tests and the RLS harness will now fail loudly on any regression

---

## Phase 3: User Story 1 — My own settings actually drive my numbers (Priority: P1) 🎯 MVP

**Goal**: one authoritative cost calculation, and the operator's configured labor rate is the figure actually used.

**Independent Test**: set the labor rate to a distinctive value and confirm the labor line reflects it; open the same product from the product list, the product detail and the channel pricing screen and confirm all three report an identical make-cost to the cent.

**Tier 0 — code only, no migration.** Its acceptance criterion is that reported costs **change**; the delta report is a deliverable.

### Tests for User Story 1

> Write these first. They must fail before implementation, and they must never be made to pass by restoring the hardcoded rate.

- [X] T013 [P] [US1] Test that the tenant labor rate reaches every costing call site, in `backend/tests/api/test_costing_uses_tenant_rate.py`
- [X] T014 [P] [US1] Test that one product reports an identical make-cost from the list, detail and pricing endpoints, in `backend/tests/api/test_cost_consistency.py`
- [X] T015 [P] [US1] Rewrite `backend/tests/unit/test_costing_service.py` against the single implementation, with expected values recomputed from inputs rather than carried over
- [X] T016 [P] [US1] Rewrite `backend/tests/unit/test_costing_service_product_cost.py` the same way
- [X] T017 [P] [US1] Rewrite `backend/tests/unit/test_costing_service_pure.py` the same way
- [X] T018 [P] [US1] Rewrite `backend/tests/unit/test_pricing_models.py` for decimal returns from `SalesChannel` and `ProductPricing`

### Implementation for User Story 1

- [X] T019 [US1] Delete `calculate_make_cost` and `_calculate_model_cost` from `backend/app/models/product.py` (lines 461-546) and remove every import of them (Constitution III)
- [X] T020 [P] [US1] Convert `SalesChannel.calculate_platform_fee` to `Decimal` in and out in `backend/app/models/sales_channel.py`
- [X] T021 [P] [US1] Convert `ProductPricing.calculate_profit` to return `Decimal` values instead of `float` in `backend/app/models/product_pricing.py`
- [X] T022 [US1] Thread the tenant labor rate and overhead percentage into all 12 `CostingService` call sites in `backend/app/api/v1/products.py`
- [X] T023 [US1] Thread the same into the 2 call sites in `backend/app/api/v1/models.py` (lines 48 and 157)
- [X] T024 [US1] Replace `Mapped[float]` with `Mapped[Decimal]` on every `Numeric` column in `backend/app/models/` — `model.py`, `product.py`, `sales_channel.py`, `product_pricing.py`, `spool.py`, `consumable.py`, `model_material.py`
- [X] T025 [US1] Run `backend/scripts/cost_delta_report.py` and commit its output to `specs/002-pricing-engine-rebuild/delta-tier0.md`, with every changed cost attributed to the labor-rate correction and no unattributed change
- [X] T026 [US1] Make the three screens read the same cost field from one endpoint shape in `frontend/src/components/products/ProductList.tsx`, `ProductDetail.tsx` and `ProductPricingEditor.tsx`
- [X] T026a [P] [US1] Vitest test asserting the three screens render one identical make-cost in `frontend/src/components/products/ProductDetail.test.tsx`

**Checkpoint**: one implementation, the configured rate honoured, delta report accepted. US1 is shippable on its own.

---

## Phase 4: User Story 2 — A make-cost that includes the machine and the failures (Priority: P1)

**Goal**: machine occupancy, purge and spool remainder, the plate/item and handling/finishing labor split, overhead per machine-hour, and a failure premium applied only to work at risk.

**Independent Test**: seed the golden fixture and confirm the make-cost it reports; then vary print hours alone and confirm only the machine and overhead lines move.

**Depends on**: US1 (there must be one engine to extend).

### Tests for User Story 2

- [X] T027 [P] [US2] Golden-case test in `backend/tests/unit/pricing/test_golden_case.py` asserting a make-cost of **CA$20.30**, with the expected value computed from the fixture's inputs in one unrounded chain and rounded only for the assertion
- [X] T028 [P] [US2] Failure-mode tests in `backend/tests/unit/pricing/test_yield_modes.py`: yield 1.0 is a no-op under both modes; `per_part` and `per_plate` agree exactly at one print per plate; at four per plate with the same yield figure `per_plate` is strictly higher (divisor `y` versus `y^N`, research D3)
- [X] T029 [P] [US2] At-risk boundary test in `backend/tests/unit/pricing/test_at_risk_split.py`: the premium touches material, waste, machine, overhead, handling and finishing, and leaves packaging materials and packing labor untouched
- [X] T030 [P] [US2] Landed-cost tests in `backend/tests/unit/pricing/test_landed_cost.py`: four equal spools split shipping evenly and land at CA$31.00 each; one 250 g spool with three 1 kg spools allocates shipping by weight, with the expected per-spool amount computed from the fixture's own inputs rather than approximated; recoverable tax excluded and non-recoverable included; unknown weights fall back to an even split and say so
- [X] T031 [P] [US2] Incomplete-costing tests in `backend/tests/unit/pricing/test_incomplete_costing.py`: a printer with no cost policy and an item with no print time are both reported incompletely costed, never costed at zero
- [X] T032 [P] [US2] Provenance registry coverage test in `backend/tests/unit/pricing/test_provenance_registry.py` asserting every numeric input reachable by the cost engine has a registry entry (research D1 — this test is the enforcement the database cannot give)
- [X] T033 [P] [US2] Policy resolution tests in `backend/tests/unit/pricing/test_pricing_policy.py`: an as-of read returns the row in effect; a write creates a new effective row and never updates in place
- [X] T034 [P] [US2] Endpoint tests in `backend/tests/api/test_pricing_policy_api.py` and `backend/tests/api/test_printer_cost_policy.py` covering success, `403` for member and viewer with the figure left untouched, `422` validation, `404` not found

### Models for User Story 2

- [X] T035 [P] [US2] Extend `backend/app/models/printer.py` with `purchase_price Numeric(10,2)` nullable, `expected_lifetime_hours Integer` nullable, `maintenance_reserve_total Numeric(10,2)` nullable, `measured_watts Numeric(8,2)` nullable, `electricity_rate_per_kwh Numeric(8,4)` nullable, plus a derived `machine_rate_per_hour` property and a CHECK that `expected_lifetime_hours > 0` where `purchase_price` is set
- [X] T036 [P] [US2] Extend `backend/app/models/model.py` with `waste_grams Numeric(8,2)` default 0, `expected_yield Numeric(5,4)` default 1.0 with a CHECK restricting it to `(0, 1]`, `failure_mode String(10)` default `'per_part'` with a CHECK of `per_part` or `per_plate`, and `labor_hours_per_plate`, `labor_hours_per_item`, `finishing_hours_per_item`, `packing_hours_per_item` each `Numeric(8,3)` default 0. Retain and deprecate `labor_hours`; do not add a print-time field
- [X] T037 [P] [US2] Create `backend/app/models/tenant_pricing_policy.py` with the typed temporal columns listed in data-model.md including `default_machine_rate_per_hour Numeric(10,4)` nullable as the FR-011 fallback, a partial unique index on `(tenant_id) WHERE effective_to IS NULL`, and a CHECK that `expected_monthly_machine_hours > 0` when `overhead_method = 'per_machine_hour'`
- [X] T038 [P] [US2] Create `backend/app/models/pricing_input_provenance.py` with `source` CHECK-constrained to `policy | observed | measured | assumed`, unique on `(tenant_id, entity_type, entity_id, field_name)` and an index on `(tenant_id, source)`
- [X] T039 [P] [US2] Create `backend/app/models/filament_purchase.py` and extend `backend/app/models/spool.py` with `filament_purchase_id` nullable FK and `unusable_remainder_grams Numeric(8,2)` nullable — a spool with no parent purchase must stay valid (FR-008e)

### Services for User Story 2

- [X] T040 [US2] Implement `backend/app/services/provenance.py`: the `(entity_type, field_name)` registry, batched reads keyed on `(entity_type, entity_id) IN (...)`, writes, and observed-share computation from a breakdown's own lines
- [X] T041 [US2] Implement `backend/app/services/pricing_policy.py` resolving policy as-of a date and writing a new effective row per change
- [X] T042 [US2] Implement `backend/app/services/landed_cost.py`: shipping allocated by weight, tax recoverability, usable weight after the unusable remainder, even-split fallback flag, and the derivation trace FR-008f requires
- [X] T043 [US2] Rewrite `backend/app/services/costing.py` to emit the structured breakdown: machine line from the machine rate, overhead per machine-hour with the percentage method retained as an option, the four labor components, the at-risk and not-at-risk split, the failure premium per mode, packaging as not-at-risk, and the existing recursion with cycle detection and depth limit preserved
- [X] T044 [US2] Make the per-printer configuration win over the model-level figure in `backend/app/services/costing.py` — `model_printer_configs.print_time_minutes` and `material_weight_grams` take precedence when a config row exists, falling back to `models.print_time_minutes`

### Migration for User Story 2

- [X] T045 [US2] Write the Tier 1 migration in `backend/alembic/versions/`, chained onto `commerce_handover_v1`: new tables and columns, RLS policies on each new table, `labor_hours` copied into `labor_hours_per_item`, one `tenant_pricing_policy` row seeded per tenant from `Tenant.settings["default_labor_rate"]` with `effective_from = tenant.created_at`, and a provenance row of `source = 'assumed'`, `as_of = created_at` for every existing numeric input
- [X] T045a [US2] Run `backend/scripts/cost_delta_report.py` against the Tier 1 migration and commit the output to `specs/002-pricing-engine-rebuild/delta-tier1.md`, attributing every changed cost to a specific newly introduced line (machine, waste, yield, overhead method, landed cost) with no unattributed change

### Endpoints for User Story 2

- [X] T046 [P] [US2] Add `GET` and `PUT /printers/{printer_id}/cost-policy` in `backend/app/api/v1/printers.py`, admin or owner for the write, returning the derived rate with its component parts
- [X] T047 [P] [US2] Create `backend/app/api/v1/pricing_policy.py` with `GET /settings/pricing-policy` (all roles) and `PUT` (admin or owner, writing a new effective row)
- [X] T048 [P] [US2] Create `backend/app/api/v1/filament_purchases.py` with CRUD and the allocation shown per spool
- [X] T048a [P] [US2] API tests for filament purchases in `backend/tests/api/test_filament_purchases.py` covering `201` on create, `401` unauthenticated, `422` validation, `404` not found, and the per-spool allocation in the response
- [X] T049 [US2] Update `GET /models/{id}/cost` and `GET /products/{id}/cost` in `backend/app/api/v1/models.py` and `products.py` to the new breakdown, returning `409` with the offending chain on a circular reference and `409` on depth exceeded
- [X] T050 [US2] Register the new routers in `backend/app/main.py`

### Frontend for User Story 2

- [X] T051 [P] [US2] Build `frontend/src/components/pricing/CostBreakdownPanel.tsx` showing each line with its amount, risk class, origin and date, plus `incomplete_reasons`
- [X] T052 [P] [US2] Build the machine cost policy form in `frontend/src/components/printers/PrinterCostPolicyForm.tsx`
- [X] T053 [P] [US2] Build the pricing policy screen in `frontend/src/components/settings/PricingPolicySettings.tsx`
- [X] T054 [P] [US2] Build the filament purchase UI showing the per-spool allocation in `frontend/src/components/filaments/FilamentPurchaseForm.tsx`
- [X] T055 [US2] Add `frontend/src/lib/api/pricing.ts` and `frontend/src/hooks/usePricing.ts`, and extend `frontend/src/types/pricing.ts`
- [X] T055a [P] [US2] Vitest tests for the cost breakdown — lines, risk class, origin, date, incomplete reasons — in `frontend/src/components/pricing/CostBreakdownPanel.test.tsx`

**Checkpoint**: the golden case reports CA$20.30 from its own inputs; the two failure modes agree at one per plate and diverge above it.

---

## Phase 5: User Story 3 — A margin that survives contact with the marketplace (Priority: P1)

**Goal**: the real fee stack, shipping kept honest, tax-exclusive margin, and the margin basis as an operator setting.

**Independent Test**: configure the golden channel's fee rules and postage, confirm the margin reported at CA$64.99, and confirm a fee charged on item-plus-shipping moves when shipping revenue moves.

**Depends on**: US2 (a margin needs a correct cost).

### Tests for User Story 3

- [X] T056 [P] [US3] Fee engine tests in `backend/tests/unit/pricing/test_fee_engine.py`: all seven bases; rules evaluate in `sort_order`; no fee is ever charged on another fee (research D9)
- [X] T057 [P] [US3] Clamp tests in `backend/tests/unit/pricing/test_fee_clamps.py`: a maximum binds and the itemised list says so; a minimum binds; a rule with `min_amount > max_amount` is rejected at save time
- [X] T058 [P] [US3] Basis arithmetic tests in `backend/tests/unit/pricing/test_fee_bases.py`: `per_unit_sold` charges three times on three units while `per_order` charges once; `item_plus_shipping` changes with shipping revenue and shipping revenue is never netted before fees
- [X] T059 [P] [US3] Tax tests in `backend/tests/unit/pricing/test_sales_tax.py`: two otherwise identical sales, one with `tax_remitter = 'marketplace'` and one with `'operator'`, report the same margin; tax collected appears as a liability and never as revenue or profit
- [X] T060 [P] [US3] Margin basis tests in `backend/tests/unit/pricing/test_margin_basis.py`: all three bases change only the percentage, the make-cost stays CA$20.30 and the profit stays CA$22.92, and every figure names its basis
- [X] T061 [P] [US3] Migration parity test in `backend/tests/integration/test_fee_migration_parity.py` asserting the converted rules reproduce each channel's previous fee amount — every channel, not a sample
- [X] T062 [P] [US3] Legacy profile test in `backend/tests/unit/pricing/test_legacy_profile.py` reproducing the superseded 66.4% through the override profile, with an assertion that no second cost implementation exists (research D7)
- [X] T063 [P] [US3] Golden margin test in `backend/tests/unit/pricing/test_golden_case.py` asserting **35.3%** at CA$64.99 on the default basis
- [X] T064 [P] [US3] Endpoint tests in `backend/tests/api/test_fee_rules.py` and `backend/tests/api/test_reconciliation.py` covering success, `403` by role, `422` validation, `404` not found, and `409` when an order-scoped actual would push the period remainder below zero; plus an assertion that planned fees and a recorded statement total agree within 1% of the fee amount once the entered rates match the schedule (SC-009)

### Models for User Story 3

- [X] T065 [P] [US3] Create `backend/app/models/fee_rule.py` with `basis` CHECK-constrained to `item_subtotal | item_plus_shipping | order_total | per_listing | per_order | per_unit_sold | per_month`, `rate_pct Numeric(7,4)`, `fixed_amount Numeric(10,2)`, nullable `min_amount` and `max_amount` with a CHECK that `min_amount <= max_amount` when both are present, nullable `incidence_pct`, `sort_order Integer`, `applies_from Date`, `applies_to Date` nullable
- [X] T066 [P] [US3] Create `backend/app/models/fee_actual.py` with a CHECK enforcing exactly one of a period scope (`period_start`, `period_end`) or an order scope (`order_id`), and `source` recorded as entered
- [X] T067 [P] [US3] Create `backend/app/models/shipping_profile.py` with `destination_zone`, `weight_bracket_min_grams`, `weight_bracket_max_grams`, `postage_cost`, `carrier`, `effective_from` — packaging stays on the product and does not appear here
- [X] T068 [P] [US3] Extend `backend/app/models/sales_channel.py` with `tax_remitter String(12)` CHECK-constrained to `marketplace | operator`, `expected_discount_pct`, `expected_refund_pct`, `free_shipping_threshold` nullable, `rounding_rule String(20)` nullable, `currency_code String(3)`, `offsite_ads_opt_in Boolean` default false; mark `fee_percentage` and `fee_fixed` deprecated while keeping them populated
- [X] T069 [P] [US3] Extend `backend/app/models/order.py` with `postage_paid Numeric(10,2)` and `sales_tax_collected Numeric(10,2)` — and leave `shipping_cost` alone, since it is revenue charged, not cost

### Services for User Story 3

- [X] T070 [US3] Implement `backend/app/services/fee_engine.py` with `compute(channel, order_context, as_of)` returning an itemised list, each entry carrying `name`, `basis`, `amount`, `clamp_applied` and `is_expected`; `incidence_pct` scales planning figures only and never a recorded actual
- [X] T071 [US3] Implement tax-exclusive margin and liability tracking in `backend/app/services/costing.py` and the margin path, deriving and exposing the tax-exclusive amount when a recorded figure was tax-inclusive (FR-028e)
- [X] T072 [US3] Implement margin basis resolution from policy, and attach the basis label to every percentage, in `backend/app/services/costing.py`
- [X] T073 [US3] Implement `backend/app/services/channel_pnl.py` absorbing periodic and per-listing costs over actual order volume, reporting unabsorbed cost rather than dividing by zero, and reconciling planned against recorded actual fees with the unallocated remainder
- [X] T074 [US3] Implement the legacy override profile as a fixture in `backend/tests/fixtures/legacy_profile.py` — machine rate zero, yield 1.0, waste zero, nominal spool weight, overhead by percentage, no shipping, no reserves, fees reduced to the two migrated rules

### Migration for User Story 3

- [X] T075 [US3] Write the Tier 2 migration in `backend/alembic/versions/`: fee rules, fee actuals and shipping profiles with RLS; the new channel and order columns; and the data migration converting each channel's `fee_percentage` and `fee_fixed` into equivalent dated `fee_rule` rows
- [X] T075a [US3] Run the same delta report for the Tier 2 migration into `specs/002-pricing-engine-rebuild/delta-tier2.md`, attributing each change to the fee rules, shipping, tax treatment or margin basis

### Endpoints for User Story 3

- [X] T076 [P] [US3] Create `backend/app/api/v1/fee_rules.py` with list, create, update, delete scoped to a channel (admin or owner for writes) and `POST .../preview` taking a hypothetical order context (member)
- [X] T077 [P] [US3] Create `backend/app/api/v1/reconciliation.py` with `POST /reconciliation/fee-actuals` and `GET /reconciliation/channel-pnl`
- [X] T078 [P] [US3] Create `backend/app/api/v1/shipping_profiles.py` with CRUD
- [X] T078a [P] [US3] API tests for shipping profiles in `backend/tests/api/test_shipping_profiles.py` covering `200`/`201`, `401`, `422`, `404`
- [X] T079 [US3] Update the margin endpoint in `backend/app/api/v1/products.py` to return itemised fees, the margin basis, reserves, postage paid and shipping revenue, and the observed share
- [X] T080 [US3] Register the new routers in `backend/app/main.py`

### Frontend for User Story 3

- [X] T081 [P] [US3] Build `frontend/src/components/sales-channels/FeeRuleEditor.tsx` and extend `SalesChannelForm.tsx` with the tax remitter, reserves, threshold and rounding rule
- [X] T082 [P] [US3] Build `frontend/src/components/pricing/FeeBreakdownTable.tsx` showing each fee with its basis, whether a clamp bound, and whether it is an expectation
- [X] T083 [P] [US3] Build `frontend/src/components/pricing/MarginBasisLabel.tsx` and place it beside every margin percentage in `ProductPricingEditor.tsx` and `ProductDetail.tsx`
- [X] T084 [P] [US3] Build the reconciliation and channel P&L screen in `frontend/src/components/pricing/ChannelReconciliation.tsx`
- [X] T085 [US3] Add `frontend/src/lib/api/feeRules.ts` and `frontend/src/hooks/useFeeRules.ts`
- [X] T085a [P] [US3] Vitest tests for the fee table and basis label — clamp flag, expected-incidence flag, basis named beside every percentage — in `frontend/src/components/pricing/FeeBreakdownTable.test.tsx`

**Checkpoint**: 35.3% at CA$64.99; basis switching changes only the percentage; the superseded 66.4% is reproducible as data.

---

## Phase 6: User Story 4 — Tell me the price, don't make me guess it (Priority: P2)

**Goal**: state a target margin, receive the price that achieves it, correctly solved against the price the percentage fees are themselves charged on — and, where the judgement is the operator's rather than the system's, see margin across a ladder of prices instead of a single computed figure (FR-007).

**Independent Test**: ask for a 35% target on the golden item and channel and confirm CA$64.64 before rounding.

**Depends on**: US2 and US3 (built earlier it would confidently return the wrong price).

- [X] T086 [P] [US4] Solver tests in `backend/tests/unit/pricing/test_solver.py`: CA$64.64 for a 35% target; the three margin bases each solved correctly; a capped fee that stops scaling with price and is reported as binding; rounding and free-shipping snap each shown as an adjustment; an unachievable target reported with its binding constraint rather than a number
- [X] T086a [P] [US4] Price-ladder tests in `backend/tests/unit/pricing/test_price_ladder.py`: margin is returned at each price point on the basis in effect, the ladder's bounds and step are inputs rather than constants, and no single market-judgement figure is ever stored (FR-007)
- [X] T087 [US4] Implement `backend/app/services/pricing_solver.py` with one closed form per margin basis and a bounded clamp loop — solve, check which clamps bind, move each bound fee to the fixed bucket, re-solve, terminating in at most one pass per capped rule (research D10)
- [X] T088 [US4] Add `POST /products/{product_id}/pricing/{channel_id}/solve` in `backend/app/api/v1/products.py` returning the raw and rounded price, the adjustments in order, `binding_clamps[]` and the full `inputs`; `422` with `reason: "unachievable"` when no price exists
- [X] T088a [US4] Add `GET /products/{product_id}/pricing/{channel_id}/ladder` in `backend/app/api/v1/products.py`, taking a price range and step and returning margin, profit and profit per machine-hour at each point
- [X] T088b [US4] API tests for the solve and ladder endpoints in `backend/tests/api/test_price_solver.py` covering `200`, `401`, `422` with `reason: "unachievable"`, and `404` for an unpriced product on that channel
- [X] T089 [P] [US4] Build `frontend/src/components/pricing/PriceSolverPanel.tsx` presenting the result as a proposal the operator applies or rejects — nothing is published to a channel automatically
- [X] T089a [P] [US4] Vitest test asserting the solver result is a proposal that publishes nothing, and that an unachievable target renders its binding constraint, in `frontend/src/components/pricing/PriceSolverPanel.test.tsx`
- [X] T089b [P] [US4] Build `frontend/src/components/pricing/PriceLadder.tsx` presenting margin across the ladder for the operator to choose from, with no value written back automatically

**Checkpoint**: the solver returns CA$64.64 and explains itself.

---

## Phase 7: User Story 5 — Settled orders keep the margin they had (Priority: P2)

**Goal**: snapshots written once at sale, temporal prices, and a frozen exchange rate.

**Independent Test**: record an order, note its margin, change a spool price, a labor rate, an overhead setting and a fee rule, then re-read the order — the margin must be identical.

**Depends on**: US2 and US3 (a snapshot of a wrong cost is worth little). This phase carries the heaviest refactor in the feature.

- [X] T090 [P] [US5] Snapshot immutability test in `backend/tests/integration/test_snapshot_immutability.py`: after changing a spool price, a labor rate, an overhead setting and a fee rule, **zero** settled orders report a different margin
- [X] T091 [P] [US5] Temporal pricing tests in `backend/tests/unit/pricing/test_temporal_pricing.py`: an order from an earlier period reports the price effective on its date; overlapping date ranges are rejected at save time; overlapping quantity tiers are rejected; the price at exactly a break quantity is unambiguous
- [X] T092 [P] [US5] Exchange-rate tests in `backend/tests/unit/pricing/test_fx.py` using `respx`: a fetched rate is reused for the day; an unreachable service falls back to the last known rate with its date; a manual rate overrides; a sale is never blocked; a never-fetched pair asks rather than implying 1:1; a frozen rate survives a better rate becoming known
- [X] T093 [P] [US5] Extend `backend/app/models/order.py` `OrderItem` with `cost_breakdown_json JSONB`, `make_cost_at_sale Numeric(10,2)`, `list_price_at_sale Numeric(10,2)`, `fees_json JSONB`, `fx_rate Numeric(14,8)`, `margin_basis_at_sale String(20)` and `pricing_rev Integer`, all nullable and all written once
- [X] T094 [P] [US5] Extend `backend/app/models/product_pricing.py` with `valid_from Date` not null, `valid_to Date` nullable and `min_quantity Integer` default 1; drop `uq_product_channel_pricing` and add a partial unique index on `(product_id, sales_channel_id, min_quantity) WHERE valid_to IS NULL` (research D6)
- [X] T095 [P] [US5] Create `backend/app/models/fx_rate.py` — **not** tenant-scoped, since a published rate is not tenant data; document the deliberate RLS exception in the model docstring
- [X] T096 [US5] Write the snapshot at the moment of sale in `backend/app/services/order_fulfillment.py` and the checkout path, recording the breakdown, price, fees, rate and margin basis as they stood
- [X] T097 [US5] Implement as-of price resolution and a `Product.current_pricing` relationship primary-joined on `valid_to IS NULL`, then update every read site in `backend/app/api/v1/products.py` and `backend/app/api/v1/shop.py`
- [X] T098 [US5] Implement the exchange-rate adapter behind a narrow port in `backend/app/services/fx_service.py`, with day reuse, stale fallback, manual override and no network access in tests
- [X] T099 [US5] Write the Tier 3 migration in `backend/alembic/versions/`: snapshot columns, order postage and tax, the `fx_rates` table, and the constraint swap — the downgrade must document that it collapses price history to the current row
- [X] T099a [US5] Run the same delta report for the Tier 3 migration into `specs/002-pricing-engine-rebuild/delta-tier3.md`, and assert alongside T090 that zero settled order's margin moved
- [X] T100 [P] [US5] Build price history and quantity tiers into `frontend/src/components/products/ProductPricingEditor.tsx`
- [X] T100a [P] [US5] Vitest tests for price history and quantity tiers in `frontend/src/components/products/ProductPricingEditor.test.tsx`

**Checkpoint**: history is immovable. Watch the shop read paths this phase disturbs.

---

## Phase 8: User Story 6 — How much should I trust this number? (Priority: P3)

**Goal**: provenance visible on every line, the observed share stated, stale measurements flagged, and divergent observations held for review.

**Independent Test**: open a cost breakdown and confirm every line names its origin and date and the panel states the observed share.

**Depends on**: US2 (the provenance table and registry land there).

- [X] T101 [P] [US6] Variance tests in `backend/tests/unit/pricing/test_variance.py`: with enough outcomes and a close value the estimate updates on its own and its origin becomes observed, dated, with the outcomes it came from; a value diverging beyond the threshold is held as a proposal while pricing keeps using the current estimate; a rejected proposal is not re-raised from the same outcomes but a later one from new outcomes is; a newer proposal supersedes a pending one; an operator decision is never updated whatever the divergence
- [X] T102 [P] [US6] Provenance endpoint tests in `backend/tests/api/test_provenance.py`: reads available to viewer; a write rejected for a field whose origin is `observed`; a stale measurement flagged while still showing its last value
- [X] T103 [P] [US6] Create `backend/app/models/estimate_revision.py` with `state` CHECK-constrained to `pending | accepted | rejected`, `derived_from_run_ids JSONB`, `current_value`, `observed_value`, `divergence_pct`
- [X] T104 [US6] Implement `backend/app/services/variance_service.py`: rolling average once `min_outcomes_before_auto_update` is reached, proposal beyond `estimate_divergence_threshold_pct`, supersede-rather-than-queue, and the rule that a measurement updates but a decision never does
- [X] T105 [US6] Add `GET /provenance` and `PUT /provenance/{entity_type}/{entity_id}/{field_name}` in a new `backend/app/api/v1/provenance.py`, rejecting writes to observed fields
- [X] T106 [US6] Add `GET /estimate-revisions` and the accept and reject actions in `backend/app/api/v1/provenance.py`
- [X] T107 [P] [US6] Build `frontend/src/components/pricing/ProvenanceBadge.tsx` and `EstimateProposalList.tsx`, and add the observed-share summary and stale warning to `CostBreakdownPanel.tsx`
- [X] T107a [P] [US6] Vitest tests for the provenance badge, the observed share and the stale warning in `frontend/src/components/pricing/ProvenanceBadge.test.tsx`
- [X] T108 [US6] Write the migration for `estimate_revisions` in `backend/alembic/versions/` with its RLS policy

**Checkpoint**: a reader can tell an observed figure from a guess, and fee lines are labelled as entered.

---

## Phase 9: User Story 7 — Order the queue by what actually pays (Priority: P3)

**Goal**: profit per machine-hour as a headline figure, telemetry feeding the estimates, and catalogue-wide shocks as background jobs.

**Independent Test**: confirm the profit per machine-hour reported for the golden case and run a material-price shock across the catalogue.

**Depends on**: US2 (machine hours must be costed first).

- [X] T109 [P] [US7] Reporting and scenario tests in `backend/tests/api/test_scenarios.py`: profit per machine-hour of **CA$2.41** for the golden case; a scenario request acknowledged with `202` before any calculation; a finished run writing no cost, price or provenance figure; a partial or failed run reporting what it got and why it stopped; a result stating the shock and inputs it used; plus an assertion that at least 70% of the golden item's make-cost lines carry an observed origin while fee lines stay labelled as entered (SC-010)
- [X] T110 [P] [US7] Telemetry tests in `backend/tests/unit/pricing/test_telemetry_ingestion.py`: actual grams and print hours written to the run, 3MF metadata as the fallback, an offline printer producing no estimate change, and a smart-plug reading updating `measured_watts` with `source = 'observed'`
- [X] T111 [P] [US7] Create `backend/app/models/scenario_run.py` with `state` CHECK-constrained to `queued | running | succeeded | partial | failed`, `shock_json`, `inputs_json`, `margin_floor_pct`, `result_json`, `error_text`
- [X] T112 [US7] Create the Celery application and task package at `backend/app/tasks/celery_app.py` and `backend/app/tasks/scenario.py`
- [X] T113 [US7] Implement `backend/app/services/scenario_service.py` driving the engine through the same override mechanism the legacy profile uses, writing nothing authoritative
- [X] T114 [US7] Create `backend/app/api/v1/scenarios.py` with `POST /scenarios` returning `202`, `GET /scenarios/{id}` reporting state and result, and `GET /scenarios` for history
- [X] T115 [US7] Implement telemetry ingestion in `backend/app/tasks/telemetry.py` against the existing `printer_adapter` protocol, writing `actual_grams` and `actual_print_hours` onto production runs with 3MF metadata as the fallback
- [X] T116 [US7] Implement smart-plug ingestion in `backend/app/tasks/power.py` updating `printers.measured_watts` with an observed origin
- [X] T117 [US7] Add profit per machine-hour to the margin response and use it to order the print queue in `backend/app/services/print_queue_service.py`
- [X] T117a [US7] End-to-end accuracy test in `backend/tests/integration/test_realised_margin_accuracy.py`: a settled order with recorded actual fees, actual material use and actual print time reports a margin within 2 percentage points of the margin computed from what was actually received and actually paid (SC-001)
- [X] T118 [US7] Write the migration for `scenario_runs` in `backend/alembic/versions/` with its RLS policy
- [X] T119 [P] [US7] Build `frontend/src/components/pricing/ScenarioRunPanel.tsx` with job state and the below-floor list, and surface profit per machine-hour beside margin percentage
- [X] T119a [P] [US7] Vitest test for scenario job states — queued, running, partial, failed — in `frontend/src/components/pricing/ScenarioRunPanel.test.tsx`
- [X] T120 [US7] Add the Celery worker deployment manifest in `infrastructure/k8s/` and point the broker URL at the cluster Redis service rather than the configured `redis://localhost:6379/1` default (research D4)

**Checkpoint**: all seven stories are functional. Capacity, not margin percentage, orders the queue.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [ ] T121 [P] Update the pricing section of `CLAUDE.md` so it does not contradict the constitution or this feature
- [X] T122 [P] Add tracing spans to the cost, fee and solver paths via `backend/app/observability/tracing.py`, instrumenting `backend/app/services/costing.py`, `fee_engine.py` and `pricing_solver.py`
- [ ] T123 Drop the deprecated `SalesChannel.fee_percentage` and `fee_fixed` columns and the legacy `Tenant.settings["default_labor_rate"]` key, in a migration under `backend/alembic/versions/`, once no read path remains
- [ ] T124 Retire the legacy comparison profile per FR-052 by deleting `backend/tests/fixtures/legacy_profile.py` and its test
- [ ] T125 [P] Document the pricing model for operators in `docs-site/docs/pricing-model.md`
- [ ] T126 Run the full `specs/002-pricing-engine-rebuild/quickstart.md` validation end to end

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup; blocks every user story
- **US1 (Phase 3)**: depends on Foundational. No migration — ships alone
- **US2 (Phase 4)**: depends on US1
- **US3 (Phase 5)**: depends on US2
- **US4 (Phase 6)**: depends on US2 and US3
- **US5 (Phase 7)**: depends on US2 and US3
- **US6 (Phase 8)**: depends on US2
- **US7 (Phase 9)**: depends on US2
- **Polish (Phase 10)**: depends on every story being complete; T123 and T124 are irreversible and go last

### An honest note on story independence

The template's usual claim — that stories are independent and can be staffed in parallel — only partly holds here. US1 → US2 → US3 is a real chain: a margin cannot be correct before the cost is, and a solver built on wrong fees returns wrong prices with confidence. Once US3 lands, **US4, US5, US6 and US7 are genuinely parallel** and touch mostly separate files.

Each story nonetheless remains independently *testable and shippable* in its own right once its predecessors are in, which is what the checkpoints assert.

### Within Each User Story

Tests are written first and must fail before implementation. Then models, then services, then migration, then endpoints, then frontend. A story is complete when its checkpoint passes.

### Parallel Opportunities

- Setup: T002, T003, T005, T006 together
- Foundational: T008 through T012 together
- US1: the six test tasks T013–T018 together; then T020, T021 and T026a together
- US2: the eight test tasks T027–T034 together plus T048a and T055a; the five model tasks T035–T039 together; the four frontend tasks T051–T054 together
- US3: the nine test tasks T056–T064 together plus T078a and T085a; the five model tasks T065–T069 together; T076–T078 together; T081–T084 together
- US4: T086 and T086a together; then T089, T089a and T089b together
- US5: T090–T092 together, then T093–T095 together; T100 and T100a together
- US6: T101, T102 and T107a together
- US7: T109, T110 and T119a together
- After US3: US4, US5, US6 and US7 in parallel across developers

---

## Parallel Example: User Story 2

```bash
# All eight tests for User Story 2 together:
Task: "Golden-case test asserting CA$20.30 in backend/tests/unit/pricing/test_golden_case.py"
Task: "Failure-mode tests in backend/tests/unit/pricing/test_yield_modes.py"
Task: "At-risk boundary test in backend/tests/unit/pricing/test_at_risk_split.py"
Task: "Landed-cost tests in backend/tests/unit/pricing/test_landed_cost.py"
Task: "Incomplete-costing tests in backend/tests/unit/pricing/test_incomplete_costing.py"
Task: "Provenance registry coverage test in backend/tests/unit/pricing/test_provenance_registry.py"
Task: "Policy resolution tests in backend/tests/unit/pricing/test_pricing_policy.py"
Task: "Endpoint tests in backend/tests/api/test_pricing_policy_api.py"

# Then all five models together:
Task: "Extend backend/app/models/printer.py with machine cost columns"
Task: "Extend backend/app/models/model.py with the cost profile columns"
Task: "Create backend/app/models/tenant_pricing_policy.py"
Task: "Create backend/app/models/pricing_input_provenance.py"
Task: "Create backend/app/models/filament_purchase.py and extend spool.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1: Setup
2. Phase 2: Foundational
3. Phase 3: User Story 1
4. **STOP and VALIDATE**: one cost implementation, the configured labor rate honoured, the delta report reviewed
5. Ship it — this alone makes every figure on screen belong to the operator

### Incremental Delivery

Each tier leaves the system more correct than before, so each is shippable:

1. Setup + Foundational → guardrails
2. US1 → one engine, honoured settings **(MVP)**
3. US2 → a make-cost that includes the machine and the failures
4. US3 → a margin that survives the marketplace
5. US4, US5, US6, US7 → in parallel, in any order the team prefers
6. Polish → retire the deprecated columns and the legacy comparison

### Parallel Team Strategy

One developer carries US1 → US2 → US3 as a chain. Once US3 lands, four tracks open: the solver (US4), snapshots and temporal pricing (US5), provenance and proposals (US6), telemetry and scenarios (US7). US5 is the one to give the most experienced hand — it touches every price read path including the storefront.

---

## Notes

- **The trap to avoid**: US1 and US2 change reported costs on purpose. An agent or developer optimising for a green suite will be tempted to restore the hardcoded rate or patch an expected value back to its defective figure. The Constitution's Development Workflow section names that a failed change, not a passing one.
- The golden case is asserted to the cent at every phase, always recomputed from the fixture's inputs in one unrounded chain — never a value copied from a document.
- T099's downgrade collapses price history to the current row. Understand that before ever running it.
- T123 and T124 are irreversible cleanups; they go last, after every read path is gone.
- Commit after each task or logical group, `type: description`, no AI markers (Constitution VII).
