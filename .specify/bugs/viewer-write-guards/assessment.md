# Bug Assessment: A viewer can write on routers outside pricing

- **Slug**: viewer-write-guards
- **Created**: 2026-10-24
- **Source**: pasted text (side finding S3 from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 21 round)
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

> FR-007c makes the viewer a reader, yet a walk of every v1 router finds write routes with no role
> guard: print_queue (8), products images (6), model_files (6), filament_types (5), categories
> (5), designers (3), reviews (4), webhooks (6), printer_bambu (8). The pricing write routes are
> handled in the feature (Phase 21, T250); these are the rest.

## Symptom

A user with the `viewer` role can create, edit, cancel or delete records on these routers
because the handlers depend only on `get_current_user` / `get_current_tenant`, not on
`require_member` or `require_admin`. Expected: a viewer gets 403 on every non-GET route.

## Reproduction

1. Log in as a viewer of a tenant (fixture: `test_user` with role `viewer`).
2. `POST /api/v1/categories` with a valid body.
3. Observe 201 instead of 403. The same holds for the routes listed below.

## Suspected Code Paths

Unguarded write handlers confirmed by reading the signatures (no `require_*` dependency):

- `app/api/v1/print_queue.py` — `create_print_job`, `update_print_job`, `assign_job_to_printer`, `auto_assign_jobs`, `cancel_print_job`, `start_print_job`, `complete_print_job`, `fail_print_job`
- `app/api/v1/products.py` — `update_product_image`, `set_primary_image`, `delete_product_image`, `rotate_product_image` (plus the image upload routes)
- `app/api/v1/filament_types.py` — `create_filament_type`, `bulk_create`, `update_filament_type`, `delete_filament_type`
- `app/api/v1/categories.py` — `create_category`, `update_category`, `delete_category`, `add_product_to_category`, `remove_product_from_category`
- `app/api/v1/designers.py` — `create_designer`, `update_designer`, `delete_designer`
- `app/api/v1/reviews.py` — `update_review`, `approve_review`, `reject_review`, `delete_review`
- `app/api/v1/model_files.py` (6), `app/api/v1/webhooks.py` (6), `app/api/v1/printer_bambu.py` (8) — counted in the converge walk; their decorators use a different layout, so list them exactly during the fix.
- `backend/app/auth/dependencies.py` — `require_member`, `require_admin`.

## Root Cause Hypothesis

These routers were written before the role hierarchy existed or copied from a neighbour without
a guard; nothing tests role outcomes outside the pricing write list. Confidence: high.

## Proposed Remediation

**Preferred**: Add `Depends(require_member)` to every non-GET route on these routers;
`require_admin` for destructive or configuration routes (webhook endpoints, review moderation,
Bambu printer credentials, deletes). Then add one test that walks `app.routes`, and for every
non-GET route under `/api/v1` (tenant-scoped, not shop or auth) asserts a role dependency or a
named exception with a reason. That test supersedes the pricing-only one from T250, so coordinate:
land T250 first, then widen its population here.

**Alternatives**:
- A router-level `dependencies=[Depends(require_member)]` on each write-only router — less
  repetition, but GET routes on the same router would need splitting out.

**Files likely to change**:
- the nine routers above
- `backend/tests/api/test_write_route_role_guards.py` (new, or the T250 test widened)

**Tests to add or update**:
- Derived walk: every non-GET tenant route has a role guard or a named exception.
- Per router, one viewer-403 and one member-success test.

## Risks & Considerations

- The frontend may let viewers reach these actions; hide or disable them by role so viewers see no buttons that now 403.
- Printer agents or webhooks that call write routes with a service token need a role or an explicit exception.

## Open Questions

- None. Checked: `app/models/filament_type.py` holds no cost or price field and neither `costing.py` nor `cost_resolution.py` reads `FilamentType`, so `filament_types` writes are outside the pricing feature.
