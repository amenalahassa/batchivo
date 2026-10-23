"""The channel endpoints read and write the dated economics (task T136).

The service is proved in ``tests/unit/pricing/test_channel_economics.py``.
What this file proves is that the HTTP surface goes through it: that a ``PUT``
opens a period rather than editing one, that a ``GET`` with ``as_of`` reads the
figures that were in force then, and that changing a reserve needs the role
FR-007a reserves it to.

The pairing matters more than any single assertion. A single-date test would
pass against the mutable column this change replaced, which is the defect:
raising a refund reserve used to change what every past plan said it had
reserved.
"""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.clock import today
from app.models.sales_channel import SalesChannel
from app.models.sales_channel_economics import SalesChannelEconomics
from app.models.user import UserRole

pytestmark = pytest.mark.asyncio

URL = "/api/v1/sales-channels"

# The business date the service dates a period from, not the server's
# locale: `app/core/clock.py` returns the UTC date, and between the two
# midnights `date.today()` is a day behind it -- which made this file fail
# for part of every day for reasons that had nothing to do with the code
# under test (Constitution III: one notion of today).
TODAY = today()
LAST_MONTH = TODAY - timedelta(days=30)

OLD_RESERVE = "2.0000"
NEW_RESERVE = "20.0000"


def _body(**overrides) -> dict:
    body = {
        "name": f"Economics {overrides.pop('suffix', 'channel')}",
        "platform_type": "etsy",
        "monthly_cost": "0",
        "tax_remitter": "operator",
        "currency_code": "CAD",
        "expected_discount_pct": "0",
        "expected_refund_pct": OLD_RESERVE,
        "is_active": True,
    }
    body.update(overrides)
    return body


async def _create(client: AsyncClient, **overrides) -> dict:
    response = await client.post(URL, json=_body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


class TestCreating:
    async def test_a_new_channel_gets_a_dated_first_period(
        self, client: AsyncClient, db_session
    ) -> None:
        # Every channel has a period from the start, which is what keeps the
        # legacy-column fallback unreachable in a live database.
        created = await _create(client, suffix="first")

        rows = list(
            (
                await db_session.execute(
                    select(SalesChannelEconomics).where(
                        SalesChannelEconomics.sales_channel_id == UUID(created["id"])
                    )
                )
            )
            .scalars()
            .all()
        )

        assert len(rows) == 1
        assert rows[0].effective_to is None
        assert rows[0].expected_refund_pct == Decimal(OLD_RESERVE)

    async def test_the_response_carries_the_figures_it_was_given(self, client: AsyncClient) -> None:
        created = await _create(
            client,
            suffix="echo",
            free_shipping_threshold="45.00",
            rounding_rule="psychological_99",
        )

        assert created["expected_refund_pct"] == OLD_RESERVE
        assert created["free_shipping_threshold"] == "45.00"
        assert created["rounding_rule"] == "psychological_99"


class TestUpdating:
    async def test_a_change_opens_a_period_and_leaves_the_old_one_alone(
        self, client: AsyncClient, db_session
    ) -> None:
        created = await _create(client, suffix="supersede")
        # The first period starts today, so the change has to start later or
        # the two would collapse onto one day.
        tomorrow = TODAY + timedelta(days=1)

        response = await client.put(
            f"{URL}/{created['id']}",
            json={"expected_refund_pct": NEW_RESERVE, "effective_from": tomorrow.isoformat()},
        )

        assert response.status_code == 200, response.text
        rows = list(
            (
                await db_session.execute(
                    select(SalesChannelEconomics)
                    .where(SalesChannelEconomics.sales_channel_id == UUID(created["id"]))
                    .order_by(SalesChannelEconomics.effective_from)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        assert rows[0].expected_refund_pct == Decimal(OLD_RESERVE)
        assert rows[0].effective_to == TODAY
        assert rows[1].expected_refund_pct == Decimal(NEW_RESERVE)
        assert rows[1].effective_to is None

    async def test_the_past_figure_is_still_readable_afterwards(self, client: AsyncClient) -> None:
        # This is the requirement, in one test: the figure a plan was built on
        # does not move when the operator changes their mind.
        created = await _create(client, suffix="history")
        tomorrow = TODAY + timedelta(days=1)
        await client.put(
            f"{URL}/{created['id']}",
            json={"expected_refund_pct": NEW_RESERVE, "effective_from": tomorrow.isoformat()},
        )

        then = await client.get(f"{URL}/{created['id']}", params={"as_of": TODAY.isoformat()})
        later = await client.get(f"{URL}/{created['id']}", params={"as_of": tomorrow.isoformat()})

        assert then.json()["expected_refund_pct"] == OLD_RESERVE
        assert later.json()["expected_refund_pct"] == NEW_RESERVE

    async def test_an_operational_field_is_still_set_in_place(
        self, client: AsyncClient, db_session
    ) -> None:
        # A channel's name is configuration, not a decision with a history.
        created = await _create(client, suffix="rename")

        response = await client.put(f"{URL}/{created['id']}", json={"name": "Renamed channel"})

        assert response.status_code == 200
        assert response.json()["name"] == "Renamed channel"
        rows = list(
            (
                await db_session.execute(
                    select(SalesChannelEconomics).where(
                        SalesChannelEconomics.sales_channel_id == UUID(created["id"])
                    )
                )
            )
            .scalars()
            .all()
        )
        # No new period: nothing monetary was named.
        assert len(rows) == 1

    async def test_a_figure_outside_its_range_is_a_422(self, client: AsyncClient) -> None:
        created = await _create(client, suffix="range")

        response = await client.put(f"{URL}/{created['id']}", json={"expected_refund_pct": "150"})

        assert response.status_code == 422

    async def test_an_unknown_channel_is_a_404(self, client: AsyncClient) -> None:
        response = await client.put(f"{URL}/{uuid4()}", json={"expected_refund_pct": NEW_RESERVE})

        assert response.status_code == 404


class TestWhoMayChangeAReserve:
    async def test_a_member_is_refused_and_nothing_is_written(
        self, client: AsyncClient, db_session, as_role
    ) -> None:
        """FR-007a: a reserve is monetary policy."""
        created = await _create(client, suffix="member")

        async with as_role(UserRole.MEMBER) as member:
            response = await member.put(
                f"{URL}/{created['id']}", json={"expected_refund_pct": NEW_RESERVE}
            )

        assert response.status_code == 403
        rows = list(
            (
                await db_session.execute(
                    select(SalesChannelEconomics).where(
                        SalesChannelEconomics.sales_channel_id == UUID(created["id"])
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].expected_refund_pct == Decimal(OLD_RESERVE)

    async def test_a_member_may_still_rename_the_channel(
        self, client: AsyncClient, as_role
    ) -> None:
        # FR-007b: the operational part of a channel is not monetary policy,
        # so the gate is on the figures rather than on the endpoint.
        created = await _create(client, suffix="member-rename")

        async with as_role(UserRole.MEMBER) as member:
            response = await member.put(f"{URL}/{created['id']}", json={"name": "Member renamed"})

        assert response.status_code == 200

    async def test_a_viewer_may_read_the_figures(self, client: AsyncClient, as_role) -> None:
        """FR-007c: every role sees every cost and margin."""
        created = await _create(client, suffix="viewer")

        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.get(f"{URL}/{created['id']}")

        assert response.status_code == 200
        assert response.json()["expected_refund_pct"] == OLD_RESERVE

    async def test_the_role_that_set_it_is_recorded(self, client: AsyncClient, db_session) -> None:
        # FR-012: the screen showing a figure can say where it came from.
        created = await _create(client, suffix="audit")
        await client.put(
            f"{URL}/{created['id']}",
            json={
                "expected_refund_pct": NEW_RESERVE,
                "effective_from": (TODAY + timedelta(days=1)).isoformat(),
            },
        )

        row = (
            (
                await db_session.execute(
                    select(SalesChannelEconomics).where(
                        SalesChannelEconomics.sales_channel_id == UUID(created["id"]),
                        SalesChannelEconomics.effective_to.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )

        assert row.set_by_role in {"admin", "owner"}
        assert row.set_by_user_id is not None


class TestListing:
    async def test_each_channel_carries_its_own_figures(self, client: AsyncClient) -> None:
        await _create(client, suffix="list-a", expected_refund_pct=OLD_RESERVE)
        await _create(client, suffix="list-b", expected_refund_pct="7.0000")

        response = await client.get(URL, params={"limit": 1000})

        by_name = {row["name"]: row for row in response.json()["channels"]}
        assert by_name["Economics list-a"]["expected_refund_pct"] == OLD_RESERVE
        assert by_name["Economics list-b"]["expected_refund_pct"] == "7.0000"

    async def test_as_of_reads_the_list_as_it_stood(self, client: AsyncClient) -> None:
        created = await _create(client, suffix="list-history")
        tomorrow = TODAY + timedelta(days=1)
        await client.put(
            f"{URL}/{created['id']}",
            json={"expected_refund_pct": NEW_RESERVE, "effective_from": tomorrow.isoformat()},
        )

        then = await client.get(URL, params={"limit": 1000, "as_of": TODAY.isoformat()})
        later = await client.get(URL, params={"limit": 1000, "as_of": tomorrow.isoformat()})

        def reserve(payload) -> str:
            return next(
                row["expected_refund_pct"]
                for row in payload.json()["channels"]
                if row["id"] == created["id"]
            )

        assert reserve(then) == OLD_RESERVE
        assert reserve(later) == NEW_RESERVE

    async def test_the_list_agrees_with_the_detail(self, client: AsyncClient) -> None:
        # One figure, two screens. Two resolvers that disagreed would be the
        # defect Constitution III forbids.
        created = await _create(client, suffix="agree", free_shipping_threshold="45.00")

        listed = await client.get(URL, params={"limit": 1000})
        detail = await client.get(f"{URL}/{created['id']}")

        row = next(r for r in listed.json()["channels"] if r["id"] == created["id"])
        for field in (
            "expected_discount_pct",
            "expected_refund_pct",
            "free_shipping_threshold",
            "rounding_rule",
        ):
            assert row[field] == detail.json()[field], field


class TestTheWire:
    async def test_every_amount_crosses_as_a_string(self, client: AsyncClient) -> None:
        # Constitution IV: a reserve as a JSON number is a float by the time
        # the console reads it.
        created = await _create(client, suffix="wire", free_shipping_threshold="45.00")

        for key in (
            "expected_discount_pct",
            "expected_refund_pct",
            "free_shipping_threshold",
        ):
            assert isinstance(created[key], str), key

    async def test_an_absent_threshold_is_null_not_zero(self, client: AsyncClient) -> None:
        # Zero would read as "shipping is always free", which is the opposite
        # of "the operator has set no threshold".
        created = await _create(client, suffix="null")

        assert created["free_shipping_threshold"] is None

    async def test_unauthenticated_is_a_401(self, unauthenticated_client: AsyncClient) -> None:
        response = await unauthenticated_client.get(URL)

        assert response.status_code == 401


class TestTheLegacyColumnsAreNotTheAuthority:
    async def test_a_stale_column_is_never_read(self, client: AsyncClient, db_session) -> None:
        # The columns stay for the pure costing functions' fallback. If a read
        # ever preferred them, this is the test that catches it: the column is
        # set to a figure the operator never chose.
        created = await _create(client, suffix="stale")
        channel = (
            await db_session.execute(
                select(SalesChannel).where(SalesChannel.id == UUID(created["id"]))
            )
        ).scalar_one()
        channel.expected_refund_pct = Decimal("99")
        db_session.add(channel)
        await db_session.commit()

        response = await client.get(f"{URL}/{created['id']}")

        assert response.json()["expected_refund_pct"] == OLD_RESERVE
