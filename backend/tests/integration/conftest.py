"""Shared scaffolding for the settled-order integration tests.

One settled, snapshotted order with actuals recorded against it is the setup
both the SC-001 accuracy test and the realised-margin alert test need, and it
is 150 lines of it. It lives here so the two read the same sale: a divergence
test built on a different fixture would be comparing against a different plan,
and the two files would drift until one of them was quietly wrong.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core import clock
from app.models.fee_actual import FeeActual
from app.models.fee_rule import FeeRule
from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.product_model import ProductModel
from app.models.product_pricing import ProductPricing
from app.models.production_run import ProductionRun
from app.models.sales_channel import SalesChannel
from app.models.spool import Spool
from app.models.tenant_pricing_policy import TenantPricingPolicy
from app.services.sale_snapshot import write_sale_snapshot

pytestmark = pytest.mark.asyncio

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")
TOLERANCE = Decimal("2")

SALE_DAY = clock.today() - timedelta(days=20)
LIST_PRICE = Decimal("64.99")
SHIPPING_CHARGED = Decimal("6.00")
POSTAGE_PAID = Decimal("9.50")

#: What the statement actually charged, which is not what was planned.
FEES_ACTUALLY_CHARGED = Decimal("9.84")

#: What the plate actually used, against 145 g and 9.5 h planned.
GRAMS_ACTUALLY_USED = Decimal("155")
HOURS_ACTUALLY_TAKEN = Decimal("10.25")
COST_PER_GRAM_ACTUAL = Decimal("31.00") / Decimal("975")


@pytest_asyncio.fixture
async def settled(db_session, test_tenant, test_filament_type):
    """One settled, snapshotted order, with actuals recorded against it."""
    db_session.add(
        TenantPricingPolicy(
            id=uuid4(),
            tenant_id=test_tenant.id,
            print_labor_rate=Decimal("25.00"),
            finishing_labor_rate=Decimal("25.00"),
            overhead_method="per_machine_hour",
            overhead_monthly_pool=Decimal("180.00"),
            expected_monthly_machine_hours=Decimal("600"),
            electricity_rate_per_kwh=Decimal("0.13"),
            default_machine_rate_per_hour=Decimal("0.23235"),
            margin_basis="customer_total",
            effective_from=SALE_DAY - timedelta(days=60),
        )
    )

    spool = Spool(
        id=uuid4(),
        tenant_id=test_tenant.id,
        filament_type_id=test_filament_type.id,
        spool_id=f"REAL-{uuid4().hex[:6]}",
        initial_weight=Decimal("1000"),
        current_weight=Decimal("700"),
        purchase_price=Decimal("31.00"),
        unusable_remainder_grams=Decimal("25"),
        is_active=True,
        is_labeled=True,
    )
    db_session.add(spool)
    await db_session.flush()

    model = Model(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku=f"REAL-MODEL-{uuid4().hex[:6]}",
        name="Settled part",
        print_time_minutes=570,
        prints_per_plate=1,
        waste_grams=Decimal("3"),
        expected_yield=Decimal("0.92"),
        failure_mode="per_part",
        labor_hours_per_item=Decimal("0.25"),
        packing_hours_per_item=Decimal("0.0833"),
        is_active=True,
    )
    db_session.add(model)
    await db_session.flush()
    db_session.add(
        ModelMaterial(
            id=uuid4(),
            model_id=model.id,
            spool_id=spool.id,
            weight_grams=Decimal("142"),
            cost_per_gram=spool.cost_per_gram,
        )
    )

    product = Product(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku=f"REAL-PROD-{uuid4().hex[:6]}",
        name="Settled product",
        packaging_cost=Decimal("0.92"),
        packaging_quantity=1,
        units_in_stock=5,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()
    db_session.add(ProductModel(id=uuid4(), product_id=product.id, model_id=model.id, quantity=1))

    # The operator keeps their books in the currency the channel sells in, so

    # costs and prices meet without a conversion (task T231).

    test_tenant.currency_code = "CAD"

    db_session.add(test_tenant)

    channel = SalesChannel(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Realised Marketplace",
        platform_type="etsy",
        monthly_cost=Decimal("0"),
        currency_code="CAD",
        tax_remitter="marketplace",
        expected_discount_pct=ZERO,
        expected_refund_pct=ZERO,
        is_active=True,
    )
    db_session.add(channel)
    await db_session.flush()

    db_session.add(
        FeeRule(
            id=uuid4(),
            tenant_id=test_tenant.id,
            sales_channel_id=channel.id,
            name="transaction",
            basis="item_plus_shipping",
            rate_pct=Decimal("6.5"),
            fixed_amount=Decimal("0.30"),
            sort_order=10,
            applies_from=SALE_DAY - timedelta(days=90),
        )
    )
    db_session.add(
        ProductPricing(
            id=uuid4(),
            product_id=product.id,
            sales_channel_id=channel.id,
            list_price=LIST_PRICE,
            valid_from=SALE_DAY - timedelta(days=60),
            min_quantity=1,
        )
    )
    await db_session.flush()

    order = Order(
        id=uuid4(),
        tenant_id=test_tenant.id,
        order_number=f"REAL-{uuid4().hex[:6]}",
        sales_channel_id=channel.id,
        status=OrderStatus.DELIVERED,
        customer_email="buyer@example.test",
        customer_name="Buyer",
        shipping_address_line1="1 Realised Way",
        shipping_city="Victoria",
        shipping_postcode="V8W 1A1",
        shipping_country="Canada",
        shipping_method="Standard",
        shipping_cost=SHIPPING_CHARGED,
        postage_paid=POSTAGE_PAID,
        subtotal=LIST_PRICE,
        total=LIST_PRICE + SHIPPING_CHARGED,
        currency="CAD",
        payment_provider="test",
        payment_status="completed",
    )
    order.items.append(
        OrderItem(
            id=uuid4(),
            tenant_id=test_tenant.id,
            product_id=product.id,
            product_sku=product.sku,
            product_name=product.name,
            quantity=1,
            unit_price=LIST_PRICE,
            total_price=LIST_PRICE,
        )
    )
    db_session.add(order)
    await db_session.flush()

    result = await write_sale_snapshot(db_session, test_tenant, order, as_of=SALE_DAY)
    assert result.wrote_anything, "the fixture must freeze a snapshot to compare against"

    # What the statement actually charged for this order (FR-041b).
    db_session.add(
        FeeActual(
            id=uuid4(),
            tenant_id=test_tenant.id,
            sales_channel_id=channel.id,
            fee_category="transaction",
            order_id=order.id,
            amount=FEES_ACTUALLY_CHARGED,
            source="entered",
        )
    )

    # What the plate actually used.
    started = datetime.now(timezone.utc) - timedelta(days=18)
    run = ProductionRun(
        id=uuid4(),
        tenant_id=test_tenant.id,
        product_id=product.id,
        run_number=f"RUN-{uuid4().hex[:6]}",
        started_at=started,
        completed_at=started + timedelta(hours=11),
        duration_hours=HOURS_ACTUALLY_TAKEN,
        actual_total_weight_grams=GRAMS_ACTUALLY_USED,
        cost_per_gram_actual=COST_PER_GRAM_ACTUAL,
        status="completed",
        total_plates=1,
        completed_plates=1,
    )
    db_session.add(run)
    await db_session.commit()

    return {"order": order, "run": run, "product": product, "channel": channel}


async def reload_item(db_session, order) -> OrderItem:
    return (
        (
            await db_session.execute(
                select(OrderItem)
                .where(OrderItem.order_id == order.id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .first()
    )
