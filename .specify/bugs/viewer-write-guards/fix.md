# Bug Fix: A viewer can write on routers outside pricing

- **Slug**: viewer-write-guards
- **Fixed**: 2026-10-25
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Every unguarded write handler on the twelve routers now takes `RequireMember` or `RequireAdmin`.
A derived test walks every non-pricing router, so the pricing walk and this one together cover
every write route in `app.api.v1`.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/app/api/v1/print_queue.py` | modified | 8 × `RequireMember` |
| `backend/app/api/v1/products.py` | modified | 6 image routes × `RequireMember` |
| `backend/app/api/v1/filament_types.py` | modified | 4 member, delete admin |
| `backend/app/api/v1/categories.py` | modified | 4 member, delete admin |
| `backend/app/api/v1/designers.py` | modified | 2 member, delete admin |
| `backend/app/api/v1/reviews.py` | modified | 4 × admin (moderation) |
| `backend/app/api/v1/model_files.py` | modified | upload/parse/update member; `link_local_file`, `validate_local_path`, delete admin |
| `backend/app/api/v1/webhooks.py` | modified | 6 × admin |
| `backend/app/api/v1/printer_bambu.py` | modified | connection create/update/delete admin; connect, disconnect, AMS map/unmap/sync member |
| `backend/app/api/v1/pages.py` | modified | 3 × admin |
| `backend/app/api/v1/spoolmandb.py` | modified | `sync_database` admin |
| `backend/app/api/v1/test.py` | modified | `send_test_email` admin |
| `backend/tests/unit/test_write_route_role_guards.py` | added test | derived walk over `NOT_PRICING_MODULES` |
| `backend/tests/unit/pricing/test_pricing_write_guards_derived.py` | modified | dropped the six image-route exceptions, now guarded |
| `backend/tests/api/test_viewer_write_guards.py` | added test | behavioural sample through the real auth path |

The split follows the convention already in `products.py`: deleting a top-level record,
configuration, credentials and moderation are admin; everyday edits are member.

## Tests Added or Updated

- `tests/unit/test_write_route_role_guards.py`: every write route on a tenant router has a role
  guard in its dependency tree or a named exception. `_INLINE` exceptions are checked against the
  handler's source, and stale exceptions fail.
- `tests/api/test_viewer_write_guards.py`: 20 routes refused to a viewer, 9 admin routes refused
  to a member, every sample proven to be a real route, and a member still creates a category (201).

## Local Verification

- `pytest tests/unit/test_write_route_role_guards.py tests/unit/pricing/test_pricing_write_guards_derived.py`: 9 passed.
- `pytest tests/api/test_viewer_write_guards.py`: 50 passed.
- Full CI-equivalent run: see `../FIX-RUN.md`.

## Deviations from Assessment

- **The derived walk found 12 more write routes** that the text sweep had counted as guarded:
  9 on `settings.py` and 3 on `tenant_members.py`. Each is in fact guarded, **inline**: the
  handler calls `_require_admin_role(user, tenant)` first. A dependency walk cannot see that, so
  they are named exceptions (`_INLINE`). A dedicated test fails if any of them stops calling it.
- `shipping.POST /rates` is named as an exception: it quotes postage and writes nothing.
- Public modules (auth, customer auth, shop, signed webhooks, signup) are excluded as a whole, each
  with its reason (`PUBLIC_MODULES`).

## Follow-ups

- **Frontend**: hide or disable the now-refused actions for viewers (and the admin-only ones for
  members), so nobody sees buttons that return 403.
- `settings.py` and `tenant_members.py` could move from the inline check to `RequireAdmin`, so the
  walk needs no exceptions. That is behaviour-neutral but out of scope here.
- `model_files.validate_local_path` / `link_local_file` are admin-only now. Whether they are
  confined to a configured root is still unchecked, and could be its own security bug.
