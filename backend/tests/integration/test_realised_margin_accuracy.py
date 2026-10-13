"""The margin reported for a settled sale tracks what actually moved (T117a).

SC-001: for a settled order, the margin the system reports is within **two
percentage points** of the margin computed from what was actually received and
actually paid.

## Why the tolerance exists, and why it is not a licence

Two points is there for rounding and for the figures nobody can realise -- the
labor somebody spent, the overhead absorbed, the failure premium charged
against starts that never became parts. None of those has an observed
counterpart on a single run, so they stay as the sale was costed. What *is*
realisable is the cash: the fees a statement actually charged, the filament a
run actually used, the hours a plate actually occupied.

So the expected figure in this file is assembled **from the records**, not from
the service: revenue as the order recorded it, fees as the statement recorded
them, material and machine from the production run's own actuals, and the
remaining cost lines from the snapshot the sale was priced on. If the reader
agreed with that to the cent, two points would be a generous margin; the point
of the tolerance is that it does not have to.

## The control, without which this proves nothing

``TestTheFigureTracksTheActuals`` makes a run use three times the filament and
requires the reported margin to **move by more than two points**. Without it
every assertion here would pass for a reader that ignored the actuals entirely
and echoed the snapshot -- which is precisely the defect SC-001 exists to
catch, since the snapshot is the planned margin and is right by construction.
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
from app.services.realised_margin import realised_margin
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
    db_session.add(
        ProductModel(id=uuid4(), product_id=product.id, model_id=model.id, quantity=1)
    )

    channel = SalesChannel(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Realised Marketplace",
        platform_type="etsy",
        fee_percentage=Decimal("0"),
        fee_fixed=Decimal("0"),
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
        await db_session.execute(
            select(OrderItem)
            .where(OrderItem.order_id == order.id)
            .execution_options(populate_existing=True)
        )
    ).scalars().first()


def margin_from_the_records(item: OrderItem, *, fees_paid: Decimal, run) -> Decimal:
    """The margin, assembled from what moved rather than from the reader.

    Revenue is what the order recorded. Fees are what the statement recorded.
    Material and machine come from the run's own actuals. Labor, overhead and
    packaging come from the snapshot, because a single run says nothing about
    them -- which is the honest limit of a realised figure, and part of what
    the two-point tolerance covers.
    """
    breakdown = item.cost_breakdown_json or {}
    lines = {line["key"]: Decimal(str(line["amount"])) for line in breakdown.get("lines", [])}

    material = Decimal(str(run.actual_total_weight_grams)) * Decimal(
        str(run.cost_per_gram_actual)
    )
    machine_rate = lines["machine"] / Decimal(str(breakdown["machine_hours"]))
    machine = Decimal(str(run.duration_hours)) * machine_rate

    unrealisable = sum(
        (amount for key, amount in lines.items() if key not in ("material", "waste", "machine")),
        ZERO,
    )
    premium = Decimal(str(breakdown.get("failure_premium", "0")))

    cash_in = Decimal(str(item.total_price)) + SHIPPING_CHARGED
    cash_out = fees_paid + material + machine + unrealisable + premium + POSTAGE_PAID

    return ((cash_in - cash_out) / cash_in * HUNDRED).quantize(Decimal("0.0001"))


# ---------------------------------------------------------------------------
# SC-001
# ---------------------------------------------------------------------------


class TestTheReportedMarginIsWithinTwoPoints:
    async def test_it_agrees_with_the_margin_from_what_moved(
        self, db_session, test_tenant, settled
    ) -> None:
        item = await reload_item(db_session, settled["order"])

        reported = await realised_margin(db_session, test_tenant, item)
        expected = margin_from_the_records(
            item, fees_paid=FEES_ACTUALLY_CHARGED, run=settled["run"]
        )

        assert reported.margin_pct is not None
        assert abs(reported.margin_pct - expected) <= TOLERANCE

    async def test_the_revenue_is_what_the_order_recorded(
        self, db_session, test_tenant, settled
    ) -> None:
        # Not the list price frozen at sale: what the customer was charged is
        # what the order says, discounts and all.
        item = await reload_item(db_session, settled["order"])

        reported = await realised_margin(db_session, test_tenant, item)

        assert reported.revenue_received == LIST_PRICE + SHIPPING_CHARGED

    async def test_the_fees_are_the_ones_the_statement_charged(
        self, db_session, test_tenant, settled
    ) -> None:
        item = await reload_item(db_session, settled["order"])

        reported = await realised_margin(db_session, test_tenant, item)

        assert reported.fees_paid == FEES_ACTUALLY_CHARGED
        assert reported.fees_source == "actual"

    async def test_it_names_the_figures_that_came_from_observations(
        self, db_session, test_tenant, settled
    ) -> None:
        # A realised margin that cannot say which figures are realised is a
        # planned margin with a different label (FR-001).
        item = await reload_item(db_session, settled["order"])

        reported = await realised_margin(db_session, test_tenant, item)

        joined = " ".join(reported.substitutions)
        assert "fees" in joined
        assert "material" in joined
        assert "machine time" in joined

    async def test_the_postage_paid_is_a_cost(
        self, db_session, test_tenant, settled
    ) -> None:
        item = await reload_item(db_session, settled["order"])

        reported = await realised_margin(db_session, test_tenant, item)

        assert reported.postage_paid == POSTAGE_PAID

    async def test_it_writes_nothing(self, db_session, test_tenant, settled) -> None:
        # Constitution V: a realised margin is recomputed, never stored -- and
        # the snapshot it reads is immutable (FR-038).
        item = await reload_item(db_session, settled["order"])
        before = (
            item.make_cost_at_sale,
            item.list_price_at_sale,
            item.margin_basis_at_sale,
        )

        await realised_margin(db_session, test_tenant, item)
        await db_session.commit()

        after = await reload_item(db_session, settled["order"])
        assert (
            after.make_cost_at_sale,
            after.list_price_at_sale,
            after.margin_basis_at_sale,
        ) == before


class TestTheFigureTracksTheActuals:
    """The control. Without it every assertion above passes for a reader that
    echoed the snapshot, which is the planned margin and right by
    construction."""

    async def test_three_times_the_filament_moves_the_margin(
        self, db_session, test_tenant, settled
    ) -> None:
        item = await reload_item(db_session, settled["order"])
        before = await realised_margin(db_session, test_tenant, item)

        run = settled["run"]
        run.actual_total_weight_grams = GRAMS_ACTUALLY_USED * 3
        db_session.add(run)
        await db_session.commit()

        after = await realised_margin(db_session, test_tenant, item)

        assert before.margin_pct is not None and after.margin_pct is not None
        assert before.margin_pct - after.margin_pct > TOLERANCE

    async def test_an_hour_longer_on_the_machine_moves_the_margin(
        self, db_session, test_tenant, settled
    ) -> None:
        # Smaller than the filament effect, by design: a machine hour on this
        # case costs pennies. What matters is the direction and that it moves
        # at all -- a reader ignoring the run would report the same figure.
        item = await reload_item(db_session, settled["order"])
        before = await realised_margin(db_session, test_tenant, item)

        run = settled["run"]
        run.duration_hours = HOURS_ACTUALLY_TAKEN + Decimal("40")
        db_session.add(run)
        await db_session.commit()

        after = await realised_margin(db_session, test_tenant, item)

        assert after.margin_pct < before.margin_pct

    async def test_a_worse_statement_moves_the_margin(
        self, db_session, test_tenant, settled
    ) -> None:
        item = await reload_item(db_session, settled["order"])
        before = await realised_margin(db_session, test_tenant, item)

        db_session.add(
            FeeActual(
                id=uuid4(),
                tenant_id=test_tenant.id,
                sales_channel_id=settled["channel"].id,
                fee_category="offsite_ads",
                order_id=settled["order"].id,
                amount=Decimal("8.00"),
                source="entered",
            )
        )
        await db_session.commit()

        after = await realised_margin(db_session, test_tenant, item)

        assert before.margin_pct - after.margin_pct > TOLERANCE


class TestWhatIsMissingIsSaidPlainly:
    async def test_without_a_statement_it_uses_the_planned_fees_and_says_so(
        self, db_session, test_tenant, settled
    ) -> None:
        # FR-041e: a planned fee must never be presented as a reconciled one.
        from sqlalchemy import delete

        await db_session.execute(delete(FeeActual))
        await db_session.commit()
        item = await reload_item(db_session, settled["order"])

        reported = await realised_margin(db_session, test_tenant, item)

        assert reported.fees_source == "planned"
        assert any("reconciled" in gap for gap in reported.gaps)

    async def test_without_a_run_it_says_nothing_was_observed(
        self, db_session, test_tenant, settled
    ) -> None:
        from sqlalchemy import delete

        await db_session.execute(delete(ProductionRun))
        await db_session.commit()
        item = await reload_item(db_session, settled["order"])

        reported = await realised_margin(db_session, test_tenant, item)

        assert any("production run" in gap for gap in reported.gaps)
        assert not any("material" in note for note in reported.substitutions)

    async def test_a_run_with_no_weight_recorded_says_so(
        self, db_session, test_tenant, settled
    ) -> None:
        run = settled["run"]
        run.actual_total_weight_grams = None
        db_session.add(run)
        await db_session.commit()
        item = await reload_item(db_session, settled["order"])

        reported = await realised_margin(db_session, test_tenant, item)

        assert any("filament weight" in gap for gap in reported.gaps)

    async def test_with_nothing_observed_it_still_reports_a_margin(
        self, db_session, test_tenant, settled
    ) -> None:
        # Degrading to the planned figures is correct; refusing to report is
        # not. An operator asking "what did this earn" gets the best available
        # answer, with its gaps named.
        from sqlalchemy import delete

        await db_session.execute(delete(FeeActual))
        await db_session.execute(delete(ProductionRun))
        await db_session.commit()
        item = await reload_item(db_session, settled["order"])

        reported = await realised_margin(db_session, test_tenant, item)

        assert reported.margin_pct is not None
        assert reported.gaps
