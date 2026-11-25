# Bug Fix: Packaging (Consumables) menu never appears

- **Slug**: consumables-module-never-enabled
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Added `consumables` and `designers` to `ALL_MODULES` and to the 3D-print default modules, so `GET /api/v1/modules` returns `/consumables` and `/designers`: they appear in the nav, `ModuleGuard` admits them, and they can be toggled in the module settings. Existing tenants pick them up through the existing per-module default fallback; no data migration.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/app/services/tenant_module_service.py` | modified | `consumables`, `designers` added to `ALL_MODULES` and `DEFAULT_MODULES_BY_TYPE["three_d_print"]` |
| `backend/tests/api/test_modules_consumables_route.py` | added test | nav reachability + consistency check |

## Tests Added or Updated

- `test_modules_consumables_route.py::TestConsumablesAndDesignersAreReachable::test_consumables_is_in_the_nav_of_a_3d_print_tenant`
- `...::test_designers_is_in_the_nav_of_a_3d_print_tenant`
- `...::test_consumables_carries_a_label_and_icon`
- `...::test_every_module_with_navigation_can_be_enabled` — every `MODULE_NAVIGATION` key is in `ALL_MODULES`, so a new module cannot be forgotten again.

## Local Verification

- `poetry run pytest tests/api/test_modules_consumables_route.py` → 4 passed; with the service change stashed → 4 failed (regression proven).
- `poetry run pytest tests/unit/test_tenant_module_service.py tests/api/test_modules_scenarios_route.py` → passed.

## Deviations from Assessment

- Knitting/generic tenants were not given `consumables` by default (open question in the assessment); they can enable it in module settings now that it is in `ALL_MODULES`.
- The nav label was kept as "Consumables" (no relabel, no link from the packaging card): optional items, left as follow-ups.

## Follow-ups

- Decide whether packaging deserves its own nav entry, separate from printer consumables.
- Optionally link from `ProductPackagingCard` / the packaging advisor to `/consumables` when no packaging exists.
