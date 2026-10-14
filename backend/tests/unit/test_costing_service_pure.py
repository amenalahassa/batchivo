"""Unit tests for pure/static CostingService methods.

Rewritten against the single authoritative implementation (task T017).

Uses SimpleNamespace to construct model-like objects without SQLAlchemy overhead.
Tests calculate_model_cost and calculate_cost_per_gram_from_spool.

Every expected figure is recomputed from the inputs in the test, in one
unrounded chain, rounded only for the assertion. The previous version asserted
literals produced by an engine that costed labor at 10.00/hour -- a rate no
operator chose -- so carrying those literals forward would have pinned the
defect in place. The Constitution's Development Workflow section names a suite
that turns green by restoring a defect a failed change.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.costing import CostingService

#: The engine has no default rate any more (Constitution IV): every call names
#: one. This value is distinctive enough that a figure derived from it cannot be
#: a coincidence.
RATE = Decimal("25.00")

MILLE = Decimal("0.001")
CENT = Decimal("0.01")
TEN_THOU = Decimal("0.0001")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_material(weight_grams, cost_per_gram):
    return SimpleNamespace(
        weight_grams=Decimal(str(weight_grams)),
        cost_per_gram=Decimal(str(cost_per_gram)),
    )


def make_component(quantity, unit_cost):
    return SimpleNamespace(quantity=quantity, unit_cost=Decimal(str(unit_cost)))


def make_model(**kwargs):
    defaults = dict(
        prints_per_plate=1,
        materials=[],
        components=[],
        labor_rate_override=None,
        labor_hours=None,
        overhead_percentage=None,
    )
    return SimpleNamespace(**{**defaults, **kwargs})


# ---------------------------------------------------------------------------
# The rate is required, not defaulted
# ---------------------------------------------------------------------------


class TestTheRateIsRequired:
    """A caller that forgets the rate must fail loudly.

    `DEFAULT_LABOR_RATE` is gone. A default that silently shadows the
    operator's configured value is a defect, not a fallback (Constitution IV),
    and this is the shape of the guarantee: there is nothing to fall back to.
    """

    def test_calculate_model_cost_requires_a_rate(self):
        with pytest.raises(TypeError):
            CostingService.calculate_model_cost(make_model())

    def test_the_engine_exposes_no_default_rate(self):
        from app.services import costing

        assert not hasattr(costing, "DEFAULT_LABOR_RATE"), (
            "a module-level default rate is back; the next caller to omit the "
            "rate will silently get a figure the operator never chose"
        )


# ---------------------------------------------------------------------------
# CostingService.calculate_model_cost -- material cost
# ---------------------------------------------------------------------------


class TestCalculateModelCostMaterials:
    def test_no_materials_zero_material_cost(self):
        result = CostingService.calculate_model_cost(make_model(), labor_rate=RATE)
        assert result.material_cost == Decimal("0").quantize(MILLE)

    def test_single_material(self):
        grams, per_gram = Decimal("100"), Decimal("0.03")
        model = make_model(materials=[make_material(grams, per_gram)])
        result = CostingService.calculate_model_cost(model, labor_rate=RATE)
        assert result.material_cost == (grams * per_gram).quantize(MILLE)

    def test_multiple_materials_summed(self):
        first = (Decimal("100"), Decimal("0.02"))
        second = (Decimal("50"), Decimal("0.04"))
        model = make_model(
            materials=[make_material(*first), make_material(*second)],
        )
        result = CostingService.calculate_model_cost(model, labor_rate=RATE)
        expected = first[0] * first[1] + second[0] * second[1]
        assert result.material_cost == expected.quantize(MILLE)

    def test_material_cost_divided_by_prints_per_plate(self):
        """The BOM weight is the whole plate; the cost is shared between prints."""
        grams, per_gram, per_plate = Decimal("100"), Decimal("0.04"), 2
        model = make_model(prints_per_plate=per_plate, materials=[make_material(grams, per_gram)])
        result = CostingService.calculate_model_cost(model, labor_rate=RATE)
        assert result.material_cost == (grams * per_gram / Decimal(per_plate)).quantize(MILLE)

    def test_zero_prints_per_plate_treated_as_one(self):
        """Rather than dividing by zero and failing every screen that shows a cost."""
        grams, per_gram = Decimal("50"), Decimal("0.02")
        model = make_model(prints_per_plate=0, materials=[make_material(grams, per_gram)])
        result = CostingService.calculate_model_cost(model, labor_rate=RATE)
        assert result.material_cost == (grams * per_gram).quantize(MILLE)

    def test_a_missing_prints_per_plate_is_treated_as_one(self):
        grams, per_gram = Decimal("50"), Decimal("0.02")
        model = make_model(prints_per_plate=None, materials=[make_material(grams, per_gram)])
        result = CostingService.calculate_model_cost(model, labor_rate=RATE)
        assert result.material_cost == (grams * per_gram).quantize(MILLE)

    def test_purge_and_waste_are_not_yet_costed(self):
        """Documents the gap Tier 1 closes (tasks T036, T043).

        The BOM weight is the filament that ends up in the part. Purge and
        wiped material are consumed and not yet charged, so this figure is an
        understatement by design until the waste line exists -- stated here so
        the omission is on the record rather than mistaken for completeness.
        """
        grams, per_gram = Decimal("142"), Decimal("0.0310")
        model = make_model(materials=[make_material(grams, per_gram)])
        result = CostingService.calculate_model_cost(model, labor_rate=RATE)
        assert result.material_cost == (grams * per_gram).quantize(MILLE)


# ---------------------------------------------------------------------------
# CostingService.calculate_model_cost -- component cost
# ---------------------------------------------------------------------------


class TestCalculateModelCostComponents:
    def test_no_components_zero_cost(self):
        result = CostingService.calculate_model_cost(make_model(), labor_rate=RATE)
        assert result.component_cost == Decimal("0").quantize(MILLE)

    def test_single_component(self):
        quantity, unit_cost = 3, Decimal("2.00")
        model = make_model(components=[make_component(quantity, unit_cost)])
        result = CostingService.calculate_model_cost(model, labor_rate=RATE)
        assert result.component_cost == (Decimal(quantity) * unit_cost).quantize(MILLE)

    def test_multiple_components_summed(self):
        first, second = (2, Decimal("3.00")), (5, Decimal("1.50"))
        model = make_model(
            components=[make_component(*first), make_component(*second)],
        )
        result = CostingService.calculate_model_cost(model, labor_rate=RATE)
        expected = Decimal(first[0]) * first[1] + Decimal(second[0]) * second[1]
        assert result.component_cost == expected.quantize(MILLE)

    def test_components_are_per_part_not_per_plate(self):
        """A screw per part is a screw per part, however many share a plate."""
        quantity, unit_cost = 3, Decimal("2.00")
        model = make_model(prints_per_plate=4, components=[make_component(quantity, unit_cost)])
        result = CostingService.calculate_model_cost(model, labor_rate=RATE)
        assert result.component_cost == (Decimal(quantity) * unit_cost).quantize(MILLE)


# ---------------------------------------------------------------------------
# CostingService.calculate_model_cost -- labor cost
# ---------------------------------------------------------------------------


class TestCalculateModelCostLabor:
    def test_no_labor_hours_zero_labor_cost(self):
        result = CostingService.calculate_model_cost(make_model(), labor_rate=RATE)
        assert result.labor_cost == Decimal("0").quantize(MILLE)

    def test_labor_cost_uses_the_rate_the_caller_passed(self):
        hours = Decimal("2")
        result = CostingService.calculate_model_cost(make_model(labor_hours=hours), labor_rate=RATE)
        assert result.labor_cost == (hours * RATE).quantize(MILLE)

    def test_labor_cost_with_override_rate(self):
        hours, override = Decimal("1.5"), Decimal("15.00")
        result = CostingService.calculate_model_cost(
            make_model(labor_hours=hours, labor_rate_override=override), labor_rate=RATE
        )
        assert result.labor_cost == (hours * override).quantize(MILLE)

    def test_tenant_rate_used_when_no_override(self):
        hours, tenant_rate = Decimal("1"), Decimal("12.00")
        result = CostingService.calculate_model_cost(
            make_model(labor_hours=hours), labor_rate=tenant_rate
        )
        assert result.labor_cost == (hours * tenant_rate).quantize(MILLE)

    def test_model_override_takes_precedence_over_the_tenant_rate(self):
        hours, override, tenant_rate = Decimal("1"), Decimal("20.00"), Decimal("12.00")
        result = CostingService.calculate_model_cost(
            make_model(labor_hours=hours, labor_rate_override=override),
            labor_rate=tenant_rate,
        )
        assert result.labor_cost == (hours * override).quantize(MILLE)

    def test_a_distinctive_tenant_rate_reaches_the_figure(self):
        """No plausible default could produce this number."""
        hours, distinctive = Decimal("3"), Decimal("137.00")
        result = CostingService.calculate_model_cost(
            make_model(labor_hours=hours), labor_rate=distinctive
        )
        assert result.labor_cost == (hours * distinctive).quantize(MILLE)
        assert result.labor_cost != (hours * Decimal("10.00")).quantize(MILLE)

    def test_labor_is_not_divided_by_prints_per_plate(self):
        """Documents the current treatment, which Tier 1 splits apart.

        `labor_hours` is charged per item regardless of how many share a plate.
        Tier 1 replaces it with an explicit plate/item and handling/finishing
        split (tasks T036, T043), where only the plate portion is shared.
        """
        hours = Decimal("0.25")
        result = CostingService.calculate_model_cost(
            make_model(labor_hours=hours, prints_per_plate=4), labor_rate=RATE
        )
        assert result.labor_cost == (hours * RATE).quantize(MILLE)


# ---------------------------------------------------------------------------
# CostingService.calculate_model_cost -- overhead cost
# ---------------------------------------------------------------------------


class TestCalculateModelCostOverhead:
    def test_no_overhead_zero_overhead_cost(self):
        model = make_model(materials=[make_material(100, "0.02")])
        result = CostingService.calculate_model_cost(model, labor_rate=RATE)
        assert result.overhead_cost == Decimal("0").quantize(MILLE)

    def test_overhead_percentage_applied_to_material_and_labor(self):
        grams, per_gram = Decimal("100"), Decimal("0.02")
        hours, pct = Decimal("1"), Decimal("20")
        model = make_model(
            materials=[make_material(grams, per_gram)],
            labor_hours=hours,
            overhead_percentage=pct,
        )
        result = CostingService.calculate_model_cost(model, labor_rate=RATE)
        base = grams * per_gram + hours * RATE
        assert result.overhead_cost == (base * pct / Decimal("100")).quantize(MILLE)

    def test_overhead_is_not_taken_on_components(self):
        """Documents the base, which Tier 1 replaces with per-machine-hour absorption."""
        grams, per_gram, pct = Decimal("100"), Decimal("0.02"), Decimal("20")
        model = make_model(
            materials=[make_material(grams, per_gram)],
            components=[make_component(10, "5.00")],
            overhead_percentage=pct,
        )
        result = CostingService.calculate_model_cost(model, labor_rate=RATE)
        assert result.overhead_cost == (grams * per_gram * pct / Decimal("100")).quantize(MILLE)

    def test_tenant_default_overhead_used_when_the_model_sets_none(self):
        grams, per_gram, tenant_pct = Decimal("100"), Decimal("0.02"), Decimal("10")
        model = make_model(materials=[make_material(grams, per_gram)])
        result = CostingService.calculate_model_cost(
            model, labor_rate=RATE, overhead_percentage=tenant_pct
        )
        assert result.overhead_cost == (grams * per_gram * tenant_pct / Decimal("100")).quantize(
            MILLE
        )

    def test_the_model_percentage_wins_over_the_tenant_default(self):
        grams, per_gram = Decimal("100"), Decimal("0.02")
        model_pct, tenant_pct = Decimal("30"), Decimal("10")
        model = make_model(
            materials=[make_material(grams, per_gram)], overhead_percentage=model_pct
        )
        result = CostingService.calculate_model_cost(
            model, labor_rate=RATE, overhead_percentage=tenant_pct
        )
        assert result.overhead_cost == (grams * per_gram * model_pct / Decimal("100")).quantize(
            MILLE
        )

    def test_omitting_the_tenant_overhead_means_none_not_some(self):
        """Zero here is the absence of a tenant default, not a figure shadowing one."""
        grams, per_gram = Decimal("100"), Decimal("0.02")
        model = make_model(materials=[make_material(grams, per_gram)])
        result = CostingService.calculate_model_cost(model, labor_rate=RATE)
        assert result.overhead_cost == Decimal("0").quantize(MILLE)


# ---------------------------------------------------------------------------
# CostingService.calculate_model_cost -- total cost
# ---------------------------------------------------------------------------
# CostingService.calculate_cost_per_gram_from_spool
# ---------------------------------------------------------------------------


class TestCalculateCostPerGramFromSpool:
    def test_basic_calculation(self):
        price, weight = Decimal("20.00"), Decimal("1000")
        result = CostingService.calculate_cost_per_gram_from_spool(
            purchase_price=price, initial_weight=weight
        )
        assert result == (price / weight).quantize(TEN_THOU)

    def test_none_purchase_price_returns_zero(self):
        assert CostingService.calculate_cost_per_gram_from_spool(
            purchase_price=None, initial_weight=Decimal("1000")
        ) == Decimal("0")

    def test_zero_purchase_price_returns_zero(self):
        assert CostingService.calculate_cost_per_gram_from_spool(
            purchase_price=Decimal("0"), initial_weight=Decimal("1000")
        ) == Decimal("0")

    def test_zero_initial_weight_returns_zero(self):
        """Rather than dividing by zero and failing every screen showing a cost."""
        assert CostingService.calculate_cost_per_gram_from_spool(
            purchase_price=Decimal("20.00"), initial_weight=Decimal("0")
        ) == Decimal("0")

    def test_result_has_four_decimal_places(self):
        price, weight = Decimal("15.00"), Decimal("750")
        result = CostingService.calculate_cost_per_gram_from_spool(
            purchase_price=price, initial_weight=weight
        )
        assert result == result.quantize(TEN_THOU)
        assert result == (price / weight).quantize(TEN_THOU)

    def test_fractional_result_is_quantised_not_truncated(self):
        price, weight = Decimal("17.99"), Decimal("1000")
        result = CostingService.calculate_cost_per_gram_from_spool(
            purchase_price=price, initial_weight=weight
        )
        assert result == (price / weight).quantize(TEN_THOU)

    def test_the_divisor_is_the_nominal_weight_not_the_usable_weight(self):
        """Documents the gap Tier 1 closes (tasks T039, T042).

        Filament left on the core cannot be printed, so the true per-gram cost
        divides by the usable weight. Dividing by the nominal weight understates
        it, and the landed-cost service replaces this method.
        """
        price, nominal = Decimal("31.00"), Decimal("1000")
        unusable = Decimal("25")
        result = CostingService.calculate_cost_per_gram_from_spool(
            purchase_price=price, initial_weight=nominal
        )
        assert result == (price / nominal).quantize(TEN_THOU)
        assert result < (price / (nominal - unusable)).quantize(TEN_THOU)
