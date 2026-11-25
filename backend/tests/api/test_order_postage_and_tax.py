"""Postage paid and sales tax collected, recorded on the order (task T150).

Tier 2 added both columns to `orders` and taught `reconciliation.py` to sum
them. Nothing filled them: neither appeared in an order schema, the orders API
or the fulfilment path, so for every order in every tenant they held their
default of zero. The consequences were quiet and wrong in the same direction:

- **FR-024** wants postage paid kept apart from shipping revenue and their
  difference reported as its own margin line. With postage always zero, that
  line reported the whole of shipping revenue as profit, which is how free
  shipping looked free.
- **FR-028d** wants tax the operator remits tracked as a liability per period.
  With the figure always zero, the liability report said nothing was owed.
- **SC-001** claims a settled order's reported margin lands within 2 points of
  the margin computed from what was actually received and actually paid. The
  postage actually paid was not in the system to compare against.

## Why postage is recorded twice

At sale the operator is guessing what postage will cost; when they buy the
label they know. So it is accepted at creation *and* at shipping, and shipping
must not silently zero a figure already entered — hence
`test_shipping_without_a_postage_figure_leaves_the_one_recorded_at_sale`.
"""

import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.product import Product
from app.models.sales_channel import SalesChannel
from app.models.tenant import Tenant

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def channel(db_session: AsyncSession, test_tenant: Tenant) -> SalesChannel:
    row = SalesChannel(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Craft fair",
        platform_type="other",
        # The operator remits the tax here, which is the case in which the
        # figure is a liability they owe rather than the platform's problem
        # (FR-028d). Under a platform remitter it is collected and reported,
        # but owed by someone else.
        tax_remitter="operator",
        is_active=True,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


def _payload(product: Product, channel: SalesChannel, **overrides) -> dict:
    payload = {
        "customer_email": f"buyer-{uuid4().hex[:8]}@example.com",
        "customer_name": "A Buyer",
        "shipping_address_line1": "1 Test Street",
        "shipping_city": "Testville",
        "shipping_postcode": "TE5 7ST",
        "shipping_country": "United Kingdom",
        "shipping_method": "Royal Mail 2nd Class",
        "shipping_cost": "4.99",
        "sales_channel_id": str(channel.id),
        "items": [
            {"product_id": str(product.id), "quantity": 1, "unit_price": "64.99"},
        ],
    }
    payload.update(overrides)
    return payload


async def _stored(db_session: AsyncSession, order_id: str) -> Order:
    """Read the row back, not the response: the point of the task is that the
    figures are *recorded*, and a response can echo what it was handed."""
    db_session.expire_all()
    return (await db_session.execute(select(Order).where(Order.id == UUID(order_id)))).scalar_one()


class TestRecordingAtSale:
    async def test_both_figures_are_recorded(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        response = await client.post(
            "/api/v1/orders",
            json=_payload(
                test_product,
                channel,
                postage_paid="3.85",
                sales_tax_collected="8.45",
            ),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert Decimal(str(body["postage_paid"])) == Decimal("3.85")
        assert Decimal(str(body["sales_tax_collected"])) == Decimal("8.45")

        order = await _stored(db_session, body["id"])
        assert order.postage_paid == Decimal("3.85")
        assert order.sales_tax_collected == Decimal("8.45")

    async def test_postage_is_kept_apart_from_shipping_revenue(
        self,
        client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """FR-024. Their difference is a margin line, positive or negative, and
        netting one off the other destroys it. Here postage exceeds the
        shipping charged — a loss the operator needs to be able to see."""
        body = (
            await client.post(
                "/api/v1/orders",
                json=_payload(
                    test_product,
                    channel,
                    shipping_cost="4.99",
                    postage_paid="7.20",
                ),
            )
        ).json()

        assert Decimal(str(body["shipping_cost"])) == Decimal("4.99")
        assert Decimal(str(body["postage_paid"])) == Decimal("7.20")

    async def test_tax_is_not_added_into_the_total(
        self,
        client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """FR-028c: tax is never revenue. It is collected within what the
        customer paid, not charged on top of it, so the total must not move."""
        without = (await client.post("/api/v1/orders", json=_payload(test_product, channel))).json()
        with_tax = (
            await client.post(
                "/api/v1/orders",
                json=_payload(test_product, channel, sales_tax_collected="8.45"),
            )
        ).json()

        assert Decimal(str(with_tax["total"])) == Decimal(str(without["total"]))

    async def test_postage_is_not_subtracted_from_the_total_either(
        self,
        client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """The total is what the customer paid. What the operator then spent
        posting it is a cost, and costs belong to the margin, not the invoice."""
        without = (await client.post("/api/v1/orders", json=_payload(test_product, channel))).json()
        with_postage = (
            await client.post(
                "/api/v1/orders", json=_payload(test_product, channel, postage_paid="7.20")
            )
        ).json()

        assert Decimal(str(with_postage["total"])) == Decimal(str(without["total"]))

    async def test_both_default_to_zero_so_an_existing_caller_still_works(
        self,
        client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """A caller that does not know about these fields must keep working."""
        body = (await client.post("/api/v1/orders", json=_payload(test_product, channel))).json()

        assert Decimal(str(body["postage_paid"])) == Decimal("0.00")
        assert Decimal(str(body["sales_tax_collected"])) == Decimal("0.00")

    @pytest.mark.parametrize("field", ["postage_paid", "sales_tax_collected"])
    async def test_a_negative_figure_is_refused(
        self,
        client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
        field: str,
    ) -> None:
        response = await client.post(
            "/api/v1/orders",
            json=_payload(test_product, channel, **{field: "-1.00"}),
        )

        assert response.status_code == 422


class TestRecordingAtShipping:
    """The ship handler sends an email and deducts inventory; neither is what
    these tests are about, so the email service is stubbed."""

    @staticmethod
    def _stub_email():
        service = MagicMock()
        service.send_order_shipped = AsyncMock(return_value=True)
        patcher = patch("app.services.email_service.get_email_service")
        mock = patcher.start()
        mock.return_value = service
        return patcher

    async def test_the_label_price_is_recorded_when_the_label_is_bought(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """The natural moment: at sale the figure was a guess."""
        created = (await client.post("/api/v1/orders", json=_payload(test_product, channel))).json()

        patcher = self._stub_email()
        try:
            response = await client.post(
                f"/api/v1/orders/{created['id']}/ship",
                json={"tracking_number": "AB123", "postage_paid": "3.85"},
            )
        finally:
            patcher.stop()

        assert response.status_code == 200, response.text
        order = await _stored(db_session, created["id"])
        assert order.postage_paid == Decimal("3.85")

    async def test_shipping_without_a_postage_figure_leaves_the_one_recorded_at_sale(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        created = (
            await client.post(
                "/api/v1/orders", json=_payload(test_product, channel, postage_paid="3.85")
            )
        ).json()

        patcher = self._stub_email()
        try:
            await client.post(
                f"/api/v1/orders/{created['id']}/ship", json={"tracking_number": "AB123"}
            )
        finally:
            patcher.stop()

        order = await _stored(db_session, created["id"])
        assert order.postage_paid == Decimal("3.85"), (
            "shipping must not silently zero a figure already entered"
        )

    async def test_zero_postage_is_a_figure_and_is_recorded(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """A collected order really did cost nothing to post, and that is
        different from nobody having said. Hence `is not None` in the handler
        rather than a truthiness test, which this is the guard for."""
        created = (
            await client.post(
                "/api/v1/orders", json=_payload(test_product, channel, postage_paid="3.85")
            )
        ).json()

        patcher = self._stub_email()
        try:
            await client.post(f"/api/v1/orders/{created['id']}/ship", json={"postage_paid": "0.00"})
        finally:
            patcher.stop()

        order = await _stored(db_session, created["id"])
        assert order.postage_paid == Decimal("0.00")


class TestCorrectingAfterTheFact:
    async def test_postage_can_be_corrected(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """A label that cost more than expected."""
        created = (
            await client.post(
                "/api/v1/orders", json=_payload(test_product, channel, postage_paid="3.85")
            )
        ).json()

        response = await client.patch(
            f"/api/v1/orders/{created['id']}", json={"postage_paid": "4.20"}
        )

        assert response.status_code == 200, response.text
        order = await _stored(db_session, created["id"])
        assert order.postage_paid == Decimal("4.20")

    async def test_tax_can_be_recorded_from_a_statement_later(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """A marketplace statement arrives a fortnight after the sale."""
        created = (await client.post("/api/v1/orders", json=_payload(test_product, channel))).json()

        await client.patch(f"/api/v1/orders/{created['id']}", json={"sales_tax_collected": "8.45"})

        order = await _stored(db_session, created["id"])
        assert order.sales_tax_collected == Decimal("8.45")

    async def test_a_correction_leaves_what_the_customer_paid_alone(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """These are actuals recorded against the order. Nothing the customer
        was charged moves."""
        created = (await client.post("/api/v1/orders", json=_payload(test_product, channel))).json()

        await client.patch(f"/api/v1/orders/{created['id']}", json={"postage_paid": "4.20"})

        order = await _stored(db_session, created["id"])
        assert order.shipping_cost == Decimal("4.99")
        assert order.total == Decimal(str(created["total"]))

    async def test_a_negative_correction_is_refused(
        self,
        client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        created = (await client.post("/api/v1/orders", json=_payload(test_product, channel))).json()

        response = await client.patch(
            f"/api/v1/orders/{created['id']}", json={"postage_paid": "-1.00"}
        )

        assert response.status_code == 422


class TestTheFiguresCrossTheWireExactly:
    async def test_both_are_decimal_strings_not_json_numbers(
        self,
        client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """FR-047. A new money field arriving as a binary double is the defect
        this feature exists to remove, however many floats predate it on the
        same response — `shipping_cost`, `subtotal` and `total` beside these two
        are still `float` and are a named remaining gap, not a licence."""
        response = await client.post(
            "/api/v1/orders",
            json=_payload(
                test_product,
                channel,
                postage_paid="3.85",
                sales_tax_collected="8.45",
            ),
        )
        raw = json.loads(response.text)

        assert isinstance(raw["postage_paid"], str), (
            f"postage_paid crossed the wire as {type(raw['postage_paid']).__name__}"
        )
        assert isinstance(raw["sales_tax_collected"], str)

    async def test_a_fraction_of_a_penny_is_not_rounded_away_in_transit(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """0.1 + 0.2 is the whole reason for the rule. A hundred orders at
        3.85 postage must sum to 385.00 exactly, or the reconciliation report
        disagrees with the bank by pennies that nobody can account for."""
        body = (
            await client.post(
                "/api/v1/orders", json=_payload(test_product, channel, postage_paid="3.85")
            )
        ).json()

        order = await _stored(db_session, body["id"])
        assert order.postage_paid * 100 == Decimal("385.00")


class TestTheReportsThatWereReadingZero:
    """The reason the task exists. `reconciliation.py` summed both columns
    faithfully from the day Tier 2 added them; nothing wrote to either, so the
    shipping-margin line and the tax liability reported zero for every order
    in every tenant. These are the end-to-end proofs that they no longer do."""

    @staticmethod
    def _pnl_params(channel: SalesChannel) -> dict:
        today = date.today()
        return {
            "channel_id": str(channel.id),
            # The order is created now, and `_orders_in_period` dates an order
            # by `created_at`.
            "period_start": str(today - timedelta(days=1)),
            "period_end": str(today + timedelta(days=1)),
        }

    async def test_the_shipping_margin_line_reports_the_postage_actually_paid(
        self,
        client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """FR-024. 4.99 charged against 7.20 paid is a loss of 2.21 — which the
        operator could not see at all while postage read zero, because free
        shipping and expensive shipping looked identical."""
        await client.post(
            "/api/v1/orders",
            json=_payload(test_product, channel, shipping_cost="4.99", postage_paid="7.20"),
        )

        response = await client.get(
            "/api/v1/reconciliation/channel-pnl", params=self._pnl_params(channel)
        )

        assert response.status_code == 200, response.text
        pnl = response.json()
        assert Decimal(str(pnl["postage_paid"])) == Decimal("7.20")
        assert Decimal(str(pnl["shipping_revenue"])) == Decimal("4.99")
        assert Decimal(str(pnl["shipping_net"])) == Decimal("-2.21")

    async def test_the_tax_liability_reports_what_was_collected(
        self,
        client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """FR-028d, on a channel the operator remits for."""
        await client.post(
            "/api/v1/orders",
            json=_payload(test_product, channel, sales_tax_collected="8.45"),
        )

        pnl = (
            await client.get("/api/v1/reconciliation/channel-pnl", params=self._pnl_params(channel))
        ).json()

        assert Decimal(str(pnl["sales_tax_collected"])) == Decimal("8.45")
        assert Decimal(str(pnl["sales_tax_liability"])) == Decimal("8.45")

    async def test_the_tax_collected_is_not_in_the_revenue_it_sits_beside(
        self,
        client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """FR-028c. Now that the figure is non-zero for the first time, this is
        the first time the rule could actually be broken."""
        await client.post(
            "/api/v1/orders",
            json=_payload(
                test_product,
                channel,
                shipping_cost="4.99",
                sales_tax_collected="8.45",
            ),
        )

        pnl = (
            await client.get("/api/v1/reconciliation/channel-pnl", params=self._pnl_params(channel))
        ).json()

        assert Decimal(str(pnl["revenue_tax_exclusive"])) == Decimal("64.99") + Decimal("4.99")

    async def test_two_orders_postage_sums_exactly(
        self,
        client: AsyncClient,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """A report is a sum, and a sum is where a float would have drifted."""
        for postage in ("3.85", "7.20"):
            await client.post(
                "/api/v1/orders", json=_payload(test_product, channel, postage_paid=postage)
            )

        pnl = (
            await client.get("/api/v1/reconciliation/channel-pnl", params=self._pnl_params(channel))
        ).json()

        assert pnl["order_count"] == 2
        assert Decimal(str(pnl["postage_paid"])) == Decimal("11.05")


class TestATaxRateThatChangesMidPeriod:
    """`spec.md:191` — tax recorded on an order uses the rate in effect at sale.

    This holds *structurally* rather than by arithmetic:
    `Order.sales_tax_collected` is an amount the operator enters, and nothing
    in the system derives it from a rate. So there is no rate to change, and
    the figure cannot move when a tax rate does (Constitution VI).

    That is exactly why it needed a guard (task T196). Nothing asserted it, so
    the property was one refactor away from quietly disappearing: the moment
    somebody computes this column from a configured rate — which looks like a
    convenience — a settled order's recorded tax starts restating itself every
    time the rate changes, and no test objects.
    """

    async def test_the_recorded_tax_is_an_entered_amount_not_a_derived_one(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_product: Product,
        channel: SalesChannel,
    ) -> None:
        """What is entered is what is stored, to the penny.

        20% of £64.99 is £12.998, so neither £12.998 nor £13.00 is what
        appears: £11.11 is, because that is what the operator recorded.
        """
        response = await client.post(
            "/api/v1/orders",
            json=_payload(test_product, channel, sales_tax_collected="11.11"),
        )
        assert response.status_code == 200, response.text

        order = await _stored(db_session, response.json()["id"])
        assert order.sales_tax_collected == Decimal("11.11")

    async def test_no_code_derives_the_recorded_tax_from_a_rate(self) -> None:
        """The property itself, checked where it can actually be broken.

        A behavioural test cannot catch this: there is no rate input to vary.
        What can be caught is the arrival of one — an assignment to
        `sales_tax_collected` computed from a percentage. Every legitimate
        write takes it straight from a payload or a correction.
        """
        import ast
        from pathlib import Path

        app_dir = Path(__file__).resolve().parents[2] / "app"

        offenders: list[str] = []
        for path in sorted(app_dir.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                    targets = [node.target]
                if not targets:
                    continue
                names = {
                    sub.attr
                    for target in targets
                    for sub in ast.walk(target)
                    if isinstance(sub, ast.Attribute)
                } | {
                    sub.id
                    for target in targets
                    for sub in ast.walk(target)
                    if isinstance(sub, ast.Name)
                }
                if "sales_tax_collected" not in names:
                    continue
                value = ast.unparse(node.value) if node.value is not None else ""
                # A rate would appear as a multiplication, a division, or a
                # name saying rate/pct/percent. An entered amount does not.
                if any(token in value for token in ("rate", "pct", "percent", "*", "/")):
                    offenders.append(f"{path}:{node.lineno}: {ast.unparse(node)[:120]}")

        assert offenders == [], (
            "the tax recorded on an order looks derived from a rate:\n"
            + "\n".join(f"  {line}" for line in offenders)
            + "\nIt is an amount the operator entered. Deriving it means a "
            "settled order's tax restates itself whenever the rate changes, "
            "which is the fiction Constitution VI forbids (spec.md:191)."
        )
