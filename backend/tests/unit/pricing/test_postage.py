"""Postage is one parcel per order, by zone and date, and a gap is reported (T257)."""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.shipping_profile import ShippingProfile
from app.services import postage as postage_module
from app.services.postage import (
    Postage,
    freeze_order_postage,
    postage_for_grams,
    postage_for_order,
    zone_for_destination,
)

TENANT = SimpleNamespace(id=uuid.uuid4())


def _profile(zone, low, high, cost, *, start=date(2026, 1, 1), end=None):
    return ShippingProfile(
        id=uuid.uuid4(),
        tenant_id=TENANT.id,
        name=f"{zone} {low}-{high}",
        destination_zone=zone,
        weight_bracket_min_grams=Decimal(low),
        weight_bracket_max_grams=Decimal(high) if high is not None else None,
        postage_cost=Decimal(cost),
        effective_from=start,
        effective_to=end,
    )


PROFILES = [
    _profile("domestic", 0, 500, "3.00", end=date(2026, 6, 30)),
    _profile("domestic", 0, 500, "3.50", start=date(2026, 7, 1)),
    _profile("domestic", 500, 2000, "6.00"),
    _profile("us", 0, 2000, "12.00"),
]


@pytest.fixture(autouse=True)
def _profiles(monkeypatch):
    async def fake(db, tenant):
        return PROFILES

    monkeypatch.setattr(postage_module, "_profiles", fake)


def _product(grams):
    return SimpleNamespace(id=uuid.uuid4(), sku="P", weight_grams=grams)


class TestAGapIsUnknownNotZero:
    @pytest.mark.asyncio
    async def test_no_weight(self) -> None:
        found = await postage_for_grams(None, TENANT, None)
        assert found.amount is None and found.incomplete_reasons

    @pytest.mark.asyncio
    async def test_no_profile_covers_the_parcel(self) -> None:
        found = await postage_for_grams(None, TENANT, Decimal("5000"), date(2026, 8, 1))
        assert found.amount is None
        assert "unknown rather than zero" in found.incomplete_reasons[0]


class TestItReadsTheDateAsked:
    @pytest.mark.asyncio
    async def test_a_past_date_reads_the_postage_in_force_then(self) -> None:
        assert (
            await postage_for_grams(None, TENANT, Decimal("200"), date(2026, 3, 1))
        ).amount == Decimal("3.00")
        assert (
            await postage_for_grams(None, TENANT, Decimal("200"), date(2026, 8, 1))
        ).amount == Decimal("3.50")


class TestItResolvesByZone:
    @pytest.mark.asyncio
    async def test_a_known_zone_prices_by_that_zone(self) -> None:
        found = await postage_for_grams(None, TENANT, Decimal("200"), date(2026, 8, 1), zone="us")
        assert found.amount == Decimal("12.00") and found.zone == "us"

    def test_a_destination_names_a_zone_only_when_spelled_the_same(self) -> None:
        assert zone_for_destination("US", PROFILES) == "us"
        assert zone_for_destination("France", PROFILES) is None


class TestAnOrderIsOneParcel:
    @pytest.mark.asyncio
    async def test_lines_are_weighed_together(self) -> None:
        found = await postage_for_order(None, TENANT, [(_product(300), 2)], as_of=date(2026, 8, 1))
        # 600 g is one parcel in the 500-2000 bracket, not two 300 g parcels.
        assert found.amount == Decimal("6.00")

    @pytest.mark.asyncio
    async def test_a_weightless_product_makes_the_parcel_unknown(self) -> None:
        found = await postage_for_order(None, TENANT, [(_product(None), 1)])
        assert found.amount is None

    @pytest.mark.asyncio
    async def test_the_destination_picks_the_zone(self) -> None:
        found = await postage_for_order(
            None, TENANT, [(_product(300), 1)], as_of=date(2026, 8, 1), destination="us"
        )
        assert found.amount == Decimal("12.00")


class TestFreezingOnAnOrder:
    @pytest.mark.asyncio
    async def test_a_known_parcel_is_recorded_as_derived(self) -> None:
        order = SimpleNamespace(shipping_country=None, postage_paid=None, actuals_source=None)
        found = await freeze_order_postage(None, TENANT, order, [(_product(300), 1)])
        assert order.postage_paid == found.amount and found.known
        assert order.actuals_source == "derived"

    @pytest.mark.asyncio
    async def test_a_line_with_no_product_leaves_postage_unrecorded(self) -> None:
        order = SimpleNamespace(
            shipping_country=None, postage_paid=Decimal("9"), actuals_source=None
        )
        found = await freeze_order_postage(None, TENANT, order, [(None, 1)])
        assert order.postage_paid is None and not found.known
        assert order.actuals_source is None


def test_or_zero_keeps_the_reason_separate() -> None:
    gap = Postage(None, reason="why")
    assert gap.or_zero() == Decimal("0") and gap.incomplete_reasons == ["why"]
