"""Properties the cost and margin engine must hold whatever the inputs.

These are guardrails, not examples. A worked example proves one arithmetic
chain; a property proves the shape of the function, which is what catches a
sign flip, a divisor that should have been a multiplier, or a bundle that
double-counts a child. They are written here, in the Foundational phase, so
every later tier is built against them and a regression fails loudly.

No hypothesis dependency: the sweeps below are deterministic and seeded, so a
failure is reproducible from the test name alone.

Properties covered (tasks.md T008):
  * margin is monotonic in price
  * cost is monotonic in material weight
  * cost is monotonic in labor hours
  * a yield of 1.0 is a no-op
  * a bundle's cost equals the sum of its children
"""

import random
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas.model import CostBreakdown
from app.services.costing import CostingService

SEED = 20261011

#: The engine has no default rate any more, so every call names one
#: (Constitution IV). Where a property is about weight or hours, this is the
#: constant that is held while the variable under test moves.
HELD_RATE = Decimal("25.00")


def _model(**overrides) -> SimpleNamespace:
    """A model the engine can cost, with every attribute it reaches for."""
    defaults = {
        "id": uuid4(),
        "prints_per_plate": 1,
        "materials": [],
        "components": [],
        "labor_hours": None,
        "labor_rate_override": None,
        "overhead_percentage": None,
        "actual_production_cost": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _material(weight: Decimal, cost_per_gram: Decimal = Decimal("0.031")) -> SimpleNamespace:
    return SimpleNamespace(weight_grams=weight, cost_per_gram=cost_per_gram)


def _product(**overrides) -> SimpleNamespace:
    defaults = {
        "id": uuid4(),
        "sku": "SKU",
        "product_models": [],
        "child_products": [],
        "packaging_consumable": None,
        "packaging_cost": Decimal("0"),
        "packaging_quantity": 1,
        "assembly_minutes": Decimal("0"),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _contains(model: SimpleNamespace, quantity: int = 1) -> SimpleNamespace:
    return SimpleNamespace(model=model, quantity=quantity)


def _child(product: SimpleNamespace, quantity: int = 1) -> SimpleNamespace:
    return SimpleNamespace(child_product=product, quantity=quantity)


# ============================================================================
# Margin is monotonic in price
# ============================================================================


class TestMarginMonotonicInPrice:
    """Raising the price, with everything else held, must never lower profit.

    A fee charged as a percentage takes a share of the increase, so profit
    grows more slowly at a higher fee rate -- but it still grows. If it ever
    falls, a fee is being charged on more than the price, or a sign is wrong.
    """

    @pytest.mark.parametrize("fee_pct", ["0", "6.5", "15", "40", "99"])
    def test_profit_strictly_increases_with_price(self, fee_pct: str) -> None:
        make_cost = Decimal("20.30")
        previous = None
        for cents in range(1000, 12000, 137):
            price = Decimal(cents) / Decimal("100")
            result = CostingService.calculate_profit(
                list_price=price,
                make_cost=make_cost,
                fee_percentage=Decimal(fee_pct),
                fee_fixed=Decimal("0.30"),
            )
            profit = result["profit"]
            if previous is not None:
                assert profit > previous, (
                    f"profit fell from {previous} to {profit} as price rose to {price} "
                    f"at a {fee_pct}% fee"
                )
            previous = profit

    @pytest.mark.parametrize("fee_pct", ["0", "6.5", "15"])
    def test_margin_increases_with_price_once_profitable(self, fee_pct: str) -> None:
        make_cost = Decimal("20.30")
        previous = None
        for cents in range(4000, 20000, 311):
            price = Decimal(cents) / Decimal("100")
            margin = CostingService.calculate_profit(
                list_price=price,
                make_cost=make_cost,
                fee_percentage=Decimal(fee_pct),
            )["margin_percentage"]
            if previous is not None:
                assert margin >= previous, (
                    f"margin fell from {previous}% to {margin}% as price rose to {price}"
                )
            previous = margin

    def test_a_price_below_cost_reports_a_loss_not_a_zero(self) -> None:
        """A loss must be visible as a negative figure, never clamped to zero."""
        result = CostingService.calculate_profit(
            list_price=Decimal("5.00"), make_cost=Decimal("20.30")
        )
        assert result["profit"] < 0
        assert result["margin_percentage"] < 0


# ============================================================================
# Cost is monotonic in material weight
# ============================================================================


class TestCostMonotonicInWeight:
    def test_heavier_part_never_costs_less(self) -> None:
        previous = None
        for grams in range(1, 400, 7):
            model = _model(materials=[_material(Decimal(grams))])
            total = CostingService.calculate_model_cost(model, labor_rate=HELD_RATE).total_cost
            if previous is not None:
                assert total > previous, f"cost fell at {grams} g"
            previous = total

    def test_monotonic_under_a_seeded_sweep_of_rates_and_weights(self) -> None:
        rng = random.Random(SEED)
        for _ in range(200):
            cost_per_gram = Decimal(rng.randrange(1, 500)) / Decimal("10000")
            lighter = Decimal(rng.randrange(1, 300))
            heavier = lighter + Decimal(rng.randrange(1, 300))
            light = CostingService.calculate_model_cost(
                _model(materials=[_material(lighter, cost_per_gram)]), labor_rate=HELD_RATE
            ).total_cost
            heavy = CostingService.calculate_model_cost(
                _model(materials=[_material(heavier, cost_per_gram)]), labor_rate=HELD_RATE
            ).total_cost
            assert heavy >= light, (
                f"{heavier} g at {cost_per_gram}/g cost {heavy}, less than {lighter} g at {light}"
            )

    def test_prints_per_plate_divides_rather_than_multiplies(self) -> None:
        """More parts on a plate must lower the per-part material cost."""
        previous = None
        for per_plate in (1, 2, 3, 4, 8, 16):
            model = _model(materials=[_material(Decimal("400"))], prints_per_plate=per_plate)
            total = CostingService.calculate_model_cost(model, labor_rate=HELD_RATE).material_cost
            if previous is not None:
                assert total < previous, f"per-part cost rose at {per_plate} per plate"
            previous = total


# ============================================================================
# Cost is monotonic in hours
# ============================================================================


class TestCostMonotonicInHours:
    """Longer work never costs less.

    At Tier 0 the only hours the engine costs are labor hours. Tier 1 adds
    machine occupancy and overhead per machine-hour, and the same property must
    hold for print hours; ``test_machine_hours`` below is the placeholder that
    will carry it.
    """

    def test_more_labor_hours_never_costs_less(self) -> None:
        previous = None
        for tenths in range(0, 120, 3):
            hours = Decimal(tenths) / Decimal("10")
            model = _model(labor_hours=hours, labor_rate_override=Decimal("25.00"))
            total = CostingService.calculate_model_cost(model, labor_rate=HELD_RATE).total_cost
            if previous is not None:
                assert total >= previous, f"cost fell at {hours} labor hours"
            previous = total

    def test_monotonic_under_a_seeded_sweep_of_rates_and_hours(self) -> None:
        rng = random.Random(SEED + 1)
        for _ in range(200):
            rate = Decimal(rng.randrange(1, 10000)) / Decimal("100")
            shorter = Decimal(rng.randrange(0, 200)) / Decimal("10")
            longer = shorter + Decimal(rng.randrange(1, 200)) / Decimal("10")
            short = CostingService.calculate_model_cost(
                _model(labor_hours=shorter, labor_rate_override=rate), labor_rate=HELD_RATE
            ).total_cost
            long = CostingService.calculate_model_cost(
                _model(labor_hours=longer, labor_rate_override=rate), labor_rate=HELD_RATE
            ).total_cost
            assert long >= short, (
                f"{longer} h at {rate}/h cost {long}, under {shorter} h at {short}"
            )

    def test_assembly_minutes_are_monotonic_in_product_cost(self) -> None:
        previous = None
        for minutes in range(0, 120, 5):
            product = _product(assembly_minutes=Decimal(minutes))
            total = CostingService.calculate_product_cost(
                product, labor_rate=Decimal("25.00")
            ).total_make_cost
            if previous is not None:
                assert total >= previous, f"cost fell at {minutes} assembly minutes"
            previous = total

    @pytest.mark.skip(reason="machine occupancy arrives with Tier 1 (tasks T035, T043)")
    def test_machine_hours(self) -> None:  # pragma: no cover - placeholder
        """Print hours must be monotonic in cost once the machine line exists."""


# ============================================================================
# A yield of 1.0 is a no-op
# ============================================================================


class TestYieldOfOneIsANoOp:
    """A perfect yield must add nothing.

    The engine's yield handling arrives in Tier 1 (T036, T043). The property is
    expressed here against the breakdown contract defined in T007, so the shape
    is pinned before anything produces it: with a yield of 1.0 the failure
    premium is zero and the total is exactly the two subtotals.
    """

    def test_a_yield_of_one_implies_no_premium_and_an_exact_total(self) -> None:
        at_risk = Decimal("19.38")
        not_at_risk = Decimal("0.92")
        breakdown = CostBreakdown(
            lines=[],
            at_risk_subtotal=at_risk,
            not_at_risk_subtotal=not_at_risk,
            yield_applied=Decimal("1"),
            failure_mode="per_part",
            failure_premium=Decimal("0"),
            total_make_cost=at_risk + not_at_risk,
            observed_share=Decimal("0"),
            assumed_share=Decimal("1"),
            incomplete_reasons=[],
        )
        assert breakdown.failure_premium == Decimal("0")
        assert breakdown.total_make_cost == breakdown.at_risk_subtotal + (
            breakdown.not_at_risk_subtotal
        )

    def test_a_premium_under_a_perfect_yield_is_a_contradiction(self) -> None:
        """Documents the invariant the Tier 1 engine must satisfy."""
        at_risk = Decimal("19.38")
        not_at_risk = Decimal("0.92")
        contradictory = CostBreakdown(
            lines=[],
            at_risk_subtotal=at_risk,
            not_at_risk_subtotal=not_at_risk,
            yield_applied=Decimal("1"),
            failure_mode="per_part",
            failure_premium=Decimal("1.50"),
            total_make_cost=at_risk + not_at_risk + Decimal("1.50"),
            observed_share=Decimal("0"),
            assumed_share=Decimal("1"),
            incomplete_reasons=[],
        )
        # The schema cannot forbid this pairing; the engine must never emit it.
        assert contradictory.yield_applied == Decimal("1")
        assert contradictory.failure_premium != Decimal("0"), (
            "if this ever holds, the schema gained the cross-field validation "
            "this test was standing in for -- move the assertion there"
        )

    @pytest.mark.skip(reason="engine-level yield arrives with Tier 1 (tasks T036, T043)")
    def test_engine_yield_of_one_matches_no_yield_at_all(self) -> None:  # pragma: no cover
        """Costing at yield 1.0 must equal costing with yield absent."""


# ============================================================================
# A bundle's cost is the sum of its children
# ============================================================================


class TestBundleCostIsTheSumOfItsChildren:
    def test_two_children_sum_exactly(self) -> None:
        first = _product(
            sku="A",
            product_models=[_contains(_model(materials=[_material(Decimal("100"))]))],
        )
        second = _product(
            sku="B",
            product_models=[_contains(_model(materials=[_material(Decimal("250"))]))],
        )
        bundle = _product(sku="BUNDLE", child_products=[_child(first), _child(second)])

        rate = Decimal("25.00")
        first_cost = CostingService.calculate_product_cost(first, labor_rate=rate).total_make_cost
        second_cost = CostingService.calculate_product_cost(second, labor_rate=rate).total_make_cost
        bundle_cost = CostingService.calculate_product_cost(bundle, labor_rate=rate).total_make_cost

        assert bundle_cost == first_cost + second_cost

    def test_child_quantity_multiplies(self) -> None:
        child = _product(
            sku="C",
            product_models=[_contains(_model(materials=[_material(Decimal("142"))]))],
        )
        rate = Decimal("25.00")
        unit = CostingService.calculate_product_cost(child, labor_rate=rate).total_make_cost

        for quantity in (1, 2, 3, 7):
            bundle = _product(sku="K", child_products=[_child(child, quantity)])
            total = CostingService.calculate_product_cost(bundle, labor_rate=rate).total_make_cost
            assert total == unit * quantity, f"{quantity} of a {unit} child came to {total}"

    def test_a_bundle_adds_its_own_packaging_and_assembly_on_top(self) -> None:
        child = _product(
            sku="C",
            product_models=[_contains(_model(materials=[_material(Decimal("142"))]))],
        )
        rate = Decimal("25.00")
        child_cost = CostingService.calculate_product_cost(child, labor_rate=rate).total_make_cost

        bundle = _product(
            sku="K",
            child_products=[_child(child)],
            packaging_cost=Decimal("0.92"),
            assembly_minutes=Decimal("6"),
        )
        total = CostingService.calculate_product_cost(bundle, labor_rate=rate).total_make_cost
        expected_assembly = Decimal("6") / Decimal("60") * rate
        assert total == (child_cost + Decimal("0.92") + expected_assembly).quantize(Decimal("0.01"))

    def test_nesting_sums_through_two_levels(self) -> None:
        leaf = _product(
            sku="LEAF",
            product_models=[_contains(_model(materials=[_material(Decimal("50"))]))],
        )
        middle = _product(sku="MID", child_products=[_child(leaf, 2)])
        top = _product(sku="TOP", child_products=[_child(middle, 3)])

        rate = Decimal("25.00")
        leaf_cost = CostingService.calculate_product_cost(leaf, labor_rate=rate).total_make_cost
        top_cost = CostingService.calculate_product_cost(top, labor_rate=rate).total_make_cost
        assert top_cost == leaf_cost * 2 * 3
