"""What the CSV exports say about an order's money (T199, T200).

These are the files an operator hands their accountant, and until now they
carried two figures that were not the ones the system holds:

* `Taxes` was hardcoded to `Decimal("0")` under the comment "we include VAT in
  prices", and the accounting format had no tax column at all -- while
  `Order.sales_tax_collected` is written on every order and
  `reconciliation.py` already reports it per channel as a liability where the
  operator remits it (FR-028a, FR-028d, FR-028e).
* `Refunded Amount` was `order.total` for any order whose status is
  `REFUNDED`. A partial refund sets the same status, so a 5 pound goodwill
  refund on an 80 pound order exported as 80 pounds (FR-040, FR-048).

The authority for the second figure is `RefundActual`, written by
`record_refund` and summed by `refunded_total`, which `realised_margin`
already reads. The export asking its own question of `order.status` was a
second, disagreeing answer, which FR-048 forbids whether or not the two
happen to agree today.
"""

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem, OrderStatus
from app.models.refund_actual import RefundActual
from app.models.tenant import Tenant
from app.services.export_service import ExportService

pytestmark = pytest.mark.asyncio


async def _order(
    db_session: AsyncSession,
    tenant: Tenant,
    *,
    number: str,
    total: Decimal,
    sales_tax_collected: Decimal,
    status: str = OrderStatus.DELIVERED,
) -> Order:
    order = Order(
        id=uuid4(),
        tenant_id=tenant.id,
        order_number=number,
        status=status,
        customer_email="buyer@example.invalid",
        customer_name="A Buyer",
        shipping_address_line1="1 Test Street",
        shipping_city="London",
        shipping_postcode="SW1A 1AA",
        shipping_country="United Kingdom",
        shipping_method="Standard",
        shipping_cost=Decimal("4.99"),
        subtotal=total - Decimal("4.99"),
        total=total,
        sales_tax_collected=sales_tax_collected,
        currency="GBP",
        payment_provider="square",
        payment_status="completed",
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            id=uuid4(),
            tenant_id=tenant.id,
            order_id=order.id,
            product_name="A printed thing",
            product_sku="THING-001",
            quantity=1,
            unit_price=total - Decimal("4.99"),
            total_price=total - Decimal("4.99"),
        )
    )
    await db_session.commit()
    await db_session.refresh(order)
    return order


async def _record_refund(
    db_session: AsyncSession, tenant: Tenant, order: Order, amount: Decimal
) -> None:
    db_session.add(
        RefundActual(
            id=uuid4(),
            tenant_id=tenant.id,
            order_id=order.id,
            amount=amount,
            currency="GBP",
            refunded_at=datetime.now(timezone.utc),
            source="entered",
        )
    )
    await db_session.commit()


def _rows(csv_text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(csv_text)))


@pytest_asyncio.fixture
def service(db_session: AsyncSession, test_tenant: Tenant) -> ExportService:
    return ExportService(db=db_session, tenant=test_tenant)


class TestTheShopifyExportReportsTheTaxThatWasCollected:
    async def test_it_reports_the_recorded_figure_not_zero(
        self, service: ExportService, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        await _order(
            db_session,
            test_tenant,
            number="ORD-TAX-001",
            total=Decimal("84.00"),
            sales_tax_collected=Decimal("14.00"),
        )

        row = _rows(await service.export_orders_csv())[0]

        assert Decimal(row["Taxes"]) == Decimal("14.00")

    async def test_a_tax_free_order_still_reports_zero(
        self, service: ExportService, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        """Zero is the right answer when zero is what was recorded."""
        await _order(
            db_session,
            test_tenant,
            number="ORD-TAX-002",
            total=Decimal("30.00"),
            sales_tax_collected=Decimal("0.00"),
        )

        row = _rows(await service.export_orders_csv())[0]

        assert Decimal(row["Taxes"]) == Decimal("0")


class TestTheAccountingExportCarriesTheTax:
    async def test_the_format_has_a_tax_column(
        self, service: ExportService, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        await _order(
            db_session,
            test_tenant,
            number="ORD-TAX-003",
            total=Decimal("84.00"),
            sales_tax_collected=Decimal("14.00"),
        )

        rows = _rows(await service.export_orders_accounting_csv())

        assert "Tax" in rows[0], (
            "the accounting export carries no tax column, so the one file the "
            "operator hands their accountant is silent about the liability"
        )
        assert Decimal(rows[0]["Tax"]) == Decimal("14.00")


class TestTheExportsReportTheRefundThatWasRecorded:
    async def test_a_partial_refund_exports_its_own_amount(
        self, service: ExportService, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        """The regression: 5 refunded on an 80 order is not 80 refunded."""
        order = await _order(
            db_session,
            test_tenant,
            number="ORD-REF-001",
            total=Decimal("80.00"),
            sales_tax_collected=Decimal("0.00"),
            status=OrderStatus.REFUNDED,
        )
        await _record_refund(db_session, test_tenant, order, Decimal("5.00"))

        row = _rows(await service.export_orders_csv())[0]

        assert Decimal(row["Refunded Amount"]) == Decimal("5.00")

    async def test_two_partial_refunds_add_up(
        self, service: ExportService, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        order = await _order(
            db_session,
            test_tenant,
            number="ORD-REF-002",
            total=Decimal("80.00"),
            sales_tax_collected=Decimal("0.00"),
            status=OrderStatus.REFUNDED,
        )
        await _record_refund(db_session, test_tenant, order, Decimal("5.00"))
        await _record_refund(db_session, test_tenant, order, Decimal("7.50"))

        row = _rows(await service.export_orders_csv())[0]

        assert Decimal(row["Refunded Amount"]) == Decimal("12.50")

    async def test_a_refunded_status_with_no_recorded_actual_exports_nothing(
        self, service: ExportService, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        """A blank cell says "not recorded"; a figure would be a guess.

        FR-040 wants the actual reported, not inferred from a status, and an
        empty column is the honest answer where no actual was recorded.
        """
        await _order(
            db_session,
            test_tenant,
            number="ORD-REF-003",
            total=Decimal("80.00"),
            sales_tax_collected=Decimal("0.00"),
            status=OrderStatus.REFUNDED,
        )

        row = _rows(await service.export_orders_csv())[0]

        assert row["Refunded Amount"] == ""

    async def test_an_unrefunded_order_exports_nothing(
        self, service: ExportService, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        await _order(
            db_session,
            test_tenant,
            number="ORD-REF-004",
            total=Decimal("80.00"),
            sales_tax_collected=Decimal("0.00"),
        )

        row = _rows(await service.export_orders_csv())[0]

        assert row["Refunded Amount"] == ""

    async def test_the_accounting_export_reports_the_same_figure(
        self, service: ExportService, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        """FR-048: one refund, one answer, whichever file asks."""
        order = await _order(
            db_session,
            test_tenant,
            number="ORD-REF-005",
            total=Decimal("80.00"),
            sales_tax_collected=Decimal("0.00"),
            status=OrderStatus.REFUNDED,
        )
        await _record_refund(db_session, test_tenant, order, Decimal("5.00"))

        shopify = _rows(await service.export_orders_csv())[0]
        accounting = _rows(await service.export_orders_accounting_csv())[0]

        assert accounting["Refunded Amount"] == shopify["Refunded Amount"] == "5.00"

    async def test_a_refund_on_another_tenants_order_is_not_counted(
        self, service: ExportService, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        """The bulk lookup is scoped, not just filtered by order id."""
        other = Tenant(
            id=uuid4(),
            name="Other Workshop",
            slug=f"other-{uuid4().hex[:8]}",
            tenant_type="three_d_print",
            is_active=True,
            settings={},
        )
        db_session.add(other)
        await db_session.commit()

        order = await _order(
            db_session,
            test_tenant,
            number="ORD-REF-006",
            total=Decimal("80.00"),
            sales_tax_collected=Decimal("0.00"),
            status=OrderStatus.REFUNDED,
        )
        await _record_refund(db_session, other, order, Decimal("99.00"))

        row = _rows(await service.export_orders_csv())[0]

        assert row["Refunded Amount"] == ""
