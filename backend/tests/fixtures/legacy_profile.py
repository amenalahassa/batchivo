"""The superseded cost model, expressed as overrides on the new engine.

FR-052 requires the old 66.4% margin to stay reproducible while the migration
is in flight, so an operator can see what changed and why. The obvious way to
do that -- keep the old code behind a flag -- would recreate exactly the second
implementation that Constitution III forbids and that this feature exists to
remove. research.md D7 chose the other way: run the **one** engine with a
profile of overrides that reproduces what the old model did, as data.

What the old model did, and what each override restores:

* **No machine cost.** Depreciation, maintenance reserve and power were not
  costed at all, so the machine rate is forced to zero.
* **No purge or waste.** Filament spent on priming and colour changes was not
  costed, so waste grams are zeroed.
* **Nominal spool weight.** Cost per gram divided by the spool's nominal
  weight rather than its usable weight, so the unusable remainder is zeroed.
* **No failure premium.** A yield of 1.0, so nothing is charged for failures.
* **Overhead as a percentage** of material plus labor, not absorbed per
  machine-hour.
* **No shipping and no reserves.** Postage was invisible and no refund reserve
  was held.
* **Two fees.** The whole fee stack was one percentage plus one fixed amount,
  which is what the Tier 2 data migration converts into two dated rules.

This file is deliberately a fixture rather than production code, and
deliberately small: FR-052 retires the comparison, and task T124 deletes this
module and its test in one line when it does.
"""

from datetime import date
from decimal import Decimal
from typing import Final

from app.models.fee_rule import FeeRule
from app.services.pricing_policy import CostPolicy

#: The single percentage the old model charged, as `SalesChannel.fee_percentage`
#: held it. The Tier 2 migration converts this into a dated `item_plus_shipping`
#: rule, which is the rule this profile charges.
LEGACY_FEE_PERCENTAGE: Final = Decimal("6.5")

#: The single fixed amount, as `SalesChannel.fee_fixed` held it.
LEGACY_FEE_FIXED: Final = Decimal("0.30")

#: The overhead percentage the old settings blob carried.
LEGACY_OVERHEAD_PERCENTAGE: Final = Decimal("15")

#: The labor rate every screen actually used: a hardcoded 10.00, ignoring the
#: tenant's own setting. This is the defect User Story 1 corrected, and
#: reproducing the old figure means reproducing it.
LEGACY_LABOR_RATE: Final = Decimal("10.00")

#: The names the Tier 2 migration gives the two converted rules. Kept here so
#: the parity test and this profile cannot drift apart.
MIGRATED_RULE_NAMES: Final[tuple[str, str]] = (
    "platform_percentage",
    "platform_fixed",
)


def legacy_policy(**overrides) -> CostPolicy:
    """The operator policy as the superseded model effectively had it."""
    defaults = dict(
        print_labor_rate=LEGACY_LABOR_RATE,
        finishing_labor_rate=LEGACY_LABOR_RATE,
        overhead_method="percentage",
        overhead_percentage=LEGACY_OVERHEAD_PERCENTAGE,
        overhead_monthly_pool=None,
        expected_monthly_machine_hours=None,
        default_machine_rate_per_hour=None,
        electricity_rate_per_kwh=None,
        margin_basis="customer_total",
        origin="legacy_comparison_profile",
    )
    defaults.update(overrides)
    return CostPolicy(**defaults)


def legacy_model_overrides() -> dict[str, object]:
    """Item-level overrides: no waste, no failure premium, nominal weight.

    Passed to the model builder rather than applied to a saved record, because
    the comparison must not touch any stored figure (FR-044: a shock changes
    nothing).
    """
    return {
        "waste_grams": Decimal("0"),
        "expected_yield": Decimal("1.0"),
        "failure_mode": "per_part",
    }


def legacy_printer_overrides() -> dict[str, object]:
    """Machine overrides: the old model costed no machine occupancy at all."""
    return {
        "purchase_price": None,
        "expected_lifetime_hours": None,
        "maintenance_reserve_total": None,
        "measured_watts": None,
        "electricity_rate_per_kwh": None,
    }


def legacy_channel_overrides() -> dict[str, object]:
    """Channel overrides: no reserves, and the two migrated fee rules only."""
    return {
        "expected_discount_pct": Decimal("0"),
        "expected_refund_pct": Decimal("0"),
        "fee_percentage": LEGACY_FEE_PERCENTAGE,
        "fee_fixed": LEGACY_FEE_FIXED,
        "fee_rules": legacy_fee_rules(),
    }


def legacy_fee_rules(applies_from: date | None = None) -> list[FeeRule]:
    """The two rules the Tier 2 data migration produces from one channel.

    Both on ``item_plus_shipping``, which is what a single blended percentage
    was implicitly charged on: the old code applied it to the list price, and
    the list price was the only revenue figure it had.
    """
    from uuid import uuid4

    start = applies_from or date(2020, 1, 1)
    percentage, fixed = MIGRATED_RULE_NAMES
    return [
        FeeRule(
            id=uuid4(),
            tenant_id=uuid4(),
            sales_channel_id=uuid4(),
            name=percentage,
            basis="item_plus_shipping",
            rate_pct=LEGACY_FEE_PERCENTAGE,
            fixed_amount=Decimal("0"),
            min_amount=None,
            max_amount=None,
            incidence_pct=None,
            sort_order=10,
            applies_from=start,
            applies_to=None,
        ),
        FeeRule(
            id=uuid4(),
            tenant_id=uuid4(),
            sales_channel_id=uuid4(),
            name=fixed,
            basis="per_order",
            rate_pct=Decimal("0"),
            fixed_amount=LEGACY_FEE_FIXED,
            min_amount=None,
            max_amount=None,
            incidence_pct=None,
            sort_order=20,
            applies_from=start,
            applies_to=None,
        ),
    ]


#: Postage, which the old model did not know about at all.
LEGACY_POSTAGE_PAID: Final = Decimal("0.00")

#: The price at which the superseded model reported **66.4%** on the golden
#: item, which is the figure FR-052 requires to stay reproducible.
#:
#: It is an input, declared here, and the test derives 66.4% from it rather
#: than asserting the percentage as a constant. It has to be declared because
#: the golden fixture was built to pin the *new* model's figures: under the old
#: model the same item cost CA$9.81 rather than CA$20.30, so at CA$64.99 the
#: old model reported about 77.9%, not 66.4%. 66.4% is the superseded figure at
#: this price, and what research.md D7 asks for is that the mechanism
#: reproduce it -- a profile of overrides on the one engine -- rather than that
#: a literal be stored somewhere and matched.
#:
#: Reviewed and accepted on 2026-10-12: 66.4% is not expected to hold at
#: CA$64.99, so a future reader finding 77.9% there has found the arithmetic
#: working, not a regression.
LEGACY_COMPARISON_PRICE: Final = Decimal("37.31")
