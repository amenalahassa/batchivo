"""One product, one make-cost, whichever screen asks for it.

User Story 1's independent test: *open the same product from the product list,
the product detail and the channel pricing screen and confirm all three report
an identical make-cost to the cent.*

Before this feature the three screens could disagree, because two
implementations existed -- `CostingService` and `Product.calculate_make_cost`,
the second with its own hardcoded labor rate -- and because the one that
survived did not forward its rate into nested model costs. Two figures for the
same product is not a rounding problem; it is the operator losing the ability to
trust either one (Constitution III).

The pricing screen does not publish the make-cost directly, so it is recovered
from the figures it does publish: net revenue less profit is, by definition, the
cost that was deducted.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model import Model
from app.models.model_component import ModelComponent
from app.models.model_material import ModelMaterial
from app.models.product import Product
from app.models.product_component import ProductComponent
from app.models.product_model import ProductModel
from app.models.sales_channel import SalesChannel
from app.models.tenant import Tenant
from app.services.pricing_policy import write_policy

API = "/api/v1"

LIST_PRICE = Decimal("64.99")


@pytest.fixture
async def configured_tenant(db_session: AsyncSession, test_tenant: Tenant) -> Tenant:
    """A tenant with a labor rate set, so the rate is part of every figure."""
    await write_policy(
        db_session,
        test_tenant,
        {"print_labor_rate": Decimal("25.00"), "finishing_labor_rate": Decimal("25.00")},
    )
    await db_session.commit()
    await db_session.refresh(test_tenant)
    return test_tenant


@pytest.fixture
async def rich_product(db_session: AsyncSession, configured_tenant: Tenant, test_spool) -> Product:
    """A product with every cost component, so no path can be accidentally equal.

    Material, a component, labor, overhead, packaging, assembly and a child
    product -- if any screen drops one of these, the totals diverge.
    """
    model = Model(
        id=uuid4(),
        tenant_id=configured_tenant.id,
        sku=f"CONS-MODEL-{uuid4().hex[:6]}",
        name="Consistency model",
        labor_hours=Decimal("0.25"),
        overhead_percentage=Decimal("12"),
        is_active=True,
    )
    db_session.add(model)
    await db_session.flush()
    db_session.add(
        ModelMaterial(
            id=uuid4(),
            model_id=model.id,
            spool_id=test_spool.id,
            weight_grams=Decimal("142"),
            cost_per_gram=Decimal("0.0310"),
        )
    )
    db_session.add(
        ModelComponent(
            id=uuid4(),
            model_id=model.id,
            component_name="M3 insert",
            quantity=4,
            unit_cost=Decimal("0.11"),
        )
    )

    child = Product(
        id=uuid4(),
        tenant_id=configured_tenant.id,
        sku=f"CONS-CHILD-{uuid4().hex[:6]}",
        name="Consistency child",
        assembly_minutes=4,
        is_active=True,
    )
    db_session.add(child)
    await db_session.flush()
    db_session.add(ProductModel(id=uuid4(), product_id=child.id, model_id=model.id, quantity=1))

    parent = Product(
        id=uuid4(),
        tenant_id=configured_tenant.id,
        sku=f"CONS-PROD-{uuid4().hex[:6]}",
        name="Consistency product",
        assembly_minutes=6,
        is_active=True,
    )
    db_session.add(parent)
    await db_session.flush()
    db_session.add(ProductModel(id=uuid4(), product_id=parent.id, model_id=model.id, quantity=2))
    db_session.add(
        ProductComponent(
            id=uuid4(),
            parent_product_id=parent.id,
            child_product_id=child.id,
            quantity=1,
        )
    )
    await db_session.commit()
    await db_session.refresh(parent)
    return parent


@pytest.fixture
async def channel(db_session: AsyncSession, configured_tenant: Tenant) -> SalesChannel:
    sales_channel = SalesChannel(
        id=uuid4(),
        tenant_id=configured_tenant.id,
        name=f"Consistency channel {uuid4().hex[:6]}",
        platform_type="etsy",
        monthly_cost=Decimal("0"),
        is_active=True,
    )
    db_session.add(sales_channel)
    await db_session.commit()
    await db_session.refresh(sales_channel)
    return sales_channel


async def _cost_from_detail(client: AsyncClient, product: Product) -> Decimal:
    response = await client.get(f"{API}/products/{product.id}")
    assert response.status_code == 200, response.text
    return Decimal(str(response.json()["cost_breakdown"]["total_make_cost"]))


async def _cost_from_list(client: AsyncClient, product: Product) -> Decimal:
    response = await client.get(f"{API}/products", params={"limit": 200})
    assert response.status_code == 200, response.text
    rows = [row for row in response.json()["products"] if row["sku"] == product.sku]
    assert rows, f"{product.sku} is missing from the product list"
    return Decimal(str(rows[0]["total_make_cost"]))


async def _cost_from_pricing(
    client: AsyncClient, product: Product, channel: SalesChannel
) -> Decimal:
    """Recover the make-cost the pricing screen deducted.

    net_revenue - profit == make_cost, by the definition of profit.
    """
    response = await client.post(
        f"{API}/products/{product.id}/pricing",
        json={
            "sales_channel_id": str(channel.id),
            "list_price": str(LIST_PRICE),
            "is_active": True,
        },
    )
    assert response.status_code in (200, 201), response.text
    body = response.json()
    return Decimal(str(body["net_revenue"])) - Decimal(str(body["profit"]))


class TestTheThreeScreensAgree:
    async def test_list_and_detail_report_the_same_make_cost(
        self, client: AsyncClient, rich_product: Product
    ) -> None:
        detail = await _cost_from_detail(client, rich_product)
        listed = await _cost_from_list(client, rich_product)
        assert listed == detail, (
            f"the product list reported {listed} while the detail screen "
            f"reported {detail} for the same product"
        )

    async def test_pricing_deducts_the_same_make_cost(
        self, client: AsyncClient, rich_product: Product, channel: SalesChannel
    ) -> None:
        detail = await _cost_from_detail(client, rich_product)
        priced = await _cost_from_pricing(client, rich_product, channel)
        assert priced == detail, (
            f"the pricing screen deducted {priced} while the detail screen "
            f"reported {detail}; the margin on screen is computed against a cost "
            f"the operator cannot see"
        )

    async def test_all_three_agree_to_the_cent(
        self, client: AsyncClient, rich_product: Product, channel: SalesChannel
    ) -> None:
        detail = await _cost_from_detail(client, rich_product)
        listed = await _cost_from_list(client, rich_product)
        priced = await _cost_from_pricing(client, rich_product, channel)
        assert detail == listed == priced, (
            f"three figures for one product: detail {detail}, list {listed}, pricing {priced}"
        )

    async def test_the_figure_is_not_trivially_zero(
        self, client: AsyncClient, rich_product: Product
    ) -> None:
        """Three screens agreeing on zero would prove nothing."""
        assert await _cost_from_detail(client, rich_product) > Decimal("1.00")

    async def test_they_still_agree_after_an_input_changes(
        self,
        client: AsyncClient,
        rich_product: Product,
        channel: SalesChannel,
        db_session: AsyncSession,
        configured_tenant: Tenant,
    ) -> None:
        """Agreement must survive a change, not just hold at one moment."""
        before = await _cost_from_detail(client, rich_product)

        await write_policy(
            db_session,
            configured_tenant,
            {"print_labor_rate": Decimal("50.00"), "finishing_labor_rate": Decimal("50.00")},
        )
        await db_session.commit()

        detail = await _cost_from_detail(client, rich_product)
        listed = await _cost_from_list(client, rich_product)
        assert detail > before, (
            "doubling the labor rate did not change the reported cost, so the "
            "configured rate is still not the one in use"
        )
        assert listed == detail, (
            f"after the rate changed, the list reported {listed} and the detail screen {detail}"
        )


class TestTheChildProductFigureAgreesToo:
    async def test_the_child_cost_shown_on_the_parent_matches_the_childs_own_detail(
        self, client: AsyncClient, rich_product: Product, db_session: AsyncSession
    ) -> None:
        """A bundle's child figure must match that child's own screen."""
        response = await client.get(f"{API}/products/{rich_product.id}")
        assert response.status_code == 200, response.text
        children = response.json()["child_products"]
        assert children, "the bundle reported no children"

        shown = Decimal(str(children[0]["child_product_cost"]))
        child_id = children[0]["child_product_id"]

        child_response = await client.get(f"{API}/products/{child_id}")
        assert child_response.status_code == 200, child_response.text
        own = Decimal(str(child_response.json()["cost_breakdown"]["total_make_cost"]))

        assert shown == own, (
            f"the parent shows its child at {shown} while the child's own screen reports {own}"
        )


# ============================================
# T239: the engine's own reads agree with the flat ones
# ============================================


@pytest.fixture
async def fractional_product(
    db_session: AsyncSession, configured_tenant: Tenant, test_spool
) -> Product:
    """A product whose per-model cost carries a fourth decimal.

    The flat traversal rounded each model to 0.001 before summing, so two
    models at 1.16069 became 2.322 against the engine's 2.32138: a cent apart
    once both were rounded to the currency (FR-048).
    """
    model = Model(
        id=uuid4(),
        tenant_id=configured_tenant.id,
        sku=f"FRAC-MODEL-{uuid4().hex[:6]}",
        name="Fractional model",
        is_active=True,
    )
    db_session.add(model)
    await db_session.flush()
    db_session.add(
        ModelMaterial(
            id=uuid4(),
            model_id=model.id,
            spool_id=test_spool.id,
            weight_grams=Decimal("37"),
            cost_per_gram=Decimal("0.03137"),
        )
    )
    product = Product(
        id=uuid4(),
        tenant_id=configured_tenant.id,
        sku=f"FRAC-PROD-{uuid4().hex[:6]}",
        name="Fractional product",
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()
    db_session.add(ProductModel(id=uuid4(), product_id=product.id, model_id=model.id, quantity=3))
    await db_session.commit()
    await db_session.refresh(product)
    return product


async def _cost_from_cost_endpoint(client: AsyncClient, product: Product) -> Decimal:
    response = await client.get(f"{API}/products/{product.id}/cost")
    assert response.status_code == 200, response.text
    return Decimal(str(response.json()["total_make_cost"])).quantize(Decimal("0.01"))


async def _cost_from_margin(
    client: AsyncClient, product: Product, channel: SalesChannel
) -> Decimal:
    priced = await client.post(
        f"{API}/products/{product.id}/pricing",
        json={
            "sales_channel_id": str(channel.id),
            "list_price": str(LIST_PRICE),
            "is_active": True,
        },
    )
    assert priced.status_code in (200, 201), priced.text
    response = await client.get(f"{API}/products/{product.id}/pricing/{channel.id}/margin")
    assert response.status_code == 200, response.text
    return Decimal(str(response.json()["make_cost"])).quantize(Decimal("0.01"))


async def _four_reads(client: AsyncClient, product: Product, channel: SalesChannel) -> None:
    detail = await _cost_from_detail(client, product)
    listed = await _cost_from_list(client, product)
    engine = await _cost_from_cost_endpoint(client, product)
    margin = await _cost_from_margin(client, product, channel)
    assert detail == listed == engine == margin, (
        f"one product, four make-costs: detail {detail}, list {listed}, "
        f"/cost {engine}, margin {margin}"
    )


class TestEveryReadOfTheMakeCostAgrees:
    async def test_a_bundle_reads_the_same_everywhere(
        self, client: AsyncClient, rich_product: Product, channel: SalesChannel
    ) -> None:
        await _four_reads(client, rich_product, channel)

    async def test_a_fourth_decimal_does_not_drift_a_cent(
        self, client: AsyncClient, fractional_product: Product, channel: SalesChannel
    ) -> None:
        await _four_reads(client, fractional_product, channel)

    async def test_the_flat_parts_add_up_to_the_total(
        self, client: AsyncClient, rich_product: Product
    ) -> None:
        response = await client.get(f"{API}/products/{rich_product.id}")
        assert response.status_code == 200, response.text
        flat = response.json()["cost_breakdown"]
        parts = sum(
            Decimal(str(flat[key]))
            for key in ("models_cost", "child_products_cost", "packaging_cost", "assembly_cost")
        )
        assert abs(parts - Decimal(str(flat["total_make_cost"]))) <= Decimal("0.02")
