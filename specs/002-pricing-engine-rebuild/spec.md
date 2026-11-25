# Feature Specification: Pricing Engine Rebuild — Margins That Match Reality

**Feature Branch**: `002-pricing-engine-rebuild` *(spec directory; no git branch was created — the git extension hook is not installed)*

**Created**: 2026-10-11

**Status**: Draft

**Input**: User description: "Rebuild Batchivo's pricing and costing engine so reported margins reflect reality instead of an optimistic estimate." — full description in `notes/Refonte du moteur de tarification — Batchivo.md`

## Clarifications

### Session 2026-10-11

- Q: On what amount is margin percentage calculated — what is the denominator? → A: Make it a system setting and implement all three bases: total the customer paid (item price plus shipping revenue), item price alone, and net revenue after fees. Default to the customer total, which reproduces the acceptance scenario and preserves today's behaviour.
- Q: Does a 92% yield mean 8% of individual parts fail, or 8% of whole plates are lost? → A: Both, selected per printed item. Per-part is the default; a per-plate mode is available for items where one failure condemns the whole bed, and each mode is learned from production history separately.
- Q: Who may change policy levers — labor rates, margin basis, machine policy, fee rules, target margin? → A: Two tiers. Monetary policy requires admin or owner; operational item figures (print time, waste, batching, failure mode, finishing minutes) are editable by member; costs and margins are visible to all roles including viewer.
- Q: At what granularity are actually-charged fees recorded, given that automatic ledger reading is deferred? → A: Period totals per fee category per channel as the routine entry, with the option to record a specific order's actual fee when an anomaly is suspected. An order-level figure takes precedence and reduces the period's unallocated remainder, so nothing is double counted, and later automated ingestion adds order-level rows to the same record rather than requiring a migration.
- Q: Are the six fee bases sufficient, or must a rule's shape be widened before it is frozen? → A: Widen it now: every fee rule gains an optional minimum and maximum amount, and a seventh basis "per unit sold" is added. This covers capped final-value fees, "percentage but at least X" processing minimums, and per-unit charges that a per-order basis would undercount.
- Q: How does sales tax enter the margin calculation on the revenue side? → A: Margin is always computed on tax-exclusive amounts. Each channel carries a "who remits the sales tax" indicator — the marketplace under facilitator rules, or the operator. Either way tax is excluded from revenue; where the operator remits, it is tracked as a liability rather than income.
- Q: When telemetry observes a weight, print time or yield that differs from the estimate, does the system overwrite the estimate or propose the update? → A: Automatic while the divergence stays within a threshold the operator sets; held as a proposal for review beyond it, since an outlier usually means a faulty measurement rather than a real drift.
- Q: Where does the exchange rate used for a foreign-currency sale come from? → A: Fetched from a public rate service, cached, and frozen onto the order at sale. If the service is unreachable, the last known rate is used with its date, and the operator may enter a rate by hand. A dated stale rate is preferable to a blocked sale.
- Q: On a multi-spool purchase, how are inbound shipping and recoverable tax allocated to reach a per-gram cost? → A: Inbound shipping is allocated across the purchase in proportion to each spool's weight, and recoverable sales tax is excluded from cost. Weight rather than an even split, because weight is what drives the postage. This requires recording the purchase, not only the spool.
- Q: What response time is required for a calculation spanning the whole catalogue, such as a price shock scenario? → A: Run it as a background job: the request returns a handle and the result is delivered when ready. No catalogue-size ceiling, and no stored cost figures are introduced to make it fast.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - My own settings actually drive my numbers (Priority: P1)

The operator sets an hourly labor rate in settings. Today that figure is ignored and every cost is computed from a built-in default, so the number on screen belongs to nobody. The operator wants the figures they configured to be the figures used, and wants exactly one cost per product rather than two answers depending on which screen they opened.

**Why this priority**: Everything else in this feature builds on costs the operator believes. A more elaborate model computed from the wrong labor rate is worse than the current state, because it looks more credible. This story is also the smallest shippable slice: it changes no data model and delivers trust immediately.

**Independent Test**: Set the labor rate to a distinctive value, open a product's cost breakdown, and confirm the labor line reflects that rate. Compare the cost shown on the product list, the product detail and the pricing screen for the same product and confirm all three agree to the cent.

**Acceptance Scenarios**:

1. **Given** an operator whose configured labor rate differs from the system default, **When** they view any product's cost breakdown, **Then** the labor line is computed from their configured rate.
2. **Given** the same product viewed from the product list, the product detail and the channel pricing screen, **When** each shows a make-cost, **Then** all three show the same figure.
3. **Given** the labor rate correction changes previously reported costs, **When** the change is deployed, **Then** a per-product before/after report is available for review, and no product's cost changes for any reason other than the corrected rate.

---

### User Story 2 - A make-cost that includes the machine and the failures (Priority: P1)

A 9.5-hour unattended print consumes roughly 15 minutes of the operator's attention and 9.5 hours of a machine that is depreciating, drawing power and wearing out — and which cannot print anything else meanwhile. One print in twelve fails outright. The operator needs a make-cost that charges for occupied machine time, for purge and spool remainder, for the preparation that a plate needs once regardless of how many parts sit on it, and for the expected failure rate — applied only to the work actually at risk.

**Why this priority**: This is the largest single distortion in the current model after shipping. Without it, slow prints look as cheap as fast ones and the queue gets ordered backwards.

**Independent Test**: Seed the acceptance-scenario item and confirm the make-cost it reports, then vary print hours alone and confirm only the machine and overhead lines move.

**Acceptance Scenarios**:

1. **Given** the acceptance-scenario item, **When** its cost is computed, **Then** the make-cost is CA$20.30, broken into material, waste, machine, labor, overhead and packaging lines.
2. **Given** two items identical except that one prints in 2 hours and the other in 10, **When** both are costed, **Then** the 10-hour item carries roughly five times the machine and overhead charge.
3. **Given** an item with an expected yield below 100% in the default per-part failure mode, **When** its cost is computed, **Then** the failure premium is applied to material, machine, overhead and pre-packing labor, and **not** to packaging materials or packing labor.
3b. **Given** an item whose failure mode is per-plate, **When** its cost is computed, **Then** the premium reflects losing the whole plate's at-risk cost including its one-off preparation, and is therefore heavier than the per-part premium for the same yield figure.
3c. **Given** an item whose failure mode is switched, **When** its cost is recomputed, **Then** the yield figure observed under the previous mode is not reused as if it applied to the new one.
4. **Given** a plate holding 20 parts and a plate holding 1, **When** both are costed, **Then** per-plate preparation labor is divided across the plate's output while per-item labor is not.
5. **Given** an item whose spool has an unusable remainder and a purge allowance, **When** its material cost is computed, **Then** the per-gram cost reflects the usable weight only, and purge is a separate line from part weight.
5b. **Given** a purchase of four identical spools with one shipping charge, **When** landed cost is derived, **Then** the shipping is split evenly because the weights are equal, and the per-spool landed cost matches the acceptance scenario's CA$31.00.
5c. **Given** a purchase mixing one 250 g spool with three 1 kg spools, **When** landed cost is derived, **Then** the 250 g spool carries roughly a tenth of the shipping rather than a quarter of it.
5d. **Given** an operator who can recover sales tax and one who cannot, **When** landed cost is derived from the same purchase, **Then** tax is excluded for the first and included for the second.
6. **Given** a bundle containing other products, **When** it is costed, **Then** it continues to cost recursively, and a circular or excessively deep structure is reported as an error rather than computed.

---

### User Story 3 - A margin that survives contact with the marketplace (Priority: P1)

The operator sells on a marketplace that charges a transaction percentage on the item *and* on the shipping they collected, a payment-processing percentage plus a fixed amount, a regulatory percentage, an advertising fee that lands on some orders but not all, a per-listing fee and a monthly subscription — and then there is the postage actually paid. The operator needs all of that reflected in one margin figure, instead of a single blended percentage plus a fixed fee.

**Why this priority**: Shipping and the hidden fee layers together destroy more margin than every costing omission combined. It is separated from Story 2 only because it can ship and be verified on its own.

**Independent Test**: Configure the acceptance-scenario channel's fee rules and postage, then confirm the margin reported at the stated list price, and confirm that a fee charged on item-plus-shipping changes when shipping revenue changes.

**Acceptance Scenarios**:

1. **Given** the acceptance-scenario item and channel on the default margin basis, **When** the item is priced at CA$64.99, **Then** the reported margin is 35.3%, the basis is named alongside it, and the itemised fee list names each fee with the amount it contributed.
1b. **Given** the same item and price, **When** the operator switches the margin basis to item price alone or to net revenue after fees, **Then** the percentage changes accordingly, the profit amount does not, and the newly selected basis is named alongside the figure.
2. **Given** a fee rule charged on item-plus-shipping, **When** shipping revenue is collected on the order, **Then** the fee is computed on the combined amount and shipping revenue is never netted out before fees are applied.
3. **Given** a fee that applies to only a share of orders, **When** a planned margin is computed, **Then** the fee is included at its expected incidence, and the figure is labelled as an expectation rather than a charge.
4. **Given** postage paid and shipping revenue collected that differ, **When** the margin is reported, **Then** their difference appears as its own line and may be negative.
5. **Given** a channel with a monthly cost and per-listing fees, **When** a period's channel profitability is reported, **Then** those costs are absorbed over that period's actual order volume rather than ignored.
6. **Given** a channel with an expected discount rate and an expected refund rate, **When** a planned margin is computed, **Then** both reduce planned net revenue.
7. **Given** a fee rule with a maximum amount and an order large enough to exceed it, **When** fees are computed, **Then** the fee is charged at the cap and the itemised list states that the cap applied.
8. **Given** a fee rule charged per unit sold and an order line of three units, **When** fees are computed, **Then** the fee is charged three times, unlike a per-order fee which is charged once.
9. **Given** a channel where the marketplace collects and remits sales tax and another where the operator does, **When** margins are reported for an otherwise identical sale on each, **Then** both are computed tax-exclusive and the two percentages match.
10. **Given** a sale on a channel where the operator remits the tax, **When** the period is reported, **Then** the tax collected appears as a liability owed and never as revenue or profit.

---

### User Story 4 - Tell me the price, don't make me guess it (Priority: P2)

Today the operator types a price and reads a margin, then types another price. They want the inverse: state a target margin and receive the price that achieves it — correctly solved, since the percentage fees are charged on the very price being solved for.

**Why this priority**: High value and visible, but it is only trustworthy once Stories 2 and 3 produce real costs and real fees. Built earlier, it would confidently return the wrong price.

**Independent Test**: Ask for the acceptance scenario's target margin on the acceptance item and channel, and confirm the price returned.

**Acceptance Scenarios**:

1. **Given** the acceptance item and channel and a 35% target margin, **When** the operator asks for the required price, **Then** the system returns CA$64.64 before rounding.
2. **Given** a rounding rule and a free-shipping threshold configured on the channel, **When** a price is solved, **Then** the result is adjusted by the rounding rule and may snap to the threshold, and both adjustments are shown as such.
3. **Given** a solved price, **When** the operator inspects it, **Then every** input that produced it is listed, so the price can be explained without re-deriving it.
4. **Given** a target margin that no price can achieve because percentage fees plus the target reach or exceed the whole price, **When** the operator asks for a price, **Then** the system reports the target as unachievable and names the constraint, rather than returning a number.
5. **Given** a solved price, **When** it is returned, **Then** it is a proposal the operator applies or rejects — nothing is published to any channel automatically.

---

### User Story 5 - Settled orders keep the margin they had (Priority: P2)

Filament prices change, the operator gives themselves a raise, a marketplace revises its fee schedule. None of that may rewrite what last quarter earned. The operator needs a margin trend they can reason about.

**Why this priority**: Without it, every report built on history is quietly fiction. It is P2 rather than P1 only because it protects future reporting rather than correcting today's decisions.

**Independent Test**: Record an order, note its reported margin, change a spool price, a labor rate and a fee rule, then re-read the same order's margin.

**Acceptance Scenarios**:

1. **Given** an order line created at the moment of sale, **When** it is stored, **Then** it carries the cost breakdown, the price, the fees and the exchange rate as they stood, and these are never recomputed.
2. **Given** a settled order, **When** a spool price, a labor rate, an overhead setting or a fee rule changes afterwards, **Then** that order's reported margin is unchanged.
3. **Given** a product priced differently over time on the same channel, **When** an order from an earlier period is read, **Then** the price effective on that date is the one reported.
4. **Given** actual material use and actual production time reported after the fact, **When** they are recorded, **Then** they sit alongside the planned figures and the difference is reportable, without altering the snapshot.
5. **Given** a reconciled statement of what a marketplace actually charged, **When** the operator records a period total per fee category, **Then** it sits alongside the planned fees and the difference is reportable — whether reconciliation was manual or automated.
5b. **Given** a period total already recorded and one order that looks anomalous, **When** the operator records that order's actual fee, **Then** the order-level amount takes precedence, the period's unallocated remainder falls by that amount, and the total counted does not change.
5c. **Given** actual fees that were entered by hand, **When** any figure derived from them is displayed, **Then** it is labelled as entered, never as observed.

---

### User Story 6 - How much should I trust this number? (Priority: P3)

Some figures in a cost are facts the system observed, some the operator measured once on a kitchen scale, some are policy decisions, and some are guesses nobody has revisited in a year. The operator wants to see which is which before betting a price on it.

**Why this priority**: This is the differentiator no competitor offers, but it is only meaningful once there are real observed values to contrast with assumed ones.

**Independent Test**: Open a cost breakdown and confirm every line names its origin and its date, and that the breakdown states the observed share of the total.

**Acceptance Scenarios**:

1. **Given** any numeric input to a cost, **When** it is displayed, **Then** it names its origin, the date it was set or last observed, and a confidence where one is meaningful.
2. **Given** a cost breakdown, **When** it is displayed, **Then** it states what share of the total is observed versus assumed.
3. **Given** a figure the operator decided, **When** any automated process runs, **Then** that figure is never overwritten.
4. **Given** a figure observed from its source, **When** the operator views it, **Then** it is read-only and refreshed only from that source.
5. **Given** a hand-measured figure older than its staleness threshold, **When** it is displayed, **Then** it is flagged as stale and still shows its last value rather than an empty field.
6. **Given** a hand-measured figure whose source later becomes instrumented, **When** observation begins, **Then** the figure becomes observed with no data loss and no manual re-entry.
6b. **Given** enough recorded outcomes and an observed value close to the current estimate, **When** the estimate is refreshed, **Then** it updates on its own and its origin becomes observed, dated, with the outcomes it came from.
6c. **Given** an observed value diverging from the estimate beyond the operator's threshold — a weight that doubles, for instance — **When** the update is evaluated, **Then** it is held as a proposal showing both values and the divergence, pricing keeps using the current estimate, and the figure is flagged as having a pending revision.
6d. **Given** a proposal the operator rejects, **When** the same outcomes are reconsidered, **Then** it is not proposed again, while a later proposal from new outcomes is still raised.
7. **Given** a market judgement such as what a customer will pay, **When** the operator needs it, **Then** the system shows margin across a ladder of prices and the operator chooses — the system never stores or computes a single such number.
8. **Given** that marketplace fee amounts are entered rather than read from a statement, **When** a fee line is displayed, **Then** it is not labelled as observed.

---

### User Story 7 - Order the queue by what actually pays (Priority: P3)

In a print shop the binding constraint is machine time, not money. Ranked by margin percentage, a 2% margin on a 40-hour print can outrank a healthy margin on a 2-hour one. The operator needs profit per machine-hour as a headline figure, and wants to ask what a price shock would do to the catalogue.

**Why this priority**: Decision-support that is valuable but useless until machine time is costed, which makes it strictly dependent on Story 2.

**Independent Test**: Confirm the profit per machine-hour reported for the acceptance scenario, and run a material-price shock across the catalogue.

**Acceptance Scenarios**:

1. **Given** the acceptance item at CA$64.99, **When** its profitability is reported, **Then** profit per machine-hour is CA$2.41 and is presented as a first-class figure beside margin percentage.
2. **Given** a catalogue of products, **When** the operator applies a shock such as a material price rise or a fee increase, **Then** the request is acknowledged at once, the calculation runs in the background, and the finished result lists which products fall below the operator's margin floor without any stored figure having changed.
2b. **Given** a scenario result read some days later, **When** the operator opens it, **Then** it states the shock and the inputs it was run with, so it is not mistaken for current figures.
3. **Given** a product whose realised margin diverges from plan beyond a threshold the operator set, **When** the divergence is detected, **Then** the operator is alerted and told which lines moved.

---

### Edge Cases

- **Yield of zero or 100%**: a yield of 100% must be a no-op on cost under either failure mode; a yield of zero is rejected as a configuration error rather than producing an infinite cost.
- **Per-plate failure mode on a single-part plate**: with one part per plate the two modes must agree, which is the boundary case that proves the formulas consistent.
- **Yield observed under one failure mode, then the mode changes**: the previously observed figure is not reused (see FR-015d); the item reverts to its assumed yield until history accumulates under the new mode.
- **Fewer recorded outcomes than the minimum**: the estimate stays as it was, labelled assumed, rather than being updated from a single run.
- **A sensor reporting an implausible value**: caught by the divergence threshold and held as a proposal (FR-042b), so one bad reading cannot move a price.
- **Several pending proposals on the same figure**: the latest supersedes the earlier ones rather than queueing, so the operator never reviews a stale divergence.
- **Expected capacity of zero**: overhead absorbed per machine-hour cannot be computed from zero expected machine-hours; the system reports the misconfiguration rather than dividing.
- **Unachievable target margin**: percentage fees plus target margin reaching 100% leaves no price that works (see US4 scenario 4).
- **Capped percentage fee inside the price solver**: a cap makes the fee stop growing with price, so the solver must not assume every percentage fee scales with the price it is solving for; it must detect when a cap binds and solve on the remaining uncapped portion.
- **A purchase whose spool weights are unknown**: shipping cannot be allocated by weight; the system falls back to an even split and says it did, rather than refusing the purchase.
- **A spool added to a purchase after its shipping was already allocated**: the allocation is recomputed for every spool in that purchase, and spools already consumed keep the cost snapshot they were consumed at.
- **Zero-hour or missing print time**: an item with no recorded print time carries no machine or per-hour overhead charge and is flagged as incompletely costed rather than silently costed at zero.
- **Fee rules with overlapping or gapped effective dates**: overlapping rules of the same kind on one channel are rejected at save time; a date with no applicable rule is reported rather than treated as zero fees.
- **Per-month and per-listing fees in a period with no orders**: absorption over zero volume is reported as unabsorbed cost, not as an infinite per-order fee.
- **Order-level actual fees exceeding the recorded period total**: the remainder cannot go negative; the system reports the inconsistency so the operator fixes the period total rather than silently absorbing it.
- **An order spanning two reconciliation periods**: the order-level actual belongs to the period its statement assigned it to, not the period it was placed in.
- **A channel where the marketplace collects tax and one where the operator does**: margins from both remain directly comparable, because both are computed tax-exclusive.
- **A fee the marketplace charged on a tax-inclusive total**: the fee is recorded as charged, while the revenue it was charged on is still reported tax-exclusive, and the discrepancy is visible rather than silently absorbed.
- **A tax rate that changes mid-period**: tax recorded on an order uses the rate in effect at sale, like every other snapshot figure.
- **Free shipping with shipping revenue of zero**: fees charged on item-plus-shipping fall back to the item amount; the postage paid still appears as a negative shipping line.
- **Refund or partial refund after settlement**: recorded against the settled order as an actual, reducing realised margin without rewriting the snapshot.
- **Cross-currency order**: the rate used is the one recorded at sale, never today's rate, including when the order is re-read years later.
- **Rate service unreachable at the moment of sale**: the sale proceeds on the last known rate, dated and visible as stale; it is never blocked and never silently defaults to 1:1.
- **No rate has ever been fetched for a currency pair**: the operator is asked for one rather than the sale proceeding on an implied parity.
- **Bundle containing itself, directly or transitively**: reported as an error, as today.
- **A product with no price on a channel it is listed on**: reported as unpriced rather than margin-zero.
- **A member edits an item figure that feeds a price**: permitted (FR-007b), and the resulting cost change is attributed to them in the figure's provenance, so a margin shift is traceable without granting them policy rights.
- **A viewer opens a pricing screen**: sees every cost and margin, and every editable control is unavailable rather than hidden, so the figures remain explainable.
- **An input beneath a product in its bill of materials changes**: any derived cost figure already computed must not be served afterwards.
- **An input changes while a catalogue-wide job is running**: the job's result reports the inputs it used (FR-044c) rather than mixing figures from before and after the change.
- **A catalogue-wide job fails partway**: the partial outcome and the failure are both reported; the job never presents an incomplete list as if it were complete.
- **Quantity-break boundaries**: the price at exactly the break quantity is unambiguous, and overlapping tiers are rejected at save time.
- **Margin basis changed mid-history**: a report spanning the change must label each period's percentages with the basis that produced them rather than restating earlier orders, and must not sum or average percentages across bases.
- **Net-revenue basis with fees equal to revenue**: when the selected basis is net revenue after fees and fees consume the whole amount, the percentage is undefined; the system reports it as such rather than dividing by zero.

## Requirements *(mandatory)*

### Functional Requirements

#### Input ownership

- **FR-001**: Every numeric input to a cost or price MUST carry its origin (an operator decision, a fact observed from a source, a fact measured once by hand, or an assumption), the date it was set or last observed, and a confidence where confidence is meaningful.
- **FR-002**: Operator decisions MUST be editable and MUST never be overwritten by any automated process. These include: target margin, margin basis, labor rates, machine-life and maintenance policy, overhead absorption method and expected capacity, batching quantity, finishing standard, discount policy, price rounding rule, free-shipping threshold, marketplace advertising opt-in, and final price.
- **FR-003**: Operator decisions MUST be versioned with effective dates, so that a past figure remains readable after the policy changes.
- **FR-004**: Observed facts MUST be read-only to the operator and refreshed only from their source.
- **FR-005**: Hand-measured facts MUST be editable, and the system MUST flag one as stale past a threshold rather than presenting an empty field.
- **FR-006**: A hand-measured input MUST be able to become an observed one when its source is instrumented, with no data loss and no manual re-entry.
- **FR-007**: Market judgements (what a customer will pay, competitor prices, demand) MUST NOT be stored or computed as a single number. Where one is needed, the system MUST present margin across a ladder of prices for the operator to choose from.
- **FR-007a**: Changing monetary policy MUST require an administrator or owner. This covers labor rates, margin basis, target margin, fee rules, channel economics, the overhead pool and absorption method, machine cost policy, discount policy, rounding rule and free-shipping threshold.
- **FR-007b**: Operational figures of a printed item — print time, waste allowance, batching quantity, failure mode, finishing and handling minutes, measured packaging quantities — MUST be editable by a member, since these are measurements rather than decisions.
- **FR-007c**: Costs, margins and cost breakdowns MUST be visible to every role including a viewer; visibility is never restricted by role, only editing is.
- **FR-007d**: An attempt to change monetary policy without sufficient role MUST be refused, and MUST leave the figure and its provenance untouched.

#### Cost of a printed item

- **FR-008**: Material cost MUST derive from a landed per-gram spool cost accounting for purchase price, inbound shipping, recoverable sales tax, and the unusable remainder of the spool.
- **FR-008a**: A purchase covering several spools MUST be recordable as a purchase, carrying its total inbound shipping and its tax, so that a landed cost can be derived rather than typed.
- **FR-008b**: Inbound shipping MUST be allocated across a purchase's spools in proportion to each spool's weight.
- **FR-008c**: Recoverable sales tax MUST be excluded from landed cost; non-recoverable tax MUST be included. Whether tax is recoverable MUST be an operator setting, since it depends on their tax registration.
- **FR-008d**: A landed per-gram cost MUST be derived from the usable weight — nominal weight less the measured unusable remainder — never from the nominal weight.
- **FR-008e**: A spool recorded without a parent purchase MUST remain valid, taking its cost from its own price with no allocated shipping, so existing spool records keep working.
- **FR-008f**: A landed cost MUST show how it was derived — purchase price, allocated shipping, tax treatment, usable weight — so a per-gram figure is explainable without recomputing it.
- **FR-009**: Purge, priming and colour-change waste MUST be costed as a line separate from part weight.
- **FR-010**: Machine occupancy MUST be costed per hour, derived from depreciation over expected life, a maintenance reserve, and measured power draw at the operator's electricity rate.
- **FR-011**: Machine rate MUST be settable per machine, and an item MUST be costed at the rate of the machine it is planned on, falling back to a default rate when none is assigned.
- **FR-012**: Labor MUST be split into a fixed per-plate component and a variable per-item component, and into print-handling versus finishing, which may carry different rates.
- **FR-013**: Per-plate labor MUST be divided across the plate's output; per-item labor MUST NOT be.
- **FR-014**: Overhead MUST be absorbable per machine-hour by default, from an overhead pool divided by expected monthly capacity, with a percentage-of-cost method remaining available as an option.
- **FR-015**: Expected yield MUST raise cost for the portion of work exposed to failure, and MUST NOT raise it for packaging materials or packing labor.
- **FR-015a**: Each printed item MUST declare its failure mode: per-part, where parts fail independently, or per-plate, where one failure condemns the whole plate. Per-part MUST be the default.
- **FR-015b**: Under the per-part mode, the failure premium MUST be applied to the at-risk portion of a single part's cost.
- **FR-015c**: Under the per-plate mode, the failure premium MUST account for the whole plate's at-risk cost being lost, including per-plate preparation labor, and MUST therefore scale with how many parts the plate carries.
- **FR-015d**: Observed yield MUST be learned separately for each mode from production history, and a mode change MUST NOT carry the other mode's observed figure over as if it applied.
- **FR-015e**: A cost breakdown MUST name which failure mode produced its premium, since the same yield figure means different things under each.
- **FR-016**: Packaging materials MUST be a cost line on every physical order, and packing labor MUST be distinguishable from finishing labor.
- **FR-017**: Bundles MUST continue to be costed recursively, retaining cycle detection and the depth limit.
- **FR-018**: A cost breakdown MUST itemise every line that contributed to it, each with its origin per FR-001.
- **FR-019**: An item missing an input needed for a line (print time, machine rate, yield) MUST be reported as incompletely costed rather than costed as if that line were zero.

#### Price, fees and net revenue

- **FR-020**: Each sales channel MUST own an ordered list of fee rules.
- **FR-021**: Each fee rule MUST state what it is charged on — item subtotal, item plus shipping, order total, per listing, per order, per unit sold, or per month — together with a rate, a fixed amount, and, for fees applied to only some orders, the share of orders affected.
- **FR-021a**: A fee rule charged per unit sold MUST multiply by the quantity on the order line, distinct from a per-order fee which is charged once.
- **FR-021b**: Each fee rule MUST support an optional minimum and maximum amount, applied to the amount the rule computes. This expresses a capped final-value fee and a "percentage but at least X" processing minimum.
- **FR-021c**: Where a minimum or maximum changed the amount a rule would otherwise have charged, the itemised fee list MUST say so, so a capped fee is never mistaken for a miscalculated one.
- **FR-021d**: A rule whose minimum exceeds its maximum MUST be rejected at save time.
- **FR-022**: Each fee rule MUST carry effective dates, and the system MUST reject overlapping rules of the same kind on one channel.
- **FR-023**: Fees charged on shipping revenue MUST be computed on it; shipping revenue MUST NOT be netted out before fees are applied.
- **FR-024**: Postage paid and shipping revenue collected MUST be separate figures, and their difference MUST be reported as its own margin line, positive or negative.
- **FR-025**: Periodic and per-listing channel costs MUST be absorbed over actual order volume in a channel profitability view.
- **FR-026**: Expected discounts and an expected refund rate MUST reduce planned net revenue.
- **FR-027**: Quantity breaks MUST be expressible per channel, keyed on a minimum quantity, with overlapping tiers rejected at save time.
- **FR-028**: Prices and costs MUST carry a currency, and a cross-currency sale MUST record the rate used.
- **FR-028a**: Margin MUST always be computed on tax-exclusive amounts, on every channel and under every margin basis.
- **FR-028b**: Each channel MUST declare who remits sales tax on its sales — the marketplace or the operator.
- **FR-028c**: Sales tax MUST NOT be counted as revenue in any margin or profitability figure, regardless of who remits it.
- **FR-028d**: Where the operator remits the tax, the amount collected MUST be tracked as a liability, distinct from income, and reportable per period.
- **FR-028e**: Where a recorded amount is tax-inclusive — as a marketplace statement typically shows it — the system MUST make the tax-exclusive amount it derived visible, so a reconciliation against the statement is possible without re-deriving it by hand.
- **FR-028f**: Exchange rates MUST be obtained from an external rate service, reused for further sales on the same day rather than re-requested per order, and frozen onto the order at the moment of sale.
- **FR-028g**: Where the rate service is unreachable, the most recent known rate MUST be used, and the figure MUST show the date that rate was obtained, so a stale rate is visible rather than silent.
- **FR-028h**: The operator MUST be able to enter a rate by hand, which overrides the fetched rate and is recorded with its own origin.
- **FR-028i**: A sale MUST NOT be blocked by rate-service unavailability.
- **FR-028j**: A rate frozen onto an order MUST NOT be revised when a newer or more accurate rate becomes known; the difference, where it matters, is reported as a variance rather than a correction (consistent with FR-037).
- **FR-029**: A fee applied at an expected incidence MUST be labelled as an expectation, distinct from an amount actually charged.
- **FR-030**: Existing single-percentage-plus-fixed channel configurations MUST continue to produce the same fee amounts after migration, expressed as equivalent fee rules.
- **FR-031**: The margin basis — the amount the margin percentage is calculated against — MUST be an operator setting offering all three of: the total the customer paid (item price plus shipping revenue collected), the item price alone, and net revenue after fees.
- **FR-031a**: The default margin basis MUST be the total the customer paid, so that behaviour matches today's definition and the acceptance scenario out of the box.
- **FR-031b**: Every reported margin percentage MUST state which basis produced it, so that two percentages are never compared without knowing they share a basis.
- **FR-031c**: Changing the margin basis MUST NOT alter any stored figure, any make-cost or any profit amount — only the percentage derived from them.
- **FR-031d**: A settled order's margin percentage MUST be reported on the basis in effect when it was sold; changing the setting afterwards MUST NOT restate history (consistent with FR-038).

#### Target-margin solving

- **FR-032**: Given a product, a channel and a target margin, the system MUST return the list price that achieves it, solving for the price on which percentage fees are themselves charged, on the margin basis in effect (FR-031).
- **FR-032a**: The solver MUST account for fee minimums and maximums, which make a fee stop scaling with price, and MUST report which caps or floors were binding at the price it returned.
- **FR-033**: The solved price MUST be adjusted by the operator's rounding rule and MAY snap to a channel's free-shipping threshold, with each adjustment shown as such.
- **FR-034**: The solver MUST report the inputs that produced its answer.
- **FR-035**: A target margin that no price can achieve MUST be reported as unachievable, naming the binding constraint.

#### History and truth

- **FR-036**: At the moment of sale, an order line MUST record the cost breakdown, the price, the fees and the exchange rate as they stood.
- **FR-037**: Figures recorded per FR-036 MUST never be recomputed.
- **FR-038**: Changing a spool price, a labor rate, an overhead setting or a fee rule MUST NOT alter any settled order's reported margin.
- **FR-039**: A product's price on a channel MUST be readable as at a date, so that an order reports the price effective when it was placed.
- **FR-040**: Actual material use and actual production time known after the fact MUST be recorded alongside the planned figures, with the difference reportable.
- **FR-041**: Actual fees from a reconciled statement MUST be recordable alongside the planned fees, with the difference reportable, whether reconciliation was manual or automated.
- **FR-041a**: Actual fees MUST be recordable as a period total per fee category per channel, which is the routine path while reconciliation is manual.
- **FR-041b**: Actual fees MUST also be recordable against an individual order for a given fee category, for use when a specific order looks anomalous.
- **FR-041c**: Where both exist for the same period and category, order-level amounts MUST take precedence and MUST reduce the period's unallocated remainder, so no amount is counted twice.
- **FR-041d**: A reconciliation view MUST show, per channel and period, the planned fee total, the recorded actual total, the unallocated remainder, and the difference against plan.
- **FR-041e**: Recorded actual fees MUST carry their origin as entered rather than observed (FR-001), and MUST never be presented as an observed figure until they come from an automated source.
- **FR-042**: Observed outcomes MUST update the estimates used for future pricing, and the operator MUST be alerted when a product's realised margin diverges from plan beyond a threshold they set.
- **FR-042a**: An observed measurement MUST update its estimate automatically, as a rolling average, once a minimum number of recorded outcomes is reached. The minimum MUST be an operator setting.
- **FR-042b**: Where an observed measurement diverges from the current estimate by more than an operator-set threshold, the update MUST be held as a proposal for review instead of being applied, because an outlier of that size usually indicates a faulty measurement.
- **FR-042c**: A held proposal MUST state the current estimate, the observed value, the divergence and the outcomes it came from, and MUST be acceptable or rejectable as a whole.
- **FR-042d**: A rejected proposal MUST NOT be re-proposed from the same outcomes, and MUST NOT suppress a later proposal arising from new ones.
- **FR-042e**: While a proposal is pending, pricing MUST continue to use the current estimate, and the figure MUST be flagged as having a pending revision rather than silently diverging from observation.
- **FR-042f**: Applying an update — automatically or on acceptance — MUST set the figure's origin to observed and record the date and the outcomes it was derived from.
- **FR-042g**: Automatic updating MUST apply only to measurements. An operator decision MUST never be updated by this mechanism, whatever the divergence (FR-002).

#### Reporting

- **FR-043**: Profit per machine-hour MUST be a first-class reported figure alongside margin percentage.
- **FR-044**: The operator MUST be able to apply a shock — a material price rise, a fee increase — and see which products fall below a margin floor they set, without any stored figure changing.
- **FR-044a**: A catalogue-wide calculation MUST run as a background job: the request returns a handle immediately, and the result is retrievable when ready.
- **FR-044b**: A running job MUST report its state, and MUST surface a partial or failed outcome rather than appearing to hang.
- **FR-044c**: A job's result MUST state the inputs and the shock it was run with, so a result read later is not mistaken for current figures.
- **FR-044d**: A scenario job MUST NOT write any cost, price or provenance figure.
- **FR-044e**: Catalogue size MUST NOT be capped by this feature; a larger catalogue takes longer rather than failing.
- **FR-045**: A channel profitability view MUST report a period's realised margin after absorbing that channel's periodic costs.
- **FR-046**: A cost breakdown MUST state what share of its total is observed versus assumed.

#### Correctness

- **FR-047**: Monetary values MUST be computed with exact decimal arithmetic end to end; rounding MUST occur only for display, never between intermediate steps.
- **FR-048**: There MUST be exactly one implementation of the cost calculation. A second, parallel implementation is a defect regardless of whether its output currently agrees.
- **FR-049**: A derived or cached cost figure MUST NOT be served after any input beneath it in the bill of materials has changed, including through nested bundles.
- **FR-050**: Migration MUST preserve every existing product's computed cost except where a newly introduced line, or the correction of the ignored labor rate, is the intended cause of the change.
- **FR-051**: The per-product difference caused by migration MUST be reportable and reviewable before the migration is accepted.
- **FR-052**: The superseded model's reported margin MUST remain reproducible for comparison during migration, and MUST be retired afterwards.

### Key Entities *(include if feature involves data)*

- **Filament purchase**: a buying event covering one or more spools — supplier, date, total inbound shipping, tax and whether it is recoverable — from which each spool's landed per-gram cost is derived by weight.
- **Machine cost policy**: per machine — purchase price, expected lifetime hours, maintenance reserve, measured power draw — yielding an hourly occupancy rate. Attaches to the existing printer record.
- **Printed item cost profile**: per printed item — part weight, waste allowance, print time, expected yield, failure mode (per-part or per-plate), per-plate and per-item labor, finishing time, batching quantity, and the machine it is planned on.
- **Overhead policy**: per operator — absorption method, overhead pool, expected monthly capacity.
- **Labor rate policy**: per operator — print-handling rate and finishing rate, each effective from a date.
- **Fee rule**: per channel — name, what it is charged on (one of seven bases, including per unit sold), rate, fixed amount, optional minimum and maximum amount, incidence share, effective dates, order of application.
- **Shipping profile**: postage cost by destination zone and weight bracket; distinct from shipping revenue collected and from packaging materials.
- **Channel economics**: per channel — currency, periodic cost, per-listing cost, expected discount rate, expected refund rate, free-shipping threshold, rounding rule, advertising opt-in, and who remits sales tax.
- **Sales tax record**: tax collected on an order and who is responsible for remitting it; a liability when the operator remits, never revenue.
- **Margin policy**: the operator's chosen margin basis (customer total, item price alone, or net revenue after fees), effective from a date, recorded on an order line's snapshot at sale.
- **Exchange rate record**: currency pair, rate, the date it was obtained, and its origin (fetched from the rate service or entered by the operator); frozen onto an order at sale.
- **Price point**: a product's price on a channel, effective from a date, optionally tiered by minimum quantity.
- **Order line snapshot**: the cost breakdown, price, itemised fees and exchange rate as at the moment of sale — written once.
- **Actuals record**: material used, production time, fees charged, refunds — recorded against an order or production run after the fact, never overwriting the snapshot. Fee actuals attach either to a channel period or to a single order, with order-level amounts taking precedence over the period's remainder.
- **Input provenance**: for each numeric input — origin, effective or observed date, confidence, who measured or decided it, and the role that authorised a policy change.
- **Scenario run**: a requested catalogue-wide calculation — the shock applied, the inputs used, its state, and the resulting list of products below the margin floor. Holds no authoritative cost or price.
- **Pending estimate revision**: an observed value held for review because it diverges beyond the threshold — current estimate, observed value, divergence, the outcomes behind it, and its state (pending, accepted, rejected).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a settled order, the margin the system reports is within 2 percentage points of the margin computed from what was actually received and actually paid.
- **SC-002**: On the default margin basis, the acceptance-scenario item reports a make-cost of CA$20.30, a margin of 35.3% at a list price of CA$64.99, profit per machine-hour of CA$2.41, and a required price of CA$64.64 for a 35% target margin.
- **SC-002a**: Switching the margin basis changes only the reported percentage: the make-cost stays CA$20.30 and the profit amount stays CA$22.92 under all three bases.
- **SC-002b**: For an item printed one per plate, the per-part and per-plate failure modes report the same make-cost; for the same item batched more than one per plate, the per-plate mode reports a higher one.
- **SC-003**: After changing a spool price, a labor rate, an overhead setting and a fee rule, zero settled orders report a different margin than before the change.
- **SC-004**: 100% of lines in a cost breakdown display an origin and a date, and the breakdown states its observed share.
- **SC-005**: An operator obtains the price for a target margin in a single request, with no manual trial and error.
- **SC-006**: An operator requests a whole-catalogue shock in a single action, receives an acknowledgement immediately, and can see the job's state until the result is available; the catalogue's size changes how long it takes, never whether it succeeds.
- **SC-007**: Before migration is accepted, a per-product report shows every cost that changed and attributes each change to a specific newly introduced line or to the labor-rate correction; no change is unattributed.
- **SC-008**: The same product queried from any screen reports one identical make-cost.
- **SC-009**: For a channel with any fee charged on item-plus-shipping, the fee the system plans and the fee the marketplace statement shows agree within 1% of the fee amount, once the operator's entered rates match the current schedule.
- **SC-009a**: Two otherwise identical sales, one on a channel where the marketplace remits sales tax and one where the operator does, report the same margin percentage.
- **SC-010**: Of the make-cost lines for an item printed on an instrumented machine, at least 70% carry an observed origin (part weight, print time, yield, power draw).

## Assumptions

- **Margin basis**: resolved by clarification — it is an operator setting with all three bases implemented, defaulting to the total the customer paid (see FR-031 and the Clarifications section). The target-margin solver solves against whichever basis is in effect, so a target of 35% means 35% on that basis.
- **Marketplace percentages are fixtures, not a schedule**: the rates in the acceptance scenario are illustrative. They are operator-entered, carry an effective date and an owner, and nothing corrects them automatically.
- **One new external dependency is accepted**: a public exchange-rate service, used only for cross-currency sales, with graceful degradation to the last known or a hand-entered rate (FR-028f–j). It is the only outbound dependency this feature adds.
- **Automatic ledger ingestion is out of scope** (see Non-goals in the source document). Actual fees are reconciled against a periodic statement export by hand. The design must leave room for automated ingestion later without a migration, and must never label an entered fee as observed.
- **No automatic publishing of prices**: a solved price is a proposal. Writing prices to connected channels is a separate, operator-initiated action and is out of scope here.
- **Existing foundations are reused, not rebuilt**: the recursive bill of materials with cycle detection, per-channel price rows, the packaging cost and packaging-consumable path, the per-machine item configuration that already records print time and plate quantity, the printer records, the production-run actuals, and the printer telemetry adapters.
- **Multi-tenant isolation is unchanged**: every new record is tenant-scoped under the existing isolation rules.
- **Scope is the management console**: the storefront continues to read whatever price the operator has published. Customer-facing shipping quotes are a separate concern from the postage cost recorded here.
- **Staleness thresholds and alert thresholds are operator settings**, not fixed values. Defaults: a hand-measured figure is flagged stale after 180 days, and a realised margin is alerted when it diverges from plan by more than 5 percentage points — matching the pattern of the minimum-outcomes default of 5.
- **Sales tax is tracked, not administered**: the system records what was collected, by whom it is remitted, and what is owed for a period. Computing tax rates by jurisdiction, producing filings or replacing accounting software remain out of scope (FR-028b–e).
- **The constitution is an unfilled template** (`.specify/memory/constitution.md` contains placeholders), so no project principles were applied as constraints. Worth filling before `/speckit-plan`, given this feature's correctness requirements.

## Deferred to `/speckit-plan`

One decision remains open, and it is deliberately a planning decision rather than a requirement, since no behaviour in this spec depends on which way it goes:

1. **How provenance is recorded** — attached to each figure individually, or held once per figure in a shared register — and how operator policy values move out of today's catch-all settings record into dated ones. FR-001 through FR-007d state what the operator must see and who may change what; the shape that satisfies them belongs to the plan.

Resolved in the clarification session of 2026-10-11, and no longer open: the margin basis (FR-031 through FR-031d), the at-risk boundary and failure mode (FR-015 through FR-015e), the fee-rule shape (FR-021 through FR-021d), the permission tiers (FR-007a through FR-007d), the fee-actuals granularity (FR-041a through FR-041e), sales-tax treatment (FR-028a through FR-028e), the exchange-rate source (FR-028f through FR-028j), the estimate-update policy (FR-042a through FR-042g), landed spool cost allocation (FR-008a through FR-008f) and catalogue-wide execution (FR-044a through FR-044e).

Still outstanding, and judged low enough impact to settle during planning or after: where a divergence alert surfaces (in-app, email, or both — the project already has an email service and a task queue), the shape of the price ladder in FR-007, and accessibility or localisation specifics, which follow the existing console's conventions.
