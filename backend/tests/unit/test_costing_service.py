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
        """Constitution IV: a money figure is exact, never a float.

        `incomplete_reasons` is excluded because it is not a figure -- it is
        what the engine could not cost, in words (FR-019). Everything else in
        this breakdown is an amount, and an amount that came back as a float
        has already lost the exactness the whole engine is built to keep.
        """
        breakdown = CostingService.calculate_model_cost(
            self._model(labor_hours=Decimal("1")), labor_rate=RATE
        )
        figures = {
            name: value
            for name, value in breakdown.model_dump().items()
            if name != "incomplete_reasons"
        }
        assert figures, "the breakdown must still carry figures to assert on"
        for name, value in figures.items():
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
