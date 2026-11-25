"""Tests for the SalesChannel Pydantic schemas.

The blended `fee_percentage`/`fee_fixed` pair these schemas used to carry was
removed with the columns behind it (task T123). A channel's fees are its
`fee_rules`, which have their own schemas and their own tests; what remains
here is the channel itself.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.sales_channel import SalesChannelBase, SalesChannelCreate, SalesChannelUpdate


def valid_channel(**kwargs) -> dict:
    defaults = {
        "name": "My Etsy Shop",
        "platform_type": "etsy",
    }
    defaults.update(kwargs)
    return defaults


class TestSalesChannelBase:
    def test_valid_minimal(self):
        c = SalesChannelBase(**valid_channel())
        assert c.name == "My Etsy Shop"
        assert c.monthly_cost == Decimal("0")
        assert c.is_active is True

    def test_name_empty_raises(self):
        with pytest.raises(ValidationError):
            SalesChannelBase(**valid_channel(name=""))

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            SalesChannelBase(**valid_channel(name="N" * 101))

    def test_monthly_cost_zero_accepted(self):
        c = SalesChannelBase(**valid_channel(monthly_cost=Decimal("0")))
        assert c.monthly_cost == Decimal("0")

    def test_monthly_cost_negative_raises(self):
        with pytest.raises(ValidationError):
            SalesChannelBase(**valid_channel(monthly_cost=Decimal("-5")))

    def test_is_active_default_true(self):
        c = SalesChannelBase(**valid_channel())
        assert c.is_active is True

    def test_is_active_false(self):
        c = SalesChannelBase(**valid_channel(is_active=False))
        assert c.is_active is False


class TestSalesChannelCreate:
    def test_inherits_from_base(self):
        c = SalesChannelCreate(**valid_channel())
        assert c.name == "My Etsy Shop"


class TestSalesChannelUpdate:
    def test_all_optional(self):
        u = SalesChannelUpdate()
        assert u.name is None
        assert u.monthly_cost is None
        assert u.is_active is None

    def test_partial_update(self):
        u = SalesChannelUpdate(monthly_cost=Decimal("5.0"), is_active=False)
        assert u.monthly_cost == Decimal("5.0")
        assert u.is_active is False

    def test_name_empty_raises(self):
        with pytest.raises(ValidationError):
            SalesChannelUpdate(name="")
