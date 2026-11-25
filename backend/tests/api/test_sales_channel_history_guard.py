"""A channel's history cannot be erased by deleting the channel (T240).

A permanent delete cascades the channel's fee rules, fee actuals, dated
economics and price history and nulls its orders' channel, so past margins and
P&L could no longer be reproduced (Constitution VI, FR-039). Only the owner or
admin may delete permanently, and only a channel with no history; anyone below
member is a reader (FR-007c, FR-007d).
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.product_pricing import ProductPricing
from app.models.sales_channel import SalesChannel
from app.models.tenant import Tenant
from app.models.user import UserRole

API = "/api/v1/sales-channels"


@pytest.fixture
async def channel(db_session: AsyncSession, test_tenant: Tenant) -> SalesChannel:
    row = SalesChannel(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name=f"History channel {uuid4().hex[:6]}",
        platform_type="etsy",
        is_active=True,
    )
    db_session.add(row)
    await db_session.commit()
    return row


@pytest.fixture
async def priced_channel(
    db_session: AsyncSession, test_tenant: Tenant, channel: SalesChannel
) -> SalesChannel:
    """A channel a product has been priced on: it has a price history."""
    product = Product(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku=f"HIST-{uuid4().hex[:6]}",
        name="History product",
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()
    db_session.add(
        ProductPricing(
            id=uuid4(),
            product_id=product.id,
            sales_channel_id=channel.id,
            list_price=Decimal("19.99"),
        )
    )
    await db_session.commit()
    return channel


async def _exists(db_session: AsyncSession, channel_id) -> bool:
    db_session.expire_all()
    return (
        await db_session.execute(select(SalesChannel.id).where(SalesChannel.id == channel_id))
    ).scalar_one_or_none() is not None


class TestWhoMayDelete:
    async def test_a_viewer_cannot_delete_a_channel_at_all(
        self, as_role, channel: SalesChannel, db_session: AsyncSession
    ) -> None:
        channel_id = channel.id
        async with as_role(UserRole.VIEWER) as viewer:
            soft = await viewer.delete(f"{API}/{channel_id}")
            hard = await viewer.delete(f"{API}/{channel_id}", params={"permanent": "true"})
        assert soft.status_code == 403
        assert hard.status_code == 403
        assert await _exists(db_session, channel_id)

    async def test_a_member_may_deactivate_but_not_erase(
        self, as_role, channel: SalesChannel, db_session: AsyncSession
    ) -> None:
        async with as_role(UserRole.MEMBER) as member:
            hard = await member.delete(f"{API}/{channel.id}", params={"permanent": "true"})
            soft = await member.delete(f"{API}/{channel.id}")
        assert hard.status_code == 403
        assert soft.status_code == 204
        assert await _exists(db_session, channel.id)

    async def test_an_admin_may_erase_a_channel_with_no_history(
        self, client: AsyncClient, channel: SalesChannel, db_session: AsyncSession
    ) -> None:
        response = await client.delete(f"{API}/{channel.id}", params={"permanent": "true"})
        assert response.status_code == 204
        assert not await _exists(db_session, channel.id)


class TestHistorySurvives:
    async def test_a_channel_with_a_price_history_is_refused_with_the_reason(
        self, client: AsyncClient, priced_channel: SalesChannel, db_session: AsyncSession
    ) -> None:
        channel_id = priced_channel.id
        response = await client.delete(f"{API}/{channel_id}", params={"permanent": "true"})
        assert response.status_code == 409
        assert "price periods" in response.json()["detail"]
        assert "Deactivate" in response.json()["detail"]
        assert await _exists(db_session, channel_id)
        prices = (
            (
                await db_session.execute(
                    select(ProductPricing).where(ProductPricing.sales_channel_id == channel_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(prices) == 1

    async def test_it_can_still_be_deactivated(
        self, client: AsyncClient, priced_channel: SalesChannel
    ) -> None:
        response = await client.delete(f"{API}/{priced_channel.id}")
        assert response.status_code == 204


class TestCreatingAndEditingNeedAMember:
    async def test_a_viewer_cannot_create_a_channel(self, as_role) -> None:
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.post(
                API, json={"name": f"Viewer channel {uuid4().hex[:6]}", "platform_type": "etsy"}
            )
        assert response.status_code == 403

    async def test_a_member_can_create_a_channel(self, as_role) -> None:
        async with as_role(UserRole.MEMBER) as member:
            response = await member.post(
                API, json={"name": f"Member channel {uuid4().hex[:6]}", "platform_type": "etsy"}
            )
        assert response.status_code == 201, response.text

    async def test_a_viewer_cannot_rename_a_channel(self, as_role, channel: SalesChannel) -> None:
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.put(f"{API}/{channel.id}", json={"name": "Renamed"})
        assert response.status_code == 403
