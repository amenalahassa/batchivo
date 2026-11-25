"""The Consumables and Packaging views of one table (spec 006 US1, T009).

Packaging stays a consumable with a ``packaging_kind`` (research D1): the
Packaging page asks for the packaging kinds, the Consumables page excludes
them. Both views keep working for rows created before this feature (FR-025).
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.consumable import ConsumableType
from app.models.product import Product
from app.models.shipping_profile import ShippingProfile
from app.models.tenant import Tenant
from tests.utils.packaging import make_box, make_void_fill

pytestmark = pytest.mark.asyncio

PACKAGING = "box,mailer,void_fill,wrap"


async def _magnet(db, tenant, name="Magnet 6x3") -> ConsumableType:
    row = ConsumableType(
        tenant_id=tenant.id, sku=f"MAG-{uuid4().hex[:6].upper()}", name=name, category="magnets"
    )
    db.add(row)
    await db.commit()
    return row


async def _list(client: AsyncClient, **params) -> list[dict]:
    response = await client.get("/api/v1/consumables/types", params={"page_size": 100, **params})
    assert response.status_code == 200, response.text
    return response.json()["consumables"]


class TestTwoViews:
    async def test_consumables_excludes_packaging(self, client, db_session, test_tenant):
        await make_box(db_session, test_tenant, "Box A", (100, 80, 60), weight=40)
        await make_box(db_session, test_tenant, "Box B", (200, 150, 100), weight=90)
        await make_void_fill(db_session, test_tenant, 500)
        for i in range(3):
            await _magnet(db_session, test_tenant, f"Magnet {i}")
        hardware = await _list(client, exclude_packaging="true")
        assert len(hardware) == 3
        assert all(c["packaging_kind"] is None for c in hardware)

    async def test_packaging_lists_only_packaging(self, client, db_session, test_tenant):
        await make_box(db_session, test_tenant, "Box A", (100, 80, 60), weight=40)
        await make_void_fill(db_session, test_tenant, 500)
        await _magnet(db_session, test_tenant)
        packaging = await _list(client, packaging_kind=PACKAGING)
        assert sorted(c["packaging_kind"] for c in packaging) == ["box", "void_fill"]

    async def test_a_row_from_before_the_feature_is_listed_unchanged(
        self, client, db_session, test_tenant
    ):
        box = await make_box(db_session, test_tenant, "Old box", (120, 90, 60), weight=50, cost=1)
        (row,) = await _list(client, packaging_kind=PACKAGING)
        assert row["id"] == str(box.id)
        assert row["from_catalogue"] is False and row["catalogue_key"] is None
        assert row["inner_length_mm"] == "120.0"
        assert Decimal(row["current_cost_per_unit"]) == Decimal("1")

    async def test_response_carries_catalogue_identity(self, client, db_session, test_tenant):
        box = await make_box(db_session, test_tenant, "Seeded", (100, 100, 100), weight=45)
        box.catalogue_key = "box-cube-100"
        box.catalogue_version = 1
        await db_session.commit()
        (row,) = await _list(client, packaging_kind=PACKAGING)
        assert row["from_catalogue"] is True
        assert row["catalogue_key"] == "box-cube-100"

    async def test_lists_products_that_ship_in_it(self, client, db_session, test_tenant):
        box = await make_box(db_session, test_tenant, "Box", (100, 100, 100), weight=45)
        db_session.add(
            Product(
                tenant_id=test_tenant.id, sku="DRG-1", name="Dragon", packaging_consumable_id=box.id
            )
        )
        await db_session.commit()
        (row,) = await _list(client, packaging_kind=PACKAGING)
        assert [p["sku"] for p in row["used_by_products"]] == ["DRG-1"]

    async def test_lists_the_services_a_container_fits(self, client, db_session, test_tenant):
        box = await make_box(db_session, test_tenant, "Box", (380, 280, 180), weight=45, wall=3)
        for service, limits in (
            ("small_packet", ("400", "300", "200")),
            ("lettermail", ("380", "270", "20")),
        ):
            db_session.add(
                ShippingProfile(
                    tenant_id=test_tenant.id,
                    name=service,
                    destination_zone="domestic",
                    weight_bracket_min_grams=Decimal("0"),
                    weight_bracket_max_grams=Decimal("2000"),
                    postage_cost=Decimal("9"),
                    effective_from=date(2026, 1, 1),
                    max_length_mm=Decimal(limits[0]),
                    max_width_mm=Decimal(limits[1]),
                    max_height_mm=Decimal(limits[2]),
                    catalogue_carrier="canada_post",
                    service=service,
                    tariff_version=date(2026, 1, 1),
                )
            )
        await db_session.commit()
        (row,) = await _list(client, packaging_kind=PACKAGING)
        assert row["fits_services"] == ["canada_post:small_packet"]
        detail = await client.get(f"/api/v1/consumables/types/{box.id}")
        assert detail.json()["fits_services"] == ["canada_post:small_packet"]

    async def test_void_fill_reports_its_fill_volume_origin(self, client, db_session, test_tenant):
        await make_void_fill(db_session, test_tenant, 500)
        (row,) = await _list(client, packaging_kind=PACKAGING)
        assert row["packaging_provenance"]["fill_volume_ml"] == "assumed"
        assert row["fits_services"] == []

    async def test_other_tenants_rows_are_never_listed(self, client, db_session, test_tenant):
        other = Tenant(id=uuid4(), name="Other", slug=f"o-{uuid4().hex[:8]}", settings={})
        db_session.add(other)
        await db_session.commit()
        await make_box(db_session, other, "Theirs", (100, 100, 100), weight=45)
        assert await _list(client, packaging_kind=PACKAGING) == []


class TestDeletingPackagingInUse:
    async def test_refused_with_the_products_named(self, client, db_session, test_tenant):
        box = await make_box(db_session, test_tenant, "Busy box", (100, 100, 100), weight=45)
        db_session.add(
            Product(
                tenant_id=test_tenant.id, sku="DRG-2", name="Wyvern", packaging_consumable_id=box.id
            )
        )
        await db_session.commit()
        response = await client.delete(f"/api/v1/consumables/types/{box.id}")
        assert response.status_code == 409
        assert "Wyvern (DRG-2)" in response.json()["detail"]

    async def test_unused_packaging_is_deleted(self, client, db_session, test_tenant):
        box = await make_box(db_session, test_tenant, "Idle box", (100, 100, 100), weight=45)
        assert (await client.delete(f"/api/v1/consumables/types/{box.id}")).status_code == 204


class TestValidationAndAuth:
    async def test_exclude_packaging_must_be_a_boolean(self, client):
        response = await client.get(
            "/api/v1/consumables/types", params={"exclude_packaging": "maybe"}
        )
        assert response.status_code == 422

    async def test_no_token_401(self, unauthenticated_client):
        response = await unauthenticated_client.get(
            "/api/v1/consumables/types", params={"exclude_packaging": "true"}
        )
        assert response.status_code == 401

    async def test_unknown_consumable_404(self, client):
        assert (await client.get(f"/api/v1/consumables/types/{uuid4()}")).status_code == 404
