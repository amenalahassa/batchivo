"""What a list screen is allowed to say about a cost.

Two things are pinned here, both about the payload a list screen is built from.

**No price derived from a markup.** The product list and detail handlers used to
serve `total_make_cost * 2.5` as `suggested_price`, published as "Suggested
retail price (2.5x markup)" and rendered as "SRP". No operator configured that
markup, and cost plus a flat markup lands several points below the margin
actually asked for -- which is the whole reason the solver exists. A price has
one authority, and a route is not it (FR-007/FR-048, Constitution III and IV).

**An incomplete cost says so.** `CostingService` reports what it could not cost
in `incomplete_reasons`, and the `/cost` endpoints serve it -- but the list
payloads carried only the total, so an item missing its print time or its
machine rate showed a finished-looking figure built from a zero. The list is
where a product is picked, so it is where that has to be visible (FR-019, US2).
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.product import Product
from app.models.product_model import ProductModel
from app.models.tenant import Tenant


# ---------------------------------------------------------------------------
# No markup-derived price on the wire
# ---------------------------------------------------------------------------


class TestNoSuggestedPriceIsServed:
    @pytest.mark.asyncio
    async def test_the_product_list_serves_no_suggested_price(
        self, client: AsyncClient, auth_headers: dict, test_product: Product
    ) -> None:
        response = await client.get("/api/v1/products", headers=auth_headers)
        assert response.status_code == 200

        products = response.json()["products"]
        assert products, "need at least one product to assert on its payload"
        for product in products:
            assert "suggested_price" not in product, (
                "a price derived in a route from a hardcoded 2.5x markup is not a price; "
                "the solver and the ladder own that figure (FR-007/FR-048)"
            )

    @pytest.mark.asyncio
    async def test_the_product_detail_serves_no_suggested_price(
        self, client: AsyncClient, auth_headers: dict, test_product: Product
    ) -> None:
        response = await client.get(f"/api/v1/products/{test_product.id}", headers=auth_headers)
        assert response.status_code == 200
        assert "suggested_price" not in response.json()

    @pytest.mark.asyncio
    async def test_the_make_cost_is_still_served(
        self, client: AsyncClient, auth_headers: dict, test_product: Product
    ) -> None:
        """Removing the markup must not take the engine's own figure with it."""
        response = await client.get("/api/v1/products", headers=auth_headers)
        assert response.status_code == 200
        products = response.json()["products"]
        assert all("total_make_cost" in product for product in products)


# ---------------------------------------------------------------------------
# The incompleteness flag reaches the list
# ---------------------------------------------------------------------------


async def _model_without_a_print_time(
    db: AsyncSession, tenant: Tenant, spool_id, tag: str
) -> Model:
    """A model with a material line and nothing the machine rate needs.

    No print time means the engine cannot cost the machine or the power line,
    which is exactly the case FR-019 says must be reported rather than costed
    as a zero.
    """
    model = Model(
        id=uuid4(),
        tenant_id=tenant.id,
        sku=f"INCOMPLETE-M-{tag}",
        name=f"Incomplete model {tag}",
        is_active=True,
        print_time_minutes=None,
    )
    db.add(model)
    await db.flush()

    db.add(
        ModelMaterial(
            id=uuid4(),
            model_id=model.id,
            spool_id=spool_id,
            weight_grams=Decimal("100"),
            cost_per_gram=Decimal("0.0300"),
        )
    )
    await db.flush()
    return model


class TestIncompleteReasonsOnListPayloads:
    @pytest.mark.asyncio
    async def test_the_model_list_reports_what_it_could_not_cost(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_spool,
    ) -> None:
        model = await _model_without_a_print_time(db_session, test_tenant, test_spool.id, "ML")
        await db_session.commit()
        model_id = str(model.id)

        response = await client.get("/api/v1/models", headers=auth_headers)
        assert response.status_code == 200

        rows = {row["id"]: row for row in response.json()["models"]}
        assert model_id in rows, "the model under test must be in the list"
        row = rows[model_id]

        assert "incomplete_reasons" in row, (
            "the list payload must carry the flag, or the screen where a model is "
            "picked shows an unfinished cost as a finished one (FR-019)"
        )
        assert row["incomplete_reasons"], (
            "a model with no print time cannot have its machine rate costed, so the "
            "engine must say so rather than cost that line at zero"
        )

    @pytest.mark.asyncio
    async def test_the_product_list_reports_what_it_could_not_cost(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_spool,
    ) -> None:
        model = await _model_without_a_print_time(db_session, test_tenant, test_spool.id, "PL")
        product = Product(
            id=uuid4(),
            tenant_id=test_tenant.id,
            sku=f"INCOMPLETE-P-{uuid4().hex[:6].upper()}",
            name="Incompletely costed product",
            is_active=True,
        )
        db_session.add(product)
        await db_session.flush()
        db_session.add(
            ProductModel(id=uuid4(), product_id=product.id, model_id=model.id, quantity=1)
        )
        await db_session.commit()
        product_id = str(product.id)

        response = await client.get("/api/v1/products", headers=auth_headers)
        assert response.status_code == 200

        rows = {row["id"]: row for row in response.json()["products"]}
        assert product_id in rows
        row = rows[product_id]

        assert "incomplete_reasons" in row
        assert row["incomplete_reasons"], (
            "a product whose only model has no print time is incompletely costed, and "
            "the list is where that product gets picked (FR-019, US2)"
        )

    @pytest.mark.asyncio
    async def test_a_completely_costed_product_reports_nothing(
        self, client: AsyncClient, auth_headers: dict, test_product: Product
    ) -> None:
        """An empty list, not a missing key: the screen needs to tell them apart."""
        response = await client.get("/api/v1/products", headers=auth_headers)
        assert response.status_code == 200

        rows = {row["id"]: row for row in response.json()["products"]}
        row = rows[str(test_product.id)]
        assert row["incomplete_reasons"] == []

    @pytest.mark.asyncio
    async def test_the_list_flag_matches_the_cost_endpoint(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_spool,
    ) -> None:
        """One engine, so the list and the itemised breakdown must agree.

        Two screens disagreeing about whether a cost is finished is the same
        defect as two screens disagreeing about the cost (Constitution III).
        """
        model = await _model_without_a_print_time(db_session, test_tenant, test_spool.id, "MATCH")
        product = Product(
            id=uuid4(),
            tenant_id=test_tenant.id,
            sku=f"MATCH-P-{uuid4().hex[:6].upper()}",
            name="Match product",
            is_active=True,
        )
        db_session.add(product)
        await db_session.flush()
        db_session.add(
            ProductModel(id=uuid4(), product_id=product.id, model_id=model.id, quantity=1)
        )
        await db_session.commit()
        product_id = str(product.id)

        list_resp = await client.get("/api/v1/products", headers=auth_headers)
        assert list_resp.status_code == 200
        from_list = {row["id"]: row for row in list_resp.json()["products"]}[product_id]

        cost_resp = await client.get(f"/api/v1/products/{product_id}/cost", headers=auth_headers)
        assert cost_resp.status_code == 200
        from_cost = cost_resp.json()

        assert sorted(from_list["incomplete_reasons"]) == sorted(from_cost["incomplete_reasons"])
