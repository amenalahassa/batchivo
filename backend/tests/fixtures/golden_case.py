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
