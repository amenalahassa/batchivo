"""
Tests for MaterialType Pydantic schemas.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.material import MaterialTypeBase, MaterialTypeCreate, MaterialTypeUpdate


class TestMaterialTypeBase:
    def _valid(self, **kwargs) -> dict:
        defaults = {"code": "PLA", "name": "Polylactic Acid"}
        defaults.update(kwargs)
        return defaults

    def test_valid_minimal(self):
        m = MaterialTypeBase(**self._valid())
        assert m.code == "PLA"
        assert m.is_active is True

    def test_code_too_long_raises(self):
        with pytest.raises(ValidationError):
            MaterialTypeBase(**self._valid(code="C" * 21))

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            MaterialTypeBase(**self._valid(name="N" * 101))

    def test_typical_density_negative_raises(self):
        with pytest.raises(ValidationError):
            MaterialTypeBase(**self._valid(typical_density=-0.1))

    def test_typical_density_zero_accepted(self):
        m = MaterialTypeBase(**self._valid(typical_density=0.0))
        assert m.typical_density == 0.0

    def test_typical_cost_per_kg_negative_raises(self):
        with pytest.raises(ValidationError):
            MaterialTypeBase(**self._valid(typical_cost_per_kg=-1.0))

    def test_min_temp_negative_raises(self):
        with pytest.raises(ValidationError):
            MaterialTypeBase(**self._valid(min_temp=-1))

    def test_min_temp_zero_accepted(self):
        m = MaterialTypeBase(**self._valid(min_temp=0))
        assert m.min_temp == 0

    def test_min_temp_max_500(self):
        m = MaterialTypeBase(**self._valid(min_temp=500))
        assert m.min_temp == 500

    def test_min_temp_above_max_raises(self):
        with pytest.raises(ValidationError):
            MaterialTypeBase(**self._valid(min_temp=501))

    def test_max_temp_above_max_raises(self):
        with pytest.raises(ValidationError):
            MaterialTypeBase(**self._valid(max_temp=501))

    def test_bed_temp_max_200(self):
        m = MaterialTypeBase(**self._valid(bed_temp=200))
        assert m.bed_temp == 200

    def test_bed_temp_above_max_raises(self):
        with pytest.raises(ValidationError):
            MaterialTypeBase(**self._valid(bed_temp=201))

    def test_all_optional_fields_none_by_default(self):
        m = MaterialTypeBase(**self._valid())
        assert m.description is None
        assert m.typical_density is None
        assert m.min_temp is None
        assert m.max_temp is None
        assert m.bed_temp is None


class TestMaterialTypeCreate:
    def test_inherits_from_base(self):
        m = MaterialTypeCreate(code="PETG", name="Polyethylene Terephthalate Glycol")
        assert m.code == "PETG"


class TestMaterialTypeUpdate:
    def test_all_optional(self):
        u = MaterialTypeUpdate()
        assert u.name is None
        assert u.is_active is None

    def test_partial_update(self):
        u = MaterialTypeUpdate(is_active=False, min_temp=180)
        assert u.is_active is False
        assert u.min_temp == 180


class TestTheTypicalCostIsExact:
    """`typical_cost_per_kg` was a `float` over an inferred `Float` column
    (task T154) — the last money column in `app/models/` that T024's sweep
    missed, because it was declared with no SQL type at all and so nothing in
    the diff said "money".

    It is only a default. But the figure it defaults is a spool's
    `purchase_price`, and that price is what `costing.py:cost_per_gram` divides
    by a weight to reach the per-gram cost every material line on every model
    is priced from — so the inexactness sat one keystroke upstream of the cost
    of every print (FR-047, Constitution IV).
    """

    @staticmethod
    def _valid(**kwargs) -> dict:
        defaults = {"code": "PLA", "name": "Polylactic Acid"}
        defaults.update(kwargs)
        return defaults

    def test_a_reference_price_is_a_decimal(self):
        m = MaterialTypeBase(**self._valid(typical_cost_per_kg="24.99"))

        assert isinstance(m.typical_cost_per_kg, Decimal)
        assert m.typical_cost_per_kg == Decimal("24.99")

    def test_the_price_a_supplier_quoted_is_the_price_stored(self):
        m = MaterialTypeBase(**self._valid(typical_cost_per_kg="24.99"))

        assert str(m.typical_cost_per_kg) == "24.99"

    def test_a_json_number_is_still_accepted(self):
        """Pydantic coerces it, so a caller that was sending `24.99` unquoted
        keeps working: the task is exactness downstream, not a new 422."""
        m = MaterialTypeBase(**self._valid(typical_cost_per_kg=24.99))

        assert m.typical_cost_per_kg == Decimal("24.99")

    def test_it_crosses_the_wire_as_a_decimal_string(self):
        m = MaterialTypeBase(**self._valid(typical_cost_per_kg="24.99"))

        assert m.model_dump(mode="json")["typical_cost_per_kg"] == "24.99"

    def test_more_than_two_decimal_places_is_refused(self):
        """A list price per kilogram is quoted in whole pence."""
        with pytest.raises(ValidationError):
            MaterialTypeBase(**self._valid(typical_cost_per_kg="24.999"))

    def test_a_material_with_no_reference_price_is_valid(self):
        m = MaterialTypeBase(**self._valid())

        assert m.typical_cost_per_kg is None

    def test_the_density_beside_it_is_still_a_float(self):
        """Deliberate, and the reason this is a test rather than a comment: a
        density is a physical measurement, not an amount of money, and 1.24
        g/cm³ loses nothing to a binary double. Converting it too would make
        `Decimal` mean "number" instead of "money"."""
        m = MaterialTypeBase(**self._valid(typical_density=1.24))

        assert isinstance(m.typical_density, float)


class TestTheColumnMatchesTheSchema:
    """`Float` is a *subclass* of `Numeric` in SQLAlchemy, so `isinstance(...,
    Numeric)` is true of the exact thing this task removed. Both assertions
    below therefore name `Float` directly — the check that reads most
    naturally here is the one that cannot fail."""

    def test_the_stored_type_is_exact_not_binary(self):
        """The schema being exact is worth nothing if the column rounds it to
        the nearest double on the way in."""
        from sqlalchemy import Float, Numeric

        from app.models.material import MaterialType

        column_type = MaterialType.__table__.c.typical_cost_per_kg.type
        assert isinstance(column_type, Numeric)
        assert not isinstance(column_type, Float), (
            f"typical_cost_per_kg is stored as {column_type!r}, a binary float"
        )
        assert column_type.scale == 2, "whole pence, matching spools.purchase_price"

    def test_the_density_column_is_still_a_float(self):
        """The control, for the same reason as the schema-level one above: a
        density is a measurement, and converting it too would make `Numeric`
        mean "number" rather than "money"."""
        from sqlalchemy import Float

        from app.models.material import MaterialType

        assert isinstance(MaterialType.__table__.c.typical_density.type, Float)
