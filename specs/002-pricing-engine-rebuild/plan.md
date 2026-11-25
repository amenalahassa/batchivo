# Implementation Plan: Pricing Engine Rebuild — Margins That Match Reality

**Branch**: `002-pricing-engine-rebuild` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-pricing-engine-rebuild/spec.md`

## Summary

Reported margins overstate reality by roughly 31 points on a representative marketplace order, because the engine costs no machine time, no shipping, and collapses a stack of six or more marketplace fees into one percentage plus a fixed amount. Two live defects compound it: a second, float-based cost implementation on the model layer, and a tenant labor rate that no caller passes.

The approach is additive, not a rewrite. The existing recursive bill of materials with cycle detection, the per-channel price rows, the packaging path, the per-printer item configuration, the production-run actuals and the printer telemetry adapters are all reused. Work lands in five tiers, each shipping a more correct system than the one before and none depending on a later one: live defects first, then true make-cost, then real net revenue, then immutable history and the price solver, then observed data and the feedback loop.

Three design decisions carry the plan: provenance lives in one side table keyed by entity and field rather than column triples; operator policy moves out of the `Tenant.settings` JSON blob into a typed temporal table; and the superseded model required by FR-052 is reproduced as a *profile of overrides on the new engine*, not as a second implementation — which is what keeps the plan inside Constitution principle III. Full reasoning in [research.md](./research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend, `requires-python = ">=3.12,<4.0"`), TypeScript 5.9 (frontend)

**Primary Dependencies**: FastAPI ≥0.124, SQLAlchemy 2.0 async, Alembic ≥1.13, Pydantic v2, psycopg 3 / asyncpg, Celery ≥5.3 with Redis (configured, not yet used), React 19.2, TanStack Query 5.90, TanStack Router, shadcn/ui, Zod 4

**Storage**: PostgreSQL 16 with row-level security; Redis 7 for the Celery broker (Tier 4 only)

**Testing**: pytest ≥9 with pytest-asyncio and pytest-xdist, respx for HTTP mocking, fakeredis; Vitest 4 and Playwright 1.59 on the frontend

**Target Platform**: k3s cluster behind a Cloudflare Tunnel; Python 3.12-Alpine and Node-Alpine images

**Project Type**: Multi-tenant web service (FastAPI backend plus React SPA), with a public storefront on separate routes

**Performance Goals**: Per-product cost and margin remain an interactive read, recomputed on demand with no stored derived figure (Constitution V). Catalogue-wide calculations are background jobs that acknowledge immediately and report state (FR-044a–e); catalogue size changes duration, never success.

**Constraints**: 94 Alembic revisions in place on a single head (`commerce_handover_v1`); a fresh database must still reach head. Existing production routes and API endpoints stay functional throughout. Every new table carries `tenant_id` under RLS. Exact decimal arithmetic end to end; no `float` in costing or pricing code.

**Scale/Scope**: Single-workshop tenants — hundreds of products, tens of printers, thousands of orders per year. 103 functional requirements across 7 user stories; 9 new tables, 7 extended tables, one table trimmed; 9 new backend service modules and 12 new frontend components.

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.0.0. Re-checked after Phase 1 design — result unchanged.*

| Principle | Gate | Status |
|---|---|---|
| I. Multi-Tenant Isolation | Every new table carries `tenant_id` with an RLS policy; every new endpoint takes `get_current_tenant` and uses `get_tenant_db`. The 13 new tables are listed with their policies in [data-model.md](./data-model.md). | **PASS** |
| II. Tests Are Part of the Change | Each tier ships its tests in the same change. The golden case is a fixture asserted to the cent, computed from the fixture's own inputs. The ~1,100 lines of existing costing tests are rewritten against the new breakdown in Tier 0 and Tier 1, never patched to restore old values. | **PASS** |
| III. One Authoritative Implementation | Tier 0 deletes `Product.calculate_make_cost` and `Product._calculate_model_cost`; `CostingService` becomes the single entry point. FR-052's legacy comparison is a profile of overrides on the new engine, not a preserved copy — see [research.md](./research.md) D7. | **PASS** |
| IV. Money Is Exact, Settings Honoured | No money-column migration is needed: every monetary column is already `Numeric`. Tier 0 corrects the `Mapped[float]` annotations, wires the tenant labor rate through all 14 call sites, and adds the enforcement described in D8. | **PASS** |
| V. Derived Figures Expire With Inputs | No stored derived cost is introduced in any tier. The unused cost-cache helpers in `cache_service.py` stay unused. Tier 4's scenario runs store a *scenario result* labelled with the inputs it used, which is not an authoritative figure (FR-044c–d). | **PASS** |
| VI. History Immutable, Provenance Visible | Tier 3 writes order-line snapshots once. Tier 1 introduces the provenance side table. Tier 2's channel changes and Tier 3's temporal pricing both leave settled orders untouched, asserted by a dedicated test. | **PASS** |
| VII. Deployment Through The Pipeline | Tier 4 adds one Kubernetes manifest for a Celery worker, delivered by commit to `main` and synced by ArgoCD like any other change. No manual image build, no direct `kubectl apply`. | **PASS** |

Two items were examined and found **not** to be violations:

- **The legacy comparison mode (FR-052)** looked like a second implementation. It is expressed as an override profile fed to the one engine, so no parallel calculation exists. Had it been a preserved copy of the old code, it would have required an entry in Complexity Tracking.
- **The Celery worker (Tier 4)** adds a deployment unit, not an architectural layer. Celery is already configured in `backend/app/config.py`; only the worker, the task modules and the manifest are missing.

One constraint the Constitution imposes that the plan must carry explicitly: fixing the labor rate (Tier 0) **changes reported costs by design**, so "existing numbers unchanged" cannot be an exit criterion. The per-product delta report is a deliverable, not a side effect.

## Project Structure

### Documentation (this feature)

```text
specs/002-pricing-engine-rebuild/
├── plan.md              # This file
├── research.md          # Phase 0: the ten design decisions, with rationale
├── data-model.md        # Phase 1: entities, constraints, migration sequence
├── contracts/
│   ├── pricing-api.md   # Phase 1: REST contracts for costing, fees, policy, reconciliation
│   └── jobs.md          # Phase 1: background job and telemetry ingestion contracts
├── quickstart.md        # Phase 1: how to validate each tier end to end
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /speckit-specify)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
backend/app/
├── models/
│   ├── printer.py                  # EXTEND: machine cost policy fields
│   ├── model.py                    # EXTEND: waste, yield, failure mode, labor split
│   ├── product.py                  # TRIM: delete calculate_make_cost/_calculate_model_cost
│   ├── spool.py                    # EXTEND: link to filament purchase, usable weight
│   ├── sales_channel.py            # EXTEND: tax remitter, reserves, rounding; deprecate fee_*
│   ├── product_pricing.py          # EXTEND (Tier 3): valid_from/valid_to, quantity tiers
│   ├── order.py                    # EXTEND (Tier 3): OrderItem snapshot columns, postage paid
│   ├── tenant_pricing_policy.py    # NEW: typed temporal operator policy
│   ├── pricing_input_provenance.py # NEW: provenance side table
│   ├── filament_purchase.py        # NEW: purchase with allocated inbound shipping
│   ├── fee_rule.py                 # NEW: ordered, dated fee rules with caps and floors
│   ├── fee_actual.py               # NEW: reconciled fees, period or order scoped
│   ├── shipping_profile.py         # NEW: postage by zone and weight bracket
│   ├── fx_rate.py                  # NEW: fetched and manual exchange rates
│   ├── estimate_revision.py        # NEW (Tier 4): held proposals
│   └── scenario_run.py             # NEW (Tier 4): background scenario state and result
├── services/
│   ├── costing.py                  # REWRITE: structured breakdown, at-risk split, yield
│   ├── landed_cost.py              # NEW: per-gram spool cost from purchase allocation
│   ├── fee_engine.py               # NEW: ordered rule evaluation with caps and incidence
│   ├── pricing_solver.py           # NEW: target-margin solve, cap-aware, three bases
│   ├── provenance.py               # NEW: registry, read/write, observed-share computation
│   ├── pricing_policy.py           # NEW: as-of policy resolution
│   ├── channel_pnl.py              # NEW: periodic cost absorption, fee reconciliation
│   ├── variance_service.py         # NEW (Tier 4): rolling update, threshold, proposals
│   └── scenario_service.py         # NEW (Tier 4): override-driven catalogue runs
├── api/v1/
│   ├── products.py                 # UPDATE: 14 CostingService call sites, breakdown shape
│   ├── models.py                   # UPDATE: same
│   ├── printers.py                 # UPDATE: machine cost policy endpoints
│   ├── fee_rules.py                # NEW
│   ├── pricing_policy.py           # NEW
│   ├── reconciliation.py           # NEW: fee actuals, channel P&L
│   └── scenarios.py                # NEW (Tier 4)
├── schemas/                        # Pydantic Base/Create/Update/Response per new resource
└── tasks/                          # NEW (Tier 4): celery_app.py, scenario, telemetry, variance

backend/alembic/versions/           # One migration per tier, chained onto commerce_handover_v1
backend/tests/
├── unit/pricing/                   # Cost engine, fee engine, solver, landed cost, provenance
├── api/                            # Endpoint contracts per new router
├── integration/                    # Snapshot immutability, migration deltas, RLS
└── fixtures/golden_case.py         # The acceptance scenario as seeded data

frontend/src/
├── components/pricing/             # NEW: CostBreakdownPanel, ProvenanceBadge,
│                                   #      MarginBasisLabel, FeeBreakdownTable,
│                                   #      EstimateProposalList, ScenarioRunPanel
├── components/products/            # UPDATE: ProductPricingEditor, ProductDetail
├── components/models/              # UPDATE: ModelDetail cost breakdown
├── components/printers/            # UPDATE: machine cost policy form
├── components/sales-channels/      # UPDATE: SalesChannelForm + FeeRuleEditor
├── components/settings/            # UPDATE: pricing policy screen
├── lib/api/                        # NEW: feeRules.ts, pricing.ts, scenarios.ts
├── hooks/                          # NEW: useFeeRules, usePricing, useScenarios
└── types/pricing.ts                # NEW: mirrors the backend breakdown schemas

infrastructure/k8s/                 # Tier 4: celery-worker deployment manifest
```

**Structure Decision**: the existing web-application split is kept — `backend/` (FastAPI) and `frontend/` (React SPA) — and the backend's flat `services/` convention is followed rather than introducing a `pricing/` package, so the new modules sit beside `costing.py` the way `production_run.py` and `print_queue_service.py` already do. New API routers follow the one-file-per-resource pattern in `api/v1/`. No new top-level project is created.

## Tier Sequencing

Each tier is independently shippable and leaves the system more correct than before. Exit criteria are the gates for moving on.

### Tier 0 — Live defects and blocking debt

Delete `Product.calculate_make_cost` and `Product._calculate_model_cost` (`backend/app/models/product.py:461-546` — float arithmetic, labor rate hardcoded to `10.0`). Convert `SalesChannel.calculate_platform_fee(float)` to decimal, to be superseded by the fee engine in Tier 2. Wire the tenant labor rate through all 14 `CostingService` call sites in `api/v1/products.py` and `api/v1/models.py`. Correct the `Mapped[float]` annotations on `Numeric` columns. Add the float-ban enforcement (research.md D8). Rewrite the existing costing tests against the single implementation. Produce the per-product before/after delta report.

No migration. No money-column changes — every monetary column is already `Numeric`.

**Exit**: one cost implementation; the configured labor rate is the one used; the delta report reviewed and accepted; suite green without any expected value restored to its defective figure.

### Tier 1 — True make-cost

Machine cost policy on the existing `Printer`; `Model` gains waste, yield, failure mode and the plate/item and handling/finishing labor split; overhead absorbed per machine-hour with the percentage method retained as an option; the at-risk versus not-at-risk split with yield applied only to the at-risk portion; landed spool cost derived from a new `FilamentPurchase` with inbound shipping allocated by weight; the provenance side table and the typed temporal policy table, with policy values migrated out of `Tenant.settings`.

**Exit**: the golden case reports a make-cost of CA$20.30, computed from the fixture's inputs in one unrounded chain; per-part and per-plate modes agree at one print per plate and diverge above it.

### Tier 2 — Fee rules engine and real net revenue

`FeeRule` with seven bases, caps, floors, incidence and effective dates, replacing `SalesChannel.fee_percentage`/`fee_fixed` through a data migration that reproduces current fee amounts exactly. `ShippingProfile` with postage paid kept distinct from shipping revenue collected. Refund and discount reserves at channel level. Tax-exclusive margin with the per-channel tax-remitter indicator. The three margin bases as an operator setting, named beside every percentage. Fee actuals recorded per period with optional per-order overrides.

**Exit**: the golden case reports 35.3% at CA$64.99 on the default basis; switching basis changes only the percentage; the superseded model's 66.4% is reproducible through the legacy override profile.

### Tier 3 — Snapshots, solver, temporal pricing

Order-line snapshots written once at sale. The algebraic target-margin solver, cap-aware and basis-aware. `ProductPricing` becomes temporal with quantity tiers. Channel P&L absorbing periodic and per-listing costs over actual volume. Multi-currency with the exchange-rate service, its day reuse, its stale fallback and manual override.

**Exit**: changing a spool price, a labor rate, an overhead setting and a fee rule alters zero settled orders' reported margins; the solver returns CA$64.64 for a 35% target.

### Tier 4 — Observed data and the feedback loop

Printer telemetry and smart-plug ingestion writing actuals. The variance engine: automatic rolling update within threshold, held proposal beyond it. Catalogue-wide scenario runs as Celery jobs with persisted state. One new Kubernetes manifest for the worker.

**Exit**: at least 70% of the golden item's make-cost lines carry an observed origin, and the interface shows that share while labelling fee lines as entered.

## Complexity Tracking

> No Constitution violations require justification. The two candidates examined — the legacy comparison mode and the new Celery worker — were resolved within the principles, as recorded in the Constitution Check above.
