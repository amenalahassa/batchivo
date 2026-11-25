# Bug Assessment: Inventory transactions never store their metadata

- **Slug**: inventory-transaction-metadata-dropped
- **Created**: 2026-11-23
- **Source**: side finding from the `011-bambu-print-send` build (test `test_inventory_print_usage.py`)
- **Verdict**: valid (open)
- **Severity**: low (no figure is wrong; the context recorded with a stock movement is lost)

## Report

`InventoryTransactionService.create_transaction` builds the row with
`InventoryTransaction(..., metadata=metadata)` (`backend/app/services/inventory_transaction.py`,
around line 87). The mapped attribute is `transaction_metadata` (column name `metadata`,
`backend/app/models/inventory_transaction.py:117-122`). Passing `metadata=` sets a plain instance
attribute that shadows the declarative `Base.metadata`, so the column stays `NULL`.

Every caller is affected: usage, return and adjustment transactions written with metadata
(variance info, run details) are stored without it.

## Reproduction

Create any transaction through `create_transaction(..., metadata={"k": "v"})`, commit, re-read the
row: `transaction_metadata` is `None`.

## Remediation

In `create_transaction`, pass `transaction_metadata=metadata` instead of `metadata=metadata`,
with a regression test that re-reads the row. Then the explicit assignment added by spec 011 in
`create_print_usage_transaction` becomes redundant and can be removed.

Not fixed in 011: the approved scope there forbids changing existing inventory methods. 011's own
usage transactions set `transaction_metadata` directly, so they are stored correctly.
