# Per-product delta — Tier 3 (snapshots, temporal prices, exchange rates)

**Before**: `b8ce936` (Tier 2 and the solver complete) | **After**: working tree
**Declared causes**: sale snapshots, temporal price resolution, quantity tiers,
exchange rates, and one defect found while wiring them up

## Make-cost: nothing moved, by construction

Tier 3 adds no cost line and changes no cost input. Everything it introduces is
about **when** a figure is read, not what it is:

| Tenant | SKU | Before | After | Delta | Attributed to |
|---|---|---:|---:|---:|---|
| (all) | (all) | — | — | 0.00 | unchanged — no Tier 3 change reaches `total_make_cost` |

As in Tier 2 this is structural rather than sampled, and it is enforced:

- `app/services/temporal_pricing.py` and `app/services/fx_service.py` are
  imported *by* the read paths and import nothing from `costing.py`. Neither can
  reach `_item_lines`, where every cost line is built.
- `app/services/sale_snapshot.py` *calls* the cost engine and stores what it
  returns. It has no path to change what the engine computes.
- `tests/unit/pricing/test_golden_case.py` still derives the CA$20.30 make-cost
  from the fixture's inputs, and passes unchanged. So do the other pricing unit
  tests — 703 across `tests/unit/pricing`, `tests/unit/test_sync_payload_builders.py`,
  `tests/api/test_product_margin.py` and `tests/integration/test_snapshot_immutability.py`
  after this tier.

One addition does reach the breakdown, and it is additive: `machine_hours`, a
new nullable field carrying the machine occupancy of one sellable unit. It is
null where no print time is recorded anywhere below the item — never zero,
which would read as an item that occupies no machine. No existing figure is
derived from it; US7's profit-per-machine-hour is.

## Margin: no settled order's margin moved — and that is now provable

This is the tier's actual claim, and it is the one FR-038 makes:

> changing a spool price, a labor rate, an overhead setting or a fee rule must
> not alter any settled order's reported margin.

`tests/integration/test_snapshot_immutability.py` (19 tests) builds three
settled orders, snapshots them, then changes all four inputs — the spool price
by +50%, the labor rate from CA$25.00 to CA$41.00, the overhead pool from
CA$180/600h to CA$540/200h, and the channel commission from 6.5% to 12.0%:

| Figure | Before the edits | After the edits | Delta |
|---|---:|---:|---:|
| Settled orders reporting a different margin | 0 of 3 | 0 of 3 | **0** |
| Frozen `make_cost_at_sale` | unchanged | unchanged | 0.00 |
| Frozen `list_price_at_sale` | unchanged | unchanged | 0.00 |
| Frozen `fees_json` | unchanged | unchanged | 0.00 |
| Frozen `fx_rate` | unchanged | unchanged | 0 |

### Why that table is not vacuous

A test that reads a frozen number and asserts it did not change would pass even
if the four edits had done nothing. So the same file subjects an order with
**no** snapshot to the identical edits and requires its margin to move. It does,
for each of the four separately. The inputs genuinely moved; the settled orders
held still by design.

The labor-rate edit is deliberately the most hostile version available: it
rewrites the **historical policy row in place**, rather than going through
`write_policy`, which would open a new effective row that a dated read steps
around on its own. That removes the second layer of protection and leaves only
the snapshot standing.

## Price resolution: the figure a read returns

Before this tier a product had one price row per channel, so "the price" and
"the price on that date" were the same question. They are no longer:

| Read | Before | After |
|---|---|---|
| Storefront product page | the single row, or **0.00** when absent | the row with `valid_to IS NULL`, or *unpriced* |
| Product detail screen | the single row | the current row, with its period and tier |
| Etsy / Shopify listing sync | the single row | the current row only |
| Margin endpoint | the single row | the row in effect on `as_of` |
| Sale snapshot | n/a | the row in effect on the order's date |

Two of those changes are consequential rather than cosmetic:

**The storefront no longer substitutes zero for a missing price.** Five shop
read sites each filtered `product.pricing` in place and fell back to
`Decimal("0")`. An unpriced product therefore appeared on a public page as
free. They now all call `storefront_price`, which returns `None`, and the page
treats the product as unpriced.

**The two marketplace sync services would have published a superseded price.**
`etsy_sync` and `shopify_sync` read `product.pricing`, which since this tier is
the full history in `valid_from` descending order. Left alone, each would have
pushed whichever row the ORM returned first to a live listing — undercharging
every customer who bought at it. Both now read the current rows only.

### Quantity tiers

A price now carries `min_quantity`, a half-open lower bound. The resolution
rule is that the **highest tier the quantity reaches wins**, so at exactly a
break quantity the answer is unambiguous: with tiers at 1, 10 and 50, ten units
are priced at the 10+ figure.

| Quantity | 1+ at 64.99 | 10+ at 59.99 | 50+ at 54.99 | Resolved |
|---:|---|---|---|---:|
| 9 | ✓ | | | 64.99 |
| 10 | ✓ | ✓ | | **59.99** |
| 49 | ✓ | ✓ | | 59.99 |
| 50 | ✓ | ✓ | ✓ | **54.99** |

Existing products are unaffected: the migration stamps every existing row
`min_quantity = 1`, so every current price is the base tier and resolves exactly
as it did before.

## Exchange rates: an unknown rate is not parity

`fx_service` returns `None` for a currency pair it has never had a rate for,
and `require_rate` raises. Neither ever returns `1.0`.

| Situation | Before | After |
|---|---|---|
| Rate known for today | n/a | reused, not re-fetched (one request per pair per day) |
| Service unreachable | n/a | last known rate, flagged stale, carrying its date |
| Operator entered a rate | n/a | overrides the fetched one; the fetched row is kept |
| Pair never fetched | n/a | **unknown** — never 1.0 — and a sale still completes |
| A better rate becomes known | n/a | a settled order's frozen rate is not revised |

`tests/unit/pricing/test_fx.py` (58 tests) covers each row without a network,
and one of them exists only to fail if the unknown case is ever "simplified"
into a default of one.

## A defect this tier exposed and fixed

Wiring the dated reads together surfaced a bug that predates this feature and
was silently wrong for part of every day.

`write_policy` dated a policy row from `datetime.now(timezone.utc).date()`.
Every endpoint that read a policy back defaulted its `as_of` to
`date.today()` — the **local** date of the machine the process runs on. In
UTC−4, between 20:00 and midnight local, those are different days:

| Local time (UTC−4) | `date.today()` | UTC date | Policy written then | Read back as |
|---|---|---|---|---|
| 14:00 | 12 Oct | 12 Oct | effective 12 Oct | the new figure |
| 21:00 | 12 Oct | **13 Oct** | effective **13 Oct** | **the figure it replaced** |

So an operator changing their margin basis or labor rate in the evening saw no
effect, with nothing on screen to explain it — the read found no policy in
force and fell back to the legacy settings. The same split reached a price
period, a fee rule's effective date, an exchange rate's day and a sale
snapshot's reference date.

`tests/api/test_product_margin.py::test_switching_the_basis_moves_only_the_percentage`
caught it, because this tier's work happened to run after 20:00 local. It would
otherwise have shipped.

There is now one notion of today, in `app/core/clock.py`, and every path that
dates a monetary record or reads one as at a date calls it (Constitution III).
It returns the UTC date, so a record's `created_at` and its effective date come
from the same clock. The remaining honest gap is named in that module: an
operator in UTC−4 making a change at 21:00 still sees it dated tomorrow, which
wants a per-tenant business timezone rather than the server's locale.

A second, smaller defect found the same way: `resolve_policy_row` broke ties on
`created_at`, which has second resolution. Two policy writes in the same second
were indistinguishable and the tie resolved arbitrarily. Among rows sharing a
start date the open row is by definition the later write, so that is now the
tiebreaker.

## Migration safety

`20261012_pricing_tier3.py` (`pricing_tier3_v1`), single head, reached cleanly:

- **Every existing price keeps applying, from when it was set.** `valid_from` is
  backfilled from each row's `created_at` date rather than from today. Dating
  them from today would have left every historical order with no price in effect.
- **`valid_to` stays null**, so each existing row becomes the current period of
  its own history and every past order resolves to the figure it was charged.
- **The constraint swap is ordered.** `uq_product_channel_pricing` forbade
  exactly the history this table now holds, so it is dropped — but only after
  `valid_to` exists and is populated, because the partial unique index that
  replaces it is defined over that column. Both happen in one transaction.
- **Nothing is backfilled into a snapshot.** Lines settled before the migration
  read as *unknown*, not zero: a zero make-cost on a settled order is
  indistinguishable from a real one. A snapshot reconstructed from today's
  inputs would be the restatement FR-037 forbids, and would be
  indistinguishable from one frozen at the time.
- **`fx_rates` carries no `tenant_id`**, the one deliberate exception to the RLS
  rule in this feature — a published exchange rate is not tenant data. The
  reasoning is in `app/models/fx_rate.py`, and the rate that *is* tenant data,
  the one frozen onto `order_items.fx_rate`, sits on a tenant-scoped table under
  RLS.

### The downgrade is destructive

`downgrade()` cannot restore a one-row-per-channel constraint while several
periods exist, so it **deletes every superseded row** and every non-base tier
before restoring it. Every settled order then stops reporting the price it was
charged and starts reporting today's. It is implemented rather than left to
fail because a downgrade that raises halfway has already dropped the index and
left the table in neither shape. Read the migration's module docstring before
ever running it.

## What an operator should take from this

Nothing they make costs more than it did yesterday, and no margin they have
already reported has changed. Three things are different:

1. **A price has a history.** Changing a price opens a new period instead of
   overwriting the old one, so last quarter's orders keep reporting last
   quarter's prices. The product screen shows what a product sells for now; the
   history is behind a button, deliberately with no margin column.
2. **A settled order's margin is frozen.** Changing a spool price, a labor
   rate, an overhead setting or a fee rule changes what the *next* sale will
   earn, and nothing about what past sales did.
3. **An unknown exchange rate reads as unknown.** A cross-currency sale with no
   rate on record is reported as having no rate rather than being valued at 1:1,
   and the sale still completes.

Re-run the margin side of this report against real products and real channel
fee schedules before accepting Tier 3 on the operator's behalf:

```bash
cd backend && poetry run pytest tests/integration/test_snapshot_immutability.py tests/unit/pricing/test_temporal_pricing.py tests/unit/pricing/test_fx.py -v
```
