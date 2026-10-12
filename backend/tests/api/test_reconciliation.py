"""`/reconciliation` — plan against statement, and channel P&L (task T064).

The two requirements this suite exists for:

* **FR-041c's conflict.** An order-scoped amount that would push a period's
  unallocated remainder below zero is a contradiction between two figures the
  operator entered. It is a ``409`` -- reported, so the period total gets
  fixed -- rather than absorbed into a negative remainder nobody looks at.
* **FR-025's edge case.** A period with no orders has nothing to divide a
  subscription over. The cost is reported as unabsorbed rather than divided by
  zero, because a channel that sold nothing has not become free.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee_actual import FeeActual
from app.models.fee_rule import FeeRule
from app.models.order import Order
from app.models.sales_channel import SalesChannel
from app.models.tenant import Tenant
from app.models.user import UserRole

pytestmark = pytest.mark.asyncio

PERIOD_START = "2026-06-01"
PERIOD_END = "2026-06-30"
IN_PERIOD = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)

ACTUALS_URL = "/api/v1/reconciliation/fee-actuals"
PNL_URL = "/api/v1/reconciliation/channel-pnl"


@pytest_asyncio.fixture
async def channel(db_session: AsyncSession, test_tenant: Tenant) -> SalesChannel:
    row = SalesChannel(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Reconciliation Marketplace",
        platform_type="etsy",
        fee_percentage=Decimal("0"),
        fee_fixed=Decimal("0"),
        monthly_cost=Decimal("30.00"),
        tax_remitter="operator",
        expected_discount_pct=Decimal("0"),
        expected_refund_pct=Decimal("0"),
        currency_code="CAD",
        offsite_ads_opt_in=False,
        is_active=True,
    )
    db_session.add(row)
    db_session.add(
        FeeRule(
            id=uuid4(),
            tenant_id=test_tenant.id,
            sales_channel_id=row.id,
            name="transaction",
            basis="item_plus_shipping",
            rate_pct=Decimal("6.5"),
            fixed_amount=Decimal("0"),
            sort_order=10,
            applies_from=IN_PERIOD.date() - timedelta(days=365),
        )
    )
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def _make_order(
    db_session: AsyncSession,
    tenant: Tenant,
    channel: SalesChannel,
    *,
    subtotal: Decimal = Decimal("100.00"),
    shipping: Decimal = Decimal("0.00"),
    postage: Decimal = Decimal("0.00"),
    tax: Decimal = Decimal("0.00"),
    placed: datetime = IN_PERIOD,
    status_value: str = "delivered",
) -> Order:
    order = Order(
        id=uuid4(),
        tenant_id=tenant.id,
        sales_channel_id=channel.id,
        order_number=f"ORD-{uuid4().hex[:8]}",
        customer_name="Reconciliation Customer",
        customer_email="recon@example.com",
        shipping_address_line1="1 Test Street",
        shipping_city="Testville",
        shipping_postcode="T35T",
        shipping_country="Canada",
        shipping_method="Standard",
        shipping_cost=shipping,
        postage_paid=postage,
        sales_tax_collected=tax,
        subtotal=subtotal,
        total=subtotal + shipping + tax,
        currency="CAD",
        status=status_value,
        created_at=placed,
        updated_at=placed,
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order


def _period_body(**overrides) -> dict:
    body = {
        "fee_category": "transaction",
        "amount": "6.50",
        "period_start": PERIOD_START,
        "period_end": PERIOD_END,
    }
    body.update(overrides)
    return body


# ============================================================================
# Recording actuals
# ============================================================================


class TestRecordingAPeriodTotal:
    async def test_an_admin_can_record_a_period_total(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await client.post(
            ACTUALS_URL, json=_period_body(sales_channel_id=str(channel.id))
        )

        assert response.status_code == 201
        body = response.json()
        assert Decimal(body["amount"]) == Decimal("6.50")
        assert body["order_id"] is None

    async def test_a_recorded_actual_is_entered_never_observed(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """FR-041e: a figure a human typed must not read as an observation."""
        body = (
            await client.post(ACTUALS_URL, json=_period_body(sales_channel_id=str(channel.id)))
        ).json()

        assert body["source"] == "entered"

    async def test_an_unknown_channel_is_a_404(self, client: AsyncClient) -> None:
        response = await client.post(ACTUALS_URL, json=_period_body(sales_channel_id=str(uuid4())))

        assert response.status_code == 404

    async def test_reading_as_unauthenticated_is_a_401(
        self, unauthenticated_client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await unauthenticated_client.post(
            ACTUALS_URL, json=_period_body(sales_channel_id=str(channel.id))
        )

        assert response.status_code == 401

    async def test_a_member_is_refused_and_nothing_is_recorded(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        channel: SalesChannel,
        as_role,
    ) -> None:
        """FR-007a and FR-007d together."""
        async with as_role(UserRole.MEMBER) as member:
            response = await member.post(
                ACTUALS_URL, json=_period_body(sales_channel_id=str(channel.id))
            )

        assert response.status_code == 403
        rows = (await db_session.execute(select(FeeActual))).scalars().all()
        assert list(rows) == []


class TestTheScopeMustBeExactlyOne:
    async def test_both_scopes_at_once_is_a_422(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        """A row with both would be counted twice."""
        order = await _make_order(db_session, test_tenant, channel)

        response = await client.post(
            ACTUALS_URL,
            json=_period_body(sales_channel_id=str(channel.id), order_id=str(order.id)),
        )

        assert response.status_code == 422

    async def test_neither_scope_is_a_422(self, client: AsyncClient, channel: SalesChannel) -> None:
        response = await client.post(
            ACTUALS_URL,
            json={
                "sales_channel_id": str(channel.id),
                "fee_category": "transaction",
                "amount": "6.50",
            },
        )

        assert response.status_code == 422

    async def test_half_a_period_is_a_422(self, client: AsyncClient, channel: SalesChannel) -> None:
        response = await client.post(
            ACTUALS_URL,
            json={
                "sales_channel_id": str(channel.id),
                "fee_category": "transaction",
                "amount": "6.50",
                "period_start": PERIOD_START,
            },
        )

        assert response.status_code == 422

    async def test_a_period_ending_before_it_starts_is_a_422(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await client.post(
            ACTUALS_URL,
            json=_period_body(
                sales_channel_id=str(channel.id),
                period_start=PERIOD_END,
                period_end=PERIOD_START,
            ),
        )

        assert response.status_code == 422


class TestOrderScopedAmounts:
    async def test_an_order_scoped_amount_can_be_recorded(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        """FR-041b: for when one order looks anomalous."""
        order = await _make_order(db_session, test_tenant, channel)

        response = await client.post(
            ACTUALS_URL,
            json={
                "sales_channel_id": str(channel.id),
                "fee_category": "transaction",
                "amount": "4.00",
                "order_id": str(order.id),
            },
        )

        assert response.status_code == 201
        assert response.json()["period_start"] is None

    async def test_an_unknown_order_is_a_404(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await client.post(
            ACTUALS_URL,
            json={
                "sales_channel_id": str(channel.id),
                "fee_category": "transaction",
                "amount": "4.00",
                "order_id": str(uuid4()),
            },
        )

        assert response.status_code == 404

    async def test_an_amount_exceeding_the_period_total_is_a_409(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        """FR-041c's edge case: reported, never absorbed silently."""
        order = await _make_order(db_session, test_tenant, channel)
        period = await client.post(
            ACTUALS_URL,
            json=_period_body(sales_channel_id=str(channel.id), amount="5.00"),
        )
        assert period.status_code == 201

        response = await client.post(
            ACTUALS_URL,
            json={
                "sales_channel_id": str(channel.id),
                "fee_category": "transaction",
                "amount": "9.00",
                "order_id": str(order.id),
            },
        )

        assert response.status_code == 409
        assert "exceeds the period total" in str(response.json()["detail"])

    async def test_an_amount_inside_the_period_total_is_accepted(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        order = await _make_order(db_session, test_tenant, channel)
        await client.post(
            ACTUALS_URL, json=_period_body(sales_channel_id=str(channel.id), amount="10.00")
        )

        response = await client.post(
            ACTUALS_URL,
            json={
                "sales_channel_id": str(channel.id),
                "fee_category": "transaction",
                "amount": "4.00",
                "order_id": str(order.id),
            },
        )

        assert response.status_code == 201

    async def test_a_different_category_does_not_conflict(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        """The remainder is per category, as FR-041a scopes it."""
        order = await _make_order(db_session, test_tenant, channel)
        await client.post(
            ACTUALS_URL, json=_period_body(sales_channel_id=str(channel.id), amount="5.00")
        )

        response = await client.post(
            ACTUALS_URL,
            json={
                "sales_channel_id": str(channel.id),
                "fee_category": "payment_processing",
                "amount": "99.00",
                "order_id": str(order.id),
            },
        )

        assert response.status_code == 201


# ============================================================================
# Channel P&L
# ============================================================================


class TestChannelProfitability:
    async def _pnl(self, client: AsyncClient, channel: SalesChannel, **params):
        query = {
            "channel_id": str(channel.id),
            "period_start": PERIOD_START,
            "period_end": PERIOD_END,
        }
        query.update(params)
        return await client.get(PNL_URL, params=query)

    async def test_revenue_and_planned_fees_come_from_the_orders(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        await _make_order(db_session, test_tenant, channel, subtotal=Decimal("100.00"))
        await _make_order(db_session, test_tenant, channel, subtotal=Decimal("50.00"))

        body = (await self._pnl(client, channel)).json()

        assert body["order_count"] == 2
        assert Decimal(body["revenue_tax_exclusive"]) == Decimal("150.00")
        assert Decimal(body["planned_fee_total"]) == Decimal("9.75")

    async def test_a_cancelled_order_is_not_counted(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        """It charged no fees and absorbed no overhead."""
        await _make_order(db_session, test_tenant, channel)
        await _make_order(db_session, test_tenant, channel, status_value="cancelled")

        body = (await self._pnl(client, channel)).json()

        assert body["order_count"] == 1

    async def test_an_order_outside_the_period_is_not_counted(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        await _make_order(db_session, test_tenant, channel)
        await _make_order(
            db_session,
            test_tenant,
            channel,
            placed=datetime(2026, 1, 15, tzinfo=timezone.utc),
        )

        body = (await self._pnl(client, channel)).json()

        assert body["order_count"] == 1

    async def test_the_subscription_is_absorbed_over_actual_order_volume(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        """FR-025."""
        for _ in range(3):
            await _make_order(db_session, test_tenant, channel)

        body = (await self._pnl(client, channel)).json()

        absorbed = {cost["key"]: cost for cost in body["absorbed_costs"]}
        assert Decimal(absorbed["monthly_cost"]["total"]) == Decimal("30.00")
        assert absorbed["monthly_cost"]["order_count"] == 3
        assert Decimal(absorbed["monthly_cost"]["per_order"]) == Decimal("10.0000")
        assert absorbed["monthly_cost"]["is_unabsorbed"] is False

    async def test_a_period_with_no_orders_reports_the_cost_unabsorbed(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """FR-025's edge case: not divided by zero, and not reported as free."""
        body = (await self._pnl(client, channel)).json()

        assert body["order_count"] == 0
        absorbed = {cost["key"]: cost for cost in body["absorbed_costs"]}
        assert absorbed["monthly_cost"]["per_order"] is None
        assert absorbed["monthly_cost"]["is_unabsorbed"] is True
        assert Decimal(body["unabsorbed_total"]) == Decimal("30.00")

    async def test_the_margin_names_its_basis(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        """FR-031b, at period scale."""
        await _make_order(db_session, test_tenant, channel)

        body = (await self._pnl(client, channel)).json()

        assert body["margin_basis"] == "customer_total"
        assert body["margin_basis_label"]

    async def test_postage_and_shipping_revenue_are_separate(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        """FR-024, at period scale."""
        await _make_order(
            db_session,
            test_tenant,
            channel,
            shipping=Decimal("5.00"),
            postage=Decimal("9.50"),
        )

        body = (await self._pnl(client, channel)).json()

        assert Decimal(body["shipping_revenue"]) == Decimal("5.00")
        assert Decimal(body["postage_paid"]) == Decimal("9.50")
        assert Decimal(body["shipping_net"]) == Decimal("-4.50")

    async def test_sales_tax_is_a_liability_and_never_revenue(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        """FR-028c and FR-028d."""
        await _make_order(
            db_session,
            test_tenant,
            channel,
            subtotal=Decimal("100.00"),
            tax=Decimal("13.00"),
        )

        body = (await self._pnl(client, channel)).json()

        assert Decimal(body["revenue_tax_exclusive"]) == Decimal("100.00")
        assert Decimal(body["sales_tax_collected"]) == Decimal("13.00")
        assert Decimal(body["sales_tax_liability"]) == Decimal("13.00")

    async def test_a_marketplace_remitted_channel_owes_no_liability(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        channel.tax_remitter = "marketplace"
        await db_session.commit()
        await _make_order(db_session, test_tenant, channel, tax=Decimal("13.00"))

        body = (await self._pnl(client, channel)).json()

        assert Decimal(body["sales_tax_liability"]) == Decimal("0")
        assert Decimal(body["sales_tax_collected"]) == Decimal("13.00")


class TestReconciliationReporting:
    async def _pnl(self, client: AsyncClient, channel: SalesChannel):
        return await client.get(
            PNL_URL,
            params={
                "channel_id": str(channel.id),
                "period_start": PERIOD_START,
                "period_end": PERIOD_END,
            },
        )

    async def test_nothing_recorded_reports_no_difference_rather_than_zero(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        """A channel nobody reconciled has not reconciled perfectly."""
        await _make_order(db_session, test_tenant, channel)

        body = (await self._pnl(client, channel)).json()

        assert body["actual_fee_total"] is None
        assert body["fee_difference"] is None
        row = next(r for r in body["reconciliation"] if r["category"] == "transaction")
        assert row["actual_total"] is None
        assert row["difference"] is None

    async def test_a_recorded_period_total_is_compared_against_plan(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        """FR-041d."""
        await _make_order(db_session, test_tenant, channel, subtotal=Decimal("100.00"))
        await client.post(
            ACTUALS_URL, json=_period_body(sales_channel_id=str(channel.id), amount="7.00")
        )

        body = (await self._pnl(client, channel)).json()
        row = next(r for r in body["reconciliation"] if r["category"] == "transaction")

        assert Decimal(row["planned"]) == Decimal("6.50")
        assert Decimal(row["actual_total"]) == Decimal("7.00")
        assert Decimal(row["difference"]) == Decimal("0.50")

    async def test_an_order_amount_reduces_the_unallocated_remainder(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        """FR-041c: order-level takes precedence, nothing counted twice."""
        order = await _make_order(db_session, test_tenant, channel)
        await client.post(
            ACTUALS_URL, json=_period_body(sales_channel_id=str(channel.id), amount="10.00")
        )
        await client.post(
            ACTUALS_URL,
            json={
                "sales_channel_id": str(channel.id),
                "fee_category": "transaction",
                "amount": "4.00",
                "order_id": str(order.id),
            },
        )

        body = (await self._pnl(client, channel)).json()
        row = next(r for r in body["reconciliation"] if r["category"] == "transaction")

        assert Decimal(row["actual_period"]) == Decimal("10.00")
        assert Decimal(row["actual_order_scoped"]) == Decimal("4.00")
        assert Decimal(row["unallocated_remainder"]) == Decimal("6.00")
        assert Decimal(row["actual_total"]) == Decimal("10.00"), (
            "the period total is the authority; counting the order rows on top "
            "would double the category"
        )

    async def test_a_category_recorded_but_never_planned_still_appears(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
    ) -> None:
        """A fee the operator pays and has not modelled is the point of this."""
        await _make_order(db_session, test_tenant, channel)
        await client.post(
            ACTUALS_URL,
            json=_period_body(
                sales_channel_id=str(channel.id),
                fee_category="offsite_ads",
                amount="9.75",
            ),
        )

        body = (await self._pnl(client, channel)).json()
        categories = {row["category"] for row in body["reconciliation"]}

        assert "offsite_ads" in categories
        row = next(r for r in body["reconciliation"] if r["category"] == "offsite_ads")
        assert Decimal(row["planned"]) == Decimal("0.00")
        assert Decimal(row["difference"]) == Decimal("9.75")

    async def test_a_viewer_may_read_the_pnl(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        channel: SalesChannel,
        as_role,
    ) -> None:
        """FR-007c."""
        await _make_order(db_session, test_tenant, channel)

        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.get(
                PNL_URL,
                params={
                    "channel_id": str(channel.id),
                    "period_start": PERIOD_START,
                    "period_end": PERIOD_END,
                },
            )

        assert response.status_code == 200

    async def test_an_unknown_channel_is_a_404(self, client: AsyncClient) -> None:
        response = await client.get(
            PNL_URL,
            params={
                "channel_id": str(uuid4()),
                "period_start": PERIOD_START,
                "period_end": PERIOD_END,
            },
        )

        assert response.status_code == 404

    async def test_a_period_ending_before_it_starts_is_a_422(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await client.get(
            PNL_URL,
            params={
                "channel_id": str(channel.id),
                "period_start": PERIOD_END,
                "period_end": PERIOD_START,
            },
        )

        assert response.status_code == 422

    async def test_a_missing_period_is_a_422(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await client.get(PNL_URL, params={"channel_id": str(channel.id)})

        assert response.status_code == 422
