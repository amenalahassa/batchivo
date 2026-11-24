# Bug Fix: Loading one product's cost tree costs about a second of CPU

- **Slug**: cost-load-options-depth-slow
- **Fixed**: 2026-11-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

`cost_load_options()` declares one level (5 options instead of 105). A new
`load_bundle_levels(db, products)` walks the bundle levels below, one query per level that has
children, down to `BUNDLE_LOAD_DEPTH` (= `MAX_RECURSION_DEPTH`, still the one limit). The
engine is untouched and no figure changes. Approved by the user through the orchestrator
(question B, option a).

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/app/services/cost_resolution.py` | modified | one-level options; `load_bundle_levels`; `product_cost_breakdown` walks before costing |
| `backend/app/api/v1/products.py` | modified | walker after the cost loads: `product_with_cost`, list (search and plain), component add/update. Create route untouched (007 is moving it); covered through `product_with_cost` |
| `backend/tests/integration/test_cost_load_levels.py` | added test | figures, depth limit, speed |
| `backend/tests/integration/test_cost_graph_coherence.py`, `test_product_graph_load_strategy.py` | modified | their loaders call the walker, as every caller now does |

Scenario sweep, queue profitability and sale snapshot go through `product_cost_breakdown`,
which walks itself.

## Tests Added or Updated

- `test_cost_load_levels.py::TestNoFigureChanges::test_a_three_level_bundle_costs_as_the_full_eager_load_did`:
  the whole breakdown (`model_dump`) equals what the old full eager tree gives; total 21.00.
- `...::test_the_itemised_breakdown_walks_the_levels_itself`: `product_cost_breakdown` alone, 21.00.
- `TestOneDepthLimit::test_a_chain_deeper_than_the_engine_allows_raises_its_error`: a chain of
  `MAX_RECURSION_DEPTH + 3` raises `MaxDepthExceededError`, not `MissingGreenlet`.
- `TestItCostsWhatTheCatalogueHas`: 5 options; a flat product walks with 0 queries.

## Local Verification

Load + cost, median of 5, same data, same figures:

| Case | Before | After |
|------|--------|-------|
| Flat product | 0.590 s | 0.084 s |
| Three-level bundle | 1.006 s | 0.248 s |
| Scenario task, 1-product catalogue | 18.1 s | 0.4-2.7 s |

- `pytest tests/unit` → 4768 passed; `pytest tests --ignore=tests/unit` → 2998 passed, 67 skipped.
- `ruff check`, `ruff format --check` clean.

## Deviations from Assessment

- No `populate_existing` in the walker: it refreshes through `Product.parent_products`
  (selectin by default) and reset the level above's `child_product` link (`MissingGreenlet`,
  caught by the new test). Without it SQLAlchemy still descends into the already-loaded
  collections and fills what is missing.

## Follow-ups

- A new cost read must call `load_bundle_levels` (or go through `product_cost_breakdown`);
  the docstring says so.
