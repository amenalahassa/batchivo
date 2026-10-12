# Per-product delta — Tier 2 (fee rules, shipping, tax, margin basis)

**Before**: `dd4e258` (Tier 1 complete) | **After**: working tree
**Declared causes**: fee-rules, shipping (postage paid), refund reserve, tax treatment, margin basis

## Make-cost: nothing moved, by construction

Tier 2 adds no cost line and changes no cost input. Every figure it introduces
sits **after** the make-cost in the chain: the fee stack, the refund reserve,
postage paid, the tax treatment and the margin basis are all applied to a
cost the engine has already finished computing.

| Tenant | SKU | Before | After | Delta | Attributed to |
|---|---|---:|---:|---:|---|
| (all) | (all) | — | — | 0.00 | unchanged — no Tier 2 change reaches `total_make_cost` |

This is a structural claim, not a sample, and it is enforced rather than
asserted:

- `app/services/fee_engine.py` is imported *by* `costing.py` and imports nothing
  from it. The fee stack cannot reach `_item_lines`, which is where every cost
  line is built.
- `CostingService.margin()` takes a finished `make_cost` as an argument. It has
  no path to recompute one.
- `tests/unit/pricing/test_golden_case.py` asserts the make-cost is CA$20.30
  from the fixture's inputs, and it passes unchanged across this tier. So do the
  387 pre-existing pricing unit tests.

The cost delta script was therefore not re-run against a seeded clone for this
tier: it measures `total_make_cost`, the quantity this tier provably does not
touch. `delta-tier3.md` (task T099a) will need it again, because Tier 3 changes
how a price is resolved as at a date.

## Margin: this is where Tier 2 moves the numbers

The figures below are the golden acceptance case — a 142 g part at CA$64.99,
make-cost CA$20.30 — on a channel that before this tier carried a single
blended fee of **6.5% + CA$0.30**, which is the shape every existing channel
had.

| Figure | Before | After | Delta |
|---|---:|---:|---:|
| Make-cost | 20.30 | 20.30 | 0.00 |
| Fees charged | 4.52 | 10.64 | +6.12 |
| Refund reserve | 0.00 | 1.62 | +1.62 |
| Postage paid | 0.00 | 9.50 | +9.50 |
| **Profit** | **40.17** | **22.92** | **−17.25** |
| **Margin** (customer total) | **61.8%** | **35.3%** | **−26.5 pts** |

### Attribution, verified

| Cause | Movement |
|---|---:|
| Fee rules — the real stack replaces one blended percentage | −6.12 |
| Refund reserve — 2.5% held against revenue (FR-026) | −1.62 |
| Postage paid — free shipping is not free (FR-024) | −9.50 |
| Rounding residue | −0.01 |
| **Total** | **−17.25** |

The three causes sum to −17.24 against an actual movement of −17.25. The cent
is the rounding boundary, not an unattributed change: the before figure rounds
its single fee to the cent, while the after chain carries the fees and the
reserve unrounded and rounds the profit once. Both roundings are deliberate and
both are pinned by tests — `test_the_rounded_lines_read_a_cent_high` in
`test_golden_case.py` records exactly this cent.

### Where each −CA$ comes from

The fee stack that replaced the blended 6.5% + CA$0.30:

| Fee | Basis | Amount |
|---|---|---:|
| transaction | item plus shipping | 4.22 |
| payment_processing | order total | 2.25 |
| regulatory_operating | item subtotal | 2.17 |
| order_handling | per order | 2.00 |
| **Total** | | **10.64** |

A single percentage could express the first of those. The margin was wrong by
the other three, and by the postage, every time.

### Tax treatment: no movement on this case

The golden case collects no sales tax, so the tax treatment moves nothing here
— which is the point of FR-028c and is asserted directly rather than inferred:
`test_sales_tax.py::test_two_identical_sales_report_the_same_margin` shows that
two otherwise identical sales, one marketplace-remitted and one
operator-remitted, report the **same** margin. Tax never enters a margin under
either answer, so this tier's tax work changes no reported margin at all. What
it changes is that the liability is now visible where the operator owes it.

### Margin basis: the percentage only

| Basis | Margin | Profit | Make-cost |
|---|---:|---:|---:|
| Customer total (default) | 35.3% | 22.92 | 20.30 |
| Item price alone | 35.3% | 22.92 | 20.30 |
| Net revenue after fees | 42.2% | 22.92 | 20.30 |

FR-031c holds: the profit and the make-cost are identical under all three, and
only the percentage moves. The first two coincide on this case because the
channel ships free, so the customer total *is* the item price — which is why
the acceptance figure of 35.3% holds under either, and why
`test_margin_basis.py` exercises the three-way difference on a case that does
carry shipping revenue.

## Migration safety

`tests/integration/test_fee_migration_parity.py` is the evidence for FR-030, and
it passed against PostgreSQL over six channels covering every shape the old
pair could take — percentage only, fixed only, both, neither, an awkward rate,
and a large fee — at five prices each, with **exact** equality rather than a
tolerance:

- Every channel charges exactly what it charged before, including as at a date
  before the migration ran.
- A channel charging nothing gets no rules rather than two rows charging zero.
- `fee_percentage` and `fee_fixed` are kept and kept populated, so FR-030 stays
  checkable until task T123 drops them.
- The downgrade removes the derived rules and leaves that pair untouched.

## What an operator should take from this

Nothing they make costs more than it did yesterday. What changed is that the
margin now subtracts the fees the marketplace actually charges and the postage
the operator actually pays. On the acceptance case that is 26.5 percentage
points — and the old 61.8% was never money anyone received.

Re-run the margin side of this report against real products and real channel
fee schedules before accepting Tier 2 on the operator's behalf. The figures
above are the golden fixture, not their catalogue:

```bash
cd backend && poetry run pytest tests/integration/test_fee_migration_parity.py -v
```
