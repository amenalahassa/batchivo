# Bug Assessment: Packaging (Consumables) menu never appears — module is never enabled

- **Slug**: consumables-module-never-enabled
- **Created**: 2026-11-03
- **Source**: pasted text (local bugcap #59; user report bugcap #44 + screenshot of the nav, 2026-11-03)
- **Verdict**: valid
- **Severity**: high

## Report (verbatim or summarized)

bugcap #44 "Packaging Consumable" (user): "Pas possible d'ajouter un packaging sur le modele mais je n'ai pas acces a l'interface de configuration des packages. Fix: corriger pour rendre cela accessible."

User, 2026-11-03: the menu has no entry to manage packages. The nav visible in the screenshot: Products, Scenarios, Models, Categories, Runs, Filaments, Printers, Channels, Orders, Settings, Help.

## Symptom

There is no menu entry to create or edit packaging, so an operator cannot set up the packages a model or product should ship in, and the packaging advisor has nothing to suggest. Expected: a "Consumables" (packaging) entry in the nav, reachable for a 3D-print tenant. Typing `/consumables` directly is also refused by the module guard.

## Reproduction

1. Log in as a 3D-print tenant (default modules).
2. The top nav has no "Consumables"/packaging entry (nor "Designers").
3. Navigate to `/consumables` by URL → `ModuleGuard` refuses it (path not in any active module's routes).
4. Settings → modules: "consumables" cannot be switched on (not in the toggle list; `set` raises `Unknown module`).

## Suspected Code Paths

- `backend/app/services/tenant_module_service.py:18-59` — `DEFAULT_MODULES_BY_TYPE["three_d_print"]` and `ALL_MODULES` list `spools, models, printers, production, products, orders, categories, sales_channels` — no `consumables`, no `designers`.
- `backend/app/services/tenant_module_service.py:105-142` — `get_enabled_modules` only returns names from the defaults or `ALL_MODULES`, so `consumables` is never enabled; `:178-179` rejects enabling it (`Unknown module`).
- `backend/app/api/v1/modules.py:89-91,103-114,145-175` — `MODULE_NAVIGATION["consumables"]` maps to `/consumables` and the registry has a `consumables` module (`app/modules/threed_print/consumables.py:19`), but disabled modules are skipped, so the route never reaches the frontend.
- `frontend/src/components/layout/AppLayout.tsx:115-145` — uses the server's nav when it is non-empty; the static fallback (which does list Consumables) only applies while loading/on error.
- `frontend/src/App.tsx:292-302` + `frontend/src/hooks/useModules.ts:106-141` — `/consumables` is wrapped in `ModuleGuard`; `/consumables` is not in `commonPaths`, so direct access is blocked too.
- The packaging screens themselves exist and work behind that route: `components/inventory/ConsumableList.tsx`, `PackagingFieldsSection.tsx`, `AddConsumableDialog.tsx`.

## Root Cause Hypothesis

`consumables` and `designers` were added to the module registry and to `MODULE_NAVIGATION`, but not to `ALL_MODULES` / `DEFAULT_MODULES_BY_TYPE` in `TenantModuleService`, which is the single source the enabled-module list is built from. They are therefore always treated as disabled: hidden from the nav, refused by `ModuleGuard`, and not toggleable. Confidence: **high**.

## Proposed Remediation

**Preferred**: add `"consumables"` and `"designers"` to `ALL_MODULES` and to `DEFAULT_MODULES_BY_TYPE["three_d_print"]`. `get_enabled_modules` already falls back per module to the type default for modules with no `tenant_modules` row (`:133-142`), so existing tenants get them without a data migration. Optionally relabel the nav entry "Consumables & Packaging" so the packaging set-up is discoverable, and add a link from the product packaging card / packaging advisor to `/consumables` when no packaging exists.

**Alternatives**:
- Derive `ALL_MODULES` from the module registry (`get_module_registry().get_all_modules()`) instead of a hand-kept list, so a new module cannot be forgotten again. Better long-term; touches the service's import graph (watch for circular imports, cf. `modules/base.py:54`).

**Files likely to change**:
- `backend/app/services/tenant_module_service.py`
- `backend/tests/unit/test_tenant_module_service.py`, `backend/tests/integration/test_tenant_modules_api.py`
- Optionally `backend/app/api/v1/modules.py` (label), `frontend/src/components/products/ProductPackagingCard.tsx` (link)

**Tests to add or update**:
- `GET /api/v1/modules` for a 3D-print tenant with no `tenant_modules` rows includes `/consumables` and `/designers`.
- Same for a tenant that has rows for the older modules only (per-module fallback).
- Enabling/disabling `consumables` through the module settings endpoint works (no `Unknown module`).
- A consistency test: every key of `MODULE_NAVIGATION` and every registry module is in `ALL_MODULES`.

## Risks & Considerations

- Knitting/generic tenants: decide whether `consumables` belongs in their defaults (packaging applies to any seller) — likely yes for packaging, no for printer maintenance items.
- Backend consumables endpoints are not gated by module, so no data is exposed by enabling it; the change is nav/guard only.
- Note the naming mismatch `spools` (nav/defaults) vs `filament_types` (registry): it works today only because `spools` is also a registry module; the consistency test above will surface it.

## Open Questions

- [NEEDS CLARIFICATION: should packaging get its own nav entry ("Packaging") separate from printer consumables, or stay inside Consumables?]
