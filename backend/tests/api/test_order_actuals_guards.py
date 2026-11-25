"""Actual figures on an order are written by a member, and say who wrote them (T241).

`PATCH /orders/{id}` writes postage paid and sales tax collected -- the
realised margin's postage and the P&L's tax liability -- and returns
`/complete` writes a `RefundActual`. Both were open to any role, while
`POST /orders/{id}/refund` already required an admin (FR-007d, FR-040). The
figures also carried no trace of who entered them (FR-041e, FR-001).
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.return_request import (
    ReturnAction,
    ReturnItem,
    ReturnReason,
    ReturnRequest,
    ReturnStatus,
)
from app.models.tenant import Tenant
from app.models.user import UserRole

API = "/api/v1"


@pytest.fixture
async def order(db_session: AsyncSession, test_tenant: Tenant) -> Order:
    row = Order(
        tenant_id=test_tenant.id,
        order_number=f"ORD-ACT-{uuid4().hex[:6]}",
        status=OrderStatus.PROCESSING,
        customer_email="actuals@example.com",
        customer_name="Actuals Customer",
        shipping_address_line1="1 Actual Street",
        shipping_city="London",
        shipping_postcode="SW1A 1AA",
        shipping_country="GB",
        shipping_method="Royal Mail 2nd Class",
        subtotal=Decimal("25.00"),
        shipping_cost=Decimal("4.99"),
        total=Decimal("29.99"),
        postage_paid=Decimal("3.20"),
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.fixture
async def received_return(
    db_session: AsyncSession, test_tenant: Tenant, order: Order
) -> ReturnRequest:
    product = Product(
        tenant_id=test_tenant.id,
        sku=f"ACT-{uuid4().hex[:6]}",
        name="Actuals product",
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()
    item = OrderItem(
        tenant_id=test_tenant.id,
        order_id=order.id,
        product_id=product.id,
        product_name=product.name,
        product_sku=product.sku,
        quantity=1,
        unit_price=Decimal("25.00"),
        total_price=Decimal("25.00"),
    )
    db_session.add(item)
    await db_session.flush()
    request = ReturnRequest(
        tenant_id=test_tenant.id,
        rma_number=f"RMA-ACT-{uuid4().hex[:6]}",
        order_id=order.id,
        customer_email=order.customer_email,
        customer_name=order.customer_name,
        status=ReturnStatus.RECEIVED,
        reason=ReturnReason.DEFECTIVE,
        requested_action=ReturnAction.REFUND,
    )
    db_session.add(request)
    await db_session.flush()
    db_session.add(ReturnItem(return_request_id=request.id, order_item_id=item.id, quantity=1))
    await db_session.commit()
    await db_session.refresh(request)
    return request


async def _stored(db_session: AsyncSession, order_id) -> Order:
    db_session.expire_all()
    return (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()


class TestTheViewerReadsOnly:
    async def test_a_viewer_cannot_overwrite_postage_or_tax(
        self, as_role, order: Order, db_session: AsyncSession
    ) -> None:
        order_id = order.id
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.patch(
                f"{API}/orders/{order_id}",
                json={"postage_paid": "0.00", "sales_tax_collected": "9.99"},
            )
        assert response.status_code == 403
        stored = await _stored(db_session, order_id)
        assert stored.postage_paid == Decimal("3.20")
        assert stored.sales_tax_collected is None

    @pytest.mark.parametrize("action", ["ship", "deliver", "fulfill"])
    async def test_a_viewer_cannot_move_an_order_on(
        self, as_role, order: Order, action: str
    ) -> None:
        order_id = order.id
        body = {"tracking_number": "TRK1"} if action == "ship" else None
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.post(f"{API}/orders/{order_id}/{action}", json=body)
        assert response.status_code == 403

    async def test_a_viewer_cannot_cancel_an_order(self, as_role, order: Order) -> None:
        order_id = order.id
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.post(
                f"{API}/orders/{order_id}/cancel", json={"reason": "viewer"}
            )
        assert response.status_code == 403


class TestWhoEnteredItIsKept:
    async def test_a_member_s_figures_are_recorded_as_entered_by_them(
        self, as_role, order: Order, db_session: AsyncSession
    ) -> None:
        order_id = order.id
        async with as_role(UserRole.MEMBER) as member:
            response = await member.patch(
                f"{API}/orders/{order_id}",
                json={"postage_paid": "3.85", "sales_tax_collected": "5.00"},
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["actuals_source"] == "entered"
        assert body["actuals_recorded_by_user_id"]

        stored = await _stored(db_session, order_id)
        assert stored.postage_paid == Decimal("3.85")
        assert stored.sales_tax_collected == Decimal("5.00")
        assert stored.actuals_source == "entered"
        assert str(stored.actuals_recorded_by_user_id) == body["actuals_recorded_by_user_id"]
        assert stored.actuals_recorded_at is not None

    async def test_a_patch_that_names_neither_figure_leaves_the_origin_alone(
        self, client: AsyncClient, order: Order, db_session: AsyncSession
    ) -> None:
        order_id = order.id
        response = await client.patch(f"{API}/orders/{order_id}", json={"internal_notes": "hi"})
        assert response.status_code == 200, response.text
        assert (await _stored(db_session, order_id)).actuals_source is None


class TestCompletingAReturnIsTheAdminsCall:
    async def test_a_member_cannot_complete_a_return(
        self, as_role, received_return: ReturnRequest
    ) -> None:
        return_id = received_return.id
        async with as_role(UserRole.MEMBER) as member:
            response = await member.post(
                f"{API}/returns/{return_id}/complete", json={"refund_amount": "25.00"}
            )
        assert response.status_code == 403

    async def test_a_viewer_cannot_approve_a_return(
        self, as_role, received_return: ReturnRequest
    ) -> None:
        return_id = received_return.id
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.post(f"{API}/returns/{return_id}/approve", json={})
        assert response.status_code == 403
