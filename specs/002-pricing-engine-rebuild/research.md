# Phase 0 Research — Pricing Engine Rebuild

**Feature**: 002-pricing-engine-rebuild | **Date**: 2026-10-11

The specification carries no `[NEEDS CLARIFICATION]` markers — ten were resolved across two clarification sessions. What remained for research was one deferred design decision (provenance storage) plus nine implementation decisions that the tiers cannot be sequenced without. Each is recorded as decision, rationale, alternatives.

---

## D1 — Provenance storage: one side table

**Decision**: a single table `pricing_input_provenance`, keyed `(tenant_id, entity_type, entity_id, field_name)`, holding `source`, `as_of`, `confidence`, `measured_by_user_id`, `authorised_by_role`. Valid `(entity_type, field_name)` pairs live in a Python registry module, `services/provenance.py`, and a test asserts every numeric input reachable by the cost engine has a registry entry.

**Rationale**: the inputs are spread across `Model`, `ModelMaterial`, `Product`, `Printer`, `Spool`, `FilamentPurchase` and operator policy. Column triples would add roughly 75 columns across seven tables for ~25 inputs, and each new input would mean another migration. A breakdown already loads its entities, so provenance comes back in one extra query batched on `(entity_type, entity_id) IN (...)`. The observed-versus-assumed share (FR-046) is computed from the breakdown's own lines, not from a database aggregate, so cross-field aggregation is not a hot path. The side table also makes FR-006 — a hand-measured input becoming observed when its source is instrumented — a row update rather than a schema change.

**Alternatives considered**:
- *Column triples per field*: better type safety and queryability, rejected for schema multiplication and per-input migrations.
- *A JSONB provenance column per row*: compact and join-free, but no better integrity than the side table, and it buries provenance inside the rows it describes, making "show me everything still assumed" a full scan of seven tables.

**Accepted cost**: PostgreSQL cannot enforce a foreign key on a field name. The registry plus its coverage test is the enforcement, and that is a test, not a constraint — stated plainly so nobody later assumes the database is guarding it.

## D2 — Operator policy leaves the settings blob for a typed temporal table

**Decision**: a new table `tenant_pricing_policy`, one row per effective period, with typed columns for every policy lever (print and finishing labor rates, margin basis, target margin default, overhead method, overhead pool, expected monthly machine hours, rounding rule, staleness and alert thresholds, minimum outcomes before auto-update, divergence threshold, tax recoverability). Each row carries `effective_from`, `effective_to`, `set_by_user_id`, `set_by_role`. Changing one lever writes a new row copying the rest; reads resolve as-of a date.

`Tenant.settings["default_labor_rate"]` — already commented as a legacy field, default `20.0`, a `float`, and read by nobody — is migrated into the first policy row as both labor rates, with `source = 'assumed'` and `as_of = tenant.created_at`. The JSON key stays readable for one release; a test asserts the engine never reads it.

**Rationale**: FR-002 and FR-003 require policy values to be versioned and never overwritten, which a JSON blob cannot express. The number of levers is bounded at roughly fifteen, so a typed temporal row is cheaper to read and safer to type than a key-value table, and it answers "what was the policy on this date" in one query — needed by FR-031d and FR-039.

**Alternatives considered**:
- *Key-value policy rows*: flexible, rejected because every read becomes a pivot and no column has a type.
- *Keeping policy in `Tenant.settings` with a history table beside it*: two sources of truth for the same value, which principle III rules out in spirit.

## D3 — What a yield figure means under each failure mode

**Decision**: the stored yield is always a **per-part success probability**. The failure mode decides how one part's failure propagates:

- `per_part`: only that part is lost. Divisor on the at-risk portion is `y`.
- `per_plate`: one failure condemns the plate. Divisor is `y^N`, where `N` is prints per plate.

Both reduce to `y` at `N = 1`, which is why the spec's edge case asserts the two modes agree on a single-part plate and SC-002b asserts per-plate is heavier when batched.

Learning differs by mode (FR-015d): under `per_part`, `y` comes from parts succeeded over parts attempted; under `per_plate`, observation yields a plate success rate, and `y` is its `N`-th root. A figure learned under one mode is not carried across a mode change.

**Rationale**: the naive reading — divide the plate's at-risk cost by a plate yield — turns out to be algebraically identical to the per-part formula, so it would have produced two modes that always agree and a spec criterion that could never pass. Deriving plate survival from part survival is what actually distinguishes them, and it matches the clarified intent that one failure condemns the bed.

**Alternatives considered**:
- *Storing a plate-level yield directly*: makes the two modes numerically identical for the same stored figure, and makes the figure meaningless when batching changes.
- *Independent yields per mode on the same record*: two fields that must not disagree, for no gain over deriving one from the other.

**Flagged for review**: the golden case places finishing labor inside the at-risk portion, which the spec then states as a requirement (FR-015, US2 scenario 3). Strictly, a part that failed was never finished. Keeping finishing at-risk is what reproduces CA$20.30, and it is defensible as modelling rework, but it is a modelling choice rather than a physical truth and is called out here so a later reader does not mistake it for an oversight.

## D4 — Catalogue-wide work runs on a Celery worker with persisted state

**Decision**: Celery with the Redis broker, plus a `scenario_runs` table holding state, inputs, the shock applied and the result. A new Kubernetes manifest adds the worker. Tier 4 only.

**Rationale**: Celery is already configured in `backend/app/config.py` but has **no task modules and no worker deployment anywhere in `infrastructure/`** — so this is wiring plus one manifest, not a new technology choice. FR-044b requires a running job to report its state, which survives a worker restart only if the state is in the database rather than the broker.

**Alternatives considered**:
- *FastAPI `BackgroundTasks`*: in-process, dies with the pod, no state — fails FR-044b outright.
- *A database job table polled in-process*: that is the same as the above with persistence, and it burns request-handler capacity on catalogue sweeps.

**Carried forward as a deployment note**: the configured broker URL is `redis://localhost:6379/1`, which must resolve to the cluster Redis service before the worker runs in production.

## D5 — Exchange rates come from one swappable adapter

**Decision**: an `fx_rates` table caching `(base, quote, rate_date, rate, source)`, filled by a single adapter behind a narrow port so the provider can be replaced without touching the pricing code. Default provider: a no-key ECB-backed endpoint, publishing once per business day — which is exactly why FR-028f reuses a rate for the day rather than requesting per order. Fallbacks per FR-028g–i: last known rate with its date, manual override, never a blocked sale, never an implied 1:1.

**Rationale**: the pricing engine must not know where a rate came from beyond its origin label, and the provider is the one dependency in this feature that can disappear without warning.

**Open at implementation time**: confirm the chosen endpoint's current availability and terms, and that it covers the CAD, GBP, USD and EUR pairs this workshop needs. The port keeps that confirmation cheap; a wrong guess costs an adapter, not a redesign.

## D6 — Temporal pricing without a new PostgreSQL extension

**Decision**: `ProductPricing` gains `valid_from` and `valid_to`. The unique constraint `uq_product_channel_pricing` is dropped and replaced by a **partial unique index** on `(product_id, sales_channel_id) WHERE valid_to IS NULL` — one current price per product and channel — with overlap prevention enforced in the service plus a test. A new `Product.current_pricing` relationship (primary-join on `valid_to IS NULL`) serves the read paths, while `Product.pricing` becomes the full history.

**Rationale**: a range exclusion constraint would be stricter but requires the `btree_gist` extension, which is an operational dependency this cluster has not declared. The partial index covers the invariant that actually matters at read time — exactly one current row — and the service guard plus test covers historical overlap.

**Alternatives considered**:
- *`btree_gist` exclusion constraint*: strictly better integrity, rejected for the undeclared extension dependency; revisit if the extension is adopted for other reasons.
- *A separate price-history table*: leaves two tables to keep consistent and duplicates every read path.

**Blast radius, measured**: dropping the unique constraint touches every read of `ProductPricing`, including the `lazy="joined"` `sales_channel` relationship and the pricing collections in `api/v1/products.py`. This is the heaviest refactor in the plan, which is why it sits in Tier 3, after costs are already correct.

## D7 — The superseded model is a profile of overrides, not a second implementation

**Decision**: FR-052's requirement that the old 66.4% stay reproducible during migration is satisfied by running the **new** engine with a legacy override profile: machine rate zero, yield 1.0, waste zero, nominal spool weight instead of usable weight, overhead by percentage of material plus labor, no shipping, no reserves, and the fee engine reduced to the two rules the Tier 2 data migration produced. The override mechanism is the one Tier 4's scenario service needs anyway.

**Rationale**: preserving the old code to reproduce the old number would create precisely the parallel implementation that Constitution III forbids and that this feature exists to remove. Expressing the old model as data makes the comparison a fixture, deletable in one line when FR-052 retires it.

**Alternatives considered**:
- *Keeping the old methods behind a feature flag*: simple, and a direct principle III violation that would have required a Complexity Tracking entry.
- *Hardcoding 66.4% as a constant for the comparison*: reproduces one number for one product and proves nothing for any other.

## D8 — Banning float where no linter can

**Decision**: three layers. First, a per-module mypy override tightening `app/services/costing.py`, `landed_cost.py`, `fee_engine.py`, `pricing_solver.py` and `channel_pnl.py` beyond the project-wide `disallow_untyped_defs`. Second, a unit test that parses those modules with `ast` and fails on a `float` annotation or a `float(...)` call. Third, `Mapped[Decimal]` annotations on every `Numeric` column touched, so the type hints stop lying.

**Rationale**: ruff has no rule for "this package may not use this builtin type", and writing a custom plugin is more machinery than the problem deserves. An AST test is ten lines, runs in the existing suite, and fails with a precise file and line.

**Alternatives considered**:
- *A custom ruff or flake8 plugin*: correct and disproportionate.
- *Relying on review*: this defect already shipped once, in `Product.calculate_make_cost`.

## D9 — Fee engine evaluation semantics

**Decision**: rules evaluate in `sort_order`, each against an amount derived from the order, never from another fee — there is no fee on fee. `order_total` means what the customer paid, item plus shipping plus any gift wrap, and never includes other fees. For each rule the amount is `rate × basis + fixed`, then clamped by `minimum` and `maximum` if present, with a flag recording that a clamp bound (FR-021c). `incidence_pct` scales a rule's amount for *planning only* and is never applied to a recorded actual (FR-029, FR-041e). All arithmetic in `Decimal`, rounded only at the end.

**Rationale**: fee-on-fee is how marketplace fee models are most often got wrong, and making the bases depend only on order amounts keeps rule order from changing any total — order then matters solely for presentation and for clamp attribution.

## D10 — The solver is a bounded iteration, not a fixed point

**Decision**: for a given margin basis, with no clamp binding, margin is linear in price and the required price has a closed form. Caps break linearity, so: solve assuming no clamp binds, check which clamps bind at that price, move each bound fee into the fixed bucket, re-solve. This terminates in at most one pass per capped rule, deterministically, and the result reports which clamps bound (FR-032a). Three closed forms are implemented, one per margin basis:

- customer total: denominator is item price plus shipping revenue
- item price alone: denominator is the item price
- net revenue after fees: denominator is the customer total less fees

Where percentage fees plus the target reach or exceed the whole denominator, no price exists and the solver reports the binding constraint rather than returning a number (FR-035).

**Rationale**: a numeric root-finder would also work and would be harder to explain to an operator asking why the price is what it is (FR-034). Closed forms with a bounded clamp loop stay explainable and exactly reproducible.

**Verification against the golden case**: basis = customer total, free shipping so shipping revenue is zero, variable rate 12.5% plus a 2.5% refund reserve, fixed CA$2.52, costs CA$29.80 — giving `P × (1 − 0.125 − 0.025 − 0.35) = 32.32`, so `P = 64.64`. This is the figure the spec asserts, and it is recomputed from the fixture rather than copied.

---

## Carried-forward risks

| Risk | Where it bites | Mitigation |
|---|---|---|
| Tier 0's delta report shows large, surprising cost moves | Operator trust, before any new feature lands | The report is a reviewed deliverable, per product, with each change attributed to the labor-rate fix |
| Tier 3's temporal pricing touches every price read path | Regressions in product and shop endpoints | Partial unique index plus `current_pricing` relationship; the shop reads only current prices |
| The rate provider disappears | Tier 3 multi-currency | Narrow port, cached table, manual override already required by FR-028h |
| The existing 1,100 lines of costing tests | Tiers 0–2, repeatedly | Rewritten against the new breakdown in the tier that changes the behaviour, never patched to the old values |
| Celery worker introduced late | Tier 4 only | Tiers 0–3 ship without any new deployment unit |
