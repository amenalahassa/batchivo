# Bug Assessment: Loading one product's cost tree costs about a second of CPU

- **Slug**: cost-load-options-depth-slow
- **Created**: 2026-11-24
- **Source**: pasted text (orchestrator: `scenario.spec.ts` fails on clean main 31d7463; cost-and-margin, history and price-finder fail intermittently)
- **Verdict**: valid (app defect, performance)
- **Severity**: high (every product read and every scenario run pays it, and it grows with the catalogue; e2e gate red)

## Report (verbatim or summarized)

```
3) scenario.spec.ts › a material shock runs to a result and leaves every price as it was
   Error: locator.click: Test timeout of 30000ms exceeded.
   (in openProduct, after the scenario reached `succeeded`)
```

Worker log on the isolated stack:

```
Task scenario.run[9bd5cdcb-...] succeeded in 18.14s: 'succeeded'
```

The seeded tenant has **one** product. The flaky journeys all open the product page and
take 9-15 s each against a 30 s test timeout.

## Symptom

A scenario over a one-product catalogue takes ~18 s; the journey's 30 s budget runs out on the
next step. Product reads (`/products/{id}` and the list) take ~1 s of CPU each on a flat product.
Expected: well under a second for both.

## Reproduction

1. Seed the e2e tenant; start the backend, a Redis and a Celery worker.
2. Run `scenario.spec.ts`, or profile `execute_run` directly (cProfile, scratch script).
3. Profile: 19.6 s in `_priced_products`, of which ~12 s in SQLAlchemy `_generate_cache_key`
   (848k `_gen_cache_key` calls) and ~5.6 s compiling. Timing `select(Product).options(*cost_load_options())`
   on one flat product by `BUNDLE_LOAD_DEPTH`: 0 → 0.11 s, 2 → 0.15 s, 5 → 0.17 s, 10 → 0.44 s, 20 → 1.0 s.

## Suspected Code Paths

- `backend/app/services/cost_resolution.py:cost_load_options()` generates the bundle chain to
  `BUNDLE_LOAD_DEPTH + 1 = 21` levels (= `MAX_RECURSION_DEPTH` 20), i.e. 105 selectinload
  options with prefixes up to ~45 relationships long. Since 50a927a (T254-T258).
- Callers: `backend/app/api/v1/products.py:132`, `backend/app/services/scenario_service.py:_priced_products`,
  `backend/app/services/print_queue_service.py:316`.

## Root Cause Hypothesis

The comment says a `selectin` level costs nothing when the level above returned no rows. That is
true of SQL, but not of SQLAlchemy: every sub-load still walks, keys and compiles the whole option
tree, and the tree grows quadratically with depth. Declaring the full engine depth statically turns
one product read into ~1 s of CPU. The scenario path is worse because the tree hangs below
`ProductPricing.product`. Confidence: high (profile and depth sweep).

## Proposed Remediation

**Preferred** (needs the orchestrator's approval: pricing-engine zone): load bundle levels on
demand. `cost_load_options()` declares one level: the cost inputs, plus the component rows and
their `child_product`. A new `async load_bundle_levels(db, products)` then walks down: it collects
the child products reached at the current level, and while there are any and the depth is within
`BUNDLE_LOAD_DEPTH`, it issues one query for those children with the same one-level options.
`populate_existing` fills their collections. The engine and its single limit are unchanged;
a flat catalogue pays one level.

**Alternatives**:
- Lower `BUNDLE_LOAD_DEPTH` to 3: brings back two limits that drift. Rejected.
- Raise the scenario journey's timeout only: hides the defect; the flaky journeys stay flaky.

**Files likely to change**:
- `backend/app/services/cost_resolution.py`
- `backend/app/api/v1/products.py`, `backend/app/services/scenario_service.py`, `backend/app/services/print_queue_service.py` (call the walker after the base query)
- `backend/tests/...` regression tests

**Tests to add or update**:
- A three-level bundle is costed identically after the change (no `MissingGreenlet`).
- A bundle deeper than `MAX_RECURSION_DEPTH` still raises the engine's `MaxDepthExceededError`.
- A budget test: the option list for one level stays small (not depth-dependent).

## Risks & Considerations

- Every cost read goes through this; any relationship the walker forgets surfaces as
  `MissingGreenlet`. Existing bundle and costing tests cover that.
- No figure changes: loading only, the engine is untouched.

## Open Questions

- Question B to the orchestrator: approval to change `cost_resolution.py` and its callers.
