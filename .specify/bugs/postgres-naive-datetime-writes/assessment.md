# Bug Assessment: Aware datetimes written to naive Postgres columns turn the integration stage red

- **Slug**: postgres-naive-datetime-writes
- **Created**: 2026-10-24
- **Re-assessed**: 2026-10-25 (against `7a2776e`)
- **Source**: pasted text (side finding S1 from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 21 round)
- **Verdict**: valid (still open; the margin-alert flake from the original report is fixed)
- **Severity**: critical

## Report (verbatim or summarized)

> On PostgreSQL, tests/api/test_platform_admin.py (4 failed, 3 errors) and
> tests/api/test_shopify_sync.py::test_sync_shopify_success fail: a timezone-aware datetime is
> written into TIMESTAMP WITHOUT TIME ZONE columns (platform_admin_audit_logs via
> app/auth/middleware.py:71; external_listings.last_synced_at). SQLite tolerates it so the unit
> suite is green while CI's integration stage is red. Also the margin-alert log tests
> (test_margin_alert TestTheSweep, test_margin_alert_delivery x2) pass alone but fail under xdist.

## Re-assessment changes

- **Scope is now exact.** A walk of `Base.metadata` finds 7 `DateTime` columns without
  `timezone=True`, not an open-ended "sweep". All 7 receive aware values (list below).
- **The margin-alert flake is out of scope: it is fixed.** `3f83621` made `alembic/env.py` call
  `fileConfig(..., disable_existing_loggers=False)`, guarded by `tests/unit/test_alembic_logging.py`.
  Before that, a test running migrations disabled every existing logger, including
  `app.tasks.margin_alerts`. The three tests already use
  `caplog.at_level(logging.WARNING, logger="app.tasks.margin_alerts")`.

## Symptom

On PostgreSQL, inserting a platform-admin audit row, updating a platform setting, recording a
webhook delivery or syncing a Shopify/Etsy listing fails. asyncpg refuses an offset-aware value
for a `timestamp without time zone` parameter (`DataError`), so the request returns 500.
Expected: the row is stored.

## Reproduction

1. Start Postgres and point the test settings at it, as `.woodpecker/test-integration.yml` does
   (or `docker-compose.test.yml`).
2. `cd backend && poetry run pytest tests/api/test_platform_admin.py tests/api/test_shopify_sync.py::test_sync_shopify_success -p no:randomly`
3. Observe the failures on the audit-log `created_at` and `external_listings.last_synced_at` parameters.

Not re-run in this pass: no batchivo Postgres was running locally. The evidence is the model
metadata walk plus the writers below.

## Suspected Code Paths

Naive columns (from `Base.metadata`) and their aware writers:

| Column | Model | Aware writer |
|---|---|---|
| `platform_admin_audit_logs.created_at` | `app/models/platform_admin.py:77` (default `datetime.now(UTC)`) | `app/services/platform_admin.py:367` relies on the default |
| `platform_settings.updated_at` | `app/models/platform_admin.py:129` | `app/services/platform_admin.py:290` |
| `webhook_subscriptions.last_triggered_at`, `last_success_at` | `app/models/webhook.py` | `app/services/webhook_service.py:358-359` |
| `webhook_deliveries.completed_at`, `next_retry_at` | `app/models/webhook.py` | `app/services/webhook_service.py:349,395,412` |
| `external_listings.last_synced_at` | `app/models/external_listing.py:74` | `app/services/shopify_sync.py:161,171`, `app/services/etsy_sync.py:266,373,393` |

Readers that already work around the defect:

- `app/services/shopify_sync.py:331` compares against `last_synced_at.replace(tzinfo=None)`. This
  must change with the column type.
- `app/services/etsy_sync.py:294-295` reads `last_synced_at` for a freshness check.

Migrations that created the columns without a timezone:
`b5c6d7e8f9g0_add_platform_admin_audit_logs.py`, plus the webhook and external-listing create revisions.

## Root Cause Hypothesis

SQLAlchemy maps a bare `Mapped[datetime]` to `DateTime()` (timezone=False). `Base` has no
`type_annotation_map`. `TimestampMixin` declares `DateTime(timezone=True)` explicitly, but these 7
columns do not. The writers use `datetime.now(UTC)`. SQLite stores anything, so only CI's
Postgres stage fails. Confidence: high.

## Proposed Remediation

**Preferred**: Store instants as `timestamptz`.

1. Declare the 7 columns `mapped_column(DateTime(timezone=True), ...)`.
2. Add one Alembic migration that alters each column with
   `ALTER COLUMN <col> TYPE timestamptz USING <col> AT TIME ZONE 'UTC'`. Downgrade does the
   reverse.
3. Drop the `.replace(tzinfo=None)` at `shopify_sync.py:331`. Make sure the other side of that
   comparison is aware.
4. Add a unit test that walks `Base.metadata` and fails on any `DateTime` column without
   `timezone=True`. This makes the defect impossible to reintroduce.

**Alternatives**:
- Write naive UTC at every writer. This needs no migration, but every future writer must
  remember it, and it contradicts `TimestampMixin`.
- Set `type_annotation_map = {datetime: DateTime(timezone=True)}` on `Base`. It fixes the models
  in one line, but the migration is still needed, and it silently changes autogenerate output for
  every bare annotation.

**Files likely to change**:
- `backend/app/models/platform_admin.py`, `webhook.py`, `external_listing.py`
- `backend/app/services/shopify_sync.py` (the naive comparison)
- `backend/alembic/versions/<new>_timestamptz_for_instant_columns.py`
- `backend/tests/unit/test_datetime_columns_are_aware.py` (new)

**Tests to add or update**:
- Metadata walk: every `DateTime` column has `timezone=True`.
- Postgres-run regression: create an audit log, update a platform setting, record a webhook
  delivery and sync a listing, then read each back as aware.
- The Shopify freshness check still skips an unchanged product after the type change.

## Risks & Considerations

- `ALTER TYPE` rewrites each table. All four are small.
- Existing naive values must be read as UTC (`AT TIME ZONE 'UTC'`). Every writer found uses UTC.
- Any reader that compares these columns with a naive datetime will start raising. Grep the
  readers after the change (`shopify_sync.py:331` is the one known case).
- This blocks merging: CI's integration stage stays red until it is fixed.

## Open Questions

- None.
