# Postage delta from the catalogue release step

FR-018a and the constitution (Additional Constraints) require the per-record
difference a change to computed values makes to be reported before the change
is accepted. The release step produces it itself:

```bash
cd backend
poetry run python -m app.cli.seed_catalogues --all-tenants --dry-run --report delta.md
```

Every tenant's seeding runs in a transaction that is rolled back; the report
lists, per product and zone, the postage for one unit before and after.

## Run 1 — copy of the dev database (2026-11-04)

**Not the production run.** Production data was not available in this
session; the run below is against `batchivo_spec006`, a copy of the local dev
database (`pg_dump batchivo`), migrated to `catalogue_columns_v1`. The release
is accepted only after the same command has been run against a copy of
production and its report added below as Run 2.

| Tenant | Currency | Packaging | Postage |
|---|---|---|---|
| e2e-pricing | GBP | 16 added, 0 skipped | royal_mail: 8 added, 0 skipped |
| handy | CAD | 16 added, 0 skipped | canada_post: 39 added, 0 skipped |

Postage per product and zone that changes: **none**.

Why, checked per product (not taken from the report alone):

| Tenant | SKU | Zone | Before | After | Why unchanged |
|---|---|---|---|---|---|
| e2e-pricing | E2E-DRAGON-P | domestic | 3.40 | 3.40 | No packaging accepted, so the parcel has no size; every seeded Royal Mail service has size limits and is never matched by a parcel without a size. The operator's weight-only profile still prices it. |
| handy | PROD-001 | CA, USA | unknown | unknown | No recorded weight: postage is unknown before and after (the margin already says so). |

What will change once operators act: a product that accepts a catalogue box
gets a sized parcel, and the seeded size-limited services can then price it,
cheapest first, or by the default service. That is a change the operator makes
by accepting packaging, not one the release makes.

## Run 2 — release data (2026-11-04)

There is no production deployment of this release: the local dev database is
the only environment with real shop data. The dry run was repeated on a fresh
copy of it (`batchivo_devcopy`, taken from `batchivo` today and migrated to
`catalogue_columns_v1`), so the report covers the data the release is applied
to.

| Tenant | Packaging | Postage |
|---|---|---|
| e2e-pricing | 16 added, 0 skipped | royal_mail: 8 added, 0 skipped |
| handy | 16 added, 0 skipped | canada_post: 39 added, 0 skipped |

Postage per product and zone that changes: **none** (same reasons as Run 1).

Should a production instance be created later, run the command above against
a copy of its data before applying the release there.
