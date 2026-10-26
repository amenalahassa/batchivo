"""Postage priced from the packed parcel (T044, T045, T060; research D9).

``build_parcel`` is the one place a parcel is assembled; ``_price`` picks a
size-limited profile before a weight-only one; an order's units are packed by
the advisor. Where no packaging or size class is recorded, the figure is the
one postage gave before.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.consumable import ConsumableType
from app.models.order import Order
from app.models.product import Product
from app.models.shipping_profile import ShippingProfile
from app.services import postage
from app.services.dims import Dims, Parcel
from app.services.postage import (
    NO_PACKAGING_RECORDED,
    ORDER_PACKING_UNAVAILABLE,
    _price,
    build_parcel,
    freeze_order_postage,
    postage_for_order,
)
from tests.utils.packaging import make_box, make_void_fill, set_dims

ON = date(2026, 6, 1)


def _d(*values) -> Dims:
    return Dims(*(Decimal(str(v)) for v in values))


def _box(name="Box M", inner=(150, 100, 60), weight="40", wall="3", kind="box") -> ConsumableType:
    length, width, height = inner if inner else (None, None, None)
    return ConsumableType(
        name=name,
        packaging_kind=kind,
        inner_length_mm=None if length is None else Decimal(str(length)),
        inner_width_mm=None if width is None else Decimal(str(width)),
        inner_height_mm=None if height is None else Decimal(str(height)),
        wall_mm=None if wall is None else Decimal(wall),
        empty_weight_grams=None if weight is None else Decimal(weight),
    )


def _profile(
    name: str,
    cost: str,
    low: str = "0",
    high: str | None = None,
    limits: tuple | None = None,
    divisor: str | None = None,
    zone: str = "domestic",
) -> ShippingProfile:
    length, width, height = (Decimal(str(v)) for v in limits) if limits else (None, None, None)
    return ShippingProfile(
        name=name,
        destination_zone=zone,
        weight_bracket_min_grams=Decimal(low),
        weight_bracket_max_grams=None if high is None else Decimal(high),
        postage_cost=Decimal(cost),
        effective_from=date(2026, 1, 1),
        max_length_mm=length,
        max_width_mm=width,
        max_height_mm=height,
        volumetric_divisor=None if divisor is None else Decimal(divisor),
    )


def _parcel(grams, outer=None) -> Parcel:
    return Parcel(grams=Decimal(str(grams)), outer=_d(*outer) if outer else None)


# ============================================
# build_parcel
# ============================================


class TestBuildParcel:
    def test_sums_items_and_packaging(self) -> None:
        parcel = build_parcel([(Decimal("180"), 1)], [(_box(), 1)])
        assert parcel.grams == Decimal("220")
        assert parcel.outer == _d(156, 106, 66)

    def test_quantities_multiply(self) -> None:
        fill = _box(name="Paper", inner=None, weight="5", wall=None, kind="void_fill")
        parcel = build_parcel([(Decimal("100"), 3)], [(_box(), 1), (fill, 2)])
        assert parcel.grams == Decimal("350")

    def test_an_unknown_item_weight_is_unknown_not_zero(self) -> None:
        parcel = build_parcel([(None, 1)], [(_box(), 1)])
        assert parcel.grams is None
        assert parcel.reasons

    def test_a_box_without_weight_is_unknown(self) -> None:
        parcel = build_parcel([(Decimal("180"), 1)], [(_box(weight=None), 1)])
        assert parcel.grams is None
        assert "Box M has no empty weight" in parcel.reasons[0]

    def test_unweighed_void_fill_counts_as_nothing_and_says_so(self) -> None:
        fill = _box(name="Paper", inner=None, weight=None, wall=None, kind="void_fill")
        parcel = build_parcel([(Decimal("180"), 1)], [(_box(), 1), (fill, 2)])
        assert parcel.grams == Decimal("220")
        assert any("Paper" in r for r in parcel.reasons)

    def test_wall_three_adds_six_per_axis(self) -> None:
        assert build_parcel([], [(_box(wall="3"), 1)]).outer == _d(156, 106, 66)

    def test_no_wall_is_taken_as_zero_and_said(self) -> None:
        parcel = build_parcel([], [(_box(wall=None), 1)])
        assert parcel.outer == _d(150, 100, 60)
        assert any("wall" in r for r in parcel.reasons)


# ============================================
# Choosing a profile
# ============================================


class TestPrice:
    def test_the_packed_weight_picks_the_bracket(self) -> None:
        profiles = [_profile("Light", "3.00", "0", "200"), _profile("Heavy", "4.50", "200", "500")]
        parcel = build_parcel([(Decimal("180"), 1)], [(_box(), 1)])
        assert _price(profiles, parcel, zone=None, as_of=ON).amount == Decimal("4.50")

    def test_weight_only_profiles_keep_todays_order(self) -> None:
        """H1: the first by bracket wins, as before, even when another is cheaper."""
        profiles = [_profile("A", "5.00", "0", "1000"), _profile("B", "3.00", "100", "1000")]
        assert _price(profiles, _parcel(500), zone=None, as_of=ON).amount == Decimal("5.00")

    def test_size_classes_first_cheapest_first(self) -> None:
        profiles = [
            _profile("Parcel", "4.00", "0", "2000"),
            _profile("Small parcel", "3.50", "0", "2000", limits=(450, 350, 160)),
            _profile("Large letter", "2.70", "0", "750", limits=(353, 250, 25)),
        ]
        small = _price(profiles, _parcel(300, (160, 110, 70)), zone=None, as_of=ON)
        assert small.amount == Decimal("3.50")
        letter = _price(profiles, _parcel(100, (250, 353, 20)), zone=None, as_of=ON)
        assert letter.amount == Decimal("2.70")

    def test_too_deep_for_a_large_letter(self) -> None:
        profiles = [
            _profile("Large letter", "2.70", "0", "750", limits=(353, 250, 25)),
            _profile("Parcel", "4.00", "0", "2000"),
        ]
        found = _price(profiles, _parcel(100, (300, 200, 30)), zone=None, as_of=ON)
        assert found.amount == Decimal("4.00")

    def test_volumetric_weight_moves_the_bracket(self) -> None:
        profiles = [
            _profile("Up to 2 kg", "4.00", "0", "2000", divisor="5000"),
            _profile("2-10 kg", "9.00", "2000", "10000", divisor="5000"),
        ]
        # 400 × 300 × 200 mm = 24 000 cm³ / 5000 = 4.8 kg chargeable.
        found = _price(profiles, _parcel(1000, (400, 300, 200)), zone=None, as_of=ON)
        assert found.amount == Decimal("9.00")
        assert profiles[1].chargeable_grams(_parcel(1000, (400, 300, 200))) == Decimal("4800")

    def test_a_size_class_never_matches_an_unknown_size(self) -> None:
        profiles = [_profile("Large letter", "2.70", "0", "750", limits=(353, 250, 25))]
        found = _price(profiles, _parcel(100), zone=None, as_of=ON)
        assert found.amount is None
        assert "unknown rather than zero" in found.reason

    def test_a_weight_only_profile_ignores_the_size(self) -> None:
        profiles = [_profile("Parcel", "4.00", "0", "2000")]
        assert _price(profiles, _parcel(100, (900, 900, 900)), zone=None, as_of=ON).amount == (
            Decimal("4.00")
        )

    def test_an_unknown_weight_says_why(self) -> None:
        parcel = build_parcel([(Decimal("180"), 1)], [(_box(weight=None), 1)])
        found = _price([_profile("Parcel", "4.00")], parcel, zone=None, as_of=ON)
        assert found.amount is None
        assert "no empty weight" in found.reason


# ============================================
# Orders, through the database
# ============================================


async def _product(db, tenant, sku, weight=180, dims=None, packaging=None) -> Product:
    product = Product(id=uuid4(), tenant_id=tenant.id, sku=sku, name=sku, weight_grams=weight)
    if dims is not None:
        set_dims(product, *dims)
    if packaging is not None:
        product.packaging_consumable_id = packaging.id
        product.packaging_quantity = 1
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


async def _profiles(db, tenant, *profiles: ShippingProfile) -> None:
    for profile in profiles:
        profile.tenant_id = tenant.id
        db.add(profile)
    await db.commit()


@pytest.mark.asyncio
class TestOrders:
    async def test_one_unit_uses_its_packaging(self, db_session, test_tenant) -> None:
        box = await make_box(db_session, test_tenant, "Box M", (150, 100, 60), weight=40, wall=3)
        product = await _product(db_session, test_tenant, "DRG-1", packaging=box)
        await _profiles(
            db_session,
            test_tenant,
            _profile("Light", "3.00", "0", "200"),
            _profile("Heavy", "4.50", "200", "500"),
        )

        found = await postage_for_order(db_session, test_tenant, [(product, 1)], as_of=ON)
        assert found.amount == Decimal("4.50")  # 180 g + 40 g box
        assert found.notes == ()

    async def test_no_packaging_is_weight_only_and_said(self, db_session, test_tenant) -> None:
        product = await _product(db_session, test_tenant, "DRG-1")
        await _profiles(db_session, test_tenant, _profile("Light", "3.00", "0", "200"))

        found = await postage_for_order(db_session, test_tenant, [(product, 1)], as_of=ON)
        assert found.amount == Decimal("3.00")
        assert found.notes == (NO_PACKAGING_RECORDED,)

    async def test_three_of_one_line_never_use_the_single_unit_box(
        self, db_session, test_tenant
    ) -> None:
        """H2, now through the advisor: three units go in a box that holds three."""
        small = await make_box(db_session, test_tenant, "Small", (60, 60, 60), weight=10)
        large = await make_box(db_session, test_tenant, "Large", (200, 100, 60), weight=50)
        product = await _product(
            db_session, test_tenant, "DRG-1", weight=100, dims=(40, 40, 40), packaging=small
        )
        await _profiles(
            db_session,
            test_tenant,
            _profile("Light", "3.00", "0", "300"),
            _profile("Heavy", "4.50", "300", "1000"),
        )

        found = await postage_for_order(db_session, test_tenant, [(product, 3)], as_of=ON)
        # 3 × 100 g + the 50 g large box -- not the small box's 10 g.
        assert found.amount == Decimal("4.50")
        plan = await postage.plan_order_parcels(db_session, test_tenant, [(product, 3)])
        assert [p.container.id for p in plan.parcels] == [large.id]

    async def test_two_lines_are_packed_together(self, db_session, test_tenant) -> None:
        box = await make_box(db_session, test_tenant, "Box", (200, 100, 60), weight=50)
        a = await _product(db_session, test_tenant, "A", weight=100, dims=(40, 40, 40))
        b = await _product(db_session, test_tenant, "B", weight=100, dims=(40, 40, 40))
        await _profiles(db_session, test_tenant, _profile("Parcel", "4.00", "0", "1000"))

        plan = await postage.plan_order_parcels(db_session, test_tenant, [(a, 1), (b, 1)])
        assert len(plan.parcels) == 1
        assert plan.parcels[0].container.id == box.id
        assert plan.parcels[0].parcel.grams == Decimal("250")

    async def test_a_split_order_sums_two_parcels(self, db_session, test_tenant) -> None:
        await make_box(db_session, test_tenant, "Box", (70, 70, 70), weight=20)
        product = await _product(db_session, test_tenant, "BIG", weight=100, dims=(45, 45, 45))
        await _profiles(db_session, test_tenant, _profile("Parcel", "4.00", "0", "1000"))

        found = await postage_for_order(db_session, test_tenant, [(product, 2)], as_of=ON)
        assert found.amount == Decimal("8.00")

    async def test_a_line_without_dimensions_stays_weight_only(
        self, db_session, test_tenant
    ) -> None:
        await make_box(db_session, test_tenant, "Box", (200, 100, 60), weight=50)
        product = await _product(db_session, test_tenant, "NODIMS", weight=100)
        await _profiles(db_session, test_tenant, _profile("Parcel", "4.00", "0", "1000"))

        found = await postage_for_order(db_session, test_tenant, [(product, 2)], as_of=ON)
        assert found.amount == Decimal("4.00")
        assert found.notes == (ORDER_PACKING_UNAVAILABLE,)
        plan = await postage.plan_order_parcels(db_session, test_tenant, [(product, 2)])
        assert plan.warnings == ({"code": "dimensions_required", "sku": "NODIMS"},)

    async def test_void_fill_weight_is_in_the_parcel(self, db_session, test_tenant) -> None:
        await make_box(db_session, test_tenant, "Box", (200, 100, 60), weight=50)
        await make_void_fill(db_session, test_tenant, fill_volume_ml=500, weight=4)
        a = await _product(db_session, test_tenant, "A", weight=100, dims=(40, 40, 40))

        plan = await postage.plan_order_parcels(db_session, test_tenant, [(a, 2)])
        packed = plan.parcels[0]
        fill_units = sum(q for c, q in packed.packing if c.packaging_kind == "void_fill")
        assert fill_units > 0
        assert packed.parcel.grams == Decimal("250") + Decimal("4") * fill_units


@pytest.mark.asyncio
class TestHistory:
    async def test_a_settled_orders_postage_does_not_move(self, db_session, test_tenant) -> None:
        order = Order(
            tenant_id=test_tenant.id,
            order_number=f"ORD-{uuid4().hex[:6]}",
            customer_email="a@example.com",
            customer_name="A",
            shipping_address_line1="1 Road",
            shipping_city="Town",
            shipping_postcode="AB1 2CD",
            shipping_country="domestic",
            shipping_method="Standard",
            subtotal=Decimal("20"),
            shipping_cost=Decimal("0"),
            total=Decimal("20"),
            postage_paid=Decimal("3.00"),
            actuals_source="derived",
        )
        db_session.add(order)
        await db_session.commit()

        await make_box(db_session, test_tenant, "Box", (200, 100, 60), weight=50)
        await _profiles(
            db_session,
            test_tenant,
            _profile("Large letter", "1.00", "0", "750", limits=(353, 250, 25)),
        )
        await db_session.refresh(order)
        assert order.postage_paid == Decimal("3.00")

    async def test_freezing_a_new_order_uses_the_packed_parcel(
        self, db_session, test_tenant
    ) -> None:
        box = await make_box(db_session, test_tenant, "Box M", (150, 100, 60), weight=40, wall=3)
        product = await _product(db_session, test_tenant, "DRG-1", packaging=box)
        await _profiles(
            db_session,
            test_tenant,
            _profile("Light", "3.00", "0", "200"),
            _profile("Heavy", "4.50", "200", "500"),
        )
        order = type("O", (), {"shipping_country": "domestic"})()

        found = await freeze_order_postage(db_session, test_tenant, order, [(product, 1)])
        assert found.amount == Decimal("4.50")
        assert order.postage_paid == Decimal("4.50")
        assert order.actuals_source == "derived"
