"""Exchange rates: entered by hand, frozen with their day, and never parity.

* Task T223: an operator can record a rate, see the sales waiting on one, and
  fill them -- without ever revising a rate a sale already froze (FR-028j).
* Task T232: a frozen rate keeps its day and origin, and the snapshot's
  warnings are kept with the line rather than only logged.
* Task T231: a cost kept in the books currency is converted before it meets a
  price in another, and a pair with no rate is refused, never treated as 1.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.fx_rate import FxRate
from app.models.order import Order, OrderItem
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import fx_service
from app.services.currency_edge import books_to_sale, cost_in_sale_currency
from app.services.sale_snapshot import write_sale_snapshot

pytestmark = pytest.mark.asyncio

URL = "/api/v1/fx-rates"
SOLD_ON = date(2026, 9, 1)


async def _usd_order(db_session, tenant: Tenant, *, fx_rate=None) -> Order:
    """A sale in USD for a tenant keeping its books in CAD, placed on SOLD_ON."""
    placed = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    order = Order(
        id=uuid4(),
        tenant_id=tenant.id,
        order_number=f"ORD-{uuid4().hex[:8]}",
        customer_name="FX Customer",
        customer_email="fx@example.com",
        shipping_address_line1="1 Test Street",
        shipping_city="Testville",
        shipping_postcode="T35T",
        shipping_country="United States",
        shipping_method="Standard",
        shipping_cost=Decimal("0"),
        subtotal=Decimal("20.00"),
        total=Decimal("20.00"),
        currency="USD",
        status="delivered",
        created_at=placed,
        updated_at=placed,
    )
    db_session.add(order)
    db_session.add(
        OrderItem(
            id=uuid4(),
            tenant_id=tenant.id,
            order_id=order.id,
            product_sku="FX-1",
            product_name="Priced abroad",
            quantity=1,
            unit_price=Decimal("20.00"),
            total_price=Decimal("20.00"),
            fx_rate=fx_rate,
        )
    )
    tenant.currency_code = "CAD"
    db_session.add(tenant)
    await db_session.commit()
    return order


async def _snapshot(db_session, tenant: Tenant, order_id) -> OrderItem:
    order = (
        await db_session.execute(
            select(Order).where(Order.id == order_id).options(selectinload(Order.items))
        )
    ).scalar_one()
    await write_sale_snapshot(db_session, tenant, order, as_of=SOLD_ON, commit=True)
    line = await _line(db_session, order_id)
    # The client shares this session, and its tenant must not be left expired.
    await db_session.refresh(tenant)
    return line


async def _line(db_session, order_id) -> OrderItem:
    # Re-read without expiring the session the client shares.
    return (
        await db_session.execute(
            select(OrderItem)
            .where(OrderItem.order_id == order_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _rate(db_session, rate: str, on: date, source: str = "service") -> None:
    await fx_service.record_rate(
        db_session, base="USD", quote="CAD", rate=Decimal(rate), rate_date=on, source=source
    )
    await db_session.commit()


# ============================================================================
# T232: the frozen rate keeps its day, its origin and its warnings
# ============================================================================


class TestTheFrozenRateKeepsItsProvenance:
    async def test_a_stale_rate_is_frozen_with_its_day_and_origin(
        self, db_session, test_tenant
    ) -> None:
        tenant_id = test_tenant.id
        await _rate(db_session, "1.35", date(2026, 8, 20))
        order = await _usd_order(db_session, test_tenant)
        await db_session.refresh(test_tenant)

        line = await _snapshot(db_session, test_tenant, order.id)

        assert line.tenant_id == tenant_id
        assert line.fx_rate == Decimal("1.35")
        assert line.fx_rate_date == date(2026, 8, 20)
        assert line.fx_rate_source == "service"
        assert line.fx_quote_currency == "CAD"
        assert any("last known" in reason for reason in line.snapshot_incomplete)

    async def test_the_order_read_serves_them(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        await _rate(db_session, "1.35", date(2026, 8, 20))
        order = await _usd_order(db_session, test_tenant)
        order_id = order.id
        await db_session.refresh(test_tenant)
        await _snapshot(db_session, test_tenant, order_id)

        body = (await client.get(f"/api/v1/orders/{order_id}")).json()

        [item] = body["items"]
        assert item["fx_rate"] == "1.35000000"
        assert item["fx_rate_date"] == "2026-08-20"
        assert item["fx_rate_source"] == "service"
        assert item["fx_rate_is_stale"] is True
        assert any("last known" in reason for reason in item["snapshot_incomplete"])

    async def test_a_sale_with_no_rate_records_it_as_unknown_not_parity(
        self, db_session, test_tenant
    ) -> None:
        order = await _usd_order(db_session, test_tenant)
        await db_session.refresh(test_tenant)

        line = await _snapshot(db_session, test_tenant, order.id)

        assert line.fx_rate is None
        assert line.fx_quote_currency == "CAD"
        assert any("no exchange rate" in reason for reason in line.snapshot_incomplete)


# ============================================================================
# T223: the operator enters a rate by hand
# ============================================================================


class TestAManualRate:
    async def test_it_lists_the_lines_waiting_on_a_rate(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        order = await _usd_order(db_session, test_tenant)
        order_id = order.id
        await db_session.refresh(test_tenant)
        await _snapshot(db_session, test_tenant, order_id)

        body = (await client.get(f"{URL}/waiting")).json()

        [line] = body["lines"]
        assert line["order_id"] == str(order_id)
        assert (line["base_currency"], line["quote_currency"]) == ("USD", "CAD")

    async def test_it_fills_a_line_that_froze_none(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        order = await _usd_order(db_session, test_tenant)
        order_id = order.id
        await db_session.refresh(test_tenant)
        await _snapshot(db_session, test_tenant, order_id)

        response = await client.post(
            f"{URL}/manual",
            json={
                "base_currency": "usd",
                "quote_currency": "CAD",
                "rate": "1.3600",
                "rate_date": "2026-09-01",
            },
        )

        assert response.status_code == 201, response.text
        assert response.json()["lines_filled"] == 1
        assert response.json()["source"] == "manual"
        line = await _line(db_session, order_id)
        assert line.fx_rate == Decimal("1.36")
        assert line.fx_rate_source == "manual"
        assert not any("no exchange rate" in r for r in (line.snapshot_incomplete or []))
        assert (await client.get(f"{URL}/waiting")).json()["total"] == 0

    async def test_it_never_revises_a_frozen_rate(
        self, client: AsyncClient, db_session, test_tenant
    ) -> None:
        order = await _usd_order(db_session, test_tenant, fx_rate=Decimal("1.30"))
        order_id = order.id
        await db_session.refresh(test_tenant)
        await _snapshot(db_session, test_tenant, order_id)

        response = await client.post(
            f"{URL}/manual",
            json={
                "base_currency": "USD",
                "quote_currency": "CAD",
                "rate": "1.50",
                "rate_date": "2026-09-01",
            },
        )

        assert response.status_code == 201
        assert response.json()["lines_filled"] == 0
        assert (await _line(db_session, order_id)).fx_rate == Decimal("1.30")

    async def test_a_different_rate_for_the_same_day_is_refused(
        self, client: AsyncClient, db_session
    ) -> None:
        await _rate(db_session, "1.36", SOLD_ON, source="manual")

        response = await client.post(
            f"{URL}/manual",
            json={
                "base_currency": "USD",
                "quote_currency": "CAD",
                "rate": "1.40",
                "rate_date": "2026-09-01",
            },
        )

        assert response.status_code == 409
        rows = (await db_session.execute(select(FxRate))).scalars().all()
        assert [row.rate for row in rows] == [Decimal("1.36")]

    @pytest.mark.parametrize(
        "body",
        [
            {"base_currency": "USD", "quote_currency": "CAD", "rate": "0"},
            {"base_currency": "USD", "quote_currency": "CAD", "rate": "-1.2"},
            {"base_currency": "US", "quote_currency": "CAD", "rate": "1.2"},
            {"base_currency": "USD", "quote_currency": "USD", "rate": "1.2"},
            {"base_currency": "USD", "quote_currency": "CAD"},
        ],
    )
    async def test_an_unusable_rate_is_a_422(self, client: AsyncClient, body: dict) -> None:
        assert (await client.post(f"{URL}/manual", json=body)).status_code == 422

    async def test_a_member_cannot_enter_one(self, client: AsyncClient, as_role) -> None:
        async with as_role(UserRole.MEMBER):
            response = await client.post(
                f"{URL}/manual",
                json={"base_currency": "USD", "quote_currency": "CAD", "rate": "1.2"},
            )

        assert response.status_code == 403

    async def test_a_viewer_may_see_what_is_waiting(self, client: AsyncClient, as_role) -> None:
        async with as_role(UserRole.VIEWER):
            response = await client.get(f"{URL}/waiting")

        assert response.status_code == 200

    async def test_unauthenticated_is_a_401(self, unauthenticated_client: AsyncClient) -> None:
        response = await unauthenticated_client.post(
            f"{URL}/manual",
            json={"base_currency": "USD", "quote_currency": "CAD", "rate": "1.2"},
        )

        assert response.status_code == 401


# ============================================================================
# T231: one currency before a subtraction
# ============================================================================


class TestCostsMeetPricesInOneCurrency:
    async def test_a_settled_cost_is_divided_by_the_frozen_rate(self) -> None:
        line = OrderItem(fx_rate=Decimal("1.25"))

        assert cost_in_sale_currency(line, Decimal("10.00")) == Decimal("8")

    async def test_a_settled_line_with_no_rate_has_no_converted_cost(self) -> None:
        assert cost_in_sale_currency(OrderItem(fx_rate=None), Decimal("10.00")) is None

    async def test_a_quote_in_the_books_currency_is_parity(self, db_session, test_tenant) -> None:
        test_tenant.currency_code = "CAD"

        conversion = await books_to_sale(db_session, test_tenant, "cad", SOLD_ON)

        assert conversion.rate == Decimal("1")
        assert conversion.reasons == ()

    async def test_a_quote_with_no_rate_is_unknown_never_one(self, db_session, test_tenant) -> None:
        test_tenant.currency_code = "CAD"

        conversion = await books_to_sale(db_session, test_tenant, "USD", SOLD_ON)

        assert conversion.rate is None
        assert "no exchange rate" in conversion.reasons[0]

    async def test_a_quote_converts_costs_at_the_resolved_rate(
        self, db_session, test_tenant
    ) -> None:
        test_tenant.currency_code = "CAD"
        await fx_service.record_rate(
            db_session, base="CAD", quote="USD", rate=Decimal("0.74"), rate_date=SOLD_ON
        )

        conversion = await books_to_sale(db_session, test_tenant, "USD", SOLD_ON)

        assert conversion.apply(Decimal("10.00")) == Decimal("7.4000")

    async def test_the_margin_endpoint_refuses_a_pair_with_no_rate(
        self, client: AsyncClient, db_session, test_tenant, test_product
    ) -> None:
        from app.models.product_pricing import ProductPricing
        from app.models.sales_channel import SalesChannel

        channel = SalesChannel(
            id=uuid4(),
            tenant_id=test_tenant.id,
            name="US Marketplace",
            platform_type="etsy",
            currency_code="USD",
            is_active=True,
        )
        db_session.add(channel)
        db_session.add(
            ProductPricing(
                id=uuid4(),
                product_id=test_product.id,
                sales_channel_id=channel.id,
                list_price=Decimal("25.00"),
                is_active=True,
            )
        )
        test_tenant.currency_code = "CAD"
        db_session.add(test_tenant)
        await db_session.commit()

        response = await client.get(
            f"/api/v1/products/{test_product.id}/pricing/{channel.id}/margin"
        )

        assert response.status_code == 409, response.text
        assert response.json()["detail"]["reason"] == "no_exchange_rate"
