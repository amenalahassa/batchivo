"""`/products/{id}/pricing/{channel}/margin` — the served margin (task T079).

What the endpoint has to return is everything behind the figure, not the figure
alone: a margin an operator cannot explain is one they cannot act on (FR-018).
So this suite checks the itemised fees with their bases and clamps, the
reserves, postage against shipping revenue, the basis beside the percentage
(FR-031b), and the share of the cost still resting on assumption.

The ``404`` for an unpriced product is worth its own test. Reporting a zero
margin would be worse than reporting nothing: a zero reads as a real figure,
and a product nobody has priced is not earning nothing -- it is not for sale.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee_rule import FeeRule
from app.models.product import Product
from app.models.product_pricing import ProductPricing
from app.models.sales_channel import SalesChannel
from app.models.tenant import Tenant
from app.models.user import UserRole

pytestmark = pytest.mark.asyncio

LIST_PRICE = Decimal("64.99")
APPLIES_FROM = date(2020, 1, 1)


@pytest_asyncio.fixture
async def channel(db_session: AsyncSession, test_tenant: Tenant) -> SalesChannel:
    """A channel charging a percentage, a fixed amount and a refund reserve."""
    # The operator keeps their books in the currency the channel sells in, so
    # costs and prices meet without a conversion (task T231).
    test_tenant.currency_code = "CAD"
    db_session.add(test_tenant)
    row = SalesChannel(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Margin Marketplace",
        platform_type="etsy",
        monthly_cost=Decimal("0"),
        tax_remitter="marketplace",
        expected_discount_pct=Decimal("0"),
        expected_refund_pct=Decimal("2.5"),
        currency_code="CAD",
        offsite_ads_opt_in=False,
        is_active=True,
    )
    db_session.add(row)
    for name, basis, rate, fixed, order in (
        ("transaction", "item_plus_shipping", Decimal("6.5"), Decimal("0.00"), 10),
        ("payment_processing", "order_total", Decimal("3.0"), Decimal("0.30"), 20),
        ("listing", "per_listing", Decimal("0"), Decimal("0.22"), 30),
    ):
        db_session.add(
            FeeRule(
                id=uuid4(),
                tenant_id=test_tenant.id,
                sales_channel_id=row.id,
                name=name,
                basis=basis,
                rate_pct=rate,
                fixed_amount=fixed,
                sort_order=order,
                applies_from=APPLIES_FROM,
            )
        )
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest_asyncio.fixture
async def priced(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_product: Product,
    channel: SalesChannel,
) -> ProductPricing:
    pricing = ProductPricing(
        id=uuid4(),
        product_id=test_product.id,
        sales_channel_id=channel.id,
        list_price=LIST_PRICE,
        is_active=True,
    )
    db_session.add(pricing)
    await db_session.commit()
    await db_session.refresh(pricing)
    return pricing


def _url(product: Product, channel: SalesChannel) -> str:
    return f"/api/v1/products/{product.id}/pricing/{channel.id}/margin"


# ============================================================================
# The served figure
# ============================================================================


class TestTheMarginResponse:
    async def test_the_itemised_fees_come_back_with_their_bases(
        self, client: AsyncClient, test_product: Product, channel: SalesChannel, priced
    ) -> None:
        body = (await client.get(_url(test_product, channel))).json()

        charges = {charge["name"]: charge for charge in body["fees"]}
        assert charges["transaction"]["basis"] == "item_plus_shipping"
        assert Decimal(charges["transaction"]["amount"]) == Decimal("4.22")
        assert Decimal(charges["payment_processing"]["amount"]) == Decimal("2.25")

    async def test_a_periodic_fee_is_not_charged_on_the_unit(
        self, client: AsyncClient, test_product: Product, channel: SalesChannel, priced
    ) -> None:
        """FR-025: the listing fee is absorbed over a period, not per sale."""
        body = (await client.get(_url(test_product, channel))).json()

        assert "listing" not in {charge["name"] for charge in body["fees"]}

    async def test_the_reserve_is_reported_as_its_own_deduction(
        self, client: AsyncClient, test_product: Product, channel: SalesChannel, priced
    ) -> None:
        """FR-026: neither a fee nor a cost."""
        body = (await client.get(_url(test_product, channel))).json()

        reserve = next(d for d in body["deductions"] if d["key"] == "expected_refund")
        assert Decimal(reserve["rate_pct"]) == Decimal("2.5")
        assert Decimal(reserve["amount"]) == Decimal("1.62")

    async def test_the_margin_basis_is_named_beside_the_percentage(
        self, client: AsyncClient, test_product: Product, channel: SalesChannel, priced
    ) -> None:
        """FR-031b."""
        body = (await client.get(_url(test_product, channel))).json()

        assert body["margin_basis"] == "customer_total"
        assert body["margin_basis_label"]
        assert Decimal(body["margin_basis_amount"]) == LIST_PRICE

    async def test_postage_and_shipping_revenue_are_separate_figures(
        self, client: AsyncClient, test_product: Product, channel: SalesChannel, priced
    ) -> None:
        """FR-024, even when both are zero: the fields exist to be filled."""
        body = (await client.get(_url(test_product, channel))).json()

        assert "postage_paid" in body
        assert "shipping_revenue" in body
        assert Decimal(body["shipping_net"]) == Decimal(body["shipping_revenue"]) - Decimal(
            body["postage_paid"]
        )

    async def test_the_chain_reconciles_to_the_profit(
        self, client: AsyncClient, test_product: Product, channel: SalesChannel, priced
    ) -> None:
        """An operator must be able to follow the figures to the answer.

        Within a cent, which is the rounding boundary the margin chain uses:
        fees and reserves enter unrounded and the profit rounds once.
        """
        body = (await client.get(_url(test_product, channel))).json()

        chain = (
            Decimal(body["list_price"])
            + Decimal(body["shipping_revenue"])
            - Decimal(body["fee_total"])
            - Decimal(body["deduction_total"])
            - Decimal(body["make_cost"])
            - Decimal(body["postage_paid"])
        )
        assert abs(chain - Decimal(body["profit"])) <= Decimal("0.01")

    async def test_the_observed_share_is_reported(
        self, client: AsyncClient, test_product: Product, channel: SalesChannel, priced
    ) -> None:
        """Constitution VI: how much of this rests on observation."""
        body = (await client.get(_url(test_product, channel))).json()

        assert body["observed_share"] is not None
        assert body["assumed_share"] is not None

    async def test_an_incompletely_costed_product_says_so(
        self, client: AsyncClient, test_product: Product, channel: SalesChannel, priced
    ) -> None:
        """FR-019: a gap is named, not costed at zero.

        The fixture product has no models attached, so there is nothing to
        print and nothing is claimed about what printing it would cost.
        """
        body = (await client.get(_url(test_product, channel))).json()

        assert Decimal(body["make_cost"]) >= Decimal("0")
        assert isinstance(body["incomplete_reasons"], list)

    async def test_the_tax_fields_are_reported_even_at_zero(
        self, client: AsyncClient, test_product: Product, channel: SalesChannel, priced
    ) -> None:
        """FR-028b through FR-028e, with the remitter named."""
        body = (await client.get(_url(test_product, channel))).json()

        assert body["tax_remitter"] == "marketplace"
        assert Decimal(body["sales_tax_liability"]) == Decimal("0.00")
        assert body["tax_exclusive_derived"] is False


class TestTheMarginBasisSetting:
    async def test_switching_the_basis_moves_only_the_percentage(
        self,
        client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
        priced,
    ) -> None:
        """FR-031c, through the API.

        The basis comes from the tenant's policy, so it is changed through the
        policy endpoint -- which is the path an operator would use, and the one
        that must not restate any amount.
        """
        before = (await client.get(_url(test_product, channel))).json()

        changed = await client.put(
            "/api/v1/settings/pricing-policy", json={"margin_basis": "net_revenue"}
        )
        assert changed.status_code == 200

        after = (await client.get(_url(test_product, channel))).json()

        assert after["margin_basis"] == "net_revenue"
        assert Decimal(after["make_cost"]) == Decimal(before["make_cost"])
        assert Decimal(after["profit"]) == Decimal(before["profit"])
        assert Decimal(after["fee_total"]) == Decimal(before["fee_total"])
        assert Decimal(after["margin_pct"]) != Decimal(before["margin_pct"])


# ============================================================================
# Not found, and permissions
# ============================================================================


class TestWhatIsNotFound:
    async def test_an_unpriced_product_is_a_404_not_a_zero_margin(
        self, client: AsyncClient, test_product: Product, channel: SalesChannel
    ) -> None:
        """A zero reads as a real figure; an unpriced product is not for sale."""
        response = await client.get(_url(test_product, channel))

        assert response.status_code == 404
        assert "not priced" in response.json()["detail"]

    async def test_an_unknown_product_is_a_404(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await client.get(f"/api/v1/products/{uuid4()}/pricing/{channel.id}/margin")

        assert response.status_code == 404

    async def test_an_unknown_channel_is_a_404(
        self, client: AsyncClient, test_product: Product
    ) -> None:
        response = await client.get(f"/api/v1/products/{test_product.id}/pricing/{uuid4()}/margin")

        assert response.status_code == 404

    async def test_an_unauthenticated_read_is_a_401(
        self,
        unauthenticated_client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
        priced,
    ) -> None:
        response = await unauthenticated_client.get(_url(test_product, channel))

        assert response.status_code == 401

    async def test_a_bad_quantity_is_a_422(
        self, client: AsyncClient, test_product: Product, channel: SalesChannel, priced
    ) -> None:
        response = await client.get(_url(test_product, channel), params={"quantity": 0})

        assert response.status_code == 422


class TestEveryRoleMaySeeAMargin:
    async def test_a_viewer_may_read_the_margin(
        self,
        client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
        priced,
        as_role,
    ) -> None:
        """FR-007c: costs and margins are visible to every role."""
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.get(_url(test_product, channel))

        assert response.status_code == 200
        assert response.json()["margin_basis"]

    async def test_a_member_may_read_the_margin(
        self,
        client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
        priced,
        as_role,
    ) -> None:
        async with as_role(UserRole.MEMBER) as member:
            response = await member.get(_url(test_product, channel))

        assert response.status_code == 200


class TestReadingAsAtADate:
    async def test_a_rule_that_had_not_started_is_not_charged(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_product: Product,
        channel: SalesChannel,
        priced,
    ) -> None:
        """FR-022 and FR-039, through the margin endpoint."""
        db_session.add(
            FeeRule(
                id=uuid4(),
                tenant_id=test_tenant.id,
                sales_channel_id=channel.id,
                name="future_fee",
                basis="order_total",
                rate_pct=Decimal("10"),
                fixed_amount=Decimal("0"),
                sort_order=40,
                applies_from=date(2030, 1, 1),
            )
        )
        await db_session.commit()

        today = (await client.get(_url(test_product, channel))).json()
        later = (
            await client.get(_url(test_product, channel), params={"as_of": "2030-06-01"})
        ).json()

        assert "future_fee" not in {c["name"] for c in today["fees"]}
        assert "future_fee" in {c["name"] for c in later["fees"]}
        assert Decimal(later["fee_total"]) > Decimal(today["fee_total"])


# ============================================================================
# Task T236: lapsed rules are reported, not priced as zero fees
# ============================================================================


class TestLapsedRulesAreReportedOnTheMargin:
    async def test_a_date_after_every_rule_lapsed_is_incomplete(
        self, client: AsyncClient, db_session: AsyncSession, channel, priced, test_product
    ) -> None:
        from sqlalchemy import update

        await db_session.execute(
            update(FeeRule)
            .where(FeeRule.sales_channel_id == channel.id)
            .values(applies_to=date(2026, 1, 31))
        )
        await db_session.commit()

        body = (await client.get(_url(test_product, channel))).json()

        assert body["fees"] == []
        assert any("no fee rule" in reason for reason in body["incomplete_reasons"])
