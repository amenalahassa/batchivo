"""Integration tests for payments API endpoints."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import AsyncGenerator
from unittest.mock import MagicMock, patch
from uuid import uuid4

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main import app
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.sales_channel import SalesChannel
from app.models.tenant import Tenant
from app.schemas.payment import PaymentError, PaymentResponse
from app.services.cart import CartService, get_cart_service
from app.services.checkout_session import CheckoutSessionService, get_checkout_session_service
from app.services.stock_reservation import StockReservationService, get_stock_reservation_service
from tests.utils.mock_redis import MockRedis


# ============================================
# Redis Mock Fixtures
# ============================================


@pytest.fixture
def fake_redis():
    """Create a fake Redis client for testing."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def mock_cart_service(fake_redis):
    """Create a cart service with fake Redis."""
    return CartService(redis_client=fake_redis)


@pytest.fixture
def mock_checkout_service(fake_redis):
    """Create a checkout session service with fake Redis."""
    return CheckoutSessionService(redis_client=fake_redis)


@pytest.fixture
def mock_reservation_redis():
    """Create a MockRedis that supports Lua scripts for stock reservation."""
    return MockRedis()


@pytest.fixture
def mock_reservation_service(mock_reservation_redis):
    """Create a stock reservation service with MockRedis (supports Lua scripts)."""
    return StockReservationService(redis_client=mock_reservation_redis)


@pytest.fixture(autouse=True)
def override_redis_services(mock_cart_service, mock_checkout_service, mock_reservation_service):
    """Override Redis-based services with mocks for all tests."""
    app.dependency_overrides[get_cart_service] = lambda: mock_cart_service
    app.dependency_overrides[get_checkout_session_service] = lambda: mock_checkout_service
    app.dependency_overrides[get_stock_reservation_service] = lambda: mock_reservation_service
    yield
    # Clean up overrides
    app.dependency_overrides.pop(get_cart_service, None)
    app.dependency_overrides.pop(get_checkout_session_service, None)
    app.dependency_overrides.pop(get_stock_reservation_service, None)


@pytest_asyncio.fixture(scope="function")
async def online_shop_channel(db_session: AsyncSession, test_tenant: Tenant) -> SalesChannel:
    """Create an online_shop sales channel for shop context resolution."""
    channel = SalesChannel(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Test Online Shop",
        platform_type="online_shop",
        is_active=True,
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)
    return channel


@pytest_asyncio.fixture(scope="function")
async def payments_client(
    db_session: AsyncSession,
    seed_material_types,
    test_tenant: Tenant,
    online_shop_channel: SalesChannel,
) -> AsyncGenerator[AsyncClient, None]:
    """Create a test HTTP client for payments with ShopContext.

    `get_shop_db` is overridden alongside `get_db` because T181 moved the two
    order-writing Square routes onto the RLS-scoped storefront session; without
    it they would open a real session of their own and see none of the rows
    this test wrote.
    """
    from app.auth.dependencies import get_shop_db, get_shop_sales_channel, get_shop_tenant

    async def override_get_db():
        yield db_session

    async def override_get_shop_tenant():
        return test_tenant

    async def override_get_shop_sales_channel():
        return (test_tenant, online_shop_channel)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_shop_db] = override_get_db
    app.dependency_overrides[get_shop_tenant] = override_get_shop_tenant
    app.dependency_overrides[get_shop_sales_channel] = override_get_shop_sales_channel
    app.state.limiter.enabled = False

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.state.limiter.enabled = True
    # Only remove the overrides we added, not all overrides (preserves Redis mocks)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_shop_db, None)
    app.dependency_overrides.pop(get_shop_tenant, None)
    app.dependency_overrides.pop(get_shop_sales_channel, None)


@pytest_asyncio.fixture(scope="function")
async def mystmereforge_channel(db_session: AsyncSession, test_tenant: Tenant) -> SalesChannel:
    """Create the Mystmereforge sales channel."""
    channel = SalesChannel(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Mystmereforge",
        platform_type="shopify",
        is_active=True,
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)
    return channel


@pytest_asyncio.fixture(scope="function")
async def shop_product(db_session: AsyncSession, test_tenant: Tenant) -> Product:
    """Create a shop-visible product."""
    product = Product(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku="SHOP-PROD-001",
        name="Shop Test Product",
        description="A product for shop testing",
        units_in_stock=100,
        is_active=True,
        shop_visible=True,
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


class TestGetPaymentConfig:
    """Tests for GET /api/v1/payments/config endpoint."""

    async def test_get_config_enabled(self, payments_client: AsyncClient):
        """Test config returns enabled when Square is configured."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = "test-location"
            mock_settings.square_environment = "sandbox"
            mock_settings.square_app_id = "test-app-id"

            response = await payments_client.get("/api/v1/payments/config")

            assert response.status_code == 200
            data = response.json()
            assert data["enabled"] is True
            assert data["environment"] == "sandbox"

    async def test_get_config_disabled_no_token(self, payments_client: AsyncClient):
        """Test config returns disabled when no token."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = ""
            mock_settings.square_location_id = "test-location"
            mock_settings.square_environment = "sandbox"

            response = await payments_client.get("/api/v1/payments/config")

            assert response.status_code == 200
            data = response.json()
            assert data["enabled"] is False

    async def test_get_config_disabled_no_location(self, payments_client: AsyncClient):
        """Test config returns disabled when no location ID."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = ""
            mock_settings.square_environment = "production"

            response = await payments_client.get("/api/v1/payments/config")

            assert response.status_code == 200
            data = response.json()
            assert data["enabled"] is False
            assert data["environment"] == "production"

    async def test_get_config_uses_sandbox_for_test_hostname(self, payments_client: AsyncClient):
        """Test hostnames use sandbox Square config without exposing production credentials."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = ""
            mock_settings.square_location_id = ""
            mock_settings.square_environment = "production"
            mock_settings.square_app_id = "prod-app-id"
            mock_settings.square_sandbox_access_token = "sandbox-token"
            mock_settings.square_sandbox_location_id = "sandbox-location"
            mock_settings.square_sandbox_app_id = "sandbox-app-id"

            response = await payments_client.get(
                "/api/v1/payments/config",
                headers={"X-Shop-Hostname": "test.mystmereforge.co.uk"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["enabled"] is True
            assert data["environment"] == "sandbox"
            assert data["app_id"] == "sandbox-app-id"
            assert data["location_id"] == "sandbox-location"


class TestProcessPayment:
    """Tests for POST /api/v1/payments/process endpoint."""

    def _create_payment_body(
        self,
        product_id: str,
        amount: int = 2999,
        item_price: int = 2500,
        shipping_cost: int = 499,
    ) -> dict:
        """Create a payment request body."""
        return {
            "payment_token": "cnon:card-nonce-ok",
            "amount": amount,
            "currency": "GBP",
            "customer": {
                "email": "customer@example.com",
                "phone": "+44123456789",
            },
            "shipping_address": {
                "first_name": "John",
                "last_name": "Doe",
                "address_line1": "123 Test Street",
                "address_line2": "Apt 4B",
                "city": "London",
                "county": "Greater London",
                "postcode": "SW1A 1AA",
                "country": "GB",
            },
            "shipping_method": "standard",
            "shipping_cost": shipping_cost,
            "items": [
                {
                    "product_id": product_id,
                    "name": "Test Product",
                    "quantity": 1,
                    "price": item_price,
                }
            ],
        }

    async def test_process_payment_not_configured(self, payments_client: AsyncClient):
        """Test payment fails when Square not configured."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = ""
            mock_settings.square_location_id = ""

            response = await payments_client.post(
                "/api/v1/payments/process",
                json=self._create_payment_body(str(uuid4())),
            )

            assert response.status_code == 503
            assert "not configured" in response.json()["detail"]

    async def test_process_payment_amount_mismatch(
        self, payments_client: AsyncClient, shop_product: Product
    ):
        """Test payment fails when amount doesn't match items + shipping."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = "test-location"

            body = self._create_payment_body(str(shop_product.id))
            body["amount"] = 9999  # Wrong amount

            response = await payments_client.post(
                "/api/v1/payments/process",
                json=body,
            )

            assert response.status_code == 400
            assert "Amount mismatch" in response.json()["detail"]

    async def test_hosted_checkout_creates_pending_order_and_square_link(
        self,
        payments_client: AsyncClient,
        shop_product: Product,
        db_session: AsyncSession,
    ):
        """Hosted Square checkout creates a pending order and returns redirect URL."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = "test-location"
            mock_settings.square_environment = "production"

            with patch("app.api.v1.payments.get_payment_service") as mock_get_service:
                mock_service = MagicMock()
                mock_service.create_payment_link.return_value = {
                    "id": "LPM_TEST_LINK",
                    "url": "https://square.link/u/test",
                    "order_id": "square_order_123",
                }
                mock_get_service.return_value = mock_service

                body = self._create_payment_body(str(shop_product.id))
                body.pop("payment_token")
                body["redirect_url"] = "https://www.mystmereforge.co.uk/order-confirmation"

                response = await payments_client.post(
                    "/api/v1/payments/hosted-checkout",
                    json=body,
                )

                assert response.status_code == 200
                data = response.json()
                assert data["checkout_url"] == "https://square.link/u/test"
                assert data["payment_link_id"] == "LPM_TEST_LINK"
                assert "-" in data["order_id"]

                mock_service.create_payment_link.assert_called_once()
                call = mock_service.create_payment_link.call_args.kwargs
                assert call["amount"] == 2999
                assert call["currency"] == "GBP"
                assert call["order_number"] == data["order_id"]

                result = await db_session.execute(
                    select(Order).where(Order.order_number == data["order_id"])
                )
                order = result.scalar_one()
                assert order.payment_provider == "square_hosted"
                assert order.payment_id == "square_order_123"
                assert order.payment_status == "PENDING_HOSTED_CHECKOUT"
                assert order.confirmation_email_sent is False

    async def test_process_payment_success(
        self,
        payments_client: AsyncClient,
        shop_product: Product,
        mystmereforge_channel: SalesChannel,
        db_session: AsyncSession,
    ):
        """Test successful payment processing creates order."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = "test-location"

            with patch("app.api.v1.payments.get_payment_service") as mock_get_service:
                mock_service = MagicMock()
                mock_service.process_payment.return_value = PaymentResponse(
                    success=True,
                    order_id="MF-TEMP123",
                    payment_id="sq_payment_123",
                    amount=2999,
                    currency="GBP",
                    status="COMPLETED",
                    receipt_url="https://squareup.com/receipt/test",
                    created_at=datetime.now(timezone.utc),
                )
                mock_get_service.return_value = mock_service

                with patch("app.api.v1.payments.get_email_service") as mock_get_email:
                    mock_email = MagicMock()
                    mock_email.send_order_confirmation.return_value = True
                    mock_get_email.return_value = mock_email

                    body = self._create_payment_body(str(shop_product.id))

                    response = await payments_client.post(
                        "/api/v1/payments/process",
                        json=body,
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["success"] is True
                    assert data["payment_id"] == "sq_payment_123"
                    assert data["status"] == "COMPLETED"
                    # Order number format is {TENANT_PREFIX}-{DATE}-{SEQUENCE}
                    assert "-" in data["order_id"]
                    assert len(data["order_id"]) > 10

                    # Verify order was created in database
                    result = await db_session.execute(
                        select(Order).where(Order.payment_id == "sq_payment_123")
                    )
                    order = result.scalar_one_or_none()
                    assert order is not None
                    assert order.customer_email == "customer@example.com"
                    assert order.status == OrderStatus.PENDING
                    assert order.payment_status == "COMPLETED"

                    # Verify email was sent
                    mock_email.send_order_confirmation.assert_called_once()

    async def test_process_payment_uses_sandbox_for_test_hostname(
        self,
        payments_client: AsyncClient,
        shop_product: Product,
        db_session: AsyncSession,
    ):
        """Test host payments use sandbox credentials and do not send customer email."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = ""
            mock_settings.square_location_id = ""
            mock_settings.square_sandbox_access_token = "sandbox-token"
            mock_settings.square_sandbox_location_id = "sandbox-location"
            mock_settings.square_sandbox_app_id = "sandbox-app-id"

            with patch("app.api.v1.payments.SquarePaymentService", create=True) as mock_service_cls:
                mock_service = MagicMock()
                mock_service.process_payment.return_value = PaymentResponse(
                    success=True,
                    order_id="MF-SANDBOX",
                    payment_id="sandbox_payment_123",
                    amount=2999,
                    currency="GBP",
                    status="COMPLETED",
                    receipt_url=None,
                    created_at=datetime.now(timezone.utc),
                )
                mock_service_cls.return_value = mock_service

                with patch("app.api.v1.payments.get_email_service") as mock_get_email:
                    body = self._create_payment_body(str(shop_product.id))

                    response = await payments_client.post(
                        "/api/v1/payments/process",
                        json=body,
                        headers={"X-Shop-Hostname": "test.mystmereforge.co.uk"},
                    )

                    assert response.status_code == 200
                    mock_service_cls.assert_called_once_with(
                        access_token="sandbox-token",
                        location_id="sandbox-location",
                        environment="sandbox",
                    )
                    mock_get_email.assert_not_called()

                    result = await db_session.execute(
                        select(Order).where(Order.payment_id == "sandbox_payment_123")
                    )
                    order = result.scalar_one()
                    assert order.payment_provider == "square_sandbox"
                    assert order.confirmation_email_sent is False

    async def test_process_payment_card_declined(
        self,
        payments_client: AsyncClient,
        shop_product: Product,
        mystmereforge_channel: SalesChannel,
    ):
        """Test payment failure returns 402."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = "test-location"

            with patch("app.api.v1.payments.get_payment_service") as mock_get_service:
                mock_service = MagicMock()
                mock_service.process_payment.return_value = PaymentError(
                    success=False,
                    error_code="CARD_DECLINED",
                    error_message="Card was declined",
                    detail="Insufficient funds",
                )
                mock_get_service.return_value = mock_service

                body = self._create_payment_body(str(shop_product.id))

                response = await payments_client.post(
                    "/api/v1/payments/process",
                    json=body,
                )

                assert response.status_code == 402
                detail = response.json()["detail"]
                assert detail["error_code"] == "CARD_DECLINED"

    async def test_failed_payment_attempts_use_unique_square_idempotency_keys(
        self,
        payments_client: AsyncClient,
        shop_product: Product,
        mystmereforge_channel: SalesChannel,
    ):
        """Failed attempts must not reuse the next order number as Square idempotency key."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = "test-location"

            with patch("app.api.v1.payments.get_payment_service") as mock_get_service:
                mock_service = MagicMock()
                mock_service.process_payment.return_value = PaymentError(
                    success=False,
                    error_code="CARD_DECLINED",
                    error_message="Card was declined",
                    detail="Insufficient funds",
                )
                mock_get_service.return_value = mock_service

                first_body = self._create_payment_body(str(shop_product.id))
                first_body["payment_token"] = "cnon:first-attempt"
                second_body = self._create_payment_body(str(shop_product.id))
                second_body["payment_token"] = "cnon:second-attempt"

                first_response = await payments_client.post(
                    "/api/v1/payments/process",
                    json=first_body,
                )
                second_response = await payments_client.post(
                    "/api/v1/payments/process",
                    json=second_body,
                )

                assert first_response.status_code == 402
                assert second_response.status_code == 402

                first_request = mock_service.process_payment.call_args_list[0].args[0]
                second_request = mock_service.process_payment.call_args_list[1].args[0]
                assert first_request.idempotency_key != second_request.idempotency_key
                assert first_request.idempotency_key.startswith("TEST-")
                assert second_request.idempotency_key.startswith("TEST-")
                assert len(first_request.idempotency_key) <= 45
                assert len(second_request.idempotency_key) <= 45

    async def test_process_payment_creates_order_items(
        self,
        payments_client: AsyncClient,
        shop_product: Product,
        mystmereforge_channel: SalesChannel,
        db_session: AsyncSession,
    ):
        """Test order items are created correctly."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = "test-location"

            with patch("app.api.v1.payments.get_payment_service") as mock_get_service:
                mock_service = MagicMock()
                mock_service.process_payment.return_value = PaymentResponse(
                    success=True,
                    order_id="MF-TEST",
                    payment_id="sq_items_test",
                    amount=5498,
                    currency="GBP",
                    status="COMPLETED",
                    created_at=datetime.now(timezone.utc),
                )
                mock_get_service.return_value = mock_service

                with patch("app.api.v1.payments.get_email_service") as mock_get_email:
                    mock_email = MagicMock()
                    mock_email.send_order_confirmation.return_value = True
                    mock_get_email.return_value = mock_email

                    body = {
                        "payment_token": "cnon:card-nonce-ok",
                        "amount": 5498,
                        "currency": "GBP",
                        "customer": {"email": "items@example.com"},
                        "shipping_address": {
                            "first_name": "Item",
                            "last_name": "Test",
                            "address_line1": "Items St",
                            "city": "London",
                            "postcode": "E1 1AA",
                            "country": "GB",
                        },
                        "shipping_method": "standard",
                        "shipping_cost": 499,
                        "items": [
                            {
                                "product_id": str(shop_product.id),
                                "name": "Product A",
                                "quantity": 2,
                                "price": 1500,
                            },
                            {
                                "product_id": str(uuid4()),  # Non-existent product
                                "name": "Product B",
                                "quantity": 1,
                                "price": 1999,
                            },
                        ],
                    }

                    response = await payments_client.post(
                        "/api/v1/payments/process",
                        json=body,
                    )

                    assert response.status_code == 200

                    # Verify order items
                    result = await db_session.execute(
                        select(Order).where(Order.payment_id == "sq_items_test")
                    )
                    order = result.scalar_one()

                    items_result = await db_session.execute(
                        select(OrderItem).where(OrderItem.order_id == order.id)
                    )
                    items = items_result.scalars().all()

                    assert len(items) == 2

                    # Check first item (existing product)
                    item_a = next(i for i in items if i.product_name == "Product A")
                    assert item_a.product_id == shop_product.id
                    assert item_a.quantity == 2
                    assert float(item_a.unit_price) == 15.00

                    # Check second item (non-existent product)
                    item_b = next(i for i in items if i.product_name == "Product B")
                    assert item_b.product_id is None
                    assert item_b.quantity == 1

    async def test_process_payment_order_number_sequence(
        self,
        payments_client: AsyncClient,
        shop_product: Product,
        mystmereforge_channel: SalesChannel,
        db_session: AsyncSession,
    ):
        """Test order numbers are sequential for the same day."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = "test-location"

            order_numbers = []
            for i in range(3):
                with patch("app.api.v1.payments.get_payment_service") as mock_get_service:
                    mock_service = MagicMock()
                    mock_service.process_payment.return_value = PaymentResponse(
                        success=True,
                        order_id="MF-TEMP",
                        payment_id=f"sq_seq_test_{i}",
                        amount=2999,
                        currency="GBP",
                        status="COMPLETED",
                        created_at=datetime.now(timezone.utc),
                    )
                    mock_get_service.return_value = mock_service

                    with patch("app.api.v1.payments.get_email_service") as mock_get_email:
                        mock_email = MagicMock()
                        mock_email.send_order_confirmation.return_value = True
                        mock_get_email.return_value = mock_email

                        body = self._create_payment_body(str(shop_product.id))

                        response = await payments_client.post(
                            "/api/v1/payments/process",
                            json=body,
                        )

                        assert response.status_code == 200
                        order_numbers.append(response.json()["order_id"])

            # Verify sequential numbering
            assert order_numbers[0].endswith("-001")
            assert order_numbers[1].endswith("-002")
            assert order_numbers[2].endswith("-003")

    async def test_process_payment_missing_sales_channel_still_succeeds(
        self, payments_client: AsyncClient, shop_product: Product
    ):
        """Test payment succeeds even when order creation fails (no sales channel).

        The payment is processed first, and if order creation fails, the error is
        logged but payment success is still returned (can be reconciled from Square).
        """
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = "test-location"

            with patch("app.api.v1.payments.get_payment_service") as mock_get_service:
                mock_service = MagicMock()
                mock_service.process_payment.return_value = PaymentResponse(
                    success=True,
                    order_id="MF-TEMP",
                    payment_id="sq_no_channel",
                    amount=2999,
                    currency="GBP",
                    status="COMPLETED",
                    created_at=datetime.now(timezone.utc),
                )
                mock_get_service.return_value = mock_service

                body = self._create_payment_body(str(shop_product.id))

                response = await payments_client.post(
                    "/api/v1/payments/process",
                    json=body,
                )

                # Payment still succeeds - order creation failure is logged only
                assert response.status_code == 200
                data = response.json()
                assert data["success"] is True
                assert data["payment_id"] == "sq_no_channel"

    async def test_process_payment_validation_errors(self, payments_client: AsyncClient):
        """Test payment validation for required fields."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = "test-location"

            # Missing payment_token
            response = await payments_client.post(
                "/api/v1/payments/process",
                json={
                    "amount": 1000,
                    "currency": "GBP",
                    "customer": {"email": "test@example.com"},
                    "shipping_address": {
                        "first_name": "Test",
                        "last_name": "User",
                        "address_line1": "123 St",
                        "city": "City",
                        "postcode": "AB1 2CD",
                        "country": "GB",
                    },
                    "shipping_method": "standard",
                    "shipping_cost": 0,
                    "items": [],
                },
            )

            assert response.status_code == 422


class TestGetPaymentStatus:
    """Tests for GET /api/v1/payments/status/{payment_id} endpoint."""

    async def test_get_status_not_configured(self, payments_client: AsyncClient):
        """Test status fails when Square not configured."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = ""

            response = await payments_client.get("/api/v1/payments/status/payment_123")

            assert response.status_code == 503
            assert "not configured" in response.json()["detail"]

    async def test_get_status_success(self, payments_client: AsyncClient):
        """Test successful payment status retrieval."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"

            with patch("app.api.v1.payments.get_payment_service") as mock_get_service:
                mock_service = MagicMock()
                mock_service.get_payment.return_value = {
                    "id": "sq_pay_123",
                    "status": "COMPLETED",
                    "amount_money": {"amount": 5000, "currency": "GBP"},
                    "receipt_url": "https://squareup.com/receipt/xyz",
                }
                mock_get_service.return_value = mock_service

                response = await payments_client.get("/api/v1/payments/status/sq_pay_123")

                assert response.status_code == 200
                data = response.json()
                assert data["payment_id"] == "sq_pay_123"
                assert data["status"] == "COMPLETED"
                assert data["amount"] == 5000
                assert data["currency"] == "GBP"
                assert data["receipt_url"] == "https://squareup.com/receipt/xyz"

    async def test_get_status_not_found(self, payments_client: AsyncClient):
        """Test payment not found returns 404."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"

            with patch("app.api.v1.payments.get_payment_service") as mock_get_service:
                mock_service = MagicMock()
                mock_service.get_payment.return_value = None
                mock_get_service.return_value = mock_service

                response = await payments_client.get("/api/v1/payments/status/nonexistent_id")

                assert response.status_code == 404
                assert "not found" in response.json()["detail"]


# ============================================
# The Square order paths: frozen and exact (tasks T180, T182)
# ============================================


class TestSquareOrderPathsFreezeAndStayExact:
    """What the two Square checkout surfaces write onto a settled order.

    Both paths persisted an ``Order`` with its lines and never snapshotted it,
    while the console order, the storefront checkout, the Shopify webhook and
    the commerce bridge all did. And both converted integer pence to pounds
    with ``int / int``, which is binary floating point: 7999 / 100 is
    79.989999999999994884. The two defects compound -- an approximation of
    what the customer paid, frozen onto nothing, with the margin re-derived
    from today's inputs (FR-036, FR-037, FR-047, Constitution IV and VI).
    """

    @staticmethod
    def _body(product_id: str, *, amount: int, item_price: int, shipping_cost: int) -> dict:
        return {
            "payment_token": "cnon:card-nonce-ok",
            "amount": amount,
            "currency": "GBP",
            "customer": {"email": "customer@example.com", "phone": "+44123456789"},
            "shipping_address": {
                "first_name": "John",
                "last_name": "Doe",
                "address_line1": "123 Test Street",
                "address_line2": None,
                "city": "London",
                "county": "Greater London",
                "postcode": "SW1A 1AA",
                "country": "GB",
            },
            "shipping_method": "standard",
            "shipping_cost": shipping_cost,
            "items": [
                {
                    "product_id": product_id,
                    "name": "Test Product",
                    "quantity": 1,
                    "price": item_price,
                }
            ],
        }

    @staticmethod
    async def _order_with_items(db_session: AsyncSession, order_number: str) -> Order:
        from sqlalchemy.orm import selectinload

        return (
            await db_session.execute(
                select(Order)
                .where(Order.order_number == order_number)
                .options(selectinload(Order.items))
            )
        ).scalar_one()

    # -- T180: the snapshot ------------------------------------------------

    async def test_hosted_checkout_freezes_the_sale_snapshot(
        self,
        payments_client: AsyncClient,
        shop_product: Product,
        db_session: AsyncSession,
    ):
        """A hosted-checkout order carries its frozen basis and revision."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = "test-location"
            mock_settings.square_environment = "production"

            with patch("app.api.v1.payments.get_payment_service") as mock_get_service:
                service = MagicMock()
                service.create_payment_link.return_value = {
                    "id": "LPM_TEST_LINK",
                    "url": "https://square.link/u/test",
                    "order_id": "square_order_123",
                }
                mock_get_service.return_value = service

                body = self._body(
                    str(shop_product.id), amount=2999, item_price=2500, shipping_cost=499
                )
                body.pop("payment_token")

                response = await payments_client.post("/api/v1/payments/hosted-checkout", json=body)
                assert response.status_code == 200, response.text
                order_number = response.json()["order_id"]

        order = await self._order_with_items(db_session, order_number)
        assert order.items, "the sale recorded no lines"
        for item in order.items:
            assert item.has_snapshot, (
                "a Square hosted-checkout line was settled with no frozen "
                "make-cost, which hides it from realised_margin and "
                "margin_alert entirely (FR-036)"
            )
            assert item.cost_breakdown_json is not None
            assert item.margin_basis_at_sale, "the basis in force was not frozen (FR-031d)"
            assert item.pricing_rev is not None

    async def test_process_payment_freezes_the_sale_snapshot(
        self,
        payments_client: AsyncClient,
        shop_product: Product,
        db_session: AsyncSession,
    ):
        """A Web Payments SDK order carries its frozen basis and revision."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = "test-location"
            mock_settings.square_environment = "production"

            with patch("app.api.v1.payments.get_payment_service") as mock_get_service:
                service = MagicMock()
                service.process_payment.return_value = PaymentResponse(
                    success=True,
                    order_id="MF-TEMP123",
                    payment_id="sq_payment_123",
                    amount=2999,
                    currency="GBP",
                    status="COMPLETED",
                    receipt_url="https://squareup.com/receipt/123",
                    created_at=datetime.now(timezone.utc),
                )
                mock_get_service.return_value = service

                with patch("app.api.v1.payments.get_email_service") as mock_get_email:
                    mock_get_email.return_value = MagicMock()
                    response = await payments_client.post(
                        "/api/v1/payments/process",
                        json=self._body(
                            str(shop_product.id), amount=2999, item_price=2500, shipping_cost=499
                        ),
                    )
                assert response.status_code == 200, response.text
                order_number = response.json()["order_id"]

        order = await self._order_with_items(db_session, order_number)
        assert order.items, "the sale recorded no lines"
        for item in order.items:
            assert item.has_snapshot, (
                "a Square Web Payments line was settled with no frozen make-cost (FR-036)"
            )
            assert item.margin_basis_at_sale
            assert item.pricing_rev is not None

    # -- T182: the arithmetic ---------------------------------------------

    async def test_hosted_checkout_converts_pence_exactly(
        self,
        payments_client: AsyncClient,
        shop_product: Product,
        db_session: AsyncSession,
    ):
        """GBP 79.99 is written as 79.99, not as 79.989999999999994884.

        The amounts are chosen so each one is a value ``int / 100`` cannot
        represent: 7999, 7500 and 499 pence.
        """
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = "test-location"
            mock_settings.square_environment = "production"

            with patch("app.api.v1.payments.get_payment_service") as mock_get_service:
                service = MagicMock()
                service.create_payment_link.return_value = {
                    "id": "LPM_TEST_LINK",
                    "url": "https://square.link/u/test",
                    "order_id": "square_order_123",
                }
                mock_get_service.return_value = service

                body = self._body(
                    str(shop_product.id), amount=7999, item_price=7500, shipping_cost=499
                )
                body.pop("payment_token")

                response = await payments_client.post("/api/v1/payments/hosted-checkout", json=body)
                assert response.status_code == 200, response.text
                order_number = response.json()["order_id"]

        order = await self._order_with_items(db_session, order_number)

        # Equality against an exact Decimal, never pytest.approx: the whole
        # point is that no approximation entered the column realised_margin.py
        # and channel_pnl.py read exactly.
        assert order.total == Decimal("79.99"), (
            f"the order total was written as {order.total!r}; integer division "
            f"by 100 is binary floating point and 7999 / 100 is not 79.99"
        )
        assert order.subtotal == Decimal("75.00")
        assert order.shipping_cost == Decimal("4.99")
        assert order.items[0].unit_price == Decimal("75.00")
        assert order.items[0].total_price == Decimal("75.00")

    async def test_process_payment_converts_pence_exactly(
        self,
        payments_client: AsyncClient,
        shop_product: Product,
        db_session: AsyncSession,
    ):
        """The Web Payments path writes exact amounts too, quantity included."""
        with patch("app.api.v1.payments.settings") as mock_settings:
            mock_settings.square_access_token = "test-token"
            mock_settings.square_location_id = "test-location"
            mock_settings.square_environment = "production"

            with patch("app.api.v1.payments.get_payment_service") as mock_get_service:
                service = MagicMock()
                service.process_payment.return_value = PaymentResponse(
                    success=True,
                    order_id="MF-TEMP123",
                    payment_id="sq_payment_456",
                    amount=6496,
                    currency="GBP",
                    status="COMPLETED",
                    receipt_url=None,
                    created_at=datetime.now(timezone.utc),
                )
                mock_get_service.return_value = service

                body = self._body(
                    str(shop_product.id), amount=0, item_price=1999, shipping_cost=499
                )
                body["items"][0]["quantity"] = 3
                body["amount"] = 1999 * 3 + 499

                with patch("app.api.v1.payments.get_email_service") as mock_get_email:
                    mock_get_email.return_value = MagicMock()
                    response = await payments_client.post("/api/v1/payments/process", json=body)
                assert response.status_code == 200, response.text
                order_number = response.json()["order_id"]

        order = await self._order_with_items(db_session, order_number)
        assert order.items[0].unit_price == Decimal("19.99")
        assert order.items[0].total_price == Decimal("59.97"), (
            f"the line total was written as {order.items[0].total_price!r}; "
            f"5997 / 100 in binary floating point is not 59.97"
        )
        assert order.total == Decimal("64.96")
        assert order.subtotal == Decimal("59.97")

    async def test_the_converter_is_exact_where_binary_division_is_not(self):
        """The unit the two routes now share, checked on its own.

        A route test proves the wiring; this proves the arithmetic, and the
        last assertion names the defect being defended against -- a value near
        enough to survive a display rounding and still be the wrong number in
        a ``Numeric`` column.
        """
        from app.core.money import pence_to_pounds

        assert pence_to_pounds(7999) == Decimal("79.99")
        assert pence_to_pounds(1) == Decimal("0.01")
        assert pence_to_pounds(0) == Decimal("0")
        assert pence_to_pounds(None) == Decimal("0")
        assert pence_to_pounds(Decimal("1999")) == Decimal("19.99")
        assert pence_to_pounds(-250) == Decimal("-2.50")

        # The parts sum to the whole, which binary division does not guarantee.
        assert pence_to_pounds(7500) + pence_to_pounds(499) == pence_to_pounds(7999)

        # The defect itself. `Decimal(float)` rather than `Decimal(str(float))`
        # on purpose: `str` prints the shortest representation that round-trips,
        # which is "79.99" and hides the value actually held. What `int / 100`
        # produces is the number below, and it is what every subsequent step --
        # a sum across lines, a comparison, a fee share -- was computed from.
        inexact = Decimal(7999 / 100)
        assert inexact != Decimal("79.99")
        assert str(inexact).startswith("79.98999999999999")
