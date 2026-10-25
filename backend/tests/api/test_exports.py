"""Tests for CSV export API endpoints."""

import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from httpx import AsyncClient

from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.product_pricing import ProductPricing
from app.models.product_variant import FulfilmentType, ProductVariant
from app.models.sales_channel import SalesChannel


class TestExportProducts:
    """Tests for product export endpoint."""

    @pytest.mark.asyncio
    async def test_export_products_csv(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_tenant,
        db_session,
    ):
        """Test exporting products as CSV."""
        # Create a test product
        product = Product(
            tenant_id=test_tenant.id,
            name="Test Export Product",
            sku="TEST-EXPORT-001",
            description="A test product for export",
            is_active=True,
            shop_visible=True,
            units_in_stock=10,
        )
        db_session.add(product)
        await db_session.commit()

        response = await async_client.get(
            "/api/v1/exports/products",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "products_" in response.headers["content-disposition"]
        assert ".csv" in response.headers["content-disposition"]

        # Parse CSV and verify content
        csv_content = response.text
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        # Should have at least one row
        assert len(rows) >= 1

        # Find our test product
        test_product_rows = [r for r in rows if r["Variant SKU"] == "TEST-EXPORT-001"]
        assert len(test_product_rows) == 1

        row = test_product_rows[0]
        assert row["Title"] == "Test Export Product"
        assert row["Variant Inventory Qty"] == "10"
        assert row["Published"] == "TRUE"
        assert row["Status"] == "active"

    @pytest.mark.asyncio
    async def test_export_products_shopify_columns(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        """Test that exported CSV has all required Shopify columns."""
        response = await async_client.get(
            "/api/v1/exports/products",
            headers=auth_headers,
        )

        assert response.status_code == 200

        csv_content = response.text
        reader = csv.DictReader(io.StringIO(csv_content))

        # Required Shopify columns
        required_columns = [
            "Handle",
            "Title",
            "Body (HTML)",
            "Vendor",
            "Type",
            "Tags",
            "Published",
            "Variant SKU",
            "Variant Grams",
            "Variant Inventory Qty",
            "Variant Price",
            "Image Src",
            "Status",
        ]

        for col in required_columns:
            assert col in reader.fieldnames, f"Missing required column: {col}"

    @pytest.mark.asyncio
    async def test_export_products_with_variants(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_tenant,
        db_session,
    ):
        """Products with size variants export one row per variant with Option1 Name = Size."""
        product = Product(
            tenant_id=test_tenant.id,
            name="Skeleton Triceratops",
            sku="SKEL-TRICE",
            description="Articulated skeleton triceratops",
            is_active=True,
            shop_visible=True,
            units_in_stock=0,
        )
        db_session.add(product)
        await db_session.flush()

        small = ProductVariant(
            tenant_id=test_tenant.id,
            product_id=product.id,
            size="Small",
            display_order=0,
            sku="SKEL-TRICE-SMALL",
            price_adjustment_pence=0,
            units_in_stock=3,
            fulfilment_type=FulfilmentType.STOCK,
        )
        large = ProductVariant(
            tenant_id=test_tenant.id,
            product_id=product.id,
            size="Large",
            display_order=1,
            sku="SKEL-TRICE-LARGE",
            price_adjustment_pence=500,  # +£5
            units_in_stock=0,
            fulfilment_type=FulfilmentType.PRINT_TO_ORDER,
            lead_time_days=5,
        )
        db_session.add(small)
        db_session.add(large)
        await db_session.commit()

        response = await async_client.get(
            "/api/v1/exports/products",
            headers=auth_headers,
        )

        assert response.status_code == 200
        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)

        # Find rows for our product (by handle)
        trice_rows = [r for r in rows if r["Handle"] == "skel-trice"]
        assert len(trice_rows) == 2, f"Expected 2 variant rows, got {len(trice_rows)}"

        small_row = next(r for r in trice_rows if r["Variant SKU"] == "SKEL-TRICE-SMALL")
        large_row = next(r for r in trice_rows if r["Variant SKU"] == "SKEL-TRICE-LARGE")

        assert small_row["Option1 Name"] == "Size"
        assert small_row["Option1 Value"] == "Small"
        assert small_row["Variant Inventory Policy"] == "deny"  # stock
        assert small_row["Variant Inventory Qty"] == "3"

        assert large_row["Option1 Name"] == "Size"
        assert large_row["Option1 Value"] == "Large"
        assert large_row["Variant Inventory Policy"] == "continue"  # print-to-order

        # Title/Body only on first row
        assert small_row["Title"] == "Skeleton Triceratops"
        assert large_row["Title"] == ""


class TestExportInventory:
    """Tests for inventory export endpoint."""

    @pytest.mark.asyncio
    async def test_export_inventory_csv(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_tenant,
        db_session,
    ):
        """Test exporting inventory as CSV."""
        # Create a test product
        product = Product(
            tenant_id=test_tenant.id,
            name="Inventory Test Product",
            sku="INV-TEST-001",
            units_in_stock=25,
        )
        db_session.add(product)
        await db_session.commit()

        response = await async_client.get(
            "/api/v1/exports/inventory",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "inventory_" in response.headers["content-disposition"]

        csv_content = response.text
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        # Find our test product
        test_rows = [r for r in rows if r["SKU"] == "INV-TEST-001"]
        assert len(test_rows) == 1
        assert test_rows[0]["Default"] == "25"

    @pytest.mark.asyncio
    async def test_export_inventory_custom_location(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        """Test exporting inventory with custom location name."""
        response = await async_client.get(
            "/api/v1/exports/inventory?location=Warehouse",
            headers=auth_headers,
        )

        assert response.status_code == 200

        csv_content = response.text
        reader = csv.DictReader(io.StringIO(csv_content))

        # Check that Warehouse column exists
        assert "Warehouse" in reader.fieldnames


class TestExportOrders:
    """Tests for orders export endpoint."""

    @pytest.mark.asyncio
    async def test_export_orders_csv(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_tenant,
        db_session,
    ):
        """Test exporting orders as CSV."""
        # Create a test order with items
        order = Order(
            tenant_id=test_tenant.id,
            order_number="TEST-ORD-EXPORT-001",
            customer_name="Export Test Customer",
            customer_email="export@test.com",
            status=OrderStatus.PROCESSING,
            payment_status="completed",
            subtotal=Decimal("50.00"),
            shipping_cost=Decimal("5.00"),
            total=Decimal("55.00"),
            currency="GBP",
            shipping_method="Standard",
            shipping_address_line1="123 Export St",
            shipping_city="London",
            shipping_postcode="SW1A 1AA",
            shipping_country="GB",
            payment_provider="square",
        )
        db_session.add(order)
        await db_session.flush()

        # Add order item (product_id=None since we don't need a real product)
        item = OrderItem(
            tenant_id=test_tenant.id,
            order_id=order.id,
            product_id=None,
            product_name="Test Export Item",
            product_sku="EXP-ITEM-001",
            quantity=2,
            unit_price=Decimal("25.00"),
            total_price=Decimal("50.00"),
        )
        db_session.add(item)
        await db_session.commit()

        response = await async_client.get(
            "/api/v1/exports/orders",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "orders_" in response.headers["content-disposition"]

        csv_content = response.text
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        # Find our test order
        test_rows = [r for r in rows if r["Name"] == "TEST-ORD-EXPORT-001"]
        assert len(test_rows) >= 1

        row = test_rows[0]
        assert row["Email"] == "export@test.com"
        assert row["Financial Status"] == "paid"
        assert row["Total"] == "55.00"
        assert row["Lineitem name"] == "Test Export Item"
        assert row["Lineitem quantity"] == "2"

    @pytest.mark.asyncio
    async def test_export_orders_date_filter(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_tenant,
        db_session,
    ):
        """Test exporting orders with date filters."""
        # Create orders with different dates
        old_order = Order(
            tenant_id=test_tenant.id,
            order_number="OLD-ORDER-001",
            customer_name="Old Customer",
            customer_email="old@test.com",
            status=OrderStatus.DELIVERED,
            payment_status="completed",
            subtotal=Decimal("20.00"),
            total=Decimal("20.00"),
            currency="GBP",
            shipping_method="Standard",
            shipping_address_line1="123 Old St",
            shipping_city="London",
            shipping_postcode="SW1A 1AA",
            shipping_country="GB",
            payment_provider="square",
        )
        old_order.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
        db_session.add(old_order)
        await db_session.commit()

        # Filter to exclude old order
        response = await async_client.get(
            "/api/v1/exports/orders?start_date=2025-01-01",
            headers=auth_headers,
        )

        assert response.status_code == 200

        csv_content = response.text
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        # Old order should not be in results
        old_orders = [r for r in rows if r["Name"] == "OLD-ORDER-001"]
        assert len(old_orders) == 0

    @pytest.mark.asyncio
    async def test_export_orders_accounting_format(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_tenant,
        db_session,
    ):
        """Test exporting orders in accounting format."""
        # Create a test order
        order = Order(
            tenant_id=test_tenant.id,
            order_number="ACC-ORD-001",
            customer_name="Accounting Customer",
            customer_email="accounting@test.com",
            status=OrderStatus.DELIVERED,
            payment_status="completed",
            subtotal=Decimal("100.00"),
            shipping_cost=Decimal("10.00"),
            total=Decimal("110.00"),
            currency="GBP",
            shipping_method="Standard",
            shipping_address_line1="123 Acc St",
            shipping_city="London",
            shipping_postcode="SW1A 1AA",
            shipping_country="GB",
            payment_provider="square",
        )
        db_session.add(order)
        await db_session.flush()

        item = OrderItem(
            tenant_id=test_tenant.id,
            order_id=order.id,
            product_id=None,  # No real product needed for export test
            product_name="Accounting Item",
            product_sku="ACC-001",
            quantity=1,
            unit_price=Decimal("100.00"),
            total_price=Decimal("100.00"),
        )
        db_session.add(item)
        await db_session.commit()

        response = await async_client.get(
            "/api/v1/exports/orders?format=accounting",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert "orders_accounting_" in response.headers["content-disposition"]

        csv_content = response.text
        reader = csv.DictReader(io.StringIO(csv_content))

        # Accounting format columns
        accounting_columns = [
            "Date",
            "Invoice Number",
            "Customer Name",
            "Customer Email",
            "Description",
            "Quantity",
            "Unit Price",
            "Line Total",
            "Subtotal",
            "Shipping",
            "Total",
            "Payment Status",
            "Payment Method",
        ]

        for col in accounting_columns:
            assert col in reader.fieldnames, f"Missing accounting column: {col}"

        rows = list(reader)
        acc_rows = [r for r in rows if r["Invoice Number"] == "ACC-ORD-001"]
        assert len(acc_rows) == 1


class TestExportAuth:
    """Tests for export endpoint authentication."""

    @pytest.mark.asyncio
    async def test_export_requires_auth(
        self,
        unauthenticated_client: AsyncClient,
    ):
        """Test that export endpoints require authentication."""
        # Products export
        response = await unauthenticated_client.get("/api/v1/exports/products")
        assert response.status_code == 401

        # Inventory export
        response = await unauthenticated_client.get("/api/v1/exports/inventory")
        assert response.status_code == 401

        # Orders export
        response = await unauthenticated_client.get("/api/v1/exports/orders")
        assert response.status_code == 401


class TestTheExportedPriceIsTheOneInForce:
    """Task T274: never a superseded row, a quantity tier or another channel's price."""

    @staticmethod
    async def _priced_product(db_session, test_tenant) -> tuple[Product, SalesChannel]:
        shopify = SalesChannel(
            tenant_id=test_tenant.id, name="Shopify", platform_type="shopify", is_active=True
        )
        fair = SalesChannel(
            tenant_id=test_tenant.id, name="Fair", platform_type="fair", is_active=True
        )
        product = Product(
            tenant_id=test_tenant.id,
            name="Priced Dragon",
            sku="PRICED-DRAGON",
            is_active=True,
            shop_visible=True,
            units_in_stock=1,
        )
        db_session.add_all([shopify, fair, product])
        await db_session.flush()
        db_session.add_all(
            [
                # Superseded: last spring's price, no longer in force.
                ProductPricing(
                    product_id=product.id,
                    sales_channel_id=shopify.id,
                    list_price=Decimal("20.00"),
                    is_active=True,
                    valid_from=date(2026, 1, 1),
                    valid_to=date(2026, 3, 31),
                ),
                ProductPricing(
                    product_id=product.id,
                    sales_channel_id=shopify.id,
                    list_price=Decimal("25.00"),
                    is_active=True,
                    valid_from=date(2026, 4, 1),
                ),
                # A ten-or-more tier is not the price of one.
                ProductPricing(
                    product_id=product.id,
                    sales_channel_id=shopify.id,
                    list_price=Decimal("22.00"),
                    is_active=True,
                    valid_from=date(2026, 4, 1),
                    min_quantity=10,
                ),
                ProductPricing(
                    product_id=product.id,
                    sales_channel_id=fair.id,
                    list_price=Decimal("30.00"),
                    is_active=True,
                    valid_from=date(2026, 4, 1),
                ),
            ]
        )
        await db_session.commit()
        return product, fair

    @staticmethod
    async def _row(async_client, auth_headers, params=None) -> dict:
        response = await async_client.get(
            "/api/v1/exports/products", headers=auth_headers, params=params or {}
        )
        assert response.status_code == 200, response.text
        rows = list(csv.DictReader(io.StringIO(response.text)))
        return next(r for r in rows if r["Variant SKU"] == "PRICED-DRAGON")

    @pytest.mark.asyncio
    async def test_the_shopify_price_of_one_is_exported(
        self, async_client: AsyncClient, auth_headers: dict, test_tenant, db_session
    ):
        await self._priced_product(db_session, test_tenant)
        row = await self._row(async_client, auth_headers)
        assert row["Variant Price"] == "25.00"
        assert row["Cost per item"] == ""

    @pytest.mark.asyncio
    async def test_a_named_channel_exports_its_own_price(
        self, async_client: AsyncClient, auth_headers: dict, test_tenant, db_session
    ):
        _, fair = await self._priced_product(db_session, test_tenant)
        row = await self._row(async_client, auth_headers, {"channel_id": str(fair.id)})
        assert row["Variant Price"] == "30.00"

    @pytest.mark.asyncio
    async def test_a_product_unpriced_on_the_channel_exports_no_price(
        self, async_client: AsyncClient, auth_headers: dict, test_tenant, db_session
    ):
        fair = SalesChannel(
            tenant_id=test_tenant.id, name="Fair only", platform_type="fair", is_active=True
        )
        product = Product(
            tenant_id=test_tenant.id,
            name="Fair Dragon",
            sku="PRICED-DRAGON",
            is_active=True,
            shop_visible=True,
            units_in_stock=1,
        )
        db_session.add_all([fair, product])
        await db_session.flush()
        db_session.add(
            ProductPricing(
                product_id=product.id,
                sales_channel_id=fair.id,
                list_price=Decimal("30.00"),
                is_active=True,
                valid_from=date(2026, 4, 1),
            )
        )
        await db_session.commit()

        row = await self._row(async_client, auth_headers)
        assert row["Variant Price"] == ""

    @pytest.mark.asyncio
    async def test_a_typed_variant_cost_is_not_exported_as_the_cost(
        self, async_client: AsyncClient, auth_headers: dict, test_tenant, db_session
    ):
        product, _ = await self._priced_product(db_session, test_tenant)
        db_session.add(
            ProductVariant(
                tenant_id=test_tenant.id,
                product_id=product.id,
                size="Large",
                display_order=0,
                sku="PRICED-DRAGON-L",
                price_adjustment_pence=500,
                units_in_stock=1,
                fulfilment_type=FulfilmentType.STOCK,
                material_cost_pence=1234,
            )
        )
        await db_session.commit()

        response = await async_client.get("/api/v1/exports/products", headers=auth_headers)
        rows = list(csv.DictReader(io.StringIO(response.text)))
        large = next(r for r in rows if r["Variant SKU"] == "PRICED-DRAGON-L")
        assert Decimal(large["Variant Price"]) == Decimal("30.00")
        assert large["Cost per item"] == ""
