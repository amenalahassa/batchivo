"""`.../pricing/{channel_id}/solve` and `.../ladder` (task T088b).

Two endpoints that compute a great deal and write nothing. What is asserted
here is the contract the pricing screens depend on, and the three ways it can
refuse: unauthenticated, a product not sold on that channel, and a target no
price achieves.

The last of those is the one worth testing hardest. FR-035 makes an
unachievable target a refusal naming the constraint rather than a number, and
the failure mode it guards against is an endpoint that returns a plausible
price for an impossible target -- which an operator would then charge.

The arithmetic itself is pinned in ``tests/unit/pricing/test_solver.py`` and
``test_price_ladder.py``, against the golden fixture and to the cent. These
tests are about the HTTP contract: status codes, shapes, and the fact that
nothing is written.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee_rule import FeeRule
from app.models.model import Model
from app.models.product import Product
from app.models.product_model import ProductModel
from app.models.product_pricing import ProductPricing
from app.models.sales_channel import SalesChannel
from app.models.tenant import Tenant

pytestmark = pytest.mark.asyncio

API = "/api/v1"
LIST_PRICE = Decimal("64.99")


def _solve_url(product: Product, channel: SalesChannel) -> str:
    return f"{API}/products/{product.id}/pricing/{channel.id}/solve"


def _ladder_url(product: Product, channel: SalesChannel) -> str:
    return f"{API}/products/{product.id}/pricing/{channel.id}/ladder"


@pytest_asyncio.fixture
async def channel(db_session: AsyncSession, test_tenant: Tenant) -> SalesChannel:
    """A channel charging a percentage and a fixed amount.

    Every lever is set explicitly rather than left to a column default, so a
    default changing underneath this file cannot quietly change what is tested.
    """
    row = SalesChannel(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Solver Marketplace",
        platform_type="etsy",
        fee_percentage=Decimal("0"),
        fee_fixed=Decimal("0"),
        monthly_cost=Decimal("0"),
        tax_remitter="marketplace",
        expected_discount_pct=Decimal("0"),
        expected_refund_pct=Decimal("2.5"),
        free_shipping_threshold=None,
        rounding_rule=None,
        currency_code="CAD",
        offsite_ads_opt_in=False,
        is_active=True,
    )
    db_session.add(row)
    await db_session.commit()

    db_session.add(
        FeeRule(
            id=uuid4(),
            tenant_id=test_tenant.id,
            sales_channel_id=row.id,
            name="transaction",
            basis="item_subtotal",
            rate_pct=Decimal("6.5"),
            fixed_amount=Decimal("0.30"),
            sort_order=10,
            applies_from=date(2020, 1, 1),
        )
    )
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest_asyncio.fixture
async def priced_product(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_product: Product,
    test_model: Model,
    channel: SalesChannel,
) -> Product:
    """A product holding one printed item and listed on the channel.

    The listing is what makes the route's parent exist: every route under
    ``/products/{id}/pricing/{channel_id}/`` describes a product sold on a
    channel, so a product with no price row there is a 404.
    """
    test_product.product_models.append(ProductModel(id=uuid4(), model_id=test_model.id, quantity=1))
    db_session.add(test_product)
    db_session.add(
        ProductPricing(
            id=uuid4(),
            product_id=test_product.id,
            sales_channel_id=channel.id,
            list_price=LIST_PRICE,
        )
    )
    await db_session.commit()
    return test_product


@pytest_asyncio.fixture
async def unlisted_product(
    db_session: AsyncSession, test_tenant: Tenant, test_model: Model
) -> Product:
    """A real product with no price on the channel under test."""
    product = Product(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku=f"UNLISTED-{uuid4().hex[:6]}",
        name="Not sold anywhere",
        units_in_stock=0,
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()
    return product


# ============================================================================
# Solving
# ============================================================================


class TestSolvingAPrice:
    async def test_a_target_margin_returns_a_price(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        response = await client.post(
            _solve_url(priced_product, channel),
            json={"target_margin_pct": "35"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["achievable"] is True
        assert Decimal(body["required_price_raw"]) > Decimal("0")
        assert Decimal(body["required_price_rounded"]) > Decimal("0")

    async def test_the_price_returned_achieves_the_target(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """The whole point of the endpoint, asserted end to end.

        Rounding rounds up, so the achieved margin is at or above the target --
        never below it, which is the one direction that would matter.
        """
        body = (
            await client.post(
                _solve_url(priced_product, channel),
                json={"target_margin_pct": "35"},
            )
        ).json()

        assert Decimal(body["margin_pct_at_price"]) >= Decimal("35")
        assert Decimal(body["margin_pct_at_price"]) < Decimal("36")

    async def test_the_margin_endpoint_agrees_at_the_solved_price(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        priced_product: Product,
        channel: SalesChannel,
    ) -> None:
        """Apply the proposal, then ask the margin endpoint what it earns.

        This is the assertion that makes the solver trustworthy: the figure it
        promised is the figure the rest of the system reports once the price is
        actually set. A solver whose answer the margin screen disputes leaves
        the operator with two numbers and no way to choose.
        """
        solved = (
            await client.post(
                _solve_url(priced_product, channel),
                json={"target_margin_pct": "35"},
            )
        ).json()
        price = Decimal(solved["required_price_rounded"])

        pricing = (
            await db_session.execute(
                select(ProductPricing).where(
                    ProductPricing.product_id == priced_product.id,
                    ProductPricing.sales_channel_id == channel.id,
                )
            )
        ).scalar_one()
        pricing.list_price = price
        await db_session.commit()

        margin = (
            await client.get(f"{API}/products/{priced_product.id}/pricing/{channel.id}/margin")
        ).json()

        assert Decimal(margin["margin_pct"]) == Decimal(solved["margin_pct_at_price"])

    async def test_the_answer_lists_every_input_behind_it(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """FR-034, US4 scenario 3."""
        body = (
            await client.post(
                _solve_url(priced_product, channel),
                json={"target_margin_pct": "35"},
            )
        ).json()

        inputs = body["inputs"]
        assert inputs
        for key in ("make_cost", "postage_paid", "target_margin_pct", "margin_basis"):
            assert key in inputs
        # Rendered as strings, so no monetary figure crosses the wire as a
        # JSON number (Constitution IV).
        assert all(isinstance(value, str) for value in inputs.values())

    async def test_the_margin_basis_is_named_beside_the_figure(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """FR-031b."""
        body = (
            await client.post(
                _solve_url(priced_product, channel),
                json={"target_margin_pct": "35"},
            )
        ).json()

        assert body["margin_basis"] in ("customer_total", "item_price", "net_revenue")
        assert body["margin_basis_label"]

    async def test_a_rounding_rule_is_reported_as_an_adjustment(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """FR-033, US4 scenario 2."""
        body = (
            await client.post(
                _solve_url(priced_product, channel),
                json={"target_margin_pct": "35", "rounding_rule": "psychological_99"},
            )
        ).json()

        adjustment = next(a for a in body["adjustments"] if a["key"] == "rounding")
        assert adjustment["label"]
        assert Decimal(adjustment["to_price"]) >= Decimal(adjustment["from_price"])
        assert body["required_price_rounded"].endswith(".99")

    async def test_the_fee_stack_at_the_solved_price_is_itemised(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """A price whose fees cannot be inspected cannot be checked."""
        body = (
            await client.post(
                _solve_url(priced_product, channel),
                json={"target_margin_pct": "35"},
            )
        ).json()

        assert body["fees"]
        for fee in body["fees"]:
            assert fee["name"]
            assert fee["basis"]
            assert isinstance(fee["amount"], str)

    async def test_money_crosses_the_wire_as_a_string(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        body = (
            await client.post(
                _solve_url(priced_product, channel),
                json={"target_margin_pct": "35"},
            )
        ).json()

        for key in (
            "required_price_raw",
            "required_price_rounded",
            "make_cost",
            "postage_paid",
            "profit_at_price",
        ):
            assert isinstance(body[key], str), f"{key} is not a decimal string"


class TestTheSolvedPriceIsOnlyAProposal:
    """US4 scenario 5: nothing is published to any channel automatically."""

    async def test_the_stored_price_is_untouched(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        priced_product: Product,
        channel: SalesChannel,
    ) -> None:
        await client.post(
            _solve_url(priced_product, channel),
            json={"target_margin_pct": "35"},
        )

        pricing = (
            await db_session.execute(
                select(ProductPricing).where(
                    ProductPricing.product_id == priced_product.id,
                    ProductPricing.sales_channel_id == channel.id,
                )
            )
        ).scalar_one()
        await db_session.refresh(pricing)

        assert Decimal(str(pricing.list_price)) == LIST_PRICE

    async def test_the_response_says_it_is_a_proposal(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """So a client cannot mistake it for a published price."""
        body = (
            await client.post(
                _solve_url(priced_product, channel),
                json={"target_margin_pct": "35"},
            )
        ).json()

        assert body["is_proposal"] is True

    async def test_solving_twice_returns_the_same_answer(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """A read with no side effects: the second call must not have moved."""
        first = (
            await client.post(_solve_url(priced_product, channel), json={"target_margin_pct": "35"})
        ).json()
        second = (
            await client.post(_solve_url(priced_product, channel), json={"target_margin_pct": "35"})
        ).json()

        assert first["required_price_raw"] == second["required_price_raw"]


class TestWhenNoPriceAchievesTheTarget:
    """FR-035, US4 scenario 4: a refusal that names the constraint."""

    async def test_an_unachievable_target_is_a_422(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        response = await client.post(
            _solve_url(priced_product, channel),
            json={"target_margin_pct": "97"},
        )

        assert response.status_code == 422

    async def test_the_refusal_carries_the_reason(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        detail = (
            await client.post(
                _solve_url(priced_product, channel),
                json={"target_margin_pct": "97"},
            )
        ).json()["detail"]

        assert detail["reason"] == "unachievable"
        assert detail["achievable"] is False

    async def test_the_refusal_names_the_binding_constraint(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """An operator must learn *why*, not merely that it failed."""
        detail = (
            await client.post(
                _solve_url(priced_product, channel),
                json={"target_margin_pct": "97"},
            )
        ).json()["detail"]

        assert detail["binding_constraint"]
        assert "97" in detail["binding_constraint"]

    async def test_no_price_is_returned(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """A very large number would read as an answer."""
        detail = (
            await client.post(
                _solve_url(priced_product, channel),
                json={"target_margin_pct": "97"},
            )
        ).json()["detail"]

        assert detail["required_price_raw"] is None
        assert detail["required_price_rounded"] is None
        assert detail["margin_pct_at_price"] is None

    async def test_the_inputs_are_still_reported(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """FR-034 does not stop applying because the answer is "no price"."""
        detail = (
            await client.post(
                _solve_url(priced_product, channel),
                json={"target_margin_pct": "97"},
            )
        ).json()["detail"]

        assert detail["inputs"]


class TestTheSolveEndpointRefuses:
    async def test_unauthenticated_is_a_401(
        self,
        unauthenticated_client: AsyncClient,
        priced_product: Product,
        channel: SalesChannel,
    ) -> None:
        response = await unauthenticated_client.post(
            _solve_url(priced_product, channel),
            json={"target_margin_pct": "35"},
        )

        assert response.status_code == 401

    async def test_a_product_not_sold_on_that_channel_is_a_404(
        self, client: AsyncClient, unlisted_product: Product, channel: SalesChannel
    ) -> None:
        """Not a price of zero, and not a price solved against nothing."""
        response = await client.post(
            _solve_url(unlisted_product, channel),
            json={"target_margin_pct": "35"},
        )

        assert response.status_code == 404

    async def test_an_unknown_product_is_a_404(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await client.post(
            f"{API}/products/{uuid4()}/pricing/{channel.id}/solve",
            json={"target_margin_pct": "35"},
        )

        assert response.status_code == 404

    async def test_an_unknown_channel_is_a_404(
        self, client: AsyncClient, priced_product: Product
    ) -> None:
        response = await client.post(
            f"{API}/products/{priced_product.id}/pricing/{uuid4()}/solve",
            json={"target_margin_pct": "35"},
        )

        assert response.status_code == 404

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"target_margin_pct": "-5"},
            {"target_margin_pct": "100"},
            {"target_margin_pct": "35", "quantity": 0},
            {"target_margin_pct": "not a number"},
        ],
        ids=["missing", "negative", "at-100", "zero-quantity", "not-a-number"],
    )
    async def test_an_invalid_body_is_a_422(
        self,
        client: AsyncClient,
        priced_product: Product,
        channel: SalesChannel,
        body: dict,
    ) -> None:
        response = await client.post(_solve_url(priced_product, channel), json=body)

        assert response.status_code == 422


# ============================================================================
# The ladder
# ============================================================================


class TestThePriceLadder:
    async def test_a_range_returns_a_rung_for_each_price(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        response = await client.get(
            _ladder_url(priced_product, channel),
            params={"price_from": "50", "price_to": "70", "step": "5"},
        )

        assert response.status_code == 200
        body = response.json()
        assert [Decimal(rung["price"]) for rung in body["rungs"]] == [
            Decimal("50.00"),
            Decimal("55.00"),
            Decimal("60.00"),
            Decimal("65.00"),
            Decimal("70.00"),
        ]

    async def test_margin_rises_across_the_ladder(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        body = (
            await client.get(
                _ladder_url(priced_product, channel),
                params={"price_from": "50", "price_to": "70", "step": "5"},
            )
        ).json()

        margins = [Decimal(rung["margin_pct"]) for rung in body["rungs"]]
        assert margins == sorted(margins)

    async def test_every_rung_names_the_basis_it_is_reported_on(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """FR-031b, on every figure rather than once per screen."""
        body = (
            await client.get(
                _ladder_url(priced_product, channel),
                params={"price_from": "50", "price_to": "60", "step": "5"},
            )
        ).json()

        assert body["margin_basis_label"]
        for rung in body["rungs"]:
            assert rung["margin_basis"] == body["margin_basis"]

    async def test_profit_per_machine_hour_is_reported(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """US7's headline figure, available where the price is chosen."""
        body = (
            await client.get(
                _ladder_url(priced_product, channel),
                params={"price_from": "60", "price_to": "60", "step": "5"},
            )
        ).json()

        rung = body["rungs"][0]
        assert body["machine_hours"] is not None
        expected = (Decimal(rung["profit"]) / Decimal(body["machine_hours"])).quantize(
            Decimal("0.01")
        )
        assert Decimal(rung["profit_per_machine_hour"]) == expected

    async def test_the_bounds_are_echoed_back(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """They were the caller's; the ladder has no range of its own (FR-007)."""
        body = (
            await client.get(
                _ladder_url(priced_product, channel),
                params={"price_from": "50", "price_to": "70", "step": "5"},
            )
        ).json()

        assert Decimal(body["price_from"]) == Decimal("50")
        assert Decimal(body["price_to"]) == Decimal("70")
        assert Decimal(body["step"]) == Decimal("5")

    async def test_no_rung_is_marked_as_recommended(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """FR-007: the choice stays with the operator, and so does the ranking."""
        body = (
            await client.get(
                _ladder_url(priced_product, channel),
                params={"price_from": "50", "price_to": "70", "step": "5"},
            )
        ).json()

        for rung in body["rungs"]:
            assert not {
                "recommended",
                "is_recommended",
                "suggested",
                "best",
                "optimal",
                "score",
                "rank",
            } & set(rung)

    async def test_money_crosses_the_wire_as_a_string(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        body = (
            await client.get(
                _ladder_url(priced_product, channel),
                params={"price_from": "60", "price_to": "60", "step": "5"},
            )
        ).json()

        rung = body["rungs"][0]
        assert isinstance(rung["price"], str)
        assert isinstance(rung["profit"], str)
        assert isinstance(body["make_cost"], str)

    async def test_the_ladder_writes_nothing(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        priced_product: Product,
        channel: SalesChannel,
    ) -> None:
        await client.get(
            _ladder_url(priced_product, channel),
            params={"price_from": "50", "price_to": "70", "step": "5"},
        )

        pricing = (
            await db_session.execute(
                select(ProductPricing).where(
                    ProductPricing.product_id == priced_product.id,
                    ProductPricing.sales_channel_id == channel.id,
                )
            )
        ).scalar_one()
        await db_session.refresh(pricing)

        assert Decimal(str(pricing.list_price)) == LIST_PRICE


class TestTheLadderEndpointRefuses:
    async def test_unauthenticated_is_a_401(
        self,
        unauthenticated_client: AsyncClient,
        priced_product: Product,
        channel: SalesChannel,
    ) -> None:
        response = await unauthenticated_client.get(
            _ladder_url(priced_product, channel),
            params={"price_from": "50", "price_to": "70", "step": "5"},
        )

        assert response.status_code == 401

    async def test_a_product_not_sold_on_that_channel_is_a_404(
        self, client: AsyncClient, unlisted_product: Product, channel: SalesChannel
    ) -> None:
        response = await client.get(
            _ladder_url(unlisted_product, channel),
            params={"price_from": "50", "price_to": "70", "step": "5"},
        )

        assert response.status_code == 404

    @pytest.mark.parametrize(
        "params",
        [
            {"price_to": "70", "step": "5"},
            {"price_from": "50", "step": "5"},
            {"price_from": "50", "price_to": "70"},
            {"price_from": "50", "price_to": "70", "step": "0"},
            {"price_from": "50", "price_to": "70", "step": "-5"},
            {"price_from": "0", "price_to": "70", "step": "5"},
        ],
        ids=["no-from", "no-to", "no-step", "zero-step", "negative-step", "zero-from"],
    )
    async def test_a_missing_or_impossible_bound_is_a_422(
        self,
        client: AsyncClient,
        priced_product: Product,
        channel: SalesChannel,
        params: dict,
    ) -> None:
        """No defaults: a default range's midpoint would imply a recommendation."""
        response = await client.get(_ladder_url(priced_product, channel), params=params)

        assert response.status_code == 422

    async def test_a_backwards_range_is_a_422_rather_than_an_empty_ladder(
        self, client: AsyncClient, priced_product: Product, channel: SalesChannel
    ) -> None:
        """An empty ladder would read as "no price works"."""
        response = await client.get(
            _ladder_url(priced_product, channel),
            params={"price_from": "70", "price_to": "50", "step": "5"},
        )

        assert response.status_code == 422
