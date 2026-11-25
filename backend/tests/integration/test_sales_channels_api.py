"""Comprehensive integration tests for Sales Channels API - all fields and operations."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from uuid import uuid4
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from app.models.sales_channel import SalesChannel
from app.models.tenant import Tenant


@pytest_asyncio.fixture
async def test_sales_channel(db_session: AsyncSession, test_tenant: Tenant) -> SalesChannel:
    """Create a test sales channel."""
    channel = SalesChannel(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Test Online Shop",
        platform_type="online_shop",
        monthly_cost=Decimal("0.00"),
        is_active=True,
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)
    return channel


class TestSalesChannelsBasicCRUD:
    """Test basic CRUD operations for Sales Channels."""

    @pytest.mark.asyncio
    async def test_create_sales_channel_minimal(self, client: AsyncClient, auth_headers: dict):
        """Test creating a sales channel with minimal required fields."""
        response = await client.post(
            "/api/v1/sales-channels",
            headers=auth_headers,
            json={
                "name": "Minimal Channel",
                "platform_type": "other",
            },
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert data["name"] == "Minimal Channel"
        assert data["platform_type"] == "other"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_sales_channel_all_fields(self, client: AsyncClient, auth_headers: dict):
        """Test creating a sales channel with all fields populated."""
        response = await client.post(
            "/api/v1/sales-channels",
            headers=auth_headers,
            json={
                "name": "Full Featured Channel",
                "platform_type": "etsy",
                "monthly_cost": "15.00",
                "is_active": True,
            },
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert data["name"] == "Full Featured Channel"
        assert data["platform_type"] == "etsy"
        assert float(data["monthly_cost"]) == 15.00
        assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_get_sales_channel(
        self, client: AsyncClient, auth_headers: dict, test_sales_channel: SalesChannel
    ):
        """Test retrieving a sales channel by ID."""
        response = await client.get(
            f"/api/v1/sales-channels/{test_sales_channel.id}", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_sales_channel.id)
        assert data["name"] == test_sales_channel.name

    @pytest.mark.asyncio
    async def test_list_sales_channels(
        self, client: AsyncClient, auth_headers: dict, test_sales_channel: SalesChannel
    ):
        """Test listing sales channels."""
        response = await client.get("/api/v1/sales-channels", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "channels" in data
        assert isinstance(data["channels"], list)
        assert len(data["channels"]) >= 1

    @pytest.mark.asyncio
    async def test_update_sales_channel(
        self, client: AsyncClient, auth_headers: dict, test_sales_channel: SalesChannel
    ):
        """Test updating a sales channel."""
        response = await client.put(
            f"/api/v1/sales-channels/{test_sales_channel.id}",
            headers=auth_headers,
            json={
                "name": "Updated Channel Name",
                "monthly_cost": "4.50",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Channel Name"
        assert float(data["monthly_cost"]) == 4.50

    @pytest.mark.asyncio
    async def test_delete_sales_channel(
        self, client: AsyncClient, auth_headers: dict, test_sales_channel: SalesChannel
    ):
        """Test deleting a sales channel (soft delete)."""
        response = await client.delete(
            f"/api/v1/sales-channels/{test_sales_channel.id}", headers=auth_headers
        )
        assert response.status_code in [200, 204]

        # Verify sales channel is soft-deleted (is_active = false)
        response = await client.get(
            f"/api/v1/sales-channels/{test_sales_channel.id}", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False


class TestSalesChannelsAllFieldsPersistence:
    """Test that all sales channel fields persist correctly."""

    @pytest.mark.asyncio
    async def test_all_fields_persist_after_update(
        self, client: AsyncClient, auth_headers: dict, test_sales_channel: SalesChannel
    ):
        """Test that ALL sales channel fields persist after update and refetch."""
        update_data = {
            "name": "Persistence Test Channel",
            "platform_type": "shopify",
            "monthly_cost": "29.00",
            "is_active": True,
        }

        update_response = await client.put(
            f"/api/v1/sales-channels/{test_sales_channel.id}",
            headers=auth_headers,
            json=update_data,
        )
        assert update_response.status_code == 200

        # Fetch and verify all fields
        get_response = await client.get(
            f"/api/v1/sales-channels/{test_sales_channel.id}", headers=auth_headers
        )
        assert get_response.status_code == 200
        data = get_response.json()

        assert data["name"] == "Persistence Test Channel"
        assert data["platform_type"] == "shopify"
        assert float(data["monthly_cost"]) == 29.00
        assert data["is_active"] is True


class TestSalesChannelsPlatformTypes:
    """Test platform type field values."""

    @pytest.mark.asyncio
    async def test_fair_platform_type(self, client: AsyncClient, auth_headers: dict):
        """Test creating channel with 'fair' platform type."""
        response = await client.post(
            "/api/v1/sales-channels",
            headers=auth_headers,
            json={
                "name": "Comic Con Booth",
                "platform_type": "fair",
                "monthly_cost": "500.00",  # Booth fee
            },
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert data["platform_type"] == "fair"

    @pytest.mark.asyncio
    async def test_online_shop_platform_type(self, client: AsyncClient, auth_headers: dict):
        """Test creating channel with 'online_shop' platform type."""
        response = await client.post(
            "/api/v1/sales-channels",
            headers=auth_headers,
            json={
                "name": "Direct Shop",
                "platform_type": "online_shop",
            },
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert data["platform_type"] == "online_shop"

    @pytest.mark.asyncio
    async def test_etsy_platform_type(self, client: AsyncClient, auth_headers: dict):
        """Test creating channel with 'etsy' platform type."""
        response = await client.post(
            "/api/v1/sales-channels",
            headers=auth_headers,
            json={
                "name": "Etsy Store",
                "platform_type": "etsy",
            },
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert data["platform_type"] == "etsy"


class TestSalesChannelsCostFields:
    """The channel's own costs.

    Its *fees* are `fee_rules` and are tested with them (FR-020); the blended
    `fee_percentage`/`fee_fixed` pair this class used to exercise was dropped
    with the columns behind it (task T123). What a channel still carries
    directly is a periodic cost.
    """

    @pytest.mark.asyncio
    async def test_monthly_cost(
        self, client: AsyncClient, auth_headers: dict, test_sales_channel: SalesChannel
    ):
        """Test updating monthly_cost."""
        response = await client.put(
            f"/api/v1/sales-channels/{test_sales_channel.id}",
            headers=auth_headers,
            json={"monthly_cost": "49.99"},
        )
        assert response.status_code == 200
        assert float(response.json()["monthly_cost"]) == 49.99

    @pytest.mark.asyncio
    async def test_zero_cost(self, client: AsyncClient, auth_headers: dict):
        """A channel that costs nothing to sell on, such as direct cash sales."""
        response = await client.post(
            "/api/v1/sales-channels",
            headers=auth_headers,
            json={
                "name": "Direct Cash Sales",
                "platform_type": "other",
                "monthly_cost": "0",
            },
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert float(data["monthly_cost"]) == 0


class TestSalesChannelsIsActive:
    """Test is_active field behavior."""

    @pytest.mark.asyncio
    async def test_is_active_default(self, client: AsyncClient, auth_headers: dict):
        """Test is_active defaults to True."""
        response = await client.post(
            "/api/v1/sales-channels",
            headers=auth_headers,
            json={
                "name": "Default Active Channel",
                "platform_type": "other",
            },
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_is_active_toggle(
        self, client: AsyncClient, auth_headers: dict, test_sales_channel: SalesChannel
    ):
        """Test toggling is_active field."""
        # Set to inactive
        response = await client.put(
            f"/api/v1/sales-channels/{test_sales_channel.id}",
            headers=auth_headers,
            json={"is_active": False},
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False

        # Set back to active
        response = await client.put(
            f"/api/v1/sales-channels/{test_sales_channel.id}",
            headers=auth_headers,
            json={"is_active": True},
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is True


class TestSalesChannelsValidation:
    """Test validation rules for sales channel fields."""

    @pytest.mark.asyncio
    async def test_channel_not_found(self, client: AsyncClient, auth_headers: dict):
        """Test accessing non-existent channel returns 404."""
        fake_id = uuid4()
        response = await client.get(f"/api/v1/sales-channels/{fake_id}", headers=auth_headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_name_rejected(self, client: AsyncClient, auth_headers: dict):
        """Test that empty name is rejected."""
        response = await client.post(
            "/api/v1/sales-channels",
            headers=auth_headers,
            json={"name": "", "platform_type": "other"},
        )
        assert response.status_code == 422


class TestSalesChannelsTenantIsolation:
    """Test multi-tenant isolation for sales channels."""

    @pytest.mark.asyncio
    async def test_cannot_access_other_tenant_channel(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """Test sales channels from other tenants are not visible."""
        # Create a different tenant
        other_tenant = Tenant(
            id=uuid4(), name="Other Tenant", slug="other-tenant-channel", settings={}
        )
        db_session.add(other_tenant)
        await db_session.flush()

        # Create a channel for the other tenant
        other_channel = SalesChannel(
            id=uuid4(),
            tenant_id=other_tenant.id,
            name="Other Tenant Channel",
            platform_type="other",
            is_active=True,
        )
        db_session.add(other_channel)
        await db_session.commit()

        # Try to access other tenant's channel
        response = await client.get(
            f"/api/v1/sales-channels/{other_channel.id}", headers=auth_headers
        )
        assert response.status_code == 404
