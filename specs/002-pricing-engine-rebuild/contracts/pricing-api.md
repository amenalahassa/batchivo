# API Contracts — Costing, Fees, Policy, Reconciliation

**Feature**: 002-pricing-engine-rebuild | **Date**: 2026-10-11

All routes are under `/api/v1`, take `get_current_tenant` and use `get_tenant_db` (Constitution I). All return `422` on validation failure and `401` unauthenticated, per the project's existing conventions, so neither is repeated per route. Monetary values serialise as decimal strings, never JSON numbers, so no float appears on the wire.

Role requirements follow FR-007a–d: **admin or owner** for monetary policy, **member** for operational item figures, **viewer** for every read.

---

## Costing reads

### `GET /models/{model_id}/cost`

Returns the structured breakdown for one printed item.

Response `200`: the `CostBreakdown` shape in [data-model.md](../data-model.md) — lines with amount, risk class, source and date; at-risk and not-at-risk subtotals; yield applied, failure mode and the failure premium; total; observed and assumed shares; `incomplete_reasons` when an input needed for a line is missing (FR-019).

`404` when the model is absent or belongs to another tenant.

### `GET /products/{product_id}/cost`

Same shape, with the recursive bill of materials resolved — `models_cost`, `child_products_cost`, packaging and assembly as lines, cycle detection and the depth limit preserved (FR-017).

`409` with the offending chain when a circular reference is detected; `409` when the depth limit is exceeded. These replace today's unhandled exceptions.

### `GET /products/{product_id}/pricing/{channel_id}/margin`

Query: `as_of` (date, optional — defaults to today), `quantity` (optional, default 1).

Response `200`: list price in effect, itemised fees (each with `name`, `basis`, `amount`, `clamp_applied`, `is_expected`), postage paid, shipping revenue, reserves, make cost, profit, margin percentage, **the margin basis that produced it** (FR-031b), profit per machine-hour, and the observed share.

`404` when the product is not priced on that channel as at `as_of` — reported as unpriced, not as a zero margin.

---

## Target-margin solving

### `POST /products/{product_id}/pricing/{channel_id}/solve`

Body: `target_margin_pct`, optional `quantity`, optional `apply_rounding` (default true), optional `snap_to_free_shipping` (default true).

Response `200`: `required_price_raw`, `required_price_rounded`, the adjustments applied in order, `binding_clamps[]` naming each fee whose cap or floor bound at that price (FR-032a), and `inputs` — every figure that produced the answer (FR-034).

Response `422` with `reason: "unachievable"` and the binding constraint when percentage fees plus the target reach or exceed the denominator (FR-035).

The result is a proposal. Nothing is published to any channel; applying it is a separate `PUT` on the price (FR-033, US4 scenario 5).

### `GET /products/{product_id}/pricing/{channel_id}/ladder`

Query: `price_from`, `price_to`, `step`, optional `quantity`.

Response `200`: margin, profit and profit per machine-hour at each price point, each on the margin basis in effect. This is how the system informs a market judgement without ever storing one (FR-007): it shows the ladder and the operator chooses. No value is written back.

---

## Machine cost policy

### `GET /printers/{printer_id}/cost-policy`
### `PUT /printers/{printer_id}/cost-policy` — **admin or owner**

Body: `purchase_price`, `expected_lifetime_hours`, `maintenance_reserve_total`, `measured_watts`, `electricity_rate_per_kwh`.

Response `200`: the stored policy plus the derived `machine_rate_per_hour` and its component parts, each with provenance. `422` when `expected_lifetime_hours` is zero or absent while a purchase price is set.

---

## Operator policy

### `GET /settings/pricing-policy`

Query: `as_of` (optional). Returns the policy row in effect, every field with its provenance and the role that last changed it.

### `PUT /settings/pricing-policy` — **admin or owner**

Writes a **new effective row**; it never updates in place (FR-003). Body carries only the levers being changed; the rest are copied forward.

Response `200`: the new row with its `effective_from`. `403` for member and viewer, leaving the figure and its provenance untouched (FR-007d).

Changing `margin_basis` here changes no stored amount — only percentages derived afterwards (FR-031c), and no settled order is restated (FR-031d).

---

## Fee rules

### `GET /sales-channels/{channel_id}/fee-rules`

Query: `as_of` (optional). Returns rules in `sort_order`.

### `POST` / `PUT` / `DELETE /sales-channels/{channel_id}/fee-rules[/{rule_id}]` — **admin or owner**

Body: `name`, `basis` (one of the seven), `rate_pct`, `fixed_amount`, `min_amount`, `max_amount`, `incidence_pct`, `sort_order`, `applies_from`, `applies_to`.

`422` when `min_amount > max_amount` (FR-021d), or when the rule overlaps another of the same name on dates (FR-022).

### `POST /sales-channels/{channel_id}/fee-rules/preview` — **member**

Body: a hypothetical order context (`item_subtotal`, `shipping_revenue`, `quantity`, `date`). Returns the itemised fees that would be charged, with clamps and expected-incidence flags — the fee engine made inspectable without creating anything.

---

## Reconciliation and channel profitability

### `POST /reconciliation/fee-actuals` — **admin or owner**

Body: either a period scope (`period_start`, `period_end`, `fee_category`, `amount`) or an order scope (`order_id`, `fee_category`, `amount`). Exactly one of the two.

Response `201`. `409` when an order-scoped amount would push the period's unallocated remainder below zero — the inconsistency is reported so the period total gets fixed (FR-041c and its edge case).

### `GET /reconciliation/channel-pnl`

Query: `channel_id`, `period_start`, `period_end`.

Response `200`: realised revenue tax-exclusive, planned fees, recorded actual fees, unallocated remainder, difference against plan (FR-041d), periodic and per-listing costs absorbed over the period's actual order volume (FR-025), sales tax collected shown as a liability and never as revenue (FR-028d), and the period's margin with its basis named.

Where a period has no orders, periodic cost is reported as unabsorbed rather than divided by zero.

---

## Provenance and estimate proposals

### `GET /provenance?entity_type=&entity_id=`

Returns every recorded origin for that entity's numeric fields — read to all roles (FR-007c).

### `PUT /provenance/{entity_type}/{entity_id}/{field_name}` — **member** for measured figures, **admin or owner** for policy figures

Records or updates a hand-measured value's origin and date. Rejected for a field whose current origin is `observed`, which is read-only and refreshed only from its source (FR-004).

### `GET /estimate-revisions?state=pending` *(Tier 4)*
### `POST /estimate-revisions/{id}/accept` | `/reject` *(Tier 4)* — **member**

A pending proposal states the current estimate, the observed value, the divergence and the outcomes behind it, and is accepted or rejected whole (FR-042c). While pending, pricing keeps using the current estimate and the figure is flagged as having a pending revision (FR-042e).
