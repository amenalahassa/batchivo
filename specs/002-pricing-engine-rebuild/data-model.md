# Phase 1 Data Model — Pricing Engine Rebuild

**Feature**: 002-pricing-engine-rebuild | **Date**: 2026-10-11

Conventions follow the existing codebase: `Base, UUIDMixin, TimestampMixin`, UUID primary keys, `tenant_id` foreign key with `ondelete="CASCADE"` and an index, `Numeric` for money and rates, `Mapped[Decimal]` annotations, table and column comments. Every table below carries an RLS policy scoped on `tenant_id`, and every read goes through `get_tenant_db`.

Money columns use `Numeric(12, 4)` for rates and derived per-unit figures, `Numeric(10, 2)` for amounts the operator types, matching what the codebase already does. Percentages are stored as `Numeric(7, 4)` holding a percentage value (6.5 means 6.5%), consistent with the existing `SalesChannel.fee_percentage`.

---

## Extended tables

### `printers` — machine cost policy (Tier 1)

| Column | Type | Notes |
|---|---|---|
| `purchase_price` | `Numeric(10,2)` nullable | All-in acquisition cost |
| `expected_lifetime_hours` | `Integer` nullable | Denominator for depreciation |
| `maintenance_reserve_total` | `Numeric(10,2)` nullable | Nozzles, belts, plates, AMS over the life |
| `measured_watts` | `Numeric(8,2)` nullable | Draw while printing |
| `electricity_rate_per_kwh` | `Numeric(8,4)` nullable | Falls back to the tenant policy value |

Derived, not stored (Constitution V): `machine_rate_per_hour = purchase_price / expected_lifetime_hours + maintenance_reserve_total / expected_lifetime_hours + measured_watts / 1000 × electricity_rate_per_kwh`.

Validation: `expected_lifetime_hours > 0` where `purchase_price` is set; a printer with incomplete policy yields no machine rate and marks the item incompletely costed (FR-019), never a zero rate.

### `models` — item cost profile (Tier 1)

| Column | Type | Notes |
|---|---|---|
| `waste_grams` | `Numeric(8,2)` default 0 | Purge, priming, colour change — separate from part weight (FR-009) |
| `expected_yield` | `Numeric(5,4)` default 1.0 | Per-part success probability (research D3) |
| `failure_mode` | `String(10)` default `'per_part'` | `per_part` or `per_plate`, CHECK constrained |
| `labor_hours_per_plate` | `Numeric(8,3)` default 0 | Divided across plate output |
| `labor_hours_per_item` | `Numeric(8,3)` default 0 | Not divided |
| `finishing_hours_per_item` | `Numeric(8,3)` default 0 | Charged at the finishing rate |
| `packing_hours_per_item` | `Numeric(8,3)` default 0 | **Not at risk** (FR-015) |

`labor_hours` is retained and deprecated: the Tier 1 migration copies it into `labor_hours_per_item` and stops reading it. Print time is **not** added here — `models.print_time_minutes` and `model_printer_configs.print_time_minutes` already exist, and the per-printer value wins when a config row exists.

Validation: `expected_yield` in `(0, 1]`; a zero yield is rejected rather than producing an infinite cost. `expected_yield = 1.0` must be a no-op under either mode.

### `spools` and `filament_purchases` — landed cost (Tier 1)

`spools` gains `filament_purchase_id` (nullable FK) and `unusable_remainder_grams` (`Numeric(8,2)`, nullable). A spool without a purchase keeps working from its own `purchase_price` with no allocated shipping (FR-008e).

### `sales_channels` — economics and tax (Tier 2)

| Column | Type | Notes |
|---|---|---|
| `tax_remitter` | `String(12)` | `marketplace` or `operator`, CHECK constrained (FR-028b) |
| `expected_discount_pct` | `Numeric(7,4)` default 0 | Reduces planned net revenue |
| `expected_refund_pct` | `Numeric(7,4)` default 0 | Reserve |
| `free_shipping_threshold` | `Numeric(10,2)` nullable | Solver may snap to it |
| `rounding_rule` | `String(20)` nullable | e.g. `psychological_99` |
| `currency_code` | `String(3)` | Channel display currency |
| `offsite_ads_opt_in` | `Boolean` default false | Policy lever |

`fee_percentage` and `fee_fixed` are **deprecated, not dropped**, in Tier 2: the migration converts each channel into equivalent `fee_rule` rows, and a later tier drops the columns once no read path remains. That drop has since landed in Polish (task T123, `pricing_drop_legacy_v1`), together with the legacy `Tenant.settings["default_labor_rate"]` key that seeded the first policy row. `monthly_cost` stays and is finally absorbed by `channel_pnl`.

### `product_pricing` — temporal (Tier 3)

Gains `valid_from` (`Date`, not null, backfilled from `created_at`), `valid_to` (`Date`, nullable), `min_quantity` (`Integer` default 1). `uq_product_channel_pricing` is dropped; replaced by a partial unique index on `(product_id, sales_channel_id, min_quantity) WHERE valid_to IS NULL`. Overlapping ranges and overlapping tiers are rejected in the service with a test (research D6).

### `order_items` — snapshot (Tier 3)

| Column | Type | Notes |
|---|---|---|
| `cost_breakdown_json` | `JSONB` nullable | Written once, never recomputed (FR-036, FR-037) |
| `make_cost_at_sale` | `Numeric(10,2)` nullable | |
| `list_price_at_sale` | `Numeric(10,2)` nullable | |
| `fees_json` | `JSONB` nullable | Itemised **planned** fees |
| `fx_rate` | `Numeric(14,8)` nullable | Frozen; never revised (FR-028j) |
| `margin_basis_at_sale` | `String(20)` nullable | The basis in effect (FR-031d) |
| `pricing_rev` | `Integer` nullable | Engine revision that produced the snapshot |

`orders` gains `postage_paid` (`Numeric(10,2)`) and `sales_tax_collected` (`Numeric(10,2)`). The existing `orders.shipping_cost` is revenue charged to the customer and **must not** be reused for postage cost.

### `products` — trimmed (Tier 0)

`calculate_make_cost` and `_calculate_model_cost` are deleted. No column changes; the packaging path (`packaging_cost`, `packaging_consumable_id`, `packaging_quantity`) is reused as-is and reclassified as not-at-risk in the breakdown.

---

## New tables

### `tenant_pricing_policy` (Tier 1)

One row per effective period; changing one lever writes a new row copying the rest (research D2).

`tenant_id`, `print_labor_rate`, `finishing_labor_rate`, `default_machine_rate_per_hour` (the FR-011 fallback when no printer is assigned), `margin_basis` (`customer_total` | `item_price` | `net_revenue`, default `customer_total`), `default_target_margin_pct`, `overhead_method` (`per_machine_hour` | `percentage`, default `per_machine_hour`), `overhead_monthly_pool`, `expected_monthly_machine_hours`, `electricity_rate_per_kwh`, `sales_tax_recoverable` (Boolean), `rounding_rule`, `staleness_threshold_days`, `margin_alert_threshold_pct`, `min_outcomes_before_auto_update` (default 5), `estimate_divergence_threshold_pct`, `effective_from` (Date), `effective_to` (Date nullable), `set_by_user_id`, `set_by_role`.

Constraints: partial unique index on `(tenant_id) WHERE effective_to IS NULL`; `expected_monthly_machine_hours > 0` when `overhead_method = 'per_machine_hour'`. Migration seeds the first row from `Tenant.settings["default_labor_rate"]` with `source = 'assumed'`, `effective_from = tenant.created_at`.

### `pricing_input_provenance` (Tier 1)

`tenant_id`, `entity_type` (CHECK against the registry's known types), `entity_id` (UUID), `field_name` (String(64)), `source` (`policy` | `observed` | `measured` | `assumed`), `as_of` (Date), `confidence` (`Numeric(5,4)` nullable), `measured_by_user_id` (nullable), `authorised_by_role` (nullable).

Unique on `(tenant_id, entity_type, entity_id, field_name)`; index on `(tenant_id, source)` for "what is still assumed". Field-name validity is enforced by the registry in `services/provenance.py` and its coverage test, not by the database (research D1).

### `filament_purchases` (Tier 1)

`tenant_id`, `supplier`, `purchase_date`, `inbound_shipping_cost`, `tax_amount`, `tax_recoverable` (Boolean), `order_reference`, `notes`. Shipping is allocated across the purchase's spools in proportion to weight (FR-008b); where weights are unknown the allocation falls back to an even split and says so.

### `fee_rules` (Tier 2)

`tenant_id`, `sales_channel_id`, `name`, `basis` (CHECK: `item_subtotal` | `item_plus_shipping` | `order_total` | `per_listing` | `per_order` | `per_unit_sold` | `per_month`), `rate_pct`, `fixed_amount`, `min_amount` (nullable), `max_amount` (nullable), `incidence_pct` (nullable), `sort_order` (Integer), `applies_from` (Date), `applies_to` (Date nullable).

Constraints: `min_amount <= max_amount` when both present (FR-021d); overlapping rules of the same `(channel, name)` over dates rejected in the service (FR-022).

### `fee_actuals` (Tier 2)

`tenant_id`, `sales_channel_id`, `fee_category` (matches a rule's `name`), `period_start`, `period_end`, `order_id` (nullable), `amount`, `source` (always entered until ingestion lands), `recorded_by_user_id`.

An order-scoped row takes precedence and reduces the period's unallocated remainder (FR-041c). A CHECK enforces exactly one of a period scope or an order scope. Order-level amounts exceeding the period total are reported, never absorbed silently.

### `shipping_profiles` (Tier 2)

`tenant_id`, `name`, `destination_zone`, `weight_bracket_min_grams`, `weight_bracket_max_grams`, `postage_cost`, `carrier`, `effective_from`. Packaging is **not** here — it stays on the product (FR-016).

### `fx_rates` (Tier 3)

`base_currency`, `quote_currency`, `rate_date`, `rate` (`Numeric(14,8)`), `source` (`service` | `manual`), `fetched_at`. Unique on `(base_currency, quote_currency, rate_date, source)`. This table is **not** tenant-scoped — a published exchange rate is not tenant data — which makes it the one exception to the RLS rule above, and it is called out so the exception is deliberate rather than an oversight.

### `estimate_revisions` (Tier 4)

`tenant_id`, `entity_type`, `entity_id`, `field_name`, `current_value`, `observed_value`, `divergence_pct`, `derived_from_run_ids` (JSONB), `state` (`pending` | `accepted` | `rejected`), `reviewed_by_user_id`, `reviewed_at`.

A later proposal on the same field supersedes an earlier pending one rather than queueing. A rejected proposal is not re-raised from the same outcomes (FR-042d).

### `scenario_runs` (Tier 4)

`tenant_id`, `requested_by_user_id`, `shock_json` (the overrides applied), `inputs_json` (what the run used), `margin_floor_pct`, `state` (`queued` | `running` | `succeeded` | `partial` | `failed`), `result_json`, `error_text`, `started_at`, `finished_at`.

Holds no authoritative cost or price (FR-044d). A result read later states the shock and inputs it ran with (FR-044c).

---

## Cost breakdown shape

Not a table — the structure the engine returns and the snapshot stores. Each line carries its amount, its risk class and its provenance, so the observed share is computable from the breakdown alone.

```text
CostBreakdown
├── lines[]: { key, label, amount, risk_class: at_risk|not_at_risk, source, as_of }
│     material, waste, machine, overhead, labor_handling, labor_finishing,
│     labor_packing, packaging, components, child_products
├── at_risk_subtotal, not_at_risk_subtotal
├── yield_applied, failure_mode, failure_premium
├── total_make_cost
├── observed_share, assumed_share
└── incomplete_reasons[]        # FR-019: what was missing, if anything
```

## Migration sequence

One migration per tier, each chained onto the current single head `commerce_handover_v1`. A fresh database must reach head after every one (Constitution, Additional Constraints).

| Tier | Migration content | Reversibility |
|---|---|---|
| 0 | None — code only | n/a |
| 1 | Printer cost columns; model cost profile; spool and purchase tables; policy and provenance tables; backfill `labor_hours` → `labor_hours_per_item`, policy row per tenant, `source = 'assumed'` provenance for every existing numeric | Downgrade drops new tables and columns; the `labor_hours` copy is additive so no data is lost |
| 2 | Fee rules, fee actuals, shipping profiles; channel columns; **data migration** converting each channel's `fee_percentage`/`fee_fixed` into equivalent rules | Downgrade removes rules; deprecated channel columns are still populated, so the old path survives a rollback |
| 3 | Order-item snapshot columns; orders postage and tax; temporal pricing with the constraint swap; `fx_rates` | The constraint swap is the one step that needs care: downgrade must re-add `uq_product_channel_pricing`, which fails if more than one row per pair exists — the downgrade path therefore collapses history to the current row and says so |
| 4 | Estimate revisions; scenario runs | Downgrade drops both |

Every migration that changes a computed value ships with the per-product delta report the Constitution requires before the change is accepted.
