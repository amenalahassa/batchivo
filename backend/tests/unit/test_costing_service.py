"""Unit tests for CostingService's pure static methods.

Rewritten against the single authoritative implementation (task T015).

Every expected figure below is **recomputed from the inputs in the test**, in
one unrounded chain, rounded only for the assertion. None is a literal carried
over from the previous version of this file. That matters here specifically:
these tests used to assert values produced by an engine that costed labor at a
rate the operator never chose, so a literal copied forward would have pinned the
defect in place. The Constitution's Development Workflow section names a suite
that turns green by restoring a defect a failed change.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.costing import (
    CircularReferenceError,
    CostingService,
    MaxDepthExceededError,
)

#: A rate no caller could get by accident, so a figure built from it proves the
#: caller's rate was used.
RATE = Decimal("25.00")

CENT = Decimal("0.01")
MILLE = Decimal("0.001")


class TestCalculateProfit:
    """Tests for CostingService.calculate_profit."""

    def test_basic_profit_no_fees(self):
        price, cost = Decimal("20.00"), Decimal("5.00")
        result = CostingService.calculate_profit(list_price=price, make_cost=cost)

        assert result["platform_fee"] == Decimal("0").quantize(CENT)
        assert result["net_revenue"] == price.quantize(CENT)
        assert result["profit"] == (price - cost).quantize(CENT)
        assert result["margin_percentage"] == ((price - cost) / price * Decimal("100")).quantize(
            CENT
        )

    def test_percentage_fee_only(self):
        price, cost, pct = Decimal("10.00"), Decimal("3.00"), Decimal("10")
        result = CostingService.calculate_profit(
            list_price=price, make_cost=cost, fee_percentage=pct
        )

        expected_fee = price * pct / Decimal("100")
        assert result["platform_fee"] == expected_fee.quantize(CENT)
        assert result["net_revenue"] == (price - expected_fee).quantize(CENT)
        assert result["profit"] == (price - expected_fee - cost).quantize(CENT)

    def test_fixed_fee_only(self):
        price, cost, fixed = Decimal("10.00"), Decimal("2.00"), Decimal("0.30")
        result = CostingService.calculate_profit(list_price=price, make_cost=cost, fee_fixed=fixed)

        assert result["platform_fee"] == fixed.quantize(CENT)
        assert result["net_revenue"] == (price - fixed).quantize(CENT)
        assert result["profit"] == (price - fixed - cost).quantize(CENT)

    def test_combined_fees(self):
        price, cost = Decimal("100.00"), Decimal("30.00")
        pct, fixed = Decimal("5"), Decimal("0.50")
        result = CostingService.calculate_profit(
            list_price=price, make_cost=cost, fee_percentage=pct, fee_fixed=fixed
        )

        expected_fee = price * pct / Decimal("100") + fixed
        assert result["platform_fee"] == expected_fee.quantize(CENT)
        assert result["net_revenue"] == (price - expected_fee).quantize(CENT)
        assert result["profit"] == (price - expected_fee - cost).quantize(CENT)

    def test_no_fee_is_ever_charged_on_another_fee(self):
        """A percentage fee is taken on the price, never on price-less-fixed-fee.

        Fee-on-fee is the most common way a marketplace fee model is got wrong
        (research.md D9). Tier 2's fee engine makes this structural; here it is
        at least asserted.
        """
        price = Decimal("100.00")
        pct, fixed = Decimal("10"), Decimal("5.00")
        result = CostingService.calculate_profit(
            list_price=price, make_cost=Decimal("0"), fee_percentage=pct, fee_fixed=fixed
        )
        charged_on_price = price * pct / Decimal("100") + fixed
        charged_on_net = (price - fixed) * pct / Decimal("100") + fixed

        assert result["platform_fee"] == charged_on_price.quantize(CENT)
        assert result["platform_fee"] != charged_on_net.quantize(CENT)

    def test_zero_price_returns_zero_margin(self):
        """A margin on nothing is undefined; zero is reported rather than raised."""
        result = CostingService.calculate_profit(list_price=Decimal("0"), make_cost=Decimal("5.00"))
        assert result["margin_percentage"] == Decimal("0")

    def test_loss_scenario(self):
        price, cost = Decimal("5.00"), Decimal("10.00")
        result = CostingService.calculate_profit(list_price=price, make_cost=cost)

        assert result["profit"] == (price - cost).quantize(CENT)
        assert result["profit"] < 0
        assert result["margin_percentage"] < 0

    def test_result_rounded_to_two_decimals(self):
        result = CostingService.calculate_profit(
            list_price=Decimal("3.00"),
            make_cost=Decimal("1.00"),
            fee_percentage=Decimal("10"),
        )
        for key in ("platform_fee", "net_revenue", "profit", "margin_percentage"):
            assert result[key] == result[key].quantize(CENT)

    def test_every_figure_is_a_decimal(self):
        """Constitution IV: no money figure may leave the engine as a float."""
        result = CostingService.calculate_profit(
            list_price=Decimal("64.99"),
            make_cost=Decimal("20.30"),
            fee_percentage=Decimal("6.5"),
            fee_fixed=Decimal("0.20"),
        )
        for key, value in result.items():
            assert isinstance(value, Decimal), f"{key} came back as {type(value).__name__}"

    def test_rounding_happens_only_at_the_end(self):
        """An intermediate round would show up as a cent of drift here."""
        price, pct = Decimal("33.33"), Decimal("6.5")
        result = CostingService.calculate_profit(
            list_price=price, make_cost=Decimal("0"), fee_percentage=pct
        )
        unrounded = price * pct / Decimal("100")
        assert result["platform_fee"] == unrounded.quantize(CENT)
        assert result["net_revenue"] == (price - unrounded).quantize(CENT)


class TestCalculateCostPerGram:
    """Tests for CostingService.calculate_cost_per_gram_from_spool."""

    def test_basic_calculation(self):
        price, weight = Decimal("20.00"), Decimal("1000")
        result = CostingService.calculate_cost_per_gram_from_spool(
            purchase_price=price, initial_weight=weight
        )
        assert result == (price / weight).quantize(Decimal("0.0001"))

    def test_none_price_returns_zero(self):
        assert CostingService.calculate_cost_per_gram_from_spool(
            purchase_price=None, initial_weight=Decimal("1000")
        ) == Decimal("0")

    def test_zero_price_returns_zero(self):
        assert CostingService.calculate_cost_per_gram_from_spool(
            purchase_price=Decimal("0"), initial_weight=Decimal("1000")
        ) == Decimal("0")

    def test_negative_price_returns_zero(self):
        assert CostingService.calculate_cost_per_gram_from_spool(
            purchase_price=Decimal("-5.00"), initial_weight=Decimal("1000")
        ) == Decimal("0")

    def test_zero_weight_returns_zero(self):
        """Rather than dividing by zero and failing a price screen."""
        assert CostingService.calculate_cost_per_gram_from_spool(
            purchase_price=Decimal("20.00"), initial_weight=Decimal("0")
        ) == Decimal("0")

    def test_result_rounded_to_four_decimals(self):
        result = CostingService.calculate_cost_per_gram_from_spool(
            purchase_price=Decimal("15.00"), initial_weight=Decimal("750")
        )
        assert result == result.quantize(Decimal("0.0001"))

    def test_the_landed_figure_is_not_yet_this_methods_concern(self):
        """This divides by the nominal weight, not the usable weight.

        Tier 1 replaces it with `app/services/landed_cost.py` (task T042), which
        allocates inbound shipping and divides by the weight actually printable
        after the unusable remainder. Asserted here so the limitation is on the
        record rather than discovered later as a surprise.
        """
        nominal = Decimal("1000")
        result = CostingService.calculate_cost_per_gram_from_spool(
            purchase_price=Decimal("31.00"), initial_weight=nominal
        )
        assert result == (Decimal("31.00") / nominal).quantize(Decimal("0.0001"))


class TestCalculateModelCost:
    """Tests for CostingService.calculate_model_cost."""

    def _model(self, **kwargs):
        """Build a minimal mock model using SimpleNamespace."""
        defaults = {
            "prints_per_plate": 1,
            "materials": [],
            "components": [],
            "labor_hours": None,
            "labor_rate_override": None,
            "overhead_percentage": None,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_the_rate_is_required(self):
        """There is no default rate to fall back to, by design.

        A caller that forgets the rate must fail loudly rather than quietly
        produce a cost at a figure nobody configured (Constitution IV).
        """
        with pytest.raises(TypeError):
            CostingService.calculate_model_cost(self._model())

    def test_empty_model_zero_cost(self):
        breakdown = CostingService.calculate_model_cost(self._model(), labor_rate=RATE)
        assert breakdown.total_cost == Decimal("0").quantize(MILLE)
        assert breakdown.material_cost == Decimal("0").quantize(MILLE)
        assert breakdown.labor_cost == Decimal("0").quantize(MILLE)
        assert breakdown.overhead_cost == Decimal("0").quantize(MILLE)

    def test_material_cost_calculated(self):
        grams, per_gram = Decimal("100"), Decimal("0.02")
        material = SimpleNamespace(weight_grams=grams, cost_per_gram=per_gram)
        breakdown = CostingService.calculate_model_cost(
            self._model(materials=[material]), labor_rate=RATE
        )
        assert breakdown.material_cost == (grams * per_gram).quantize(MILLE)

    def test_prints_per_plate_divides_material_cost(self):
        grams, per_gram, per_plate = Decimal("100"), Decimal("0.02"), 4
        material = SimpleNamespace(weight_grams=grams, cost_per_gram=per_gram)
        breakdown = CostingService.calculate_model_cost(
            self._model(materials=[material], prints_per_plate=per_plate),
            labor_rate=RATE,
        )
        assert breakdown.material_cost == (grams * per_gram / Decimal(per_plate)).quantize(MILLE)

    def test_labor_cost_uses_the_rate_the_caller_passed(self):
        hours = Decimal("2")
        breakdown = CostingService.calculate_model_cost(
            self._model(labor_hours=hours), labor_rate=RATE
        )
        assert breakdown.labor_cost == (hours * RATE).quantize(MILLE)

    def test_labor_cost_uses_override_rate(self):
        hours, override = Decimal("1"), Decimal("15")
        breakdown = CostingService.calculate_model_cost(
            self._model(labor_hours=hours, labor_rate_override=override), labor_rate=RATE
        )
        assert breakdown.labor_cost == (hours * override).quantize(MILLE)

    def test_a_distinctive_tenant_rate_reaches_the_figure(self):
        hours, distinctive = Decimal("2"), Decimal("137.00")
        breakdown = CostingService.calculate_model_cost(
            self._model(labor_hours=hours), labor_rate=distinctive
        )
        assert breakdown.labor_cost == (hours * distinctive).quantize(MILLE)

    def test_overhead_percentage_applied(self):
        grams, per_gram, pct = Decimal("100"), Decimal("0.10"), Decimal("10")
        material = SimpleNamespace(weight_grams=grams, cost_per_gram=per_gram)
        breakdown = CostingService.calculate_model_cost(
            self._model(materials=[material], overhead_percentage=pct), labor_rate=RATE
        )

        expected_material = grams * per_gram
        expected_overhead = expected_material * pct / Decimal("100")
        assert breakdown.material_cost == expected_material.quantize(MILLE)
        assert breakdown.overhead_cost == expected_overhead.quantize(MILLE)
        assert breakdown.total_cost == (expected_material + expected_overhead).quantize(MILLE)

    def test_the_tenant_overhead_default_applies_when_the_model_sets_none(self):
        grams, per_gram, tenant_pct = Decimal("100"), Decimal("0.10"), Decimal("7")
        material = SimpleNamespace(weight_grams=grams, cost_per_gram=per_gram)
        breakdown = CostingService.calculate_model_cost(
            self._model(materials=[material]),
            labor_rate=RATE,
            overhead_percentage=tenant_pct,
        )
        assert breakdown.overhead_cost == (grams * per_gram * tenant_pct / Decimal("100")).quantize(
            MILLE
        )

    def test_the_model_overhead_wins_over_the_tenant_default(self):
        grams, per_gram = Decimal("100"), Decimal("0.10")
        model_pct, tenant_pct = Decimal("20"), Decimal("7")
        material = SimpleNamespace(weight_grams=grams, cost_per_gram=per_gram)
        breakdown = CostingService.calculate_model_cost(
            self._model(materials=[material], overhead_percentage=model_pct),
            labor_rate=RATE,
            overhead_percentage=tenant_pct,
        )
        assert breakdown.overhead_cost == (grams * per_gram * model_pct / Decimal("100")).quantize(
            MILLE
        )

    def test_component_cost_added(self):
        quantity, unit = Decimal("3"), Decimal("1.50")
        component = SimpleNamespace(quantity=quantity, unit_cost=unit)
        breakdown = CostingService.calculate_model_cost(
            self._model(components=[component]), labor_rate=RATE
        )
        assert breakdown.component_cost == (quantity * unit).quantize(MILLE)

    def test_components_are_not_divided_by_prints_per_plate(self):
        """A screw per part is a screw per part, however many share a plate."""
        quantity, unit = Decimal("3"), Decimal("1.50")
        component = SimpleNamespace(quantity=quantity, unit_cost=unit)
        breakdown = CostingService.calculate_model_cost(
            self._model(components=[component], prints_per_plate=4), labor_rate=RATE
        )
        assert breakdown.component_cost == (quantity * unit).quantize(MILLE)

    def test_all_costs_sum_to_total(self):
        material = SimpleNamespace(weight_grams=Decimal("50"), cost_per_gram=Decimal("0.04"))
        component = SimpleNamespace(quantity=Decimal("2"), unit_cost=Decimal("0.75"))
        breakdown = CostingService.calculate_model_cost(
            self._model(
                materials=[material],
                components=[component],
                labor_hours=Decimal("0.5"),
                labor_rate_override=Decimal("12"),
                overhead_percentage=Decimal("5"),
            ),
            labor_rate=RATE,
        )

        expected_material = Decimal("50") * Decimal("0.04")
        expected_component = Decimal("2") * Decimal("0.75")
        expected_labor = Decimal("0.5") * Decimal("12")
        expected_overhead = (expected_material + expected_labor) * Decimal("5") / Decimal("100")

        assert breakdown.material_cost == expected_material.quantize(MILLE)
        assert breakdown.component_cost == expected_component.quantize(MILLE)
        assert breakdown.labor_cost == expected_labor.quantize(MILLE)
        assert breakdown.overhead_cost == expected_overhead.quantize(MILLE)
        assert breakdown.total_cost == (
            expected_material + expected_component + expected_labor + expected_overhead
        ).quantize(MILLE)

    def test_overhead_is_taken_on_material_plus_labor_not_on_components(self):
        """Documents the base, which Tier 1 replaces with per-machine-hour absorption."""
        material = SimpleNamespace(weight_grams=Decimal("100"), cost_per_gram=Decimal("0.10"))
        component = SimpleNamespace(quantity=Decimal("10"), unit_cost=Decimal("1.00"))
        breakdown = CostingService.calculate_model_cost(
            self._model(
                materials=[material],
                components=[component],
                labor_hours=Decimal("1"),
                overhead_percentage=Decimal("10"),
            ),
            labor_rate=RATE,
        )
        base = Decimal("100") * Decimal("0.10") + Decimal("1") * RATE
        assert breakdown.overhead_cost == (base * Decimal("10") / Decimal("100")).quantize(MILLE)

    def test_every_figure_is_a_decimal(self):
        breakdown = CostingService.calculate_model_cost(
            self._model(labor_hours=Decimal("1")), labor_rate=RATE
        )
        for name, value in breakdown.model_dump().items():
            assert isinstance(value, Decimal), f"{name} came back as {type(value).__name__}"


class TestTheSecondImplementationIsGone:
    """Constitution III: a domain calculation exists once.

    `Product.calculate_make_cost` and `Product._calculate_model_cost` computed
    the same thing in float, with labor hardcoded at 10.00/hour. They were
    deleted rather than kept in sync, and this asserts they stay deleted.
    """

    def test_product_no_longer_calculates_its_own_cost(self):
        from app.models.product import Product

        assert not hasattr(Product, "calculate_make_cost"), (
            "a second cost implementation is back on the model layer; it will "
            "diverge from CostingService silently, which is how it got here"
        )
        assert not hasattr(Product, "_calculate_model_cost")

    def test_the_engine_is_the_only_entry_point(self):
        assert hasattr(CostingService, "calculate_product_cost")
        assert hasattr(CostingService, "calculate_model_cost")


class TestCostingExceptions:
    """Tests for costing error classes."""

    def test_circular_reference_error_message(self):
        from uuid import uuid4

        pid = uuid4()
        visited = {uuid4(), uuid4()}
        err = CircularReferenceError(pid, visited)
        assert str(pid) in str(err)
        assert "Circular reference" in str(err)

    def test_max_depth_exceeded_error_message(self):
        err = MaxDepthExceededError(depth=25, max_depth=20)
        assert "25" in str(err)
        assert "20" in str(err)
