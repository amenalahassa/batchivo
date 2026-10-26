"""Packaging advisor endpoints (feature 003, contracts/packaging-api.md).

Every endpoint is covered for success, 401 (no token), 403 (viewer, writes
only), 422 and 404, including another tenant's record (Constitution II).
"""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model import Model
from app.models.product import Product
from app.models.product_model import ProductModel
from app.models.product_variant import ProductVariant
from app.models.tenant import Tenant
from app.models.user import UserRole
from tests.utils.packaging import make_box, make_void_fill, make_wrap, set_dims

pytestmark = pytest.mark.asyncio

DIMS = {"length_mm": "120.0", "width_mm": "80.0", "height_mm": "45.0"}


async def _product(db: AsyncSession, tenant: Tenant, sku: str = "PKG-P1", **kw) -> Product:
    product = Product(id=uuid4(), tenant_id=tenant.id, sku=sku, name=sku, **kw)
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


async def _variant(
    db: AsyncSession, tenant: Tenant, product: Product, size: str = "L"
) -> ProductVariant:
    variant = ProductVariant(
        tenant_id=tenant.id, product_id=product.id, size=size, sku=f"{product.sku}-{size}"
    )
    db.add(variant)
    await db.commit()
    await db.refresh(variant)
    # The tests share one session with the app, so the product's loaded
    # collection must learn of the new row.
    await db.refresh(product, ["variants"])
    return variant


async def _model(db: AsyncSession, tenant: Tenant, sku: str = "PKG-M1") -> Model:
    model = Model(id=uuid4(), tenant_id=tenant.id, sku=sku, name=sku)
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


async def _other_tenant(db: AsyncSession) -> Tenant:
    tenant = Tenant(id=uuid4(), name="Other", slug=f"other-{uuid4().hex[:8]}", settings={})
    db.add(tenant)
    await db.commit()
    return tenant


# ============================================
# Dimensions (US1)
# ============================================


class TestDimensions:
    async def test_product_dimensions_are_saved_as_entered(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        product = await _product(db_session, test_tenant)
        response = await client.put(f"/api/v1/products/{product.id}/dimensions", json=DIMS)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["length_mm"] == "120.0" and body["height_mm"] == "45.0"
        assert body["source"] == "entered" and body["set_at"] is not None
        assert body["inherited"] is False

        detail = (await client.get(f"/api/v1/products/{product.id}")).json()
        assert detail["dimensions"]["width_mm"] == "80.0"
        assert detail["is_fragile"] is False

    async def test_clearing_dimensions(self, client: AsyncClient, db_session, test_tenant) -> None:
        product = await _product(db_session, test_tenant)
        await client.put(f"/api/v1/products/{product.id}/dimensions", json=DIMS)
        response = await client.put(
            f"/api/v1/products/{product.id}/dimensions",
            json={"length_mm": None, "width_mm": None, "height_mm": None},
        )
        assert response.status_code == 200
        assert response.json()["source"] is None
        detail = (await client.get(f"/api/v1/products/{product.id}")).json()
        assert detail["dimensions"] is None

    @pytest.mark.parametrize(
        "body",
        [
            {**DIMS, "length_mm": "0"},
            {**DIMS, "width_mm": "-1"},
            {**DIMS, "height_mm": "abc"},
            {**DIMS, "length_mm": "12.34"},
            {"length_mm": "10", "width_mm": "10"},
        ],
    )
    async def test_invalid_dimensions_are_refused_naming_the_field(
        self, client: AsyncClient, db_session, test_tenant, body
    ) -> None:
        product = await _product(db_session, test_tenant)
        response = await client.put(f"/api/v1/products/{product.id}/dimensions", json=body)
        assert response.status_code == 422
        assert any(name in response.text for name in ("length_mm", "width_mm", "height_mm"))

    async def test_unknown_and_foreign_product_404(self, client: AsyncClient, db_session) -> None:
        assert (
            await client.put(f"/api/v1/products/{uuid4()}/dimensions", json=DIMS)
        ).status_code == 404
        other = await _product(db_session, await _other_tenant(db_session), sku="FOREIGN")
        assert (
            await client.put(f"/api/v1/products/{other.id}/dimensions", json=DIMS)
        ).status_code == 404

    async def test_no_token_401(self, unauthenticated_client: AsyncClient) -> None:
        for url in (
            f"/api/v1/products/{uuid4()}/dimensions",
            f"/api/v1/models/{uuid4()}/dimensions",
            f"/api/v1/products/{uuid4()}/variants/{uuid4()}/dimensions",
        ):
            assert (await unauthenticated_client.put(url, json=DIMS)).status_code == 401

    async def test_viewer_403(self, as_role, db_session, test_tenant) -> None:
        product = await _product(db_session, test_tenant)
        model = await _model(db_session, test_tenant)
        variant = await _variant(db_session, test_tenant, product)
        async with as_role(UserRole.VIEWER) as viewer:
            for url in (
                f"/api/v1/products/{product.id}/dimensions",
                f"/api/v1/models/{model.id}/dimensions",
                f"/api/v1/products/{product.id}/variants/{variant.id}/dimensions",
            ):
                assert (await viewer.put(url, json=DIMS)).status_code == 403

    async def test_model_dimensions(self, client: AsyncClient, db_session, test_tenant) -> None:
        model = await _model(db_session, test_tenant)
        response = await client.put(f"/api/v1/models/{model.id}/dimensions", json=DIMS)
        assert response.status_code == 200
        assert response.json()["source"] == "entered"
        detail = (await client.get(f"/api/v1/models/{model.id}")).json()
        assert detail["dimensions"]["length_mm"] == "120.0"

        assert (
            await client.put(f"/api/v1/models/{model.id}/dimensions", json={**DIMS, "width_mm": 0})
        ).status_code == 422
        assert (
            await client.put(f"/api/v1/models/{uuid4()}/dimensions", json=DIMS)
        ).status_code == 404
        foreign = await _model(db_session, await _other_tenant(db_session), sku="FOREIGN-M")
        assert (
            await client.put(f"/api/v1/models/{foreign.id}/dimensions", json=DIMS)
        ).status_code == 404

    async def test_variant_inherits_then_overrides(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        product = await _product(db_session, test_tenant)
        variant = await _variant(db_session, test_tenant, product)
        await client.put(f"/api/v1/products/{product.id}/dimensions", json=DIMS)

        detail = (await client.get(f"/api/v1/products/{product.id}")).json()
        shown = detail["variants"][0]["dimensions"]
        assert shown["inherited"] is True and shown["length_mm"] == "120.0"

        url = f"/api/v1/products/{product.id}/variants/{variant.id}/dimensions"
        response = await client.put(
            url, json={"length_mm": "180", "width_mm": "120", "height_mm": "60"}
        )
        assert response.status_code == 200
        assert response.json()["inherited"] is False

        listed = (await client.get(f"/api/v1/products/{product.id}/variants")).json()
        assert listed[0]["dimensions"]["length_mm"] == "180.0"

        assert (await client.put(url, json={**DIMS, "height_mm": "-3"})).status_code == 422

    async def test_variant_of_another_product_404(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        product = await _product(db_session, test_tenant)
        other = await _product(db_session, test_tenant, sku="PKG-P2")
        variant = await _variant(db_session, test_tenant, other)
        response = await client.put(
            f"/api/v1/products/{product.id}/variants/{variant.id}/dimensions", json=DIMS
        )
        assert response.status_code == 404
        assert (
            await client.put(
                f"/api/v1/products/{product.id}/variants/{uuid4()}/dimensions", json=DIMS
            )
        ).status_code == 404

    async def test_size_cm_is_untouched(self, client: AsyncClient, db_session, test_tenant) -> None:
        """FR-005: the old single size figure keeps working, and dimensions never write it."""
        product = await _product(db_session, test_tenant, size_cm=Decimal("12.5"))
        before = (await client.get(f"/api/v1/products/{product.id}")).json()["size_cm"]
        await client.put(f"/api/v1/products/{product.id}/dimensions", json=DIMS)
        after = (await client.get(f"/api/v1/products/{product.id}")).json()["size_cm"]
        assert before == after
        await db_session.refresh(product)
        assert product.size_cm == Decimal("12.5")

    async def test_fragile_flag_is_writable(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        product = await _product(db_session, test_tenant)
        response = await client.put(f"/api/v1/products/{product.id}", json={"is_fragile": True})
        assert response.status_code == 200, response.text
        assert response.json()["is_fragile"] is True

    async def test_list_shows_dimensions(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        product = set_dims(await _product(db_session, test_tenant), 10, 20, 30)
        await db_session.commit()
        listed = (await client.get("/api/v1/products")).json()["products"]
        row = next(p for p in listed if p["id"] == str(product.id))
        assert row["dimensions"]["height_mm"] == "30.0"


# ============================================
# Suggestions, accepting, settings (US2, US4)
# ============================================


async def _stock(db: AsyncSession, tenant: Tenant) -> dict:
    """The quickstart's catalogue: three boxes and a void fill."""
    return {
        "S": await make_box(db, tenant, "Box S", (100, 100, 50), weight=30),
        "M": await make_box(db, tenant, "Box M", (150, 100, 60), weight=40),
        "L": await make_box(db, tenant, "Box L", (200, 150, 100), weight=80),
        "fill": await make_void_fill(db, tenant, 1000),
    }


async def _row_counts(db: AsyncSession) -> dict[str, int]:
    from sqlalchemy import func, select

    from app.database import Base

    counts = {}
    for table in Base.metadata.sorted_tables:
        counts[table.name] = (await db.execute(select(func.count()).select_from(table))).scalar()
    return counts


class TestSuggestions:
    async def test_ranked_boxes_with_fill(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        stock = await _stock(db_session, test_tenant)
        product = set_dims(await _product(db_session, test_tenant), 120, 70, 30)
        await db_session.commit()

        response = await client.get(f"/api/v1/products/{product.id}/packaging-suggestions")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["clearance_mm"] == "10.0" and body["fragile"] is False
        assert body["item"]["length_mm"] == "120.0" and body["item"]["source"] == "entered"
        assert [s["name"] for s in body["suggestions"]] == ["Box M", "Box L"]
        first = body["suggestions"][0]
        assert first["consumable_id"] == str(stock["M"].id)
        assert first["room_mm"] == {"length": "10.0", "width": "10.0", "height": "10.0"}
        assert first["empty_volume_ml"] == "648.0"
        assert first["orientation"] == ["length", "width", "height"]
        assert first["void_fill"] == {
            "consumable_id": str(stock["fill"].id),
            "name": "Paper fill",
            "quantity": 1,
        }
        assert first["is_current"] is False
        # FR-021: the advisor serves no cost of its own.
        assert "cost" not in response.text.lower()

    async def test_writes_nothing(self, client: AsyncClient, db_session, test_tenant) -> None:
        """FR-022: asking for suggestions changes no row anywhere."""
        await _stock(db_session, test_tenant)
        product = set_dims(await _product(db_session, test_tenant), 120, 70, 30)
        await db_session.commit()
        await db_session.refresh(product)
        before_counts = await _row_counts(db_session)
        before_updated = product.updated_at

        assert (
            await client.get(f"/api/v1/products/{product.id}/packaging-suggestions")
        ).status_code == 200

        assert await _row_counts(db_session) == before_counts
        await db_session.refresh(product)
        assert product.updated_at == before_updated

    async def test_no_dimensions_is_a_prompt_not_an_error(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        await _stock(db_session, test_tenant)
        product = await _product(db_session, test_tenant)
        body = (await client.get(f"/api/v1/products/{product.id}/packaging-suggestions")).json()
        assert body["suggestions"] == [] and body["item"] is None
        assert "dimensions_required" in body["warnings"]

    async def test_nothing_fits(self, client: AsyncClient, db_session, test_tenant) -> None:
        await _stock(db_session, test_tenant)
        product = set_dims(await _product(db_session, test_tenant), 300, 300, 300)
        await db_session.commit()
        body = (await client.get(f"/api/v1/products/{product.id}/packaging-suggestions")).json()
        assert body["suggestions"] == []
        assert "nothing_fits" in body["warnings"]
        assert body["minimum_inner"] == {
            "length_mm": "320.0",
            "width_mm": "320.0",
            "height_mm": "320.0",
        }

    async def test_variant_uses_its_effective_dimensions(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        await _stock(db_session, test_tenant)
        product = set_dims(await _product(db_session, test_tenant), 120, 70, 30)
        await db_session.commit()
        large = set_dims(await _variant(db_session, test_tenant, product, "L"), 170, 120, 70)
        small = await _variant(db_session, test_tenant, product, "S")
        await db_session.commit()

        url = f"/api/v1/products/{product.id}/packaging-suggestions"
        assert [
            s["name"]
            for s in (await client.get(url, params={"variant_id": str(large.id)})).json()[
                "suggestions"
            ]
        ] == ["Box L"]
        inherited = (await client.get(url, params={"variant_id": str(small.id)})).json()
        assert [s["name"] for s in inherited["suggestions"]] == ["Box M", "Box L"]

    async def test_foreign_variant_and_product_404(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        product = await _product(db_session, test_tenant)
        other = await _product(db_session, test_tenant, sku="PKG-P2")
        variant = await _variant(db_session, test_tenant, other)
        url = f"/api/v1/products/{product.id}/packaging-suggestions"
        assert (await client.get(url, params={"variant_id": str(variant.id)})).status_code == 404
        foreign = await _product(db_session, await _other_tenant(db_session), sku="FOREIGN")
        assert (
            await client.get(f"/api/v1/products/{foreign.id}/packaging-suggestions")
        ).status_code == 404
        assert (
            await client.get(f"/api/v1/products/{uuid4()}/packaging-suggestions")
        ).status_code == 404
        assert (await client.get(url, params={"variant_id": "not-a-uuid"})).status_code == 422

    async def test_no_token_401(self, unauthenticated_client: AsyncClient) -> None:
        assert (
            await unauthenticated_client.get(f"/api/v1/products/{uuid4()}/packaging-suggestions")
        ).status_code == 401

    async def test_viewer_may_read_suggestions(self, as_role, db_session, test_tenant) -> None:
        product = await _product(db_session, test_tenant)
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.get(f"/api/v1/products/{product.id}/packaging-suggestions")
            assert response.status_code == 200

    async def test_fragile_uses_fragile_clearance_and_wrap(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        """US4 / T041: marking fragile swaps the clearance and suggests wrap."""
        await _stock(db_session, test_tenant)
        wrap = await make_wrap(db_session, test_tenant)
        product = set_dims(await _product(db_session, test_tenant), 120, 70, 30)
        await db_session.commit()
        assert (
            await client.put(f"/api/v1/products/{product.id}", json={"is_fragile": True})
        ).status_code == 200

        body = (await client.get(f"/api/v1/products/{product.id}/packaging-suggestions")).json()
        assert body["fragile"] is True and body["clearance_mm"] == "20.0"
        assert [s["name"] for s in body["suggestions"]] == ["Box L"]
        assert body["suggestions"][0]["wrap"] == {
            "consumable_id": str(wrap.id),
            "name": "Bubble wrap",
        }


class TestAccept:
    async def test_accept_sets_product_packaging_and_cost_comes_from_costing(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        stock = await _stock(db_session, test_tenant)
        stock["M"].current_cost_per_unit = Decimal("0.85")
        product = set_dims(await _product(db_session, test_tenant), 120, 70, 30)
        await db_session.commit()

        response = await client.post(
            f"/api/v1/products/{product.id}/packaging",
            json={"consumable_id": str(stock["M"].id), "quantity": 1},
        )
        assert response.status_code == 200, response.text
        assert response.json()["packaging_warnings"] == []

        detail = (await client.get(f"/api/v1/products/{product.id}")).json()
        assert detail["packaging_consumable_id"] == str(stock["M"].id)
        assert Decimal(detail["cost_breakdown"]["packaging_cost"]) == Decimal("0.85")

        body = (await client.get(f"/api/v1/products/{product.id}/packaging-suggestions")).json()
        assert [s["is_current"] for s in body["suggestions"]] == [True, False]

    async def test_accept_for_a_variant_only(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        stock = await _stock(db_session, test_tenant)
        product = await _product(db_session, test_tenant)
        variant = await _variant(db_session, test_tenant, product)
        response = await client.post(
            f"/api/v1/products/{product.id}/packaging",
            json={
                "consumable_id": str(stock["L"].id),
                "quantity": 2,
                "variant_id": str(variant.id),
            },
        )
        assert response.status_code == 200
        await db_session.refresh(product)
        await db_session.refresh(variant)
        assert product.packaging_consumable_id is None
        assert variant.packaging_consumable_id == stock["L"].id and variant.packaging_quantity == 2

    async def test_refusals(self, client: AsyncClient, db_session, test_tenant) -> None:
        stock = await _stock(db_session, test_tenant)
        product = await _product(db_session, test_tenant)
        url = f"/api/v1/products/{product.id}/packaging"
        # Void fill is not something an item is packed in.
        assert (
            await client.post(url, json={"consumable_id": str(stock["fill"].id), "quantity": 1})
        ).status_code == 422
        assert (
            await client.post(url, json={"consumable_id": str(stock["M"].id), "quantity": 0})
        ).status_code == 422
        assert (
            await client.post(url, json={"consumable_id": str(uuid4()), "quantity": 1})
        ).status_code == 404
        foreign_tenant = await _other_tenant(db_session)
        foreign_box = await make_box(db_session, foreign_tenant, "Theirs", (500, 500, 500))
        assert (
            await client.post(url, json={"consumable_id": str(foreign_box.id), "quantity": 1})
        ).status_code == 404
        assert (
            await client.post(
                f"/api/v1/products/{uuid4()}/packaging",
                json={"consumable_id": str(stock["M"].id), "quantity": 1},
            )
        ).status_code == 404

    async def test_no_token_401(self, unauthenticated_client: AsyncClient) -> None:
        body = {"consumable_id": str(uuid4()), "quantity": 1}
        assert (
            await unauthenticated_client.post(f"/api/v1/products/{uuid4()}/packaging", json=body)
        ).status_code == 401

    async def test_viewer_403(self, as_role, db_session, test_tenant) -> None:
        stock = await _stock(db_session, test_tenant)
        product = await _product(db_session, test_tenant)
        body = {"consumable_id": str(stock["M"].id), "quantity": 1}
        async with as_role(UserRole.VIEWER) as viewer:
            assert (
                await viewer.post(f"/api/v1/products/{product.id}/packaging", json=body)
            ).status_code == 403

    async def test_drift_warning_after_dimensions_change(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        """FR-024: the accepted box is kept, and flagged when it no longer fits."""
        stock = await _stock(db_session, test_tenant)
        product = set_dims(await _product(db_session, test_tenant), 120, 70, 30)
        await db_session.commit()
        await client.post(
            f"/api/v1/products/{product.id}/packaging",
            json={"consumable_id": str(stock["M"].id), "quantity": 1},
        )
        assert (await client.get(f"/api/v1/products/{product.id}")).json()[
            "packaging_warnings"
        ] == []

        await client.put(
            f"/api/v1/products/{product.id}/dimensions",
            json={"length_mm": "160", "width_mm": "100", "height_mm": "50"},
        )
        detail = (await client.get(f"/api/v1/products/{product.id}")).json()
        assert detail["packaging_warnings"] == ["accepted_packaging_does_not_fit"]
        assert detail["packaging_consumable_id"] == str(stock["M"].id)
        body = (await client.get(f"/api/v1/products/{product.id}/packaging-suggestions")).json()
        assert "accepted_packaging_does_not_fit" in body["warnings"]


class TestVariantPackagingNote:
    async def test_note_only_when_packaging_differs(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        """FR-039: a variant's own box is not what the cost breakdown uses."""
        stock = await _stock(db_session, test_tenant)
        product = await _product(db_session, test_tenant)
        large = await _variant(db_session, test_tenant, product, "L")
        same = await _variant(db_session, test_tenant, product, "M")
        await _variant(db_session, test_tenant, product, "S")
        url = f"/api/v1/products/{product.id}/packaging"
        await client.post(url, json={"consumable_id": str(stock["M"].id), "quantity": 1})
        await client.post(
            url,
            json={"consumable_id": str(stock["L"].id), "quantity": 1, "variant_id": str(large.id)},
        )
        await client.post(
            url,
            json={"consumable_id": str(stock["M"].id), "quantity": 1, "variant_id": str(same.id)},
        )

        variants = {
            v["size"]: v
            for v in (await client.get(f"/api/v1/products/{product.id}")).json()["variants"]
        }
        assert variants["L"]["packaging_notes"] == ["variant_packaging_not_costed"]
        assert variants["L"]["effective_packaging"]["name"] == "Box L"
        assert variants["L"]["effective_packaging"]["inherited"] is False
        assert variants["M"]["packaging_notes"] == []
        assert variants["S"]["packaging_notes"] == []
        assert variants["S"]["effective_packaging"]["inherited"] is True
        assert variants["S"]["effective_packaging"]["name"] == "Box M"


class TestPackagingSettings:
    async def test_defaults_until_saved(self, client: AsyncClient) -> None:
        body = (await client.get("/api/v1/settings/packaging")).json()
        assert body == {"clearance_mm": "10.0", "fragile_clearance_mm": "20.0", "configured": False}

    async def test_save_and_use(self, client: AsyncClient, db_session, test_tenant) -> None:
        response = await client.put(
            "/api/v1/settings/packaging",
            json={"clearance_mm": "0", "fragile_clearance_mm": "15.5"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "clearance_mm": "0.0",
            "fragile_clearance_mm": "15.5",
            "configured": True,
        }
        assert (await client.get("/api/v1/settings/packaging")).json()["configured"] is True

        # The operator's zero is used, not the default (FR-015).
        await make_box(db_session, test_tenant, "Exact", (120, 70, 30))
        product = set_dims(await _product(db_session, test_tenant), 120, 70, 30)
        await db_session.commit()
        body = (await client.get(f"/api/v1/products/{product.id}/packaging-suggestions")).json()
        assert [s["name"] for s in body["suggestions"]] == ["Exact"]

    async def test_refusals(self, client: AsyncClient) -> None:
        assert (
            await client.put(
                "/api/v1/settings/packaging",
                json={"clearance_mm": "-1", "fragile_clearance_mm": "2"},
            )
        ).status_code == 422
        assert (
            await client.put(
                "/api/v1/settings/packaging",
                json={"clearance_mm": "1.25", "fragile_clearance_mm": "2"},
            )
        ).status_code == 422

    async def test_no_token_401(self, unauthenticated_client: AsyncClient) -> None:
        body = {"clearance_mm": "5", "fragile_clearance_mm": "10"}
        assert (
            await unauthenticated_client.put("/api/v1/settings/packaging", json=body)
        ).status_code == 401
        assert (await unauthenticated_client.get("/api/v1/settings/packaging")).status_code == 401

    async def test_viewer_reads_but_cannot_write(self, as_role) -> None:
        body = {"clearance_mm": "5", "fragile_clearance_mm": "10"}
        async with as_role(UserRole.VIEWER) as viewer:
            assert (await viewer.put("/api/v1/settings/packaging", json=body)).status_code == 403
            assert (await viewer.get("/api/v1/settings/packaging")).status_code == 200


class TestConsumablePackagingFields:
    BOX = {
        "sku": "BOX-M",
        "name": "Box M",
        "category": "packaging",
        "packaging_kind": "box",
        "inner_length_mm": "150",
        "inner_width_mm": "100",
        "inner_height_mm": "60",
        "wall_mm": "3",
        "empty_weight_grams": "40",
    }

    async def test_create_and_patch(self, client: AsyncClient) -> None:
        created = await client.post("/api/v1/consumables/types", json=self.BOX)
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["packaging_kind"] == "box" and body["inner_length_mm"] == "150.0"
        assert body["packaging_incomplete"] is False

        updated = await client.put(
            f"/api/v1/consumables/types/{body['id']}", json={"empty_weight_grams": "42.5"}
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["empty_weight_grams"] == "42.5"

    async def test_figures_default_to_assumed(self, client: AsyncClient) -> None:
        created = (await client.post("/api/v1/consumables/types", json=self.BOX)).json()
        assert created["packaging_provenance"] == {
            "inner_length_mm": "assumed",
            "inner_width_mm": "assumed",
            "inner_height_mm": "assumed",
            "wall_mm": "assumed",
            "empty_weight_grams": "assumed",
        }

    async def test_operator_states_measured(self, client: AsyncClient) -> None:
        created = (await client.post("/api/v1/consumables/types", json=self.BOX)).json()
        updated = await client.put(
            f"/api/v1/consumables/types/{created['id']}",
            json={"empty_weight_grams": "41", "packaging_provenance": {"source": "measured"}},
        )
        assert updated.status_code == 200, updated.text
        provenance = updated.json()["packaging_provenance"]
        assert provenance["empty_weight_grams"] == "measured"
        assert provenance["wall_mm"] == "assumed"
        fetched = await client.get(f"/api/v1/consumables/types/{created['id']}")
        assert fetched.json()["packaging_provenance"]["empty_weight_grams"] == "measured"

    async def test_observed_is_refused(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/consumables/types",
            json={**self.BOX, "packaging_provenance": {"source": "observed"}},
        )
        assert response.status_code == 422

    async def test_validation(self, client: AsyncClient) -> None:
        assert (
            await client.post(
                "/api/v1/consumables/types", json={**self.BOX, "packaging_kind": "crate"}
            )
        ).status_code == 422
        assert (
            await client.post(
                "/api/v1/consumables/types", json={**self.BOX, "inner_length_mm": "0"}
            )
        ).status_code == 422
        partial = {k: v for k, v in self.BOX.items() if k != "inner_height_mm"}
        assert (await client.post("/api/v1/consumables/types", json=partial)).status_code == 422
        assert (
            await client.post("/api/v1/consumables/types", json={**self.BOX, "wall_mm": "-1"})
        ).status_code == 422

    async def test_incomplete_flag_and_kind_filter(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        await make_box(db_session, test_tenant, "Half box", None)
        await make_box(db_session, test_tenant, "Mailer", (330, 240, 30), kind="mailer")
        await make_void_fill(db_session, test_tenant, 500)
        listed = (
            await client.get("/api/v1/consumables/types", params={"packaging_kind": "box,mailer"})
        ).json()["consumables"]
        assert sorted(c["name"] for c in listed) == ["Half box", "Mailer"]
        assert {c["name"]: c["packaging_incomplete"] for c in listed} == {
            "Half box": True,
            "Mailer": False,
        }
        assert (
            await client.get("/api/v1/consumables/types", params={"packaging_kind": "crate"})
        ).status_code == 422


# ============================================
# Measure on upload (US3)
# ============================================

MESHES = Path(__file__).parent.parent / "fixtures" / "meshes"


def _mesh(name: str) -> bytes:
    return (MESHES / name).read_bytes()


async def _upload(client: AsyncClient, model: Model, name: str, content: bytes, kind="source_stl"):
    return await client.post(
        f"/api/v1/models/{model.id}/files",
        files={"file": (name, content, "application/octet-stream")},
        data={"file_type": kind},
    )


async def _bom(db: AsyncSession, product: Product, *models: Model) -> None:
    for model in models:
        db.add(ProductModel(product_id=product.id, model_id=model.id, quantity=1))
    await db.commit()
    await db.refresh(product)


class TestMeasureOnUpload:
    async def test_stl_sets_an_empty_model(self, client: AsyncClient, db_session, test_tenant):
        model = await _model(db_session, test_tenant)
        response = await _upload(client, model, "block.stl", _mesh("block_binary.stl"))

        assert response.status_code == 201
        body = response.json()
        assert body["measurement"]["status"] == "done"
        assert body["measurement"]["length_mm"] == "40.0"
        assert body["measurement"]["applied_to"] == ["model"]
        assert body["file"]["measurement"]["height_mm"] == "20.0"

        dims = (await client.get(f"/api/v1/models/{model.id}")).json()["dimensions"]
        assert dims["source"] == "measured"
        assert dims["source_file_id"] == body["file"]["id"]
        assert dims["length_mm"] == "40.0"

    async def test_entered_dimensions_win(self, client: AsyncClient, db_session, test_tenant):
        model = await _model(db_session, test_tenant)
        await client.put(f"/api/v1/models/{model.id}/dimensions", json=DIMS)

        response = await _upload(client, model, "block.stl", _mesh("block_binary.stl"))
        assert response.json()["measurement"]["applied_to"] == []
        dims = (await client.get(f"/api/v1/models/{model.id}")).json()["dimensions"]
        assert dims["source"] == "entered"
        assert dims["length_mm"] == "120.0"

    async def test_single_model_product_receives_it(
        self, client: AsyncClient, db_session, test_tenant
    ):
        model = await _model(db_session, test_tenant)
        product = await _product(db_session, test_tenant)
        await _bom(db_session, product, model)

        response = await _upload(client, model, "block.3mf", _mesh("block.3mf"), "source_3mf")
        assert response.json()["measurement"]["applied_to"] == ["model", "product"]
        dims = (await client.get(f"/api/v1/products/{product.id}")).json()["dimensions"]
        assert dims["source"] == "measured"
        assert dims["width_mm"] == "30.0"

    async def test_two_model_product_is_not_touched(
        self, client: AsyncClient, db_session, test_tenant
    ):
        model = await _model(db_session, test_tenant)
        other = await _model(db_session, test_tenant, sku="PKG-M2")
        product = await _product(db_session, test_tenant)
        await _bom(db_session, product, model, other)

        response = await _upload(client, model, "block.stl", _mesh("block_binary.stl"))
        assert response.json()["measurement"]["applied_to"] == ["model"]
        assert (await client.get(f"/api/v1/products/{product.id}")).json()["dimensions"] is None

    async def test_gcode_has_no_measurement(self, client: AsyncClient, db_session, test_tenant):
        model = await _model(db_session, test_tenant)
        response = await _upload(client, model, "plate.gcode", b"G1 X0 Y0\n", "gcode")
        assert response.status_code == 201
        assert response.json()["measurement"] is None

    async def test_unreadable_stl_still_uploads(self, client: AsyncClient, db_session, test_tenant):
        model = await _model(db_session, test_tenant)
        response = await _upload(client, model, "bad.stl", _mesh("not_a_mesh.stl"))
        assert response.status_code == 201
        measurement = response.json()["measurement"]
        assert measurement["status"] == "failed"
        assert measurement["note"]
        assert measurement["length_mm"] is None

    async def test_large_file_is_queued(
        self, client: AsyncClient, db_session, test_tenant, monkeypatch
    ):
        from app.services import mesh_bounds
        from app.tasks import mesh_measure

        queued = []
        monkeypatch.setattr(mesh_bounds, "INLINE_MEASURE_BYTES", 100)
        monkeypatch.setattr(
            mesh_measure.measure_model_file, "delay", lambda *args: queued.append(args)
        )
        model = await _model(db_session, test_tenant)

        response = await _upload(client, model, "block.stl", _mesh("block_binary.stl"))
        assert response.status_code == 201
        measurement = response.json()["measurement"]
        assert measurement["status"] == "pending"
        assert measurement["length_mm"] is None
        assert queued == [(str(test_tenant.id), response.json()["file"]["id"])]

    async def test_parse_3mf_returns_the_measurement(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/models/files/parse-3mf",
            files={"file": ("x.3mf", _mesh("two_objects.3mf"), "model/3mf")},
        )
        assert response.status_code == 200
        measurement = response.json()["measurement"]
        assert measurement["length_mm"] == "60.0"
        assert [o["name"] for o in measurement["objects"]] == ["Body", "Stand"]

    async def test_adopt_a_measured_file(self, client: AsyncClient, db_session, test_tenant):
        model = await _model(db_session, test_tenant)
        product = await _product(db_session, test_tenant)
        await _bom(db_session, product, model)
        await client.put(f"/api/v1/products/{product.id}/dimensions", json=DIMS)
        await client.put(f"/api/v1/models/{model.id}/dimensions", json=DIMS)
        uploaded = await _upload(client, model, "b.stl", _mesh("block_binary.stl"))
        file_id = uploaded.json()["file"]["id"]

        response = await client.put(
            f"/api/v1/products/{product.id}/dimensions", json={"adopt_file_id": file_id}
        )
        assert response.status_code == 200
        assert response.json()["source"] == "measured"
        assert response.json()["length_mm"] == "40.0"

    async def test_adopt_another_models_file_is_404(
        self, client: AsyncClient, db_session, test_tenant
    ):
        model = await _model(db_session, test_tenant)
        other = await _model(db_session, test_tenant, sku="PKG-M2")
        uploaded = await _upload(client, other, "b.stl", _mesh("block_binary.stl"))
        file_id = uploaded.json()["file"]["id"]

        response = await client.put(
            f"/api/v1/models/{model.id}/dimensions", json={"adopt_file_id": file_id}
        )
        assert response.status_code == 404
