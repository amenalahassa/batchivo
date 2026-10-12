"""`GET /models/{id}/cost` and `GET /products/{id}/cost` (task T049).

These are the endpoints the cost breakdown panel reads. What is asserted here
is the contract the panel depends on: every line names its origin and its risk
class, nothing missing is costed at zero, the structured total agrees with the
flat total the detail endpoints still publish, and a cycle in the operator's
own bundle is a 409 that names the chain rather than a figure or a 500.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model import Model
from app.models.printer import Printer
from app.models.product import Product
from app.models.product_component import ProductComponent
from app.models.product_model import ProductModel
from app.models.tenant import Tenant
from app.models.user import UserRole

pytestmark = pytest.mark.asyncio

API = "/api/v1"


async def _attach(db_session: AsyncSession, product: Product, model: Model) -> None:
    """Put one printed item in a product, through the relationship.

    Through the relationship rather than by inserting the join row: the
    product's `product_models` collection is eager-loaded, so a bare insert
    would leave the instance in the session holding its stale empty list and
    the test would assert against a product the endpoint sees as empty.
    """
    product.product_models.append(ProductModel(id=uuid4(), model_id=model.id, quantity=1))
    db_session.add(product)
    await db_session.commit()


# ============================================================================
# The model breakdown
# ============================================================================


class TestTheModelBreakdown:
    async def test_every_line_names_its_risk_class_and_its_origin(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        response = await client.get(f"{API}/models/{test_model.id}/cost")

        assert response.status_code == 200
        body = response.json()
        assert body["lines"], "a costed item with labor hours must report at least one line"
        for line in body["lines"]:
            assert line["risk_class"] in ("at_risk", "not_at_risk")
            assert line["source"] in ("policy", "observed", "measured", "assumed")
            assert "as_of" in line

    async def test_an_unconfigured_machine_is_reported_missing_not_free(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        """FR-019: a 9-hour print on an uncosted machine must not look free."""
        body = (await client.get(f"{API}/models/{test_model.id}/cost")).json()

        assert body["incomplete_reasons"], (
            "an item with print time but no machine rate is incompletely costed"
        )
        keys = {line["key"] for line in body["lines"]}
        assert "machine" not in keys

    async def test_the_subtotals_and_the_premium_add_up_to_the_total(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        body = (await client.get(f"{API}/models/{test_model.id}/cost")).json()

        assert Decimal(body["total_make_cost"]) == (
            Decimal(body["at_risk_subtotal"])
            + Decimal(body["not_at_risk_subtotal"])
            + Decimal(body["failure_premium"])
        )

    async def test_a_perfect_yield_adds_no_premium(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        body = (await client.get(f"{API}/models/{test_model.id}/cost")).json()

        assert Decimal(body["yield_applied"]) == Decimal("1")
        assert Decimal(body["failure_premium"]) == Decimal("0")

    async def test_money_crosses_the_wire_as_a_string(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        body = (await client.get(f"{API}/models/{test_model.id}/cost")).json()

        assert isinstance(body["total_make_cost"], str)
        for line in body["lines"]:
            assert isinstance(line["amount"], str)

    async def test_the_structured_total_agrees_with_the_detail_endpoint(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        """Constitution III: one implementation, so one figure."""
        breakdown = (await client.get(f"{API}/models/{test_model.id}/cost")).json()
        detail = (await client.get(f"{API}/models/{test_model.id}")).json()

        assert Decimal(breakdown["total_make_cost"]) == Decimal(
            detail["cost_breakdown"]["total_cost"]
        )

    async def test_a_printer_adds_the_machine_line(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_model: Model,
        test_printer: Printer,
    ) -> None:
        """FR-011: an item is costed at the rate of the machine it runs on."""
        test_printer.purchase_price = Decimal("1100.00")
        test_printer.expected_lifetime_hours = 6000
        await db_session.commit()

        without = (await client.get(f"{API}/models/{test_model.id}/cost")).json()
        with_printer = (
            await client.get(
                f"{API}/models/{test_model.id}/cost",
                params={"printer_id": str(test_printer.id)},
            )
        ).json()

        keys = {line["key"] for line in with_printer["lines"]}
        assert "machine" in keys
        assert Decimal(with_printer["total_make_cost"]) > Decimal(without["total_make_cost"])

    async def test_an_unknown_printer_is_a_404(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        response = await client.get(
            f"{API}/models/{test_model.id}/cost", params={"printer_id": str(uuid4())}
        )
        assert response.status_code == 404

    async def test_an_unknown_model_is_a_404(self, client: AsyncClient) -> None:
        response = await client.get(f"{API}/models/{uuid4()}/cost")
        assert response.status_code == 404

    async def test_unauthenticated_is_refused(
        self, unauthenticated_client: AsyncClient, test_model: Model
    ) -> None:
        response = await unauthenticated_client.get(f"{API}/models/{test_model.id}/cost")
        assert response.status_code == 401

    async def test_a_viewer_may_read(self, as_role, test_model: Model) -> None:
        async with as_role(UserRole.VIEWER) as ac:
            response = await ac.get(f"{API}/models/{test_model.id}/cost")
        assert response.status_code == 200


# ============================================================================
# The product breakdown
# ============================================================================


class TestTheProductBreakdown:
    async def test_a_product_reports_the_cost_of_the_item_it_contains(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        test_model: Model,
    ) -> None:
        await _attach(db_session, test_product, test_model)

        response = await client.get(f"{API}/products/{test_product.id}/cost")

        assert response.status_code == 200
        body = response.json()
        assert Decimal(body["total_make_cost"]) > 0
        assert body["lines"]

    async def test_the_structured_total_agrees_with_the_detail_endpoint(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        test_model: Model,
    ) -> None:
        await _attach(db_session, test_product, test_model)

        breakdown = (await client.get(f"{API}/products/{test_product.id}/cost")).json()
        detail = (await client.get(f"{API}/products/{test_product.id}")).json()

        assert Decimal(breakdown["total_make_cost"]) == Decimal(
            detail["cost_breakdown"]["total_make_cost"]
        )

    async def test_the_observed_and_assumed_shares_sum_to_one(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        test_model: Model,
    ) -> None:
        await _attach(db_session, test_product, test_model)

        body = (await client.get(f"{API}/products/{test_product.id}/cost")).json()

        assert Decimal(body["observed_share"]) + Decimal(body["assumed_share"]) == Decimal("1")

    async def test_a_circular_bundle_is_a_409_naming_the_chain(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        """FR-017: a cycle is the operator's data to fix, not a 500 to swallow."""
        first = Product(
            id=uuid4(), tenant_id=test_tenant.id, sku="CYCLE-A", name="A", is_active=True
        )
        second = Product(
            id=uuid4(), tenant_id=test_tenant.id, sku="CYCLE-B", name="B", is_active=True
        )
        db_session.add_all([first, second])
        await db_session.commit()

        db_session.add_all(
            [
                ProductComponent(
                    id=uuid4(),
                    parent_product_id=first.id,
                    child_product_id=second.id,
                    quantity=1,
                ),
                ProductComponent(
                    id=uuid4(),
                    parent_product_id=second.id,
                    child_product_id=first.id,
                    quantity=1,
                ),
            ]
        )
        await db_session.commit()

        response = await client.get(f"{API}/products/{first.id}/cost")

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason"] == "circular_reference"
        assert detail["chain"], "the 409 must name the chain it found"

    async def test_an_unknown_product_is_a_404(self, client: AsyncClient) -> None:
        response = await client.get(f"{API}/products/{uuid4()}/cost")
        assert response.status_code == 404

    async def test_unauthenticated_is_refused(
        self, unauthenticated_client: AsyncClient, test_product: Product
    ) -> None:
        response = await unauthenticated_client.get(f"{API}/products/{test_product.id}/cost")
        assert response.status_code == 401

    async def test_a_viewer_may_read(self, as_role, test_product: Product) -> None:
        async with as_role(UserRole.VIEWER) as ac:
            response = await ac.get(f"{API}/products/{test_product.id}/cost")
        assert response.status_code == 200
