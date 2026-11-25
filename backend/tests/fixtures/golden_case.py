"""The golden acceptance case — **inputs only**.

Every expected figure in the feature (the CA$20.30 make-cost, the 35.3% margin
at CA$64.99, the CA$64.64 solved price, the CA$2.41 profit per machine-hour) is
recomputed from these inputs by the test that asserts it, in one unrounded
chain, rounded only for the assertion.

No expected value lives in this file, deliberately. A fixture that carries both
the inputs and the answers lets a wrong answer be pasted in beside the inputs
that contradict it, which is exactly the failure mode the Constitution's
Development Workflow section names: a suite that turns green by restoring a
defect is a failed change.

Currency is CAD throughout. All figures are `Decimal` — never `float`
(Constitution IV).
"""

from decimal import Decimal
from typing import Final

# --------------------------------------------------------------------------
# The printed part
# --------------------------------------------------------------------------

#: Filament that ends up in the part itself.
PART_GRAMS: Final = Decimal("142")

#: Filament purged or wiped during the print. Consumed, never sold.
PURGE_GRAMS: Final = Decimal("3")

#: Wall-clock machine occupancy for the print.
PRINT_HOURS: Final = Decimal("9.5")

#: One print per plate, so the per-part and per-plate failure modes must agree
#: exactly on this case (research.md D3).
PRINTS_PER_PLATE: Final = 1

#: Share of starts that reach a sellable part.
EXPECTED_YIELD: Final = Decimal("0.92")

# --------------------------------------------------------------------------
# The filament, as landed
# --------------------------------------------------------------------------

#: Landed cost of a nominal 1 kg spool: purchase price plus allocated inbound
#: shipping plus non-recoverable tax.
SPOOL_LANDED_COST: Final = Decimal("31.00")

#: The weight that cost was quoted against.
SPOOL_NOMINAL_GRAMS: Final = Decimal("1000")

#: Filament left on the core that cannot be printed. The usable weight is the
#: nominal weight less this, which is what the per-gram cost divides by.
SPOOL_UNUSABLE_REMAINDER_GRAMS: Final = Decimal("25")

# --------------------------------------------------------------------------
# The machine
# --------------------------------------------------------------------------

PRINTER_PURCHASE_PRICE: Final = Decimal("1100.00")
PRINTER_EXPECTED_LIFETIME_HOURS: Final = 6000
PRINTER_MAINTENANCE_RESERVE_TOTAL: Final = Decimal("220.00")

#: Measured draw at the wall, not the nameplate rating.
PRINTER_MEASURED_WATTS: Final = Decimal("95")

ELECTRICITY_RATE_PER_KWH: Final = Decimal("0.13")

# --------------------------------------------------------------------------
# Labor
# --------------------------------------------------------------------------

LABOR_RATE_PER_HOUR: Final = Decimal("25.00")

#: Handling and finishing — done on a part that may still fail, so this is at
#: risk and the failure premium reaches it.
AT_RISK_LABOR_MINUTES: Final = Decimal("15")

#: Packing — done on a part already known good, so no failure premium applies.
PACKING_LABOR_MINUTES: Final = Decimal("5")

# --------------------------------------------------------------------------
# Overhead, absorbed per machine-hour
# --------------------------------------------------------------------------

MONTHLY_OVERHEAD_POOL: Final = Decimal("180.00")
EXPECTED_MONTHLY_MACHINE_HOURS: Final = Decimal("600")

# --------------------------------------------------------------------------
# Packaging — materials consumed after the part is good, never at risk
# --------------------------------------------------------------------------

PACKAGING_COST: Final = Decimal("0.92")

# --------------------------------------------------------------------------
# The channel side of the case
# --------------------------------------------------------------------------

#: The list price the golden margin is asserted at.
LIST_PRICE: Final = Decimal("64.99")

#: The margin the solver is asked to hit.
TARGET_MARGIN_PCT: Final = Decimal("35")


GOLDEN_CASE_INPUTS: Final[dict[str, Decimal | int]] = {
    "part_grams": PART_GRAMS,
    "purge_grams": PURGE_GRAMS,
    "print_hours": PRINT_HOURS,
    "prints_per_plate": PRINTS_PER_PLATE,
    "expected_yield": EXPECTED_YIELD,
    "spool_landed_cost": SPOOL_LANDED_COST,
    "spool_nominal_grams": SPOOL_NOMINAL_GRAMS,
    "spool_unusable_remainder_grams": SPOOL_UNUSABLE_REMAINDER_GRAMS,
    "printer_purchase_price": PRINTER_PURCHASE_PRICE,
    "printer_expected_lifetime_hours": PRINTER_EXPECTED_LIFETIME_HOURS,
    "printer_maintenance_reserve_total": PRINTER_MAINTENANCE_RESERVE_TOTAL,
    "printer_measured_watts": PRINTER_MEASURED_WATTS,
    "electricity_rate_per_kwh": ELECTRICITY_RATE_PER_KWH,
    "labor_rate_per_hour": LABOR_RATE_PER_HOUR,
    "at_risk_labor_minutes": AT_RISK_LABOR_MINUTES,
    "packing_labor_minutes": PACKING_LABOR_MINUTES,
    "monthly_overhead_pool": MONTHLY_OVERHEAD_POOL,
    "expected_monthly_machine_hours": EXPECTED_MONTHLY_MACHINE_HOURS,
    "packaging_cost": PACKAGING_COST,
    "list_price": LIST_PRICE,
    "target_margin_pct": TARGET_MARGIN_PCT,
}


# --------------------------------------------------------------------------
# The channel the golden case sells on (User Story 3)
#
# research.md D10 pins this side of the case by its aggregate: a variable rate
# of 12.5%, a 2.5% refund reserve, CA$2.52 of fixed fees, free shipping, and
# costs of CA$29.80 -- which is the CA$20.30 make-cost plus CA$9.50 of postage
# the operator pays because the shipping is free. That aggregate is what makes
# the margin 35.3% at CA$64.99 and the solved price CA$64.64.
#
# The rules below decompose it into the four fees a marketplace of this shape
# actually charges. The decomposition is an input like any other and the
# aggregate is derived from it in the tests, never the other way round: a test
# recomputes 12.5% and CA$2.52 from these rows and fails if an edit to one rate
# silently changes the case the rest of the spec depends on.
#
# No per-listing or per-month rule appears here, deliberately. Those are
# absorbed over a period's actual order volume (FR-025) and are not charged on
# a single sale, so putting one here would double-count it.
# --------------------------------------------------------------------------

#: Each entry is (name, basis, rate_pct, fixed_amount, sort_order).
CHANNEL_FEE_RULES: Final[tuple[tuple[str, str, Decimal, Decimal, int], ...]] = (
    # Charged on the item plus the shipping the customer paid (FR-023).
    ("transaction", "item_plus_shipping", Decimal("6.5"), Decimal("0.00"), 10),
    # A payment processor charges the whole order, including shipping.
    ("payment_processing", "order_total", Decimal("3.0"), Decimal("0.30"), 20),
    # A regulatory operating fee lands on the item alone.
    ("regulatory_operating", "item_subtotal", Decimal("3.0"), Decimal("0.22"), 30),
    # A flat charge once per order, whatever the order contains.
    ("order_handling", "per_order", Decimal("0"), Decimal("2.00"), 40),
)

#: Reserve held against revenue for refunds (FR-026).
CHANNEL_EXPECTED_REFUND_PCT: Final = Decimal("2.5")

#: No discount is expected on the golden case, so the lever is exercised
#: elsewhere and its absence here is explicit rather than unset.
CHANNEL_EXPECTED_DISCOUNT_PCT: Final = Decimal("0")

#: The channel advertises free shipping, so the customer pays nothing for it
#: and the operator pays the postage below. This is the case FR-024 exists for.
CHANNEL_SHIPPING_REVENUE: Final = Decimal("0.00")

#: What the label actually costs the operator.
POSTAGE_PAID: Final = Decimal("9.50")

#: Who hands the sales tax to the revenue authority (FR-028b). The golden
#: figures carry no tax, which is the point: margin is the same either way.
CHANNEL_TAX_REMITTER: Final = "marketplace"

CHANNEL_CURRENCY_CODE: Final = "CAD"
