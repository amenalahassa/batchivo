"""Order packaging suggestions and parcels confirmed at dispatch (T058, T062)."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consumable import ConsumableUsage
from app.models.order import Order, OrderItem, OrderStatus
from app.models.order_parcel import OrderParcel
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.shipping_profile import ShippingProfile
from app.models.tenant import Tenant
from app.models.user import UserRole
from tests.utils.packaging import make_box, make_void_fill, set_dims

pytestmark = pytest.mark.asyncio


async def _product(db, tenant, sku="DRG-01", weight=100, dims=(40, 40, 40), packaging=None):
    product = Product(id=uuid4(), tenant_id=tenant.id, sku=sku, name=sku, weight_grams=weight)
    if dims:
        set_dims(product, *dims)
    if packaging is not None:
        product.packaging_consumable_id = packaging.id
        product.packaging_quantity = 1
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


async def _order(db, tenant, *lines, postage_paid=None, actuals_source=None) -> Order:
    order = Order(
        tenant_id=tenant.id,
        order_number=f"ORD-PKG-{uuid4().hex[:6]}",
        status=OrderStatus.PROCESSING,
        customer_email="pack@example.com",
        customer_name="Pack Customer",
        shipping_address_line1="1 Box Lane",
        shipping_city="London",
        shipping_postcode="SW1A 1AA",
        shipping_country="domestic",
        shipping_method="Standard",
        subtotal=Decimal("40.00"),
        shipping_cost=Decimal("0"),
        total=Decimal("40.00"),
        postage_paid=postage_paid,
        actuals_source=actuals_source,
    )
    db.add(order)
    await db.flush()
    for product, quantity, sku in lines:
        db.add(
            OrderItem(
                tenant_id=tenant.id,
                order_id=order.id,
                product_id=product.id if product else None,
                product_sku=sku or (product.sku if product else "UNKNOWN"),
                product_name="Item",
                quantity=quantity,
                unit_price=Decimal("20.00"),
                total_price=Decimal("20.00") * quantity,
            )
        )
    await db.commit()
    return order


async def _profile(db, tenant, cost="3.95", high="2000") -> None:
    db.add(
        ShippingProfile(
            tenant_id=tenant.id,
            name="Parcel",
            destination_zone="domestic",
            weight_bracket_min_grams=Decimal("0"),
            weight_bracket_max_grams=Decimal(high),
            postage_cost=Decimal(cost),
            effective_from=date(2020, 1, 1),
        )
    )
    await db.commit()


async def _other_tenant_order(db) -> Order:
    other = Tenant(id=uuid4(), name="Other", slug=f"other-{uuid4().hex[:8]}", settings={})
    db.add(other)
    await db.commit()
    product = await _product(db, other, sku="OTHER")
    return await _order(db, other, (product, 1, None))


# ============================================
# Suggestions (US6)
# ============================================


class TestOrderSuggestions:
    async def test_two_units_packed_with_an_estimate(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        box = await make_box(db_session, test_tenant, "Box M", (200, 100, 60), weight=50, wall=3)
        product = await _product(db_session, test_tenant)
        await _profile(db_session, test_tenant)
        order = await _order(db_session, test_tenant, (product, 2, None))

        response = await client.get(f"/api/v1/orders/{order.id}/packaging-suggestions")

        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["parcels"]) == 1
        parcel = body["parcels"][0]
        assert parcel["consumable_id"] == str(box.id)
        assert parcel["contents"] == [
            {"product_id": str(product.id), "sku": "DRG-01", "quantity": 2}
        ]
        assert parcel["packed_weight_grams"] == "250.0"
        assert parcel["outer_mm"] == {
            "length_mm": "206.0",
            "width_mm": "106.0",
            "height_mm": "66.0",
        }
        assert body["estimated_postage"] == {
            "amount": "3.95",
            "zone": "domestic",
            "reason": None,
            "is_estimate": True,
            "notes": [],
        }

    async def test_a_variant_line_uses_the_variant_dimensions(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        await make_box(db_session, test_tenant, "Small", (100, 100, 100), weight=20)
        large = await make_box(db_session, test_tenant, "Large", (300, 300, 300), weight=80)
        product = await _product(db_session, test_tenant, dims=(40, 40, 40))
        variant = ProductVariant(
            tenant_id=test_tenant.id, product_id=product.id, size="XL", sku="DRG-01-XL"
        )
        set_dims(variant, 120, 120, 120)
        db_session.add(variant)
        await db_session.commit()
        await db_session.refresh(product, ["variants"])
        order = await _order(db_session, test_tenant, (product, 2, "DRG-01-XL"))

        body = (await client.get(f"/api/v1/orders/{order.id}/packaging-suggestions")).json()
        assert [p["consumable_id"] for p in body["parcels"]] == [str(large.id)]
        assert body["parcels"][0]["contents"][0]["sku"] == "DRG-01-XL"

    async def test_a_line_without_dimensions_is_named(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        await make_box(db_session, test_tenant, "Box", (200, 100, 60), weight=50)
        product = await _product(db_session, test_tenant, sku="NODIMS", dims=None)
        order = await _order(db_session, test_tenant, (product, 2, None))

        body = (await client.get(f"/api/v1/orders/{order.id}/packaging-suggestions")).json()
        assert body["parcels"] == []
        assert body["warnings"] == [{"code": "dimensions_required", "sku": "NODIMS"}]

    async def test_suggesting_writes_nothing(self, client: AsyncClient, db_session, test_tenant):
        await make_box(db_session, test_tenant, "Box", (200, 100, 60), weight=50)
        product = await _product(db_session, test_tenant)
        order = await _order(db_session, test_tenant, (product, 2, None))

        await client.get(f"/api/v1/orders/{order.id}/packaging-suggestions")
        parcels = (await db_session.execute(select(OrderParcel))).scalars().all()
        assert parcels == []

    async def test_unauthenticated_is_401(self, unauthenticated_client: AsyncClient) -> None:
        response = await unauthenticated_client.get(
            f"/api/v1/orders/{uuid4()}/packaging-suggestions"
        )
        assert response.status_code == 401

    async def test_another_tenants_order_is_404(self, client: AsyncClient, db_session) -> None:
        order = await _other_tenant_order(db_session)
        response = await client.get(f"/api/v1/orders/{order.id}/packaging-suggestions")
        assert response.status_code == 404


# ============================================
# Confirming at dispatch
# ============================================


async def _dispatch_setup(db, tenant, box_stock=12, fill_stock=10, **order_kw):
    box = await make_box(
        db, tenant, "Box M", (200, 100, 60), weight=50, wall=3, on_hand=box_stock, cost="0.80"
    )
    fill = await make_void_fill(db, tenant, fill_volume_ml=500, on_hand=fill_stock, weight=4)
    product = await _product(db, tenant)
    await _profile(db, tenant, cost="3.95")
    order = await _order(db, tenant, (product, 2, None), **order_kw)
    body = {
        "parcels": [
            {
                "items": [
                    {"consumable_id": str(box.id), "quantity": 1},
                    {"consumable_id": str(fill.id), "quantity": 2},
                ]
            }
        ]
    }
    return box, fill, order, body


class TestConfirmParcels:
    async def test_stores_parcels_takes_stock_and_derives_postage(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant
    ) -> None:
        box, fill, order, body = await _dispatch_setup(db_session, test_tenant)

        response = await client.post(f"/api/v1/orders/{order.id}/parcels", json=body)

        assert response.status_code == 201, response.text
        result = response.json()
        assert len(result["parcels"]) == 1
        parcel = result["parcels"][0]
        assert parcel["sequence"] == 1
        assert parcel["packed_weight_grams"] == "258.0"  # 2 × 100 + 50 + 2 × 4
        assert parcel["outer_length_mm"] == "206.0"
        assert {i["name"] for i in parcel["items"]} == {"Box M", "Paper fill"}
        assert result["postage"]["amount"] == "3.95"
        assert result["postage"]["is_estimate"] is False
        assert result["warnings"] == []

        await db_session.refresh(box)
        await db_session.refresh(fill)
        await db_session.refresh(order)
        assert box.quantity_on_hand == 11
        assert fill.quantity_on_hand == 8
        assert order.postage_paid == Decimal("3.95")
        assert order.actuals_source == "derived"

        usage = (
            (
                await db_session.execute(
                    select(ConsumableUsage).where(ConsumableUsage.order_id == order.id)
                )
            )
            .scalars()
            .all()
        )
        assert sorted((u.usage_type, u.quantity_used) for u in usage) == [
            ("shipping", 1),
            ("shipping", 2),
        ]
        box_usage = next(u for u in usage if u.consumable_type_id == box.id)
        assert box_usage.cost_at_use == Decimal("0.8")

        detail = (await client.get(f"/api/v1/orders/{order.id}")).json()
        assert len(detail["parcels"]) == 1
        assert detail["postage_is_estimate"] is False

    async def test_entered_postage_is_kept(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        _, _, order, body = await _dispatch_setup(
            db_session, test_tenant, postage_paid=Decimal("5.10"), actuals_source="entered"
        )
        assert (
            await client.post(f"/api/v1/orders/{order.id}/parcels", json=body)
        ).status_code == 201
        await db_session.refresh(order)
        assert order.postage_paid == Decimal("5.10")
        assert order.actuals_source == "entered"

    async def test_a_second_confirmation_is_409_and_takes_no_stock(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        box, _, order, body = await _dispatch_setup(db_session, test_tenant)
        await client.post(f"/api/v1/orders/{order.id}/parcels", json=body)

        response = await client.post(f"/api/v1/orders/{order.id}/parcels", json=body)
        assert response.status_code == 409
        await db_session.refresh(box)
        assert box.quantity_on_hand == 11

    async def test_stock_may_go_below_zero_with_a_warning(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        box, _, order, body = await _dispatch_setup(db_session, test_tenant, box_stock=0)

        response = await client.post(f"/api/v1/orders/{order.id}/parcels", json=body)
        assert response.status_code == 201
        assert response.json()["warnings"] == [
            {"code": "stock_below_zero", "consumable_id": str(box.id), "on_hand": -1}
        ]

    async def test_derived_postage_reads_as_an_estimate_until_confirmed(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        _, _, order, _ = await _dispatch_setup(
            db_session, test_tenant, postage_paid=Decimal("3.95"), actuals_source="derived"
        )
        detail = (await client.get(f"/api/v1/orders/{order.id}")).json()
        assert detail["parcels"] == []
        assert detail["postage_is_estimate"] is True

    async def test_invalid_bodies_are_422(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        box, fill, order, _ = await _dispatch_setup(db_session, test_tenant)
        url = f"/api/v1/orders/{order.id}/parcels"
        magnet = await make_box(db_session, test_tenant, "Magnet", kind="box")
        magnet.packaging_kind = None
        await db_session.commit()

        assert (await client.post(url, json={"parcels": []})).status_code == 422
        zero = {"parcels": [{"items": [{"consumable_id": str(box.id), "quantity": 0}]}]}
        assert (await client.post(url, json=zero)).status_code == 422
        not_packaging = {"parcels": [{"items": [{"consumable_id": str(magnet.id), "quantity": 1}]}]}
        assert (await client.post(url, json=not_packaging)).status_code == 422
        fill_only = {"parcels": [{"items": [{"consumable_id": str(fill.id), "quantity": 1}]}]}
        assert (await client.post(url, json=fill_only)).status_code == 422
        await db_session.refresh(box)
        assert box.quantity_on_hand == 12

    async def test_a_viewer_is_403(self, db_session, test_tenant, as_role) -> None:
        _, _, order, body = await _dispatch_setup(db_session, test_tenant)
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.post(f"/api/v1/orders/{order.id}/parcels", json=body)
        assert response.status_code == 403

    async def test_unauthenticated_is_401(self, unauthenticated_client: AsyncClient) -> None:
        response = await unauthenticated_client.post(
            f"/api/v1/orders/{uuid4()}/parcels",
            json={"parcels": [{"items": [{"consumable_id": str(uuid4()), "quantity": 1}]}]},
        )
        assert response.status_code == 401

    async def test_another_tenants_order_is_404(self, client: AsyncClient, db_session) -> None:
        order = await _other_tenant_order(db_session)
        response = await client.post(
            f"/api/v1/orders/{order.id}/parcels",
            json={"parcels": [{"items": [{"consumable_id": str(uuid4()), "quantity": 1}]}]},
        )
        assert response.status_code == 404

    async def test_two_parcels_are_weighed_with_their_own_contents(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        box, _, order, _ = await _dispatch_setup(db_session, test_tenant)
        item = {"consumable_id": str(box.id), "quantity": 1}
        body = {
            "parcels": [
                {"items": [item], "contents": [{"sku": "DRG-01", "quantity": 1}]},
                {"items": [item], "contents": [{"sku": "DRG-01", "quantity": 1}]},
            ]
        }

        result = (await client.post(f"/api/v1/orders/{order.id}/parcels", json=body)).json()
        assert [p["packed_weight_grams"] for p in result["parcels"]] == ["150.0", "150.0"]
        assert result["postage"]["amount"] == "7.90"
