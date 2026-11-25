# Per-product cost delta

**Before**: `HEAD` | **After**: working tree | **Declared causes**: labor-rate

Every row whose cost moved carries a cause that was *verified* to predict
the movement, not merely declared alongside it. A product missing from the
before ref is reported as new rather than as a delta.

| Tenant | SKU | Before | After | Delta | Attributed to |
|---|---|---:|---:|---:|---|
| handy | PROD-001 | 0.00 | 0.00 | 0.00 | unchanged |

**1 products, 0 changed, 0 unattributed.**

Of those, 0 report a non-zero cost and 0 carry a labor-bearing line (assembly, models or child products). A product with neither cannot move when the labor rate does, so it is not evidence either way.

> **This report is weak evidence.** No product in this database has an
> input the labor rate reaches, so nothing could have moved. It confirms
> the change broke no costing path; it does not show what the change does
> to real figures. Re-run it against a database with representative
> products before accepting the change on their behalf.

No cost moved without a verified cause.
