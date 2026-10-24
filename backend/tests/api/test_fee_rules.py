"""`/sales-channels/{id}/fee-rules` — configuring the real fee stack (T064).

The permission split is the part worth testing hardest. Fee rules are monetary
policy, so a member must be refused a write and the stored rule must be
unchanged afterwards (FR-007a, FR-007d) -- a refusal that still mutated
something is worse than no refusal at all. Reading is open to every role
including viewer, because a margin without its fees is a number nobody can
check (FR-007c).

The preview endpoint is a ``POST`` that creates nothing, which is why it is
open to member: it is how an operator checks a rule before trusting a margin
built on it.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee_rule import FeeRule
from app.models.sales_channel import SalesChannel
from app.models.tenant import Tenant
from app.models.user import UserRole

pytestmark = pytest.mark.asyncio

APPLIES_FROM = "2024-01-01"


def _url(channel: SalesChannel, suffix: str = "") -> str:
    return f"/api/v1/sales-channels/{channel.id}/fee-rules{suffix}"


def _body(**overrides) -> dict:
    body = {
        "name": "transaction",
        "basis": "item_plus_shipping",
        "rate_pct": "6.5",
        "fixed_amount": "0.00",
        "sort_order": 10,
        "applies_from": APPLIES_FROM,
    }
    body.update(overrides)
    return body


@pytest_asyncio.fixture
async def channel(db_session: AsyncSession, test_tenant: Tenant) -> SalesChannel:
    """A channel with its economics set explicitly, not by column default."""
    row = SalesChannel(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Fee Rule Marketplace",
        platform_type="etsy",
        monthly_cost=Decimal("0"),
        tax_remitter="operator",
        expected_discount_pct=Decimal("0"),
        expected_refund_pct=Decimal("0"),
        currency_code="CAD",
        offsite_ads_opt_in=False,
        is_active=True,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def _stored_rules(db_session: AsyncSession, channel: SalesChannel) -> list[FeeRule]:
    result = await db_session.execute(
        select(FeeRule).where(FeeRule.sales_channel_id == channel.id).order_by(FeeRule.sort_order)
    )
    return list(result.scalars().all())


# ============================================================================
# Creating
# ============================================================================


class TestCreatingAFeeRule:
    async def test_an_admin_can_create_a_rule(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await client.post(_url(channel), json=_body())

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "transaction"
        assert body["basis"] == "item_plus_shipping"
        assert Decimal(body["rate_pct"]) == Decimal("6.5")
        assert body["sales_channel_id"] == str(channel.id)

    async def test_a_clamped_rule_keeps_both_clamps(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await client.post(
            _url(channel),
            json=_body(name="capped", min_amount="0.50", max_amount="5.00"),
        )

        assert response.status_code == 201
        body = response.json()
        assert Decimal(body["min_amount"]) == Decimal("0.50")
        assert Decimal(body["max_amount"]) == Decimal("5.00")

    async def test_an_unknown_channel_is_a_404(self, client: AsyncClient) -> None:
        response = await client.post(f"/api/v1/sales-channels/{uuid4()}/fee-rules", json=_body())

        assert response.status_code == 404


class TestValidationOnCreate:
    async def test_a_floor_above_a_cap_is_a_422(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """FR-021d."""
        response = await client.post(
            _url(channel),
            json=_body(min_amount="10.00", max_amount="5.00"),
        )

        assert response.status_code == 422

    async def test_a_rate_on_a_count_basis_is_a_422(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """A percentage of a quantity is not an amount."""
        response = await client.post(
            _url(channel),
            json=_body(name="per_unit", basis="per_unit_sold", rate_pct="3"),
        )

        assert response.status_code == 422
        assert "count" in str(response.json()["detail"])

    async def test_an_unknown_basis_is_a_422(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await client.post(_url(channel), json=_body(basis="per_fortnight"))

        assert response.status_code == 422

    async def test_an_end_date_before_the_start_is_a_422(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await client.post(_url(channel), json=_body(applies_to="2023-01-01"))

        assert response.status_code == 422

    async def test_an_overlapping_rule_of_the_same_name_is_a_422(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """FR-022: both would be charged, silently doubling the fee."""
        first = await client.post(_url(channel), json=_body())
        assert first.status_code == 201

        second = await client.post(_url(channel), json=_body(rate_pct="7.0"))

        assert second.status_code == 422
        assert "already applies" in str(second.json()["detail"])

    async def test_a_rule_that_starts_after_the_last_one_closed_is_allowed(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """A rate change is two consecutive rules, not an edit (FR-003)."""
        first = await client.post(_url(channel), json=_body(applies_to="2024-12-31"))
        assert first.status_code == 201

        second = await client.post(
            _url(channel), json=_body(rate_pct="7.0", applies_from="2025-01-01")
        )

        assert second.status_code == 201

    async def test_two_different_fees_may_share_a_period(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """Overlap is refused per name; a channel charges several fees at once."""
        assert (await client.post(_url(channel), json=_body())).status_code == 201

        other = await client.post(
            _url(channel),
            json=_body(name="payment_processing", basis="order_total", sort_order=20),
        )

        assert other.status_code == 201


# ============================================================================
# Reading
# ============================================================================


class TestReadingFeeRules:
    async def test_rules_come_back_in_sort_order(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        await client.post(
            _url(channel), json=_body(name="third", basis="order_total", sort_order=30)
        )
        await client.post(_url(channel), json=_body(name="first", sort_order=10))

        body = (await client.get(_url(channel))).json()

        assert [rule["name"] for rule in body["rules"]] == ["first", "third"]
        assert body["total"] == 2

    async def test_a_closed_rule_is_returned_without_an_as_of(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """Reconciling March needs March's rule as well as today's."""
        await client.post(_url(channel), json=_body(applies_to="2024-06-30"))

        body = (await client.get(_url(channel))).json()

        assert body["total"] == 1

    async def test_an_as_of_returns_only_the_rules_in_effect_then(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        await client.post(_url(channel), json=_body(applies_to="2024-06-30"))
        await client.post(_url(channel), json=_body(rate_pct="7.0", applies_from="2024-07-01"))

        before = (await client.get(_url(channel), params={"as_of": "2024-03-01"})).json()
        after = (await client.get(_url(channel), params={"as_of": "2025-03-01"})).json()

        assert before["total"] == 1
        assert Decimal(before["rules"][0]["rate_pct"]) == Decimal("6.5")
        assert after["total"] == 1
        assert Decimal(after["rules"][0]["rate_pct"]) == Decimal("7.0")

    async def test_reading_is_unauthenticated_at_401(
        self, unauthenticated_client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await unauthenticated_client.get(_url(channel))

        assert response.status_code == 401


# ============================================================================
# Permissions
# ============================================================================


class TestOnlyAdminsMayChangeFeeRules:
    async def test_a_viewer_may_read(
        self, client: AsyncClient, channel: SalesChannel, as_role
    ) -> None:
        """FR-007c: a margin without its fees cannot be checked."""
        await client.post(_url(channel), json=_body())

        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.get(_url(channel))

        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_a_member_is_refused_a_write_and_nothing_changes(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        channel: SalesChannel,
        as_role,
    ) -> None:
        """FR-007d: the refusal must leave the figure untouched."""
        await client.post(_url(channel), json=_body())
        before = [(r.name, r.rate_pct) for r in await _stored_rules(db_session, channel)]

        async with as_role(UserRole.MEMBER) as member:
            response = await member.post(
                _url(channel), json=_body(name="sneaky", basis="order_total")
            )

        assert response.status_code == 403
        after = [(r.name, r.rate_pct) for r in await _stored_rules(db_session, channel)]
        assert after == before

    async def test_a_viewer_is_refused_a_write(
        self, client: AsyncClient, channel: SalesChannel, as_role
    ) -> None:
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.post(_url(channel), json=_body())

        assert response.status_code == 403

    async def test_a_member_may_preview(
        self, client: AsyncClient, channel: SalesChannel, as_role
    ) -> None:
        """The engine made inspectable creates nothing (FR-018)."""
        await client.post(_url(channel), json=_body())

        async with as_role(UserRole.MEMBER) as member:
            response = await member.post(_url(channel, "/preview"), json={"item_subtotal": "64.99"})

        assert response.status_code == 200


# ============================================================================
# Updating and deleting
# ============================================================================


class TestUpdatingAFeeRule:
    async def test_a_rate_can_be_changed(self, client: AsyncClient, channel: SalesChannel) -> None:
        created = (await client.post(_url(channel), json=_body())).json()

        response = await client.put(_url(channel, f"/{created['id']}"), json={"rate_pct": "7.25"})

        assert response.status_code == 200
        assert Decimal(response.json()["rate_pct"]) == Decimal("7.25")

    async def test_fields_the_body_omits_are_left_alone(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        created = (await client.post(_url(channel), json=_body(max_amount="5.00"))).json()

        updated = (
            await client.put(_url(channel, f"/{created['id']}"), json={"rate_pct": "7.25"})
        ).json()

        assert Decimal(updated["max_amount"]) == Decimal("5.00")
        assert updated["basis"] == "item_plus_shipping"

    async def test_an_update_that_would_invert_the_clamps_is_a_422(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """Validated against the merged rule, not just the body."""
        created = (await client.post(_url(channel), json=_body(max_amount="5.00"))).json()

        response = await client.put(
            _url(channel, f"/{created['id']}"), json={"min_amount": "10.00"}
        )

        assert response.status_code == 422

    async def test_an_unknown_rule_is_a_404(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await client.put(_url(channel, f"/{uuid4()}"), json={"rate_pct": "7.25"})

        assert response.status_code == 404

    async def test_a_member_is_refused_an_update(
        self, client: AsyncClient, channel: SalesChannel, as_role
    ) -> None:
        created = (await client.post(_url(channel), json=_body())).json()

        async with as_role(UserRole.MEMBER) as member:
            response = await member.put(_url(channel, f"/{created['id']}"), json={"rate_pct": "99"})

        assert response.status_code == 403


class TestDeletingAFeeRule:
    async def test_an_admin_can_delete_a_rule(
        self, client: AsyncClient, db_session: AsyncSession, channel: SalesChannel
    ) -> None:
        created = (await client.post(_url(channel), json=_body())).json()

        response = await client.delete(_url(channel, f"/{created['id']}"))

        assert response.status_code == 204
        assert await _stored_rules(db_session, channel) == []

    async def test_an_unknown_rule_is_a_404(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await client.delete(_url(channel, f"/{uuid4()}"))

        assert response.status_code == 404

    async def test_a_member_is_refused_a_delete(
        self, client: AsyncClient, db_session: AsyncSession, channel: SalesChannel, as_role
    ) -> None:
        created = (await client.post(_url(channel), json=_body())).json()

        async with as_role(UserRole.MEMBER) as member:
            response = await member.delete(_url(channel, f"/{created['id']}"))

        assert response.status_code == 403
        assert len(await _stored_rules(db_session, channel)) == 1


# ============================================================================
# Preview
# ============================================================================


class TestPreviewingTheStack:
    async def test_the_itemised_stack_comes_back_with_its_bases(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        await client.post(_url(channel), json=_body())
        await client.post(
            _url(channel),
            json=_body(
                name="payment_processing",
                basis="order_total",
                rate_pct="3.0",
                fixed_amount="0.30",
                sort_order=20,
            ),
        )

        body = (
            await client.post(
                _url(channel, "/preview"),
                json={"item_subtotal": "64.99", "as_of": "2026-06-01"},
            )
        ).json()

        charges = {charge["name"]: charge for charge in body["charges"]}
        assert charges["transaction"]["basis"] == "item_plus_shipping"
        assert Decimal(charges["transaction"]["amount"]) == Decimal("4.22")
        assert Decimal(charges["payment_processing"]["amount"]) == Decimal("2.25")
        assert Decimal(body["total"]) == Decimal("6.47")

    async def test_a_capped_fee_says_the_cap_bound(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """FR-021c, through the API."""
        await client.post(_url(channel), json=_body(max_amount="2.00"))

        body = (
            await client.post(_url(channel, "/preview"), json={"item_subtotal": "64.99"})
        ).json()

        charge = body["charges"][0]
        assert charge["clamp_applied"] == "max"
        assert Decimal(charge["amount"]) == Decimal("2.00")
        assert body["bound_clamps"] == ["transaction"]

    async def test_an_expected_fee_is_labelled_as_one(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """FR-029."""
        await client.post(_url(channel), json=_body(incidence_pct="20"))

        body = (
            await client.post(_url(channel, "/preview"), json={"item_subtotal": "100.00"})
        ).json()

        charge = body["charges"][0]
        assert charge["is_expected"] is True
        assert Decimal(charge["amount"]) == Decimal("1.30")

    async def test_shipping_revenue_moves_a_fee_charged_on_it(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """US3's independent test, through the API (FR-023)."""
        await client.post(_url(channel), json=_body())

        free = (
            await client.post(_url(channel, "/preview"), json={"item_subtotal": "50.00"})
        ).json()
        charged = (
            await client.post(
                _url(channel, "/preview"),
                json={"item_subtotal": "50.00", "shipping_revenue": "8.00"},
            )
        ).json()

        assert Decimal(charged["total"]) > Decimal(free["total"])
        assert Decimal(charged["charges"][0]["basis_amount"]) == Decimal("58.00")

    async def test_a_periodic_rule_is_reported_separately(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """FR-025: absorbed over a period, not charged on one sale."""
        await client.post(
            _url(channel),
            json=_body(name="listing", basis="per_listing", rate_pct="0", fixed_amount="0.22"),
        )

        body = (
            await client.post(
                _url(channel, "/preview"),
                json={"item_subtotal": "64.99", "listings": 10},
            )
        ).json()

        assert body["charges"] == []
        assert [c["name"] for c in body["periodic"]] == ["listing"]
        assert Decimal(body["periodic_total"]) == Decimal("2.20")

    async def test_a_tax_inclusive_preview_says_it_derived_the_exclusive_amount(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """FR-028e."""
        await client.post(_url(channel), json=_body())

        body = (
            await client.post(
                _url(channel, "/preview"),
                json={
                    "item_subtotal": "113.00",
                    "sales_tax_collected": "13.00",
                    "amounts_are_tax_inclusive": True,
                },
            )
        ).json()

        assert body["tax_exclusive_derived"] is True
        assert Decimal(body["revenue_tax_exclusive"]) == Decimal("100.00")

    async def test_a_negative_subtotal_is_a_422(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        response = await client.post(_url(channel, "/preview"), json={"item_subtotal": "-1.00"})

        assert response.status_code == 422

    async def test_the_preview_creates_nothing(
        self, client: AsyncClient, db_session: AsyncSession, channel: SalesChannel
    ) -> None:
        await client.post(_url(channel), json=_body())
        before = len(await _stored_rules(db_session, channel))

        await client.post(_url(channel, "/preview"), json={"item_subtotal": "64.99"})

        assert len(await _stored_rules(db_session, channel)) == before


# ============================================================================
# SC-009: plan and statement agree once the rates match the schedule
# ============================================================================


class TestPlannedFeesMatchTheSchedule:
    async def test_the_planned_total_is_within_one_percent_of_the_statement(
        self, client: AsyncClient, channel: SalesChannel
    ) -> None:
        """SC-009, stated as the success criterion states it.

        With the rates entered to match the published schedule, the figure the
        engine plans and the figure the statement charges must agree to within
        1% of the fee amount. Here the "statement" is the schedule applied by
        hand, which is the only thing that can be checked without a real
        marketplace in the loop -- but it is the check that catches a basis
        mistake, which is the error that actually moves the total.
        """
        price = Decimal("64.99")
        schedule = (
            ("transaction", "item_plus_shipping", Decimal("6.5"), Decimal("0.00"), 10),
            ("payment_processing", "order_total", Decimal("3.0"), Decimal("0.30"), 20),
            ("regulatory_operating", "item_subtotal", Decimal("3.0"), Decimal("0.22"), 30),
        )
        for name, basis, rate, fixed, order in schedule:
            created = await client.post(
                _url(channel),
                json=_body(
                    name=name,
                    basis=basis,
                    rate_pct=str(rate),
                    fixed_amount=str(fixed),
                    sort_order=order,
                ),
            )
            assert created.status_code == 201

        planned = Decimal(
            (
                await client.post(_url(channel, "/preview"), json={"item_subtotal": str(price)})
            ).json()["total"]
        )

        # The schedule applied by hand: every rate here is charged on the item
        # alone because there is no shipping revenue, so all three bases
        # coincide on this order.
        from_schedule = sum(
            (price * rate / Decimal("100") + fixed for _, _, rate, fixed, _ in schedule),
            Decimal("0"),
        )

        assert abs(planned - from_schedule) <= from_schedule * Decimal("0.01")
        assert planned == from_schedule.quantize(Decimal("0.01"))


# ============================================================================
# A rule is superseded, never edited (task T233)
# ============================================================================


async def _order_on(db_session: AsyncSession, tenant: Tenant, channel: SalesChannel, day: str):
    from datetime import datetime, timezone

    from app.models.order import Order

    placed = datetime.fromisoformat(day).replace(hour=12, tzinfo=timezone.utc)
    order = Order(
        id=uuid4(),
        tenant_id=tenant.id,
        sales_channel_id=channel.id,
        order_number=f"ORD-{uuid4().hex[:8]}",
        customer_name="Fee Customer",
        customer_email="fee@example.com",
        shipping_address_line1="1 Test Street",
        shipping_city="Testville",
        shipping_postcode="T35T",
        shipping_country="Canada",
        shipping_method="Standard",
        shipping_cost=Decimal("0"),
        subtotal=Decimal("100"),
        total=Decimal("100"),
        currency="CAD",
        status="delivered",
        created_at=placed,
        updated_at=placed,
    )
    db_session.add(order)
    await db_session.commit()
    return order


async def _preview(client: AsyncClient, channel: SalesChannel, as_of: str) -> str:
    response = await client.post(
        _url(channel, "/preview"), json={"item_subtotal": "100.00", "as_of": as_of}
    )
    assert response.status_code == 200, response.text
    return response.json()["total"]


class TestARuleIsSupersededNotEdited:
    async def test_a_rate_change_after_an_order_opens_a_new_rule(
        self, client: AsyncClient, db_session, test_tenant, channel
    ) -> None:
        created = (await client.post(_url(channel), json=_body())).json()
        await _order_on(db_session, test_tenant, channel, "2024-06-15")

        response = await client.put(
            _url(channel, f"/{created['id']}"),
            json={"rate_pct": "9.5", "effective_from": "2025-01-01"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["id"] != created["id"]
        assert response.json()["applies_from"] == "2025-01-01"
        rules = await _stored_rules(db_session, channel)
        for rule in rules:
            await db_session.refresh(rule)
        old = next(rule for rule in rules if str(rule.id) == created["id"])
        assert old.rate_pct == Decimal("6.5")
        assert str(old.applies_to) == "2024-12-31"

    async def test_a_past_dates_preview_is_unchanged_after_an_edit(
        self, client: AsyncClient, db_session, test_tenant, channel
    ) -> None:
        created = (await client.post(_url(channel), json=_body())).json()
        await _order_on(db_session, test_tenant, channel, "2024-06-15")
        before = await _preview(client, channel, "2024-06-15")

        await client.put(
            _url(channel, f"/{created['id']}"),
            json={"rate_pct": "20", "effective_from": "2025-01-01"},
        )

        assert await _preview(client, channel, "2024-06-15") == before == "6.50"
        assert await _preview(client, channel, "2025-06-15") == "20.00"

    async def test_an_unused_rule_is_corrected_in_place(
        self, client: AsyncClient, db_session, channel
    ) -> None:
        created = (await client.post(_url(channel), json=_body())).json()

        response = await client.put(
            _url(channel, f"/{created['id']}"),
            json={"rate_pct": "7.0", "effective_from": APPLIES_FROM},
        )

        assert response.status_code == 200
        assert response.json()["id"] == created["id"]
        assert len(await _stored_rules(db_session, channel)) == 1

    async def test_a_change_dated_into_a_used_rules_life_start_is_a_422(
        self, client: AsyncClient, db_session, test_tenant, channel
    ) -> None:
        created = (await client.post(_url(channel), json=_body())).json()
        await _order_on(db_session, test_tenant, channel, "2024-06-15")

        response = await client.put(
            _url(channel, f"/{created['id']}"),
            json={"rate_pct": "9.5", "effective_from": APPLIES_FROM},
        )

        assert response.status_code == 422

    async def test_renaming_alone_is_made_in_place(
        self, client: AsyncClient, db_session, test_tenant, channel
    ) -> None:
        created = (await client.post(_url(channel), json=_body())).json()
        await _order_on(db_session, test_tenant, channel, "2024-06-15")

        response = await client.put(_url(channel, f"/{created['id']}"), json={"sort_order": 30})

        assert response.status_code == 200
        assert response.json()["id"] == created["id"]


class TestDeletingARule:
    async def test_a_rule_nothing_used_is_deleted(
        self, client: AsyncClient, db_session, channel
    ) -> None:
        created = (await client.post(_url(channel), json=_body())).json()

        response = await client.delete(_url(channel, f"/{created['id']}"))

        assert response.status_code == 204
        assert await _stored_rules(db_session, channel) == []

    async def test_a_rule_an_order_used_is_closed_not_deleted(
        self, client: AsyncClient, db_session, test_tenant, channel
    ) -> None:
        created = (await client.post(_url(channel), json=_body())).json()
        await _order_on(db_session, test_tenant, channel, "2024-06-15")

        response = await client.delete(_url(channel, f"/{created['id']}"))

        assert response.status_code == 204
        [rule] = await _stored_rules(db_session, channel)
        await db_session.refresh(rule)
        assert rule.applies_to is not None
        # The order it priced still reads it.
        assert await _preview(client, channel, "2024-06-15") == "6.50"
