"""The shop's default postage service, a product's override, and service fit (T035)."""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.consumable import ConsumableType
from app.models.shipping_profile import ShippingProfile
from app.services import postage as postage_module
from app.services.dims import Dims, Parcel
from app.services.postage import (
    PREFERRED_SERVICE_DOES_NOT_FIT,
    OrderPlan,
    PlannedParcel,
    _price,
    postage_for_order,
    preferred_service_for,
    services_fitting,
)

ON = date(2026, 11, 4)
TENANT_ID = uuid.uuid4()


def _profile(
    service, cost, *, limits=None, low=0, high=2000, zone="domestic", carrier="canada_post"
):
    lengths = dict(zip(("max_length_mm", "max_width_mm", "max_height_mm"), limits or (None,) * 3))
    return ShippingProfile(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        name=service,
        destination_zone=zone,
        weight_bracket_min_grams=Decimal(low),
        weight_bracket_max_grams=Decimal(high) if high is not None else None,
        postage_cost=Decimal(cost),
        effective_from=date(2026, 1, 1),
        catalogue_carrier=carrier,
        service=service,
        tariff_version=date(2026, 1, 1) if carrier else None,
        **{k: (Decimal(v) if v is not None else None) for k, v in lengths.items()},
    )


SMALL = _profile("small_packet", "9.00", limits=("400", "300", "200"))
EXPEDITED = _profile("expedited_parcel", "21.00")
LETTER = _profile("lettermail", "2.61", limits=("380", "270", "20"), high=500)
PROFILES = [LETTER, SMALL, EXPEDITED]


def _parcel(grams="300", outer=("200", "150", "100")):
    return Parcel(grams=Decimal(grams), outer=Dims(*(Decimal(v) for v in outer)) if outer else None)


def _tenant(default=None):
    settings = {"postage": {"carrier": "canada_post", "default_service": default}}
    return SimpleNamespace(id=TENANT_ID, settings=settings, currency_code="CAD")


class TestPreferredServiceInPrice:
    def test_no_preference_keeps_the_cheapest_fitting(self):
        found = _price(PROFILES, _parcel(), zone="domestic", as_of=ON)
        assert found.amount == Decimal("9.00")
        assert found.notes == ()

    def test_preferred_service_used_when_it_fits(self):
        found = _price(
            PROFILES,
            _parcel(),
            zone="domestic",
            as_of=ON,
            preferred_service="canada_post:expedited_parcel",
        )
        assert found.amount == Decimal("21.00")
        assert found.notes == ()

    def test_preferred_service_not_fitting_falls_back_and_says_so(self):
        found = _price(
            PROFILES,
            _parcel(),  # 100 mm thick: no Lettermail
            zone="domestic",
            as_of=ON,
            preferred_service="canada_post:lettermail",
        )
        assert found.amount == Decimal("9.00")
        assert found.notes == (PREFERRED_SERVICE_DOES_NOT_FIT,)

    def test_unknown_preferred_service_falls_back_and_says_so(self):
        found = _price(
            PROFILES, _parcel(), zone="domestic", as_of=ON, preferred_service="usps:priority_mail"
        )
        assert found.amount == Decimal("9.00")
        assert PREFERRED_SERVICE_DOES_NOT_FIT in found.notes

    def test_nothing_fits_is_still_unknown(self):
        found = _price(
            PROFILES,
            _parcel(grams="5000"),
            zone="domestic",
            as_of=ON,
            preferred_service="canada_post:small_packet",
        )
        assert found.amount is None and found.incomplete_reasons


class TestPreferenceResolution:
    def test_product_override_wins(self):
        product = SimpleNamespace(postage_service="canada_post:expedited_parcel")
        assert (
            preferred_service_for(_tenant("canada_post:small_packet"), product)
            == "canada_post:expedited_parcel"
        )

    def test_shop_default_otherwise(self):
        product = SimpleNamespace(postage_service=None)
        assert preferred_service_for(_tenant("canada_post:small_packet"), product) == (
            "canada_post:small_packet"
        )

    def test_nothing_set(self):
        assert preferred_service_for(SimpleNamespace(settings={}), None) is None


def _product(service=None):
    return SimpleNamespace(id=uuid.uuid4(), sku="P", weight_grams=300, postage_service=service)


@pytest.fixture
def one_parcel(monkeypatch):
    async def profiles(db, tenant):
        return PROFILES

    async def plan(db, tenant, lines):
        return OrderPlan(
            (
                PlannedParcel(
                    container=None,  # type: ignore[arg-type]
                    packing=(),
                    contents=((0, 1),),
                    parcel=_parcel(),
                ),
            )
        )

    monkeypatch.setattr(postage_module, "_profiles", profiles)
    monkeypatch.setattr(postage_module, "plan_order_parcels", plan)


@pytest.mark.usefixtures("one_parcel")
class TestOrderPostageUsesThePreference:
    @pytest.mark.asyncio
    async def test_single_product_uses_its_override(self):
        found = await postage_for_order(
            None,
            _tenant("canada_post:small_packet"),
            [(_product("canada_post:expedited_parcel"), 1)],
            as_of=ON,
            zone="domestic",
        )
        assert found.amount == Decimal("21.00")

    @pytest.mark.asyncio
    async def test_single_product_without_override_uses_shop_default(self):
        found = await postage_for_order(
            None,
            _tenant("canada_post:expedited_parcel"),
            [(_product(), 1)],
            as_of=ON,
            zone="domestic",
        )
        assert found.amount == Decimal("21.00")

    @pytest.mark.asyncio
    async def test_multi_product_order_uses_shop_default(self):
        found = await postage_for_order(
            None,
            _tenant("canada_post:small_packet"),
            [(_product("canada_post:expedited_parcel"), 1), (_product(), 1)],
            as_of=ON,
            zone="domestic",
        )
        assert found.amount == Decimal("9.00")

    @pytest.mark.asyncio
    async def test_no_preference_is_unchanged(self):
        found = await postage_for_order(
            None, SimpleNamespace(id=TENANT_ID, settings={}), [(_product(), 1)], as_of=ON
        )
        assert found.amount == Decimal("9.00")
        assert found.notes == ()


def _box(inner, wall="3", kind="box"):
    l_, w, h = (Decimal(v) if v is not None else None for v in inner)
    return ConsumableType(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        sku="BOX",
        name="Box",
        packaging_kind=kind,
        inner_length_mm=l_,
        inner_width_mm=w,
        inner_height_mm=h,
        wall_mm=Decimal(wall) if wall else None,
        empty_weight_grams=Decimal("50"),
    )


class TestServicesFitting:
    def test_excludes_services_the_outer_size_exceeds(self):
        # 390 x 290 x 190 outer: fits Small Packet (400x300x200), not Lettermail.
        box = _box(("384", "284", "184"))
        assert services_fitting(box, PROFILES, ON) == [
            "canada_post:expedited_parcel",
            "canada_post:small_packet",
        ]

    def test_wall_counts_twice(self):
        # Inner 398 fits 400 alone, but not with 2 x 3 mm wall.
        box = _box(("398", "100", "100"))
        assert "canada_post:small_packet" not in services_fitting(box, PROFILES, ON)

    def test_flat_mailer_fits_lettermail(self):
        mailer = _box(("250", "180", "10"), wall="2", kind="mailer")
        assert "canada_post:lettermail" in services_fitting(mailer, PROFILES, ON)

    def test_void_fill_and_incomplete_box_fit_nothing(self):
        assert services_fitting(_box(("100", "100", "100"), kind="void_fill"), PROFILES, ON) == []
        assert services_fitting(_box((None, None, None)), PROFILES, ON) == []

    def test_profiles_without_a_service_or_out_of_force_are_ignored(self):
        operator = _profile(None, "5.00", carrier=None)
        closed = _profile("old_service", "5.00")
        closed.effective_to = date(2026, 2, 1)
        assert services_fitting(_box(("100", "100", "100")), [operator, closed], ON) == []
