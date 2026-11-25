# Per-product delta — T254 (material cost from the spool's landed cost)

**Cause**: `landed_cost` — lines whose stored per-gram figure was the browser's
prefill now cost at the spool's landed figure (usable weight, allocated shipping,
non-recoverable tax). No other input differs between the two columns.

| Tenant | SKU | Before | After | Delta | Lines re-derived | Attributed to |
|---|---|---:|---:|---:|---:|---|
| handy | PROD-001 | 0 | 0 | 0 | 0 | unchanged |

## Where this was run

Against the local dev database on 2026-10-25, before `pricing_material_from_spool_v1`
was applied. Dev holds one product with no bill of materials, so nothing moves there.

Production has not been measured. Run the same command against it **before** ArgoCD
applies the migration, and attach the output here:

    poetry run python scripts/material_cost_delta_report.py --out ../specs/002-pricing-engine-rebuild/delta-t254.md

Every change it reports is caused by `landed_cost`: the two columns differ only in which
per-gram figure the re-derived lines use. A line whose figure was not the browser's
prefill keeps it as an override and does not move (FR-050).
