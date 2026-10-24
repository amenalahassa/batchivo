# Bug Assessment: Aware datetimes written to naive Postgres columns turn the integration stage red

- **Slug**: postgres-naive-datetime-writes
- **Created**: 2026-10-24
- **Source**: pasted text (side finding S1 from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 21 round)
- **Verdict**: valid
- **Severity**: critical

## Report (verbatim or summarized)

> On PostgreSQL, tests/api/test_platform_admin.py (4 failed, 3 errors) and
> tests/api/test_shopify_sync.py::test_sync_shopify_success fail: a timezone-aware datetime is
> written into TIMESTAMP WITHOUT TIME ZONE columns (platform_admin_audit_logs via
> app/auth/middleware.py:71; external_listings.last_synced_at). SQLite tolerates it so the unit
> suite is green while CI's integration stage is red. Also the margin-alert log tests
> (test_margin_alert TestTheSweep, test_margin_alert_delivery x2) pass alone but fail under xdist.

## Symptom

Inserting a platform-admin audit row or a synced Shopify listing on PostgreSQL raises asyncpg's
"can't subtract offset-naive and offset-aware datetimes" (`DataError` on the timestamp parameter),
so the request 500s. Expected: the row is stored. Separately, three margin-alert log assertions
fail only when run alongside the rest of the integration suite under xdist.

## Reproduction

1. Start Postgres (`docker compose up -d postgres`) and point the test settings at it, as
   `.woodpecker/test-integration.yml` does.
2. `cd backend && poetry run pytest tests/api/test_platform_admin.py tests/api/test_shopify_sync.py::test_sync_shopify_success -p no:randomly`
3. Observe 5 failures / 3 errors on the audit-log `created_at` (`$8`) and `external_listings.last_synced_at` (`$7`) parameters.
4. For the flakes: `poetry run pytest tests/ --ignore=tests/unit -n 4` fails
   `tests/integration/test_margin_alert.py::TestTheSweep::test_it_logs_the_divergence_at_warning`
   and two tests in `tests/integration/test_margin_alert_delivery.py`; each passes run alone.

## Suspected Code Paths

- `backend/app/models/platform_admin.py:77` — `created_at: Mapped[datetime] = mapped_column(..., default=lambda: datetime.now(UTC))`: no `DateTime(timezone=True)`, so the column is `TIMESTAMP WITHOUT TIME ZONE` but the default is aware.
- `backend/app/services/platform_admin.py:367` — `PlatformAdminAuditLog(...)` relies on that default; reached from every platform-admin route (the trace passes through `app/auth/middleware.py:71`, `call_next`, which is only the middleware frame, not the cause).
- `backend/app/models/external_listing.py:74` — `last_synced_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, ...)`: no type, so naive.
- `backend/app/services/shopify_sync.py:153` and `backend/app/services/etsy_sync.py:266,373,393` — write `datetime.now(timezone.utc)` (aware) into it.
- `backend/alembic/versions/b5c6d7e8f9g0_add_platform_admin_audit_logs.py` — created the column without a timezone.
- Other `Mapped[datetime]` columns declared without an explicit `DateTime(timezone=True)` (e.g. `ams_slot_mapping.py:139,145`, `customer.py`, `discount.py`, `email_verification.py`) — candidates for the same defect wherever an aware value is written.
- `backend/tests/integration/test_margin_alert.py`, `test_margin_alert_delivery.py` — log-capture assertions that depend on logger state shared across tests in a worker.

## Root Cause Hypothesis

SQLAlchemy maps a bare `Mapped[datetime]` to `DateTime()` (timezone=False). The code writes
`datetime.now(UTC)`; asyncpg refuses an aware value for a `timestamp` parameter, while SQLite
stores any string, so only CI's Postgres stage sees it. Confidence: high. For the margin-alert
tests, the hypothesis is that another test in the same worker changes the logger's level,
handlers or `propagate` flag (or `caplog` captures the wrong logger), so the warning is not
captured. Confidence: medium.

## Proposed Remediation

**Preferred**: Store instants as `timestamptz`. Declare the affected columns
`mapped_column(DateTime(timezone=True), ...)` and add one Alembic migration altering
`platform_admin_audit_logs.created_at` and `external_listings.last_synced_at` (plus any other
naive column the sweep finds that receives aware values) with
`ALTER COLUMN ... TYPE timestamptz USING <col> AT TIME ZONE 'UTC'`. Add a unit test that walks
`Base.metadata` and fails on any `DateTime` column without `timezone=True` (or on a named
exception list with reasons), so the defect cannot return. For the flakes, give the three tests
an explicit `caplog.set_level(logging.WARNING, logger="<module logger>")` and make sure no
fixture leaves `propagate=False` or extra handlers on that logger.

**Alternatives**:
- Write naive UTC (`datetime.now(UTC).replace(tzinfo=None)`) at each writer — no migration, but
  every future writer must remember it, and readers comparing to aware values will break.

**Files likely to change**:
- `backend/app/models/platform_admin.py`
- `backend/app/models/external_listing.py`
- (sweep) other models with naive `Mapped[datetime]` columns
- `backend/alembic/versions/<new>_timestamptz_for_instant_columns.py`
- `backend/tests/unit/test_datetime_columns_are_aware.py` (new)
- `backend/tests/integration/test_margin_alert.py`, `test_margin_alert_delivery.py`

**Tests to add or update**:
- Metadata walk: every `DateTime` column has `timezone=True` or a documented exception.
- Postgres-run regression: create an audit log and a synced listing and read them back aware.
- Run the integration suite with `-n 4` twice to confirm the margin-alert tests are stable.

## Risks & Considerations

- Migration on a production table: `ALTER TYPE` rewrites the table; both tables are small.
- Existing naive values must be interpreted as UTC (`AT TIME ZONE 'UTC'`); confirm writers always used UTC.
- Readers that compare these columns to naive datetimes would start failing; grep for comparisons after the change.
- Blocks merging any feature: CI's integration stage is red until fixed.

## Open Questions

- [NEEDS CLARIFICATION: is the margin-alert flake reproducible on CI's Linux runners at `-n 4`, or only locally?]
