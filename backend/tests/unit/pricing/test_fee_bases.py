"""Basis arithmetic, where undercounting is easy and invisible (task T058).

Two confusions this file exists to prevent:

* **Per unit sold versus per order.** A per-unit fee on a three-unit order is
  charged three times; a per-order fee is charged once. Treating the first as
  the second undercounts by two thirds, and the error scales with the orders an
  operator is most pleased about.
* **Netting shipping before fees.** A fee on item-plus-shipping must move when
  shipping revenue moves, and must be charged on the shipping the customer paid
  rather than on what is left of it after postage (FR-023). Postage never
  reaches the fee engine at all, which is the structural half of the guarantee;
  this file asserts the arithmetic half.
"""

from datetime import date
from decimal import Decimal

from app.services import fee_engine
from app.services.fee_engine import OrderContext
from tests.unit.pricing.conftest import make_channel, make_fee_rule

AS_OF = date(2026, 6, 1)
HUNDRED = Decimal("100")


def _charges(rules, context):
    return fee_engine.compute(make_channel(fee_rules=rules), context, AS_OF)


# ============================================================================
# Per unit sold versus per order
# ============================================================================


class TestPerUnitSoldVersusPerOrder:
    def test_per_unit_charges_three_times_while_per_order_charges_once(self) -> None:
        fixed = Decimal("0.45")
        three_units = OrderContext(item_subtotal=Decimal("150.00"), quantity=3)

        stack = _charges(
            [
                make_fee_rule("per_unit", "per_unit_sold", fixed_amount=fixed, sort_order=10),
                make_fee_rule("per_order", "per_order", fixed_amount=fixed, sort_order=20),
            ],
            three_units,
        )

        assert stack.named("per_unit").amount_exact == fixed * Decimal(3)
        assert stack.named("per_order").amount_exact == fixed
        assert stack.named("per_unit").amount_exact == stack.named("per_order").amount_exact * 3

    def test_the_two_agree_exactly_on_a_single_unit_order(self) -> None:
        """The boundary case, where a confusion between them is invisible."""
        fixed = Decimal("0.45")
        one_unit = OrderContext(item_subtotal=Decimal("50.00"), quantity=1)

        stack = _charges(
            [
                make_fee_rule("per_unit", "per_unit_sold", fixed_amount=fixed, sort_order=10),
                make_fee_rule("per_order", "per_order", fixed_amount=fixed, sort_order=20),
            ],
            one_unit,
        )

        assert stack.named("per_unit").amount_exact == stack.named("per_order").amount_exact

    def test_a_per_order_fee_does_not_move_with_quantity(self) -> None:
        rule = make_fee_rule("per_order", "per_order", fixed_amount=Decimal("2.00"))

        one = _charges([rule], OrderContext(item_subtotal=Decimal("50"), quantity=1))
        ten = _charges([rule], OrderContext(item_subtotal=Decimal("500"), quantity=10))

        assert one.named("per_order").amount_exact == ten.named("per_order").amount_exact

    def test_a_per_unit_fee_moves_in_proportion_to_quantity(self) -> None:
        rule = make_fee_rule("per_unit", "per_unit_sold", fixed_amount=Decimal("0.45"))

        one = _charges([rule], OrderContext(item_subtotal=Decimal("50"), quantity=1))
        ten = _charges([rule], OrderContext(item_subtotal=Decimal("500"), quantity=10))

        assert ten.named("per_unit").amount_exact == one.named("per_unit").amount_exact * 10


# ============================================================================
# Item plus shipping
# ============================================================================


class TestItemPlusShipping:
    def test_the_fee_moves_when_shipping_revenue_moves(self) -> None:
        """US3's independent test, in one assertion."""
        rate = Decimal("6.5")
        rule = make_fee_rule("transaction", "item_plus_shipping", rate_pct=rate)
        item = Decimal("50.00")

        free = _charges([rule], OrderContext(item_subtotal=item, shipping_revenue=Decimal("0")))
        charged = _charges(
            [rule], OrderContext(item_subtotal=item, shipping_revenue=Decimal("7.00"))
        )

        assert free.named("transaction").amount_exact == item * rate / HUNDRED
        assert charged.named("transaction").amount_exact == (
            (item + Decimal("7.00")) * rate / HUNDRED
        )
        assert charged.named("transaction").amount_exact > free.named("transaction").amount_exact

    def test_the_increase_is_exactly_the_rate_on_the_extra_revenue(self) -> None:
        rate = Decimal("6.5")
        rule = make_fee_rule("transaction", "item_plus_shipping", rate_pct=rate)
        item = Decimal("50.00")
        extra = Decimal("7.00")

        free = _charges([rule], OrderContext(item_subtotal=item))
        charged = _charges([rule], OrderContext(item_subtotal=item, shipping_revenue=extra))

        moved = charged.named("transaction").amount_exact - free.named("transaction").amount_exact
        assert moved == extra * rate / HUNDRED

    def test_item_subtotal_ignores_shipping_entirely(self) -> None:
        """The contrast that makes the previous assertion mean something."""
        rule = make_fee_rule("regulatory", "item_subtotal", rate_pct=Decimal("3"))
        item = Decimal("50.00")

        free = _charges([rule], OrderContext(item_subtotal=item))
        charged = _charges([rule], OrderContext(item_subtotal=item, shipping_revenue=Decimal("7")))

        assert free.named("regulatory").amount_exact == charged.named("regulatory").amount_exact

    def test_order_total_adds_the_extras_that_item_plus_shipping_does_not(self) -> None:
        context = OrderContext(
            item_subtotal=Decimal("50.00"),
            shipping_revenue=Decimal("7.00"),
            extras=Decimal("3.00"),
        )
        stack = _charges(
            [
                make_fee_rule("on_item_plus_ship", "item_plus_shipping", rate_pct=Decimal("10")),
                make_fee_rule("on_order_total", "order_total", rate_pct=Decimal("10")),
            ],
            context,
        )

        assert stack.named("on_item_plus_ship").basis_amount == Decimal("57.00")
        assert stack.named("on_order_total").basis_amount == Decimal("60.00")


class TestShippingRevenueIsNeverNettedBeforeFees:
    def test_the_engine_has_no_way_to_see_postage(self) -> None:
        """FR-023, structurally.

        ``OrderContext`` carries revenue and counts and nothing else. There is
        no postage field for a future change to start netting out, which is a
        stronger guarantee than any assertion about a figure.
        """
        assert not hasattr(OrderContext(item_subtotal=Decimal("1")), "postage_paid")

    def test_a_fee_on_free_shipping_is_charged_on_the_item_alone(self) -> None:
        """Free shipping means no shipping revenue, not negative revenue.

        The operator's postage is a cost on the margin line (FR-024); it must
        not reduce the amount the marketplace charges its percentage on.
        """
        rule = make_fee_rule("transaction", "item_plus_shipping", rate_pct=Decimal("6.5"))
        item = Decimal("64.99")

        charge = _charges([rule], OrderContext(item_subtotal=item)).named("transaction")

        assert charge.basis_amount == item
        assert charge.amount_exact == item * Decimal("6.5") / HUNDRED
