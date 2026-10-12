"""
Tests for Model (3D print model) Pydantic schemas.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.model import (
    BOMSpoolSuggestion,
    CostBreakdown,
    CostLine,
    ModelCostBreakdown,
    ModelBase,
    ModelComponentBase,
    ModelCreate,
    ModelListResponse,
    ModelMaterialBase,
    ModelProductionDefaults,
    ModelUpdate,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TestModelCostBreakdown:
    def test_valid(self):
        c = ModelCostBreakdown(
            material_cost=Decimal("2.50"),
            component_cost=Decimal("0.30"),
            labor_cost=Decimal("5.00"),
            overhead_cost=Decimal("0.75"),
            total_cost=Decimal("8.55"),
        )
        assert c.total_cost == Decimal("8.55")


class TestModelMaterialBase:
    def test_valid(self):
        m = ModelMaterialBase(
            spool_id=uuid4(),
            weight_grams=Decimal("10.5"),
            cost_per_gram=Decimal("0.025"),
        )
        assert m.weight_grams == Decimal("10.5")

    def test_weight_grams_zero_raises(self):
        with pytest.raises(ValidationError):
            ModelMaterialBase(
                spool_id=uuid4(),
                weight_grams=Decimal("0"),
                cost_per_gram=Decimal("0.02"),
            )

    def test_cost_per_gram_zero_accepted(self):
        m = ModelMaterialBase(
            spool_id=uuid4(),
            weight_grams=Decimal("5"),
            cost_per_gram=Decimal("0"),
        )
        assert m.cost_per_gram == Decimal("0")

    def test_cost_per_gram_negative_raises(self):
        with pytest.raises(ValidationError):
            ModelMaterialBase(
                spool_id=uuid4(),
                weight_grams=Decimal("5"),
                cost_per_gram=Decimal("-0.01"),
            )


class TestModelComponentBase:
    def test_valid(self):
        c = ModelComponentBase(
            component_name="Magnets N52",
            quantity=4,
            unit_cost=Decimal("0.10"),
        )
        assert c.component_name == "Magnets N52"
        assert c.supplier is None

    def test_component_name_empty_raises(self):
        with pytest.raises(ValidationError):
            ModelComponentBase(component_name="", quantity=1, unit_cost=Decimal("0"))

    def test_component_name_max_200(self):
        c = ModelComponentBase(component_name="C" * 200, quantity=1, unit_cost=Decimal("0"))
        assert len(c.component_name) == 200

    def test_component_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            ModelComponentBase(component_name="C" * 201, quantity=1, unit_cost=Decimal("0"))

    def test_quantity_zero_raises(self):
        with pytest.raises(ValidationError):
            ModelComponentBase(component_name="Part", quantity=0, unit_cost=Decimal("0"))

    def test_unit_cost_zero_accepted(self):
        c = ModelComponentBase(component_name="Free Part", quantity=1, unit_cost=Decimal("0"))
        assert c.unit_cost == Decimal("0")

    def test_unit_cost_negative_raises(self):
        with pytest.raises(ValidationError):
            ModelComponentBase(component_name="Part", quantity=1, unit_cost=Decimal("-0.01"))

    def test_supplier_max_200(self):
        c = ModelComponentBase(
            component_name="Part", quantity=1, unit_cost=Decimal("1"), supplier="S" * 200
        )
        assert len(c.supplier) == 200

    def test_supplier_too_long_raises(self):
        with pytest.raises(ValidationError):
            ModelComponentBase(
                component_name="Part", quantity=1, unit_cost=Decimal("1"), supplier="S" * 201
            )


class TestModelBase:
    def _valid(self, **kwargs) -> dict:
        defaults = {"sku": "MDL-001", "name": "Dragon V2"}
        defaults.update(kwargs)
        return defaults

    def test_defaults(self):
        m = ModelBase(**self._valid())
        assert m.is_active is True
        assert m.labor_hours == Decimal("0")
        assert m.overhead_percentage == Decimal("0")
        assert m.prints_per_plate == 1

    def test_sku_empty_raises(self):
        with pytest.raises(ValidationError):
            ModelBase(sku="", name="Dragon")

    def test_sku_max_100(self):
        m = ModelBase(sku="S" * 100, name="Test")
        assert len(m.sku) == 100

    def test_sku_too_long_raises(self):
        with pytest.raises(ValidationError):
            ModelBase(sku="S" * 101, name="Test")

    def test_name_max_200(self):
        m = ModelBase(sku="MDL", name="N" * 200)
        assert len(m.name) == 200

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            ModelBase(sku="MDL", name="N" * 201)

    def test_labor_hours_negative_raises(self):
        with pytest.raises(ValidationError):
            ModelBase(**self._valid(labor_hours=Decimal("-0.1")))

    def test_overhead_percentage_max_100(self):
        m = ModelBase(**self._valid(overhead_percentage=Decimal("100")))
        assert m.overhead_percentage == Decimal("100")

    def test_overhead_percentage_above_100_raises(self):
        with pytest.raises(ValidationError):
            ModelBase(**self._valid(overhead_percentage=Decimal("100.01")))

    def test_prints_per_plate_minimum_1(self):
        with pytest.raises(ValidationError):
            ModelBase(**self._valid(prints_per_plate=0))

    def test_print_time_minutes_zero_accepted(self):
        m = ModelBase(**self._valid(print_time_minutes=0))
        assert m.print_time_minutes == 0

    def test_print_time_minutes_negative_raises(self):
        with pytest.raises(ValidationError):
            ModelBase(**self._valid(print_time_minutes=-1))

    def test_units_in_stock_zero_accepted(self):
        m = ModelBase(**self._valid(units_in_stock=0))
        assert m.units_in_stock == 0

    def test_units_in_stock_negative_raises(self):
        with pytest.raises(ValidationError):
            ModelBase(**self._valid(units_in_stock=-1))

    def test_image_url_max_500(self):
        m = ModelBase(**self._valid(image_url="https://x.com/" + "a" * 480))
        assert m.image_url is not None

    def test_image_url_too_long_raises(self):
        with pytest.raises(ValidationError):
            ModelBase(**self._valid(image_url="u" * 501))


class TestModelCreate:
    def test_inherits_base_defaults(self):
        m = ModelCreate(sku="MDL-002", name="Fire Drake")
        assert m.is_active is True
        assert m.prints_per_plate == 1


class TestModelUpdate:
    def test_all_optional(self):
        u = ModelUpdate()
        assert u.sku is None
        assert u.name is None
        assert u.is_active is None

    def test_partial_update(self):
        u = ModelUpdate(name="Updated Dragon", is_active=False)
        assert u.name == "Updated Dragon"
        assert u.is_active is False

    def test_sku_empty_raises(self):
        with pytest.raises(ValidationError):
            ModelUpdate(sku="")

    def test_overhead_above_100_raises(self):
        with pytest.raises(ValidationError):
            ModelUpdate(overhead_percentage=Decimal("101"))

    def test_prints_per_plate_zero_raises(self):
        with pytest.raises(ValidationError):
            ModelUpdate(prints_per_plate=0)


class TestBOMSpoolSuggestion:
    def test_valid(self):
        s = BOMSpoolSuggestion(
            spool_id=uuid4(),
            spool_name="Bambu PLA White",
            material_type_code="PLA",
            color="White",
            weight_grams=Decimal("15.0"),
            cost_per_gram=Decimal("0.025"),
            current_weight=Decimal("800.0"),
            is_active=True,
        )
        assert s.material_type_code == "PLA"
        assert s.color_hex is None

    def test_with_color_hex(self):
        s = BOMSpoolSuggestion(
            spool_id=uuid4(),
            spool_name="Bambu PLA Red",
            material_type_code="PLA",
            color="Red",
            color_hex="FF0000",
            weight_grams=Decimal("10"),
            cost_per_gram=Decimal("0.02"),
            current_weight=Decimal("500"),
            is_active=True,
        )
        assert s.color_hex == "FF0000"


class TestModelProductionDefaults:
    def test_valid_minimal(self):
        d = ModelProductionDefaults(
            model_id=uuid4(),
            sku="MDL-001",
            name="Dragon V2",
            prints_per_plate=4,
        )
        assert d.machine is None
        assert d.bom_materials == []

    def test_with_all_fields(self):
        d = ModelProductionDefaults(
            model_id=uuid4(),
            sku="MDL-001",
            name="Dragon V2",
            machine="Bambu X1C",
            print_time_minutes=240,
            prints_per_plate=4,
        )
        assert d.machine == "Bambu X1C"
        assert d.print_time_minutes == 240


class TestModelListResponse:
    def test_empty(self):
        r = ModelListResponse(models=[], total=0, skip=0, limit=20)
        assert r.total == 0
        assert r.skip == 0

    def test_paginated(self):
        r = ModelListResponse(models=[], total=100, skip=40, limit=20)
        assert r.skip == 40


# ============================================================================
# The structured cost breakdown (data-model.md, 'Cost breakdown shape')
# ============================================================================


def _line(**overrides) -> dict:
    base = {
        "key": "material",
        "label": "Filament in the part",
        "amount": Decimal("4.37"),
        "risk_class": "at_risk",
        "source": "observed",
        "as_of": date(2026, 10, 1),
    }
    base.update(overrides)
    return base


def _breakdown(**overrides) -> dict:
    base = {
        "lines": [_line()],
        "at_risk_subtotal": Decimal("4.37"),
        "not_at_risk_subtotal": Decimal("0.92"),
        "yield_applied": Decimal("0.92"),
        "failure_mode": "per_part",
        "failure_premium": Decimal("0.38"),
        "total_make_cost": Decimal("5.67"),
        "observed_share": Decimal("0.80"),
        "assumed_share": Decimal("0.20"),
        "incomplete_reasons": [],
    }
    base.update(overrides)
    return base


class TestCostLine:
    def test_valid(self):
        line = CostLine(**_line())
        assert line.amount == Decimal("4.37")
        assert line.risk_class == "at_risk"
        assert line.source == "observed"

    def test_as_of_is_optional_because_a_figure_may_never_have_been_recorded(self):
        assert CostLine(**_line(as_of=None)).as_of is None

    def test_unknown_risk_class_rejected(self):
        with pytest.raises(ValidationError):
            CostLine(**_line(risk_class="sometimes"))

    def test_unknown_source_rejected(self):
        with pytest.raises(ValidationError):
            CostLine(**_line(source="vibes"))

    def test_empty_key_rejected(self):
        with pytest.raises(ValidationError):
            CostLine(**_line(key=""))

    def test_negative_amount_allowed_so_a_credit_can_be_expressed(self):
        assert CostLine(**_line(amount=Decimal("-1.00"))).amount == Decimal("-1.00")


class TestCostBreakdown:
    def test_valid(self):
        breakdown = CostBreakdown(**_breakdown())
        assert breakdown.total_make_cost == Decimal("5.67")
        assert breakdown.failure_mode == "per_part"
        assert breakdown.incomplete_reasons == []

    def test_a_yield_of_one_is_permitted(self):
        assert CostBreakdown(**_breakdown(yield_applied=Decimal("1"))).yield_applied == Decimal("1")

    def test_a_yield_of_zero_is_rejected_because_nothing_would_ever_ship(self):
        with pytest.raises(ValidationError):
            CostBreakdown(**_breakdown(yield_applied=Decimal("0")))

    def test_a_yield_above_one_is_rejected(self):
        with pytest.raises(ValidationError):
            CostBreakdown(**_breakdown(yield_applied=Decimal("1.01")))

    def test_shares_outside_zero_to_one_are_rejected(self):
        with pytest.raises(ValidationError):
            CostBreakdown(**_breakdown(observed_share=Decimal("1.5")))
        with pytest.raises(ValidationError):
            CostBreakdown(**_breakdown(assumed_share=Decimal("-0.1")))

    def test_unknown_failure_mode_rejected(self):
        with pytest.raises(ValidationError):
            CostBreakdown(**_breakdown(failure_mode="per_week"))

    def test_incomplete_reasons_carry_what_was_missing(self):
        breakdown = CostBreakdown(**_breakdown(incomplete_reasons=["printer has no cost policy"]))
        assert breakdown.incomplete_reasons == ["printer has no cost policy"]

    def test_lines_default_to_empty_rather_than_none(self):
        payload = _breakdown()
        payload.pop("lines")
        assert CostBreakdown(**payload).lines == []
