# Per-product cost delta

**Before**: `HEAD` | **After**: working tree | **Declared causes**: new-line:machine, new-line:waste, new-line:overhead, new-line:labor_packing, new-line:failure_premium

Every row whose cost moved carries a cause that was *verified* to predict
the movement, not merely declared alongside it. A product missing from the
before ref is reported as new rather than as a delta.

| Tenant | SKU | Before | After | Delta | Attributed to |
|---|---|---:|---:|---:|---|
| handy | GOLDEN-PROD | 10.44 | 18.52 | +8.08 | new lines (machine +2.21; waste +0.10; overhead +2.85; labor_packing +1.66; failure_premium +1.28; rounding -0.02) |
| handy | PROD-001 | 0.00 | 0.00 | 0.00 | unchanged |

**2 products, 1 changed, 0 unattributed.**

Of those, 1 report a non-zero cost and 1 carry a labor-bearing line (assembly, models or child products). A product with neither cannot move when the labor rate does, so it is not evidence either way.

No cost moved without a verified cause.

---

## How this report was produced

The development database holds one product with no costable input (`PROD-001`),
which is why the Tier 0 report could only say it had broken nothing. A report
that measures nothing is not evidence that Tier 1's new lines behave, so this
one was run against a **throwaway clone** of that database with one
representative product seeded into it — the golden case from
`backend/tests/fixtures/golden_case.py`: a 142 g part with 3 g purge, 9.5 h of
print time, 92% expected yield, a machine at CA$1,100 over 6,000 h with a
CA$220 reserve and 95 W at CA$0.13/kWh, CA$180/month of overhead over 600
machine-hours, and CA$0.92 of packaging.

The clone's policy row carries the labor rate the migration seeded from the
tenant's own settings — deliberately *not* the golden case's CA$25/h — so the
labor rate does not move and the delta is the new lines alone. The development
database itself was neither migrated nor modified.

`GOLDEN-PROD` is therefore seeded data, not the operator's. Re-run this report
against a database of real products before accepting Tier 1 on their behalf:

```bash
cd backend && poetry run python scripts/cost_delta_report.py \
    --before-ref b3f5341 \
    --cause new-line:machine --cause new-line:waste --cause new-line:overhead \
    --cause new-line:labor_packing --cause new-line:failure_premium \
    --out ../specs/002-pricing-engine-rebuild/delta-tier1.md
```

**The `rounding -0.02`** in the attributed row is not a discrepancy to chase: a
line is presented rounded to the cent while the total is computed unrounded, so
five rounded lines can sum to two cents more than the total they came from. The
report allows at most half a cent per line and names the residue rather than
absorbing it.
