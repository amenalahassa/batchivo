# Bug Fix: Aware datetimes written to naive Postgres columns

- **Slug**: postgres-naive-datetime-writes
- **Fixed**: 2026-10-25
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

The seven `DateTime` columns declared without a time zone are now `DateTime(timezone=True)` in
the models and `timestamptz` in the database. A metadata walk keeps an eighth from appearing.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/app/models/platform_admin.py` | modified | `created_at`, `updated_at` → `DateTime(timezone=True)` |
| `backend/app/models/webhook.py` | modified | `last_triggered_at`, `last_success_at`, `next_retry_at`, `completed_at` |
| `backend/app/models/external_listing.py` | modified | `last_synced_at` |
| `backend/alembic/versions/20261025_timestamptz_instants.py` | added | revision `timestamptz_instants_v1`: `ALTER … TYPE timestamptz USING … AT TIME ZONE 'UTC'`, with downgrade |
| `backend/tests/unit/test_datetime_columns_are_aware.py` | added test | metadata walk, and the migration lists every column |
| `backend/tests/integration/test_every_tenant_table_has_rls.py` | added test | on a database built from migrations, each column is `timestamp with time zone` |

## Tests Added or Updated

- `tests/unit/test_datetime_columns_are_aware.py::test_every_datetime_column_is_timezone_aware`
  fails on any naive `DateTime` column.
- `tests/unit/test_datetime_columns_are_aware.py::test_the_migration_converts_every_column_the_models_fixed`
- `tests/integration/test_every_tenant_table_has_rls.py::test_instant_columns_are_timestamptz`
  (7 cases, Postgres only).

## Local Verification

- `pytest tests/unit/test_datetime_columns_are_aware.py`: 2 passed.
- `pytest tests/integration/test_every_tenant_table_has_rls.py` on the test Postgres
  (`docker-compose.test.yml`): `alembic upgrade head` ran through `timestamptz_instants_v1`,
  and all 7 column checks passed.
- Full CI-equivalent run: see `../FIX-RUN.md`.

## Deviations from Assessment

- **Severity is lower than assessed.** The reported 500 does not reproduce on the current code.
  CI and production connect with **psycopg** (`postgresql+psycopg://`), which casts an aware value
  into a naive column through the session time zone instead of refusing it. Asyncpg refuses it,
  and that driver produced the original report. `tests/api/test_platform_admin.py` and
  `test_shopify_sync.py` pass on Postgres before and after this change. The real exposure was a
  silent shift of every stored instant on a server whose `TimeZone` is not UTC. That is still
  worth fixing, but it is not critical.
- **The Shopify reader's `.replace(tzinfo=None)` is kept** (`shopify_sync.py:331`). SQLite, which
  the unit suite runs on, returns naive values even for `timezone=True` columns, so stripping the
  zone on both sides is still the comparison that works on both databases.

## Follow-ups

- If the codebase ever moves to asyncpg, `test_every_datetime_column_is_timezone_aware` is what
  keeps it safe.
