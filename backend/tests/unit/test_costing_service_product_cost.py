"""Unit tests for CostingService.calculate_product_cost.

Rewritten against the single authoritative implementation (task T016).

Tests the static method that computes full product cost breakdowns including
models, child products (bundles), packaging, assembly, and actual-vs-theoretical
variance -- with circular reference and max-depth protection.

Two things changed with Tier 0 and are asserted here rather than assumed:
the labor rate is **required**, because an engine default that shadows the
operator's configured rate is a defect (Constitution IV); and the rate is
**forwarded into nested models and child products**, so one product cost can no
longer be built from two different labor rates.

Expected figures are computed from the inputs in each test rather than copied
forward from the previous version of this file.
"""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.costing import (
    CircularReferenceError,
    CostingService,
    MAX_RECURSION_DEPTH,
    MaxDepthExceededError,
)


#: The engine has no default rate any more, so every call names one. This value
#: is distinctive enough that a figure derived from it cannot be a coincidence.
RATE = Decimal("25.00")

CENT = Decimal("0.01")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_model_ns(
    *,
    model_id=None,
    materials=None,
    components=None,
    prints_per_plate=1,
    labor_rate_override=None,
    labor_hours=None,
    overhead_percentage=None,
):
    """Build a minimal Model-like SimpleNamespace."""
    return SimpleNamespace(
        id=model_id or uuid4(),
        materials=materials or [],
        components=components or [],
        prints_per_plate=prints_per_plate,
        labor_rate_override=labor_rate_override,
        labor_hours=labor_hours,
        overhead_percentage=overhead_percentage,
    )


def make_product_model_ns(model, quantity=1):
    """Build a ProductModel association SimpleNamespace (pm.model, pm.quantity)."""
    return SimpleNamespace(model=model, quantity=quantity)


def make_product_child_ns(child_product, quantity=1):
    """Build a ProductChild association SimpleNamespace (pc.child_product, pc.quantity)."""
    return SimpleNamespace(child_product=child_product, quantity=quantity)


def make_product(
    *,
    product_id=None,
    product_models=None,
    child_products=None,
    packaging_cost=None,
    packaging_consumable=None,
    packaging_quantity=1,
    assembly_minutes=None,
):
    """Build a minimal Product-like SimpleNamespace."""
    return SimpleNamespace(
        id=product_id or uuid4(),
        product_models=product_models or [],
        child_products=child_products or [],
        packaging_cost=packaging_cost,
        packaging_consumable=packaging_consumable,
        packaging_quantity=packaging_quantity,
        assembly_minutes=assembly_minutes,
    )


# ---------------------------------------------------------------------------
# Empty product (no models, no children)
# ---------------------------------------------------------------------------


class TestEmptyProduct:
    def test_all_zeros(self):
        product = make_product()
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.models_cost == Decimal("0.00")
        assert result.child_products_cost == Decimal("0.00")
        assert result.packaging_cost == Decimal("0.00")
        assert result.assembly_cost == Decimal("0.00")
        assert result.total_make_cost == Decimal("0.00")

    def test_no_actual_cost_data(self):
        product = make_product()
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.total_actual_cost is None
        assert result.cost_variance_percentage is None
        assert result.models_with_actual_cost == 0
        assert result.models_total == 0


# ---------------------------------------------------------------------------
# Product with models
# ---------------------------------------------------------------------------


class TestProductWithModels:
    def test_single_model_cost_included(self):
        # A model with no materials/components/labor -> zero cost
        model = make_model_ns()
        pm = make_product_model_ns(model, quantity=1)
        product = make_product(product_models=[pm])
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.models_cost == Decimal("0.00")

    def test_model_quantity_multiplies_cost(self):
        grams, per_gram, quantity = Decimal("10"), Decimal("0.05"), 3
        material = SimpleNamespace(weight_grams=grams, cost_per_gram=per_gram)
        model = make_model_ns(materials=[material])
        pm = make_product_model_ns(model, quantity=quantity)
        product = make_product(product_models=[pm])
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.models_cost == (grams * per_gram * quantity).quantize(CENT)

    def test_multiple_models_costs_summed(self):
        a_grams, a_per_gram = Decimal("10"), Decimal("0.10")
        b_grams, b_per_gram, b_quantity = Decimal("5"), Decimal("0.20"), 2
        material_a = SimpleNamespace(weight_grams=a_grams, cost_per_gram=a_per_gram)
        material_b = SimpleNamespace(weight_grams=b_grams, cost_per_gram=b_per_gram)
        pm_a = make_product_model_ns(make_model_ns(materials=[material_a]), quantity=1)
        pm_b = make_product_model_ns(make_model_ns(materials=[material_b]), quantity=b_quantity)
        product = make_product(product_models=[pm_a, pm_b])
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        expected = a_grams * a_per_gram + b_grams * b_per_gram * b_quantity
        assert result.models_cost == expected.quantize(CENT)

    def test_models_total_counts_unique_model_ids(self):
        model = make_model_ns()
        pm1 = make_product_model_ns(model, quantity=1)
        pm2 = make_product_model_ns(model, quantity=1)  # same model id
        product = make_product(product_models=[pm1, pm2])
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.models_total == 1

    def test_product_model_without_model_attr_skipped(self):
        pm = SimpleNamespace(model=None, quantity=1)
        product = make_product(product_models=[pm])
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.models_cost == Decimal("0.00")


# ---------------------------------------------------------------------------
# Packaging cost
# ---------------------------------------------------------------------------


class TestPackagingCost:
    def test_manual_packaging_cost(self):
        product = make_product(packaging_cost=2.50)
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.packaging_cost == Decimal("2.50")

    def test_packaging_cost_zero_when_none(self):
        product = make_product(packaging_cost=None)
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.packaging_cost == Decimal("0.00")

    def test_consumable_packaging_cost(self):
        unit_cost, quantity = Decimal("1.25"), 3
        consumable = SimpleNamespace(current_cost_per_unit=unit_cost)
        product = make_product(packaging_consumable=consumable, packaging_quantity=quantity)
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.packaging_cost == (unit_cost * quantity).quantize(CENT)

    def test_consumable_packaging_zero_cost_per_unit(self):
        consumable = SimpleNamespace(current_cost_per_unit=None)
        product = make_product(packaging_consumable=consumable, packaging_quantity=2)
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.packaging_cost == Decimal("0.00")

    def test_consumable_overrides_manual_packaging(self):
        # When consumable is present, manual packaging_cost is ignored
        consumable = SimpleNamespace(current_cost_per_unit=Decimal("0.50"))
        product = make_product(
            packaging_consumable=consumable,
            packaging_quantity=1,
            packaging_cost=99.99,  # should be ignored
        )
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.packaging_cost == Decimal("0.50")

    def test_consumable_quantity_defaults_to_one(self):
        consumable = SimpleNamespace(current_cost_per_unit=Decimal("2.00"))
        product = make_product(packaging_consumable=consumable, packaging_quantity=None)
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.packaging_cost == Decimal("2.00")


# ---------------------------------------------------------------------------
# Assembly cost
# ---------------------------------------------------------------------------


class TestAssemblyCost:
    def test_assembly_minutes_converted_to_hours(self):
        minutes = 30
        product = make_product(assembly_minutes=minutes)
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.assembly_cost == (Decimal(minutes) / Decimal("60") * RATE).quantize(CENT)

    def test_assembly_zero_when_none(self):
        product = make_product(assembly_minutes=None)
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.assembly_cost == Decimal("0.00")

    def test_assembly_zero_minutes(self):
        product = make_product(assembly_minutes=0)
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.assembly_cost == Decimal("0.00")

    def test_assembly_uses_the_rate_the_caller_passed(self):
        minutes, rate = 60, Decimal("137.00")
        product = make_product(assembly_minutes=minutes)
        result = CostingService.calculate_product_cost(product, labor_rate=rate)
        assert result.assembly_cost == (Decimal(minutes) / Decimal("60") * rate).quantize(CENT)


# ---------------------------------------------------------------------------
# Child products (bundles)
# ---------------------------------------------------------------------------


class TestChildProducts:
    def test_child_product_cost_included(self):
        child_packaging, quantity = Decimal("1.00"), 2
        child = make_product(packaging_cost=child_packaging)
        pc = make_product_child_ns(child, quantity=quantity)
        parent = make_product(child_products=[pc])
        result = CostingService.calculate_product_cost(parent, labor_rate=RATE)
        assert result.child_products_cost == (child_packaging * quantity).quantize(CENT)

    def test_child_without_child_product_attr_skipped(self):
        pc = SimpleNamespace(child_product=None, quantity=1)
        parent = make_product(child_products=[pc])
        result = CostingService.calculate_product_cost(parent, labor_rate=RATE)
        assert result.child_products_cost == Decimal("0.00")

    def test_total_includes_child_cost(self):
        child_packaging, parent_packaging = Decimal("5.00"), Decimal("2.00")
        child = make_product(packaging_cost=child_packaging)
        pc = make_product_child_ns(child, quantity=1)
        parent = make_product(child_products=[pc], packaging_cost=parent_packaging)
        result = CostingService.calculate_product_cost(parent, labor_rate=RATE)
        assert result.total_make_cost == (child_packaging + parent_packaging).quantize(CENT)

    def test_deeply_nested_child(self):
        # grandchild -> child -> parent
        grandchild = make_product(packaging_cost=1.00)
        pc_grand = make_product_child_ns(grandchild, quantity=1)
        child = make_product(child_products=[pc_grand])
        pc_child = make_product_child_ns(child, quantity=1)
        parent = make_product(child_products=[pc_child])
        result = CostingService.calculate_product_cost(parent, labor_rate=RATE)
        assert result.child_products_cost == Decimal("1.00")


# ---------------------------------------------------------------------------
# Circular reference detection
# ---------------------------------------------------------------------------


class TestCircularReference:
    def test_direct_self_reference_raises(self):
        product_id = uuid4()
        product = make_product(product_id=product_id)
        with pytest.raises(CircularReferenceError):
            CostingService.calculate_product_cost(product, labor_rate=RATE, _visited={product_id})

    def test_indirect_circular_raises(self):
        id_a = uuid4()
        id_b = uuid4()

        # product_b has product_a as child
        product_a = make_product(product_id=id_a)
        pc = make_product_child_ns(product_a, quantity=1)
        product_b = make_product(product_id=id_b, child_products=[pc])

        # simulate product_a having product_b as child (b->a->b cycle)
        pc_b = make_product_child_ns(product_b, quantity=1)
        product_a.child_products = [pc_b]

        with pytest.raises(CircularReferenceError):
            CostingService.calculate_product_cost(product_a, labor_rate=RATE)

    def test_circular_error_contains_product_id(self):
        product_id = uuid4()
        product = make_product(product_id=product_id)
        try:
            CostingService.calculate_product_cost(product, labor_rate=RATE, _visited={product_id})
        except CircularReferenceError as exc:
            assert exc.product_id == product_id
        else:
            pytest.fail("CircularReferenceError not raised")


# ---------------------------------------------------------------------------
# Max depth exceeded
# ---------------------------------------------------------------------------


class TestMaxDepth:
    def test_max_depth_exceeded_raises(self):
        product = make_product()
        with pytest.raises(MaxDepthExceededError):
            CostingService.calculate_product_cost(
                product, labor_rate=RATE, _depth=MAX_RECURSION_DEPTH + 1
            )

    def test_at_max_depth_does_not_raise(self):
        # Exactly at MAX_RECURSION_DEPTH is still allowed (> check)
        product = make_product()
        result = CostingService.calculate_product_cost(
            product, labor_rate=RATE, _depth=MAX_RECURSION_DEPTH
        )
        assert result.total_make_cost == Decimal("0.00")

    def test_max_depth_error_contains_depth(self):
        product = make_product()
        depth = MAX_RECURSION_DEPTH + 5
        try:
            CostingService.calculate_product_cost(product, labor_rate=RATE, _depth=depth)
        except MaxDepthExceededError as exc:
            assert exc.depth == depth
            assert exc.max_depth == MAX_RECURSION_DEPTH
        else:
            pytest.fail("MaxDepthExceededError not raised")


# ---------------------------------------------------------------------------
# Actual cost tracking and variance
# ---------------------------------------------------------------------------


class TestActualCostTracking:
    def test_actual_cost_none_when_no_actual_data(self):
        model = make_model_ns()
        pm = make_product_model_ns(model)
        product = make_product(product_models=[pm])
        result = CostingService.calculate_product_cost(product, labor_rate=RATE)
        assert result.total_actual_cost is None
        assert result.cost_variance_percentage is None
        assert result.models_actual_cost is None

    def test_actual_cost_set_when_all_models_have_data(self):
        material = SimpleNamespace(weight_grams=Decimal("10"), cost_per_gram=Decimal("0.10"))
        model = make_model_ns(materials=[material])
        pm = make_product_model_ns(model, quantity=1)
        product = make_product(product_models=[pm])
        result = CostingService.calculate_product_cost(
            product, labor_rate=RATE, realised_unit_costs={model.id: Decimal("1.50")}
        )
        # theoretical cost = 1.00, actual = 1.50
        assert result.total_actual_cost is not None
        assert result.models_actual_cost == Decimal("1.50")
        assert result.models_with_actual_cost == 1

    def test_actual_cost_none_when_only_partial_models_have_data(self):
        # Two models, only one has actual cost -> total_actual_cost should be None
        model_a = make_model_ns()
        model_b = make_model_ns()
        pm_a = make_product_model_ns(model_a, quantity=1)
        pm_b = make_product_model_ns(model_b, quantity=1)
        product = make_product(product_models=[pm_a, pm_b])
        result = CostingService.calculate_product_cost(
            product, labor_rate=RATE, realised_unit_costs={model_a.id: Decimal("2.00")}
        )
        assert result.total_actual_cost is None
        assert result.models_with_actual_cost == 1
        assert result.models_total == 2

    def test_variance_percentage_calculated_correctly(self):
        grams, per_gram, actual = Decimal("10"), Decimal("0.10"), Decimal("1.50")
        material = SimpleNamespace(weight_grams=grams, cost_per_gram=per_gram)
        model = make_model_ns(materials=[material])
        pm = make_product_model_ns(model, quantity=1)
        product = make_product(product_models=[pm])
        result = CostingService.calculate_product_cost(
            product, labor_rate=RATE, realised_unit_costs={model.id: actual}
        )

        theoretical = grams * per_gram
        expected = (actual - theoretical) / theoretical * Decimal("100")
        assert result.cost_variance_percentage == expected.quantize(CENT)

    def test_negative_variance_when_actual_less_than_theoretical(self):
        grams, per_gram, actual = Decimal("10"), Decimal("0.10"), Decimal("0.80")
        material = SimpleNamespace(weight_grams=grams, cost_per_gram=per_gram)
        model = make_model_ns(materials=[material])
        pm = make_product_model_ns(model, quantity=1)
        product = make_product(product_models=[pm])
        result = CostingService.calculate_product_cost(
            product, labor_rate=RATE, realised_unit_costs={model.id: actual}
        )

        theoretical = grams * per_gram
        expected = (actual - theoretical) / theoretical * Decimal("100")
        assert result.cost_variance_percentage == expected.quantize(CENT)
        assert result.cost_variance_percentage < 0


# ---------------------------------------------------------------------------
# Default labor rate
# ---------------------------------------------------------------------------


class TestThereIsNoDefaultLaborRate:
    """The engine no longer supplies a rate of its own.

    This class previously asserted that omitting the rate produced a cost at
    10.00/hour. That was the defect: every screen in the product costed labor at
    a figure the operator never chose while their configured rate sat unread.
    Restoring that assertion would turn the suite green by restoring the defect,
    which the Constitution names a failed change.
    """

    def test_omitting_the_rate_raises_rather_than_inventing_one(self):
        product = make_product(assembly_minutes=60)
        with pytest.raises(TypeError):
            CostingService.calculate_product_cost(product)

    def test_the_rate_reaches_assembly_and_nested_models_alike(self):
        """One product cost, one labor rate.

        The engine used to apply the caller's rate to assembly and its own
        default to every nested model, so a single reported figure was built
        from two different labor rates.
        """
        labor_hours, minutes, rate = Decimal("2"), 60, Decimal("137.00")
        model = make_model_ns(labor_hours=labor_hours)
        pm = make_product_model_ns(model, quantity=1)
        product = make_product(product_models=[pm], assembly_minutes=minutes)

        result = CostingService.calculate_product_cost(product, labor_rate=rate)

        assert result.models_cost == (labor_hours * rate).quantize(CENT)
        assert result.assembly_cost == (Decimal(minutes) / Decimal("60") * rate).quantize(CENT)
        assert result.total_make_cost == (
            labor_hours * rate + Decimal(minutes) / Decimal("60") * rate
        ).quantize(CENT)

    def test_the_rate_reaches_a_nested_child_product(self):
        labor_hours, rate = Decimal("1.5"), Decimal("137.00")
        model = make_model_ns(labor_hours=labor_hours)
        child = make_product(product_models=[make_product_model_ns(model, quantity=1)])
        parent = make_product(child_products=[make_product_child_ns(child, quantity=2)])

        result = CostingService.calculate_product_cost(parent, labor_rate=rate)
        assert result.child_products_cost == (labor_hours * rate * 2).quantize(CENT)

    def test_the_tenant_overhead_default_reaches_a_nested_model(self):
        grams, per_gram, overhead = Decimal("100"), Decimal("0.10"), Decimal("10")
        material = SimpleNamespace(weight_grams=grams, cost_per_gram=per_gram)
        model = make_model_ns(materials=[material])
        product = make_product(product_models=[make_product_model_ns(model, quantity=1)])

        result = CostingService.calculate_product_cost(
            product, labor_rate=RATE, overhead_percentage=overhead
        )
        material_cost = grams * per_gram
        assert result.models_cost == (
            material_cost + material_cost * overhead / Decimal("100")
        ).quantize(CENT)

    def test_siblings_do_not_share_visited_set(self):
        # Two children with the same product id would fail if visited set was shared;
        # but they're different instances -- verify no false positive circular ref
        a_packaging, b_packaging = Decimal("1.00"), Decimal("2.00")
        child_a = make_product(product_id=uuid4(), packaging_cost=a_packaging)
        child_b = make_product(product_id=uuid4(), packaging_cost=b_packaging)
        pc_a = make_product_child_ns(child_a, quantity=1)
        pc_b = make_product_child_ns(child_b, quantity=1)
        parent = make_product(child_products=[pc_a, pc_b])
        # Should not raise even though both children are processed
        result = CostingService.calculate_product_cost(parent, labor_rate=RATE)
        assert result.child_products_cost == (a_packaging + b_packaging).quantize(CENT)
