---
sidebar_position: 2
title: How Pricing Works
---

# How Pricing Works

This page explains the figures Batchivo shows you: what goes into a cost, what
comes out of a sale, and why a number is what it is. It is the reference for
the model itself. For the screens and the day-to-day workflow, see
[Costing & Pricing](./guides/costing-pricing.md).

Three things hold throughout, and they are worth knowing before any of the
detail:

1. **Nothing is stored that can be derived.** A cost or a margin is calculated
   when you ask for it, from your current inputs and the policy in force. There
   is no cached cost to go stale. The two deliberate exceptions are the price a
   customer was actually quoted and the actuals recorded against a finished
   order — those are history, and history does not move.
2. **Every figure says where it came from.** A cost line is built from inputs
   that are each labelled observed, measured, your setting, or assumed. A
   breakdown tells you what share of the total is evidence and what share is a
   guess, so you know how much to trust it.
3. **The system proposes; you decide.** A measurement from a printer or a power
   meter can raise a suggestion to revise an estimate. It does not reprice
   anything by itself.

---

## What a make-cost is made of

The make-cost is what it costs you to have one sellable item in a box. It is
built from six lines, and the breakdown screen shows each one separately
because the useful question is usually *which* line is large, not what the total
is.

| Line | What it charges for |
|---|---|
| **Material** | The filament in the part, at your spool's real per-gram cost |
| **Waste** | Purge, flushed filament and the spool remainder you cannot print |
| **Machine** | The printer's time: depreciation, maintenance reserve and power |
| **Labour** | Your attention — per item, and per plate for setup |
| **Overhead** | Your fixed monthly costs, spread over expected machine hours |
| **Packaging** | The mailer, padding and label that ship with it |

### Material and waste

Your per-gram cost is derived from what the spool actually cost you landed —
purchase price, its share of inbound shipping, and sales tax only if you cannot
recover it — divided by the weight you can actually print. A 1 kg spool with
25 g you can never get out of it is a 975 g spool for costing purposes.

Inbound shipping is split across a purchase by weight, not evenly: a 250 g
spool bought alongside three 1 kg spools carries about a tenth of the postage,
not a quarter of it, because weight is what drove the charge.

Purge and flushed filament are a separate line from the part weight. They are
real grams that cost real money, and keeping them separate is what lets you see
that a four-colour part spends more on flushing than on the model.

### Machine time

A 9.5-hour print occupies a machine that is depreciating, drawing power, wearing
towards its next maintenance, and — most importantly — cannot print anything
else meanwhile. The machine line charges for that:

- **Depreciation**: purchase price over expected lifetime hours
- **Maintenance**: your maintenance reserve over the same hours
- **Power**: measured watts × hours × your electricity rate

Set these per printer, under the printer's cost policy. Without them, a 10-hour
print looks as cheap as a 2-hour print and your queue ends up ordered backwards.

### Labour, per item and per plate

Some work happens once per item (finishing, packing). Some happens once per
plate however many parts are on it (slicing, bed prep, starting the job). Plate
work is divided across the plate's output, so a plate of 20 lowers per-item
labour where a plate of 1 does not.

### The failure premium

If one print in twelve fails, the eleven that succeed have to carry the twelfth.
Your expected yield drives a premium on the work that was **at risk** — material,
waste, machine, overhead and the labour spent before the part was known good.

It is deliberately **not** applied to packaging or to packing labour. You do not
box a failed print, so charging the successful ones for packaging they never
consumed would overstate the cost.

Two failure modes, chosen per item:

- **Per part** (the default): a failure loses one part.
- **Per plate**: a failure condemns the whole bed. Use this where one part
  coming loose ruins the rest. The premium is heavier for the same yield figure,
  because it includes the plate's one-off preparation as well.

Switching the mode does not reuse a yield figure learned under the other one —
they measure different things.

### Bundles

A product containing other products is costed recursively, each child by its own
breakdown. A circular or absurdly deep structure is reported as an error rather
than quietly computed.

---

## What a sale actually leaves you

A make-cost is only half the picture. What the marketplace takes is the other
half, and it is usually larger than any single cost line.

### Fee rules, not a blended percentage

A single "fee percentage" cannot represent a real marketplace. Batchivo holds
each fee as its own rule with its own basis:

- A percentage of the item price
- A percentage of item **plus shipping** you collected
- A percentage of the order total
- A fixed amount per order
- A fixed amount per unit sold
- A fixed amount per listing
- A periodic charge (a monthly subscription)

Each rule can carry a minimum and a maximum, which is how a capped final-value
fee and a "3% but at least 30¢" processing fee are both expressible.

A fee that lands on only some orders — advertising, for instance — is included
at its expected incidence and labelled as an **expectation**, not a charge. A
planned margin that quietly assumed every order pays for advertising would be
wrong in the optimistic direction.

The margin screen itemises every fee with the amount it contributed, and says
when a cap applied.

### Shipping

Postage you paid and shipping revenue you collected are two different numbers,
and their difference is its own line. It is frequently negative, and that is the
point: free shipping is a cost, and it should appear as one.

Shipping revenue is never netted out before fees are applied — a marketplace
charging its percentage on item-plus-shipping charges it on what you collected.

### Sales tax

Margin is always computed on tax-exclusive amounts. Each channel records who
remits the tax — the marketplace under facilitator rules, or you. Either way tax
is excluded from revenue; where you remit it, it is tracked as a liability owed,
never as revenue or profit.

The consequence worth knowing: two otherwise identical sales, one on a
facilitator marketplace and one on your own site, report the same margin
percentage.

### The margin basis

"Margin" has three defensible denominators, and the figure differs by several
points depending on which you mean. Batchivo implements all three and names the
one in force beside every percentage:

| Basis | Denominator |
|---|---|
| **Customer total** (default) | Item price plus shipping revenue |
| **Item price** | The item price alone |
| **Net revenue** | What is left after fees |

Changing the basis changes the percentage. It does not change the profit amount
— that is the same money either way.

### Profit per machine-hour

Margin percentage says nothing about how long your machine was tied up earning
it. A 40% margin on a 20-hour print can be a worse use of a printer than a 25%
margin on a two-hour one.

Profit per machine-hour is reported alongside margin everywhere margin appears,
and the print queue can be ranked by it. Where machine hours are not recorded,
the figure is shown as unavailable rather than as zero — an unknown is not a
nought.

---

## Asking for a price instead of guessing one

Rather than typing a price and reading the margin it produced, state the margin
you want and get the price that achieves it.

This is solved, not estimated: the percentage fees are charged on the very price
being solved for, so the answer is not simply cost ÷ (1 − margin). The solver
also shows the ladder of nearby prices and the margin each would give.

Two things it will do that are worth expecting:

- **Rounding and thresholds.** If the channel has a rounding rule or a
  free-shipping threshold, the result is adjusted and both adjustments are shown
  as such, so you can see the price before and after they applied.
- **Refusing.** If percentage fees plus your target reach the whole price, no
  price achieves the target. The system says the target is unachievable and names
  the constraint, rather than returning a large number that looks like an answer.

A solved price is a proposal. Nothing is published to any channel automatically.

---

## Settled orders keep the margin they had

When you make a sale, the order line keeps the cost breakdown, the price, the
fees and the exchange rate as they stood at that moment. Raise your labour rate
tomorrow, buy more expensive filament, watch a marketplace revise its fee
schedule — last quarter's margin does not move.

What a customer was quoted is also kept, as a price snapshot, so the storefront
and the order agree about what was offered.

Policy itself is effective-dated. Changing a fee rule or a rate supersedes the
old one from a date rather than overwriting it, which is what makes a margin
trend something you can reason about instead of a number that rewrites itself.

### Realised margin

Alongside the planned figure, a finished order can report what it actually
earned: the revenue received, the fees actually charged, and the material and
machine time the production run actually consumed. Where an actual exists it
replaces the estimate; where it does not, the costed figure stands and the gap
is named. A realised margin that silently reused an estimate would be the
planned figure wearing a different label.

Actual fees come from reconciliation — a period total per fee category per
channel is the routine entry, with a specific order's fee recordable when one
looks anomalous. An order-level figure takes precedence and reduces the period's
unallocated remainder, so nothing is counted twice. Fees you entered by hand are
labelled as entered, never as observed.

---

## Where your numbers come from, and how they improve

### Provenance

Every cost input carries one of four labels:

| Label | Meaning |
|---|---|
| **Observed** | Measured by the system from a real outcome |
| **Measured** | Measured by you and entered |
| **Your setting** | A decision you made — a rate, a policy, a target |
| **Assumed** | A default nobody has confirmed |

A breakdown reports the share of its total that rests on evidence. A figure that
has not been re-measured in a long time is flagged as stale — shown next to the
value and its date, not instead of them.

A figure you decided is never relabelled as observed. Your labour rate is not an
estimate that the system gets to improve.

### Learning from outcomes

Record enough real outcomes for a measurement — actual grams, actual print time,
actual waste — and the estimate updates itself as a rolling average, its origin
becomes observed, and the outcomes it came from are recorded. How many outcomes
that takes is your setting.

If a new measurement diverges from the current estimate by more than your
threshold, the update is **held as a proposal** instead of applied. A reading
ten times the estimate is far more likely to be a faulty sensor than a real
change, and a faulty sensor must not be able to reprice your catalogue.

While a proposal is pending:

- Pricing continues to use the current estimate.
- The figure is flagged as having a pending revision, so it is not silently
  diverging from what was observed.
- The proposal states the current estimate, the observed value, the divergence
  and the outcomes behind it, and you accept or reject it as a whole.

Rejecting a proposal does not switch the alert off. It will not be re-proposed
from the same outcomes, but a new recorded outcome can raise it again.

Only measurements work this way. A decision of yours is never updated by this
mechanism, whatever the divergence.

---

## Trying out a change before making it

Ask what a 20% filament price rise, or a marketplace raising its take, would do
to the catalogue — and see which products fall below a margin floor you set.

Because a catalogue sweep can take a while, it runs as a background job: the
request comes back immediately with a handle, and the result arrives when it is
ready. The job reports its state, and surfaces a partial or failed outcome
rather than appearing to hang. A larger catalogue takes longer; it does not fail.

**A scenario writes nothing.** No cost, no price, no provenance figure changes.
The result records the shock and the inputs it ran with, so a result you read
next week is not mistaken for today's figures.

---

## Who can change what

| Change | Required role |
|---|---|
| Labour rates, margin basis, machine cost policy, fee rules, target margin | Admin or owner |
| Print time, waste, batching, failure mode, finishing minutes | Member |
| Viewing any cost or margin | Any role, including viewer |

The split is between monetary policy and operational figures. The person who
knows how long a plate takes to prepare is not necessarily the person who sets
what an hour of their time is worth.

---

## A worked example

The acceptance case the engine is tested against, so you can check your own
figures against a known one. A 142 g single-colour part:

| Input | Value |
|---|---|
| Part weight | 142 g |
| Purge | 3 g |
| Print time | 9.5 h |
| Spool landed cost | CA$31.00 per 1000 g, 25 g unusable |
| Printer | CA$1,100 over 6,000 h, CA$220 maintenance reserve |
| Power | 95 W at CA$0.13/kWh |
| Labour | 15 min at risk, 5 min packing, at CA$25/h |
| Overhead | CA$180/month over 600 expected machine-hours |
| Packaging | CA$0.92 |
| Expected yield | 92%, per part |
| Prints per plate | 1 |

**Make-cost: CA$20.30.** Priced at CA$64.99 on a marketplace charging a
transaction percentage, processing, a regulatory fee and advertising at its
expected incidence, with CA$9.50 of postage paid and no shipping collected, the
margin is **35.3%** on the customer-total basis.

Asked the other way round — what price gives a 35% margin — the answer is
**CA$64.64** before any rounding rule applies.
