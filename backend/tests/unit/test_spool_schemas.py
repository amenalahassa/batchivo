"""
Tests for Spool Pydantic schemas.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.spool import SpoolBase, SpoolCreate, SpoolUpdate


def valid_spool(**kwargs) -> dict:
    defaults = {
        "spool_id": "SPOOL-001",
        "filament_type_id": uuid4(),
        "initial_weight": 1000.0,
        "current_weight": 750.0,
    }
    defaults.update(kwargs)
    return defaults


class TestSpoolBase:
    def test_valid_minimal(self):
        s = SpoolBase(**valid_spool())
        assert s.spool_id == "SPOOL-001"
        assert s.is_active is True
        assert s.is_labeled is False

    def test_spool_id_empty_raises(self):
        with pytest.raises(ValidationError):
            SpoolBase(**valid_spool(spool_id=""))

    def test_spool_id_too_long_raises(self):
        with pytest.raises(ValidationError):
            SpoolBase(**valid_spool(spool_id="S" * 51))

    # --- filament_type_id ---
    def test_filament_type_id_required(self):
        data = valid_spool()
        del data["filament_type_id"]
        with pytest.raises(ValidationError):
            SpoolCreate(**data)

    # --- is_labeled ---
    def test_is_labeled_defaults_false(self):
        """DATA-05: is_labeled defaults to False for new spools."""
        s = SpoolBase(**valid_spool())
        assert s.is_labeled is False

    def test_is_labeled_can_be_set_true(self):
        s = SpoolBase(**valid_spool(is_labeled=True))
        assert s.is_labeled is True

    # --- Weight ---
    def test_initial_weight_zero_raises(self):
        with pytest.raises(ValidationError):
            SpoolBase(**valid_spool(initial_weight=0))

    def test_initial_weight_negative_raises(self):
        with pytest.raises(ValidationError):
            SpoolBase(**valid_spool(initial_weight=-100))

    def test_current_weight_zero_accepted(self):
        s = SpoolBase(**valid_spool(current_weight=0))
        assert s.current_weight == 0

    def test_current_weight_negative_raises(self):
        with pytest.raises(ValidationError):
            SpoolBase(**valid_spool(current_weight=-1))

    def test_purchase_price_zero_accepted(self):
        s = SpoolBase(**valid_spool(purchase_price=0))
        assert s.purchase_price == 0

    def test_purchase_price_negative_raises(self):
        with pytest.raises(ValidationError):
            SpoolBase(**valid_spool(purchase_price=-1.0))


class TestSpoolCreate:
    def test_inherits_from_base(self):
        s = SpoolCreate(**valid_spool())
        assert s.spool_id == "SPOOL-001"

    def test_filament_type_id_present(self):
        ft_id = uuid4()
        s = SpoolCreate(**valid_spool(filament_type_id=ft_id))
        assert s.filament_type_id == ft_id


class TestSpoolUpdate:
    def test_all_optional(self):
        u = SpoolUpdate()
        assert u.filament_type_id is None
        assert u.current_weight is None
        assert u.is_active is None

    def test_partial_update(self):
        u = SpoolUpdate(current_weight=500.0, is_active=False)
        assert u.current_weight == 500.0
        assert u.is_active is False

    def test_current_weight_negative_raises(self):
        with pytest.raises(ValidationError):
            SpoolUpdate(current_weight=-1.0)

    def test_spool_id_empty_raises(self):
        with pytest.raises(ValidationError):
            SpoolUpdate(spool_id="")

    def test_is_labeled_update(self):
        u = SpoolUpdate(is_labeled=True)
        assert u.is_labeled is True


class TestThePurchasePriceIsExact:
    """`purchase_price` was `Optional[float]` on all three schemas while the
    column behind it was already `Numeric` (task T152).

    It is not an idle figure. `landed_cost.py` divides it across a batch of
    spools to apportion shipping and duty, and `costing.py:cost_per_gram`
    divides it by the spool's initial weight to reach the per-gram price every
    material line on every model is costed from. Both of those are exact. The
    schema was the one lossy step in the chain: an operator typing 24.99 got
    24.989999999999998, and the error was already in the per-gram figure before
    the engine had done any arithmetic (FR-047, Constitution IV).
    """

    def test_an_entered_price_is_a_decimal(self):
        s = SpoolBase(**valid_spool(purchase_price="24.99"))

        assert isinstance(s.purchase_price, Decimal)
        assert s.purchase_price == Decimal("24.99")

    def test_the_figure_an_operator_typed_is_the_figure_stored(self):
        """The one that a binary double cannot hold. Under `float` this
        comparison failed in the fifteenth decimal place, which is invisible
        until it is divided by 1000 grams and multiplied by a few hundred
        prints."""
        s = SpoolBase(**valid_spool(purchase_price="24.99"))

        assert str(s.purchase_price) == "24.99"
        assert s.purchase_price - Decimal("24.99") == Decimal("0")

    def test_a_json_number_is_still_accepted_from_an_older_client(self):
        """Pydantic coerces it. Converting the annotation must not break a
        caller that was sending `24.99` unquoted before the schema changed —
        the point of the task is exactness downstream, not a new 422."""
        s = SpoolBase(**valid_spool(purchase_price=24.99))

        assert isinstance(s.purchase_price, Decimal)
        assert s.purchase_price == Decimal("24.99")

    def test_it_crosses_the_wire_as_a_decimal_string(self):
        """Which is what the exactness is for: a JSON number is parsed back
        into a double by whatever reads it, undoing the whole change."""
        s = SpoolBase(**valid_spool(purchase_price="24.99"))

        assert s.model_dump(mode="json")["purchase_price"] == "24.99"

    def test_more_than_two_decimal_places_is_refused(self):
        """A spool has one price, in whole pence. A third decimal place here is
        a typo or a unit confusion, not a precision the operator meant."""
        with pytest.raises(ValidationError):
            SpoolBase(**valid_spool(purchase_price="24.999"))

    def test_an_update_carries_the_same_exactness(self):
        u = SpoolUpdate(purchase_price="24.99")

        assert isinstance(u.purchase_price, Decimal)
        assert u.purchase_price == Decimal("24.99")

    def test_an_update_refuses_a_negative_price(self):
        with pytest.raises(ValidationError):
            SpoolUpdate(purchase_price="-1.00")

    def test_a_spool_with_no_price_recorded_is_still_valid(self):
        """Most spools predate anyone recording what they cost, and
        `landed_cost.py` treats the absence as unknown rather than as free."""
        s = SpoolBase(**valid_spool())

        assert s.purchase_price is None
