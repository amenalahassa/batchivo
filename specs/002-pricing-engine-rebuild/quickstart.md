# Quickstart — Validating the Pricing Engine Rebuild

**Feature**: 002-pricing-engine-rebuild | **Date**: 2026-10-11

How to prove each tier works, end to end. One section per tier, each independently runnable — a tier's checks must pass before the next tier starts. Entity fields are in [data-model.md](./data-model.md), endpoints in [contracts/pricing-api.md](./contracts/pricing-api.md); neither is repeated here.

## Prerequisites

```bash
# Backend
cd backend && poetry install
poetry run alembic upgrade head          # must succeed on a fresh database

# Frontend
cd frontend && pnpm install

# Services (from repo root)
docker compose up -d postgres redis
```

Run the suite and the linters the way the Constitution requires before any commit:

```bash
cd backend && poetry run pytest && poetry run ruff check && poetry run ruff format --check
cd frontend && npm test && npm run lint
```

## The golden fixture

`backend/tests/fixtures/golden_case.py` seeds the acceptance scenario: a 142 g single-colour part, 3 g purge, a spool landed at CA$31.00 per 1000 g with 25 g unusable, 9.5 h on a printer costing CA$1,100 over 6,000 h with CA$220 of maintenance reserve and 95 W at CA$0.13/kWh, 15 min of at-risk labor and 5 min of packing at CA$25/h, CA$180/month of overhead over 600 expected machine-hours, CA$0.92 of packaging, 92% yield, one print per plate.

**The expected values are computed in the test from the fixture's own inputs, in one unrounded chain, and rounded only for the assertion.** No figure is copied from a document — the first version of the design note asserted CA$20.31, which rounding each line had produced, where the correct figure is CA$20.30.

```bash
cd backend && poetry run pytest tests/unit/pricing/test_golden_case.py -v
```

---

## Tier 0 — Live defects

**What to prove**: one cost implementation, and the operator's labor rate is the one used.

```bash
# The deleted methods are gone: no definition and no call site remains.
# Matching a bare mention would also hit the docstring in costing.py that
# records why they were deleted, and a check that cries wolf gets ignored.
cd backend && grep -rnE "def (calculate_make_cost|_calculate_model_cost)|\.(calculate_make_cost|_calculate_model_cost)\(" --include=*.py app/ && echo "FAIL: still present" || echo "OK"

# No float in the costing and pricing modules
poetry run pytest tests/unit/pricing/test_no_float_in_money_paths.py -v

# The tenant labor rate reaches every call site
poetry run pytest tests/api/test_costing_uses_tenant_rate.py -v
```

Then, by hand: set the labor rate in settings to a distinctive value, open a product's cost breakdown, and confirm the labor line reflects it. Open the same product from the product list, the product detail and the channel pricing screen — all three must show the same make-cost to the cent.

**The delta report** is a deliverable, not an afterthought:

```bash
# `--cause` is required: the script refuses to report a cost change with no
# declared cause, and refuses a declared cause it cannot verify predicts the
# change. It exits non-zero when any change is left unattributed.
cd backend && poetry run python -m scripts.cost_delta_report \
    --before-ref HEAD~1 \
    --cause labor-rate \
    --out ../specs/002-pricing-engine-rebuild/delta-tier0.md
```

Every product whose cost changed must be attributable to the labor-rate correction. An unattributed change is a defect in this tier, not an acceptable side effect.

**Done when**: the three checks pass, the delta report is reviewed and accepted, and the suite is green *without* any expected value having been restored to its defective figure. A green suite achieved by reinstating the hardcoded rate is a failed change (Constitution, Development Workflow).

---

## Tier 1 — True make-cost

```bash
cd backend
poetry run alembic upgrade head
poetry run pytest tests/unit/pricing/ -v
```

**Checks that matter**:

- The golden case reports **CA$20.30**.
- `expected_yield = 1.0` is a no-op under both failure modes.
- At one print per plate, `per_part` and `per_plate` agree exactly; at four per plate with the same yield figure, `per_plate` is higher (research D3).
- Varying print time alone moves only the machine and overhead lines.
- A plate of 20 divides per-plate preparation labor across the plate; per-item labor is unchanged.
- The failure premium touches material, machine, overhead, handling and finishing — and leaves packaging materials and packing labor alone.
- A purchase of four equal spools splits shipping evenly and lands at CA$31.00 per spool; a purchase mixing one 250 g spool with three 1 kg spools gives the small spool roughly a tenth of the shipping, not a quarter.
- A printer with no cost policy marks the item incompletely costed, and does not cost machine time at zero.

By hand: open a cost breakdown and confirm each line names its origin and date, and that the panel states the observed share.

---

## Tier 2 — Fees, shipping, tax, margin basis

```bash
cd backend && poetry run pytest tests/unit/pricing/test_fee_engine.py tests/api/test_fee_rules.py -v
```

**Checks that matter**:

- The golden case reports **35.3%** at CA$64.99 on the default basis, with the basis named beside the figure.
- Switching the margin basis changes the percentage only: the make-cost stays CA$20.30 and the profit stays CA$22.92.
- A fee on item-plus-shipping changes when shipping revenue changes, and shipping revenue is never netted before fees.
- A capped fee charges at the cap and the itemised list says the cap bound.
- A per-unit fee on three units charges three times; a per-order fee charges once.
- Two otherwise identical sales, one where the marketplace remits tax and one where the operator does, report the **same** margin.
- Tax collected appears as a liability, never as revenue or profit.
- The data migration reproduces each channel's previous fee amounts exactly — asserted per channel, not sampled.
- The legacy override profile reproduces the superseded 66.4% without any second implementation existing (research D7).

---

## Tier 3 — Snapshots, solver, temporal pricing

```bash
cd backend && poetry run pytest tests/integration/test_snapshot_immutability.py tests/unit/pricing/test_solver.py -v
```

**The one check this tier exists for**: record an order, note its margin, then change a spool price, a labor rate, an overhead setting and a fee rule. Re-read the order. **Zero settled orders may report a different margin.**

Also:

- The solver returns **CA$64.64** for a 35% target before rounding, and reports its inputs.
- A target that no price can achieve is reported as unachievable with the binding constraint named — not as a number.
- A capped fee stops scaling with price, and the solver says which clamps bound.
- An order from an earlier period reports the price effective on its date, not today's.
- Overlapping price ranges and overlapping quantity tiers are rejected at save time.
- The frozen exchange rate survives a later, better rate becoming known.

Watch the read paths this tier disturbs: the shop endpoints, `Product.pricing` collections and the `lazy="joined"` channel relationship. The migration's downgrade path collapses price history to the current row — verify that is understood before it is ever run.

---

## Tier 4 — Observed data and the feedback loop

```bash
cd backend
poetry run pytest tests/unit/pricing/test_variance.py tests/api/test_scenarios.py -v
poetry run celery -A app.tasks.celery_app worker --loglevel=info   # locally
```

**Checks that matter**:

- Enough outcomes with a value close to the estimate: the estimate updates on its own and its origin becomes observed, dated, with the outcomes it came from.
- A value diverging beyond the threshold — a doubled weight — is held as a proposal; pricing keeps using the current estimate and the figure is flagged as having a pending revision.
- A rejected proposal is not re-raised from the same outcomes; a later proposal from new outcomes still is.
- A scenario request is acknowledged immediately and reports its state until done.
- A finished scenario writes no cost, price or provenance figure.
- At least 70% of the golden item's make-cost lines carry an observed origin, while fee lines remain labelled as entered.

In production this tier adds one Kubernetes manifest for the worker. It reaches the cluster the only way changes do: commit to `main`, Woodpecker builds, ArgoCD syncs (Constitution VII).

---

## Cross-tier regression suite

Run at every tier, not only at the end:

| Check | Why |
|---|---|
| Golden case asserted to the cent | Catches any drift in the chain |
| Margin monotonic in price; cost monotonic in weight and hours | Property tests that catch sign and algebra errors |
| Yield of 1.0 is a no-op; bundle cost equals the sum of its children | Boundary identities |
| A randomised bill-of-materials graph, leaf spool price mutated | Nothing stale is served (Constitution V) |
| Settled-order margins unchanged after any policy change | Constitution VI |
| `alembic upgrade head` on an empty database | Constitution, Additional Constraints |
| RLS: a second tenant's data is invisible through every new endpoint | Constitution I |
