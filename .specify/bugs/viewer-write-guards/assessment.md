# Bug Assessment: A viewer can write on routers outside pricing

- **Slug**: viewer-write-guards
- **Created**: 2026-10-24
- **Re-assessed**: 2026-10-25 (against `7a2776e`)
- **Source**: pasted text (side finding S3 from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 21 round)
- **Verdict**: valid (still open; scope widened by 3 routers)
- **Severity**: medium

## Report (verbatim or summarized)

> FR-007c makes the viewer a reader, yet a walk of every v1 router finds write routes with no role
> guard: print_queue (8), products images (6), model_files (6), filament_types (5), categories
> (5), designers (3), reviews (4), webhooks (6), printer_bambu (8). The pricing write routes are
> handled in the feature (Phase 21, T250); these are the rest.

## Re-assessment changes

- **All nine original routers are still unguarded.** The exact handlers are now listed below,
  including `model_files`, `webhooks` and `printer_bambu`.
- **Three more routers found** by sweeping every `app/api/v1/*.py` write route for a role
  dependency:
  - `pages.py`: `create_page`, `update_page`, `delete_page` (storefront CMS content).
  - `spoolmandb.py`: `sync_database` (triggers a sync of the shared SpoolmanDB reference data).
  - `test.py`: `send_test_email` (sends real mail through Resend).
- **Correction to the remediation.** `require_member` and `require_admin` are factories
  (`dependencies.py:231,250`). `Depends(require_member)` would resolve to the inner function and
  check nothing. Use the `RequireMember` / `RequireAdmin` aliases (`dependencies.py:266-267`) or
  `Depends(require_member())`.
- **Excluded by design**, all checked: `auth`, `customer_auth`, `customer_account`, `shop`,
  `newsletter`, `onboarding` (register/verify), `shopify_webhooks`, `payments` (public
  checkout), `discounts.get_discount_code_by_code` and `shipping.get_shipping_rates` (public
  reads over POST). Also `products.solve_product_price`, a scenario that writes nothing, and
  `provenance.put_provenance`, which checks the role in its body through `_require_write_role`.

## Symptom

A user with the `viewer` role can create, edit, cancel or delete records on these routers. The
handlers depend only on `CurrentUser` / `CurrentTenant`, never on a role guard. Expected: a viewer
gets 403 on every tenant write route.

## Reproduction

1. Log in as a viewer of a tenant (the `test_user` fixture with role `viewer`).
2. `POST /api/v1/categories` with a valid body.
3. Observe 201 instead of 403. The same holds for every handler listed below.

## Suspected Code Paths

Unguarded write handlers (no `RequireMember`/`RequireAdmin`/`require_*` in the signature):

- `app/api/v1/print_queue.py` (8): `create_print_job`, `update_print_job`,
  `assign_job_to_printer`, `auto_assign_jobs`, `cancel_print_job`, `start_print_job`,
  `complete_print_job`, `fail_print_job`. Only `delete_print_job` is guarded (`RequireAdmin`).
- `app/api/v1/products.py` (6): `upload_product_image`, `import_product_image_from_url`,
  `update_product_image`, `set_primary_image`, `delete_product_image`, `rotate_product_image`.
  Every other product write is guarded.
- `app/api/v1/filament_types.py` (5): `create_filament_type`, `bulk_create`, `batch_create`,
  `update_filament_type`, `delete_filament_type`
- `app/api/v1/categories.py` (5): `create_category`, `update_category`, `delete_category`,
  `add_product_to_category`, `remove_product_from_category`
- `app/api/v1/designers.py` (3): `create_designer`, `update_designer`, `delete_designer`
- `app/api/v1/reviews.py` (4): `update_review`, `approve_review`, `reject_review`, `delete_review`
- `app/api/v1/model_files.py` (6): `upload_file`, `link_local_file`, `validate_local_path`,
  `parse_3mf_file`, `update_file`, `delete_file`
- `app/api/v1/webhooks.py` (6): `create_subscription`, `update_subscription`,
  `delete_subscription`, `regenerate_secret`, `test_subscription`, `retry_delivery`
- `app/api/v1/printer_bambu.py` (8): `create_printer_connection`, `update_printer_connection`,
  `delete_printer_connection`, `connect_to_printer`, `disconnect_from_printer`, `map_ams_slot`,
  `unmap_ams_slot`, `sync_ams_to_inventory`
- `app/api/v1/pages.py` (3): `create_page`, `update_page`, `delete_page`
- `app/api/v1/spoolmandb.py` (1): `sync_database`
- `app/api/v1/test.py` (1): `send_test_email`
- `backend/app/auth/dependencies.py:231-267`: the factories and the `RequireMember` /
  `RequireAdmin` aliases.

## Root Cause Hypothesis

These routers were written before the role hierarchy existed, or were copied from a neighbour
without a guard. The only role tests (`test_cost_input_write_guards.py`,
`test_order_actuals_guards.py`, `test_sales_channel_history_guard.py`) cover pricing writes.
Confidence: high.

## Proposed Remediation

**Preferred**: Add `_: RequireMember` to every listed handler. Use `RequireAdmin` for
configuration and destructive routes: webhook subscriptions and secrets, Bambu printer
connections and credentials, review moderation, page publishing, `model_files.link_local_file` /
`validate_local_path` (they touch the server filesystem), `spoolmandb.sync_database`,
`test.send_test_email`, and deletes. Then add one test that walks `app.routes` and asserts that
every non-GET route under `/api/v1` either has a role dependency somewhere in its dependency tree
or appears in a named exception list with a reason. Seed that list with the by-design routes
above. This test supersedes the pricing-only walk.

**Alternatives**:
- Router-level `dependencies=[Depends(require_member())]` on routers that are write-heavy. There
  is less repetition, but GET routes on the same router would need splitting out.

**Files likely to change**:
- the twelve routers above
- `backend/tests/api/test_write_route_role_guards.py` (new, or the existing pricing walk widened)

**Tests to add or update**:
- Derived walk: every non-GET tenant route has a role guard or a named exception.
- Per router, one viewer-403 test and one member-success test (admin for the admin-only routes).

## Risks & Considerations

- The frontend may show these actions to viewers. Hide or disable them by role so viewers do not
  see buttons that now return 403.
- Printer agents or integrations that call these write routes with a service token need a role or
  an explicit exception.
- `model_files.validate_local_path` / `link_local_file` let any tenant user probe paths on the
  server. Beyond the role, confirm they are confined to a configured root, and raise it as its own
  security bug if they are not.
- `require_member()` reads `user_tenants` on an unscoped session, so it 403s everyone once RLS
  is enabled. See `rls-unscoped-routes`. Adding guards here does not make that worse, but both
  need fixing before RLS goes on.

## Open Questions

- None. Checked earlier: `FilamentType` holds no cost field and no pricing service reads it, so
  `filament_types` writes are outside the pricing feature.
