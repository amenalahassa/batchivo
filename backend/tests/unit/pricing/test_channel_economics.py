"""A channel's planning figures have a date on them (task T136).

FR-003 requires an operator decision to be effective-dated: superseded, never
updated in place. Four figures on a channel are decisions in that sense -- the
expected discount share, the refund reserve, the free-shipping threshold and
the rounding rule -- and until T136 they were plain mutable columns.

## The defect this file pins

Raising a refund reserve from 2% to 5% changed what every *past* plan said it
had reserved. The margin a product was shown as having last month became the
margin it would have had under today's reserve, which is the restatement
FR-038 forbids on a settled line and FR-003 forbids on a planning figure.
Nothing was wrong with the arithmetic; the input had no date.

So the assertions here are mostly pairs: the same sale, read as at two dates,
reporting the two figures that were actually in force -- and the engine given
two economics values, returning two margins. A single-date test would pass for
the mutable column this change replaced.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.sales_channel import SalesChannel
from app.models.sales_channel_economics import ECONOMICS_FIELDS, SalesChannelEconomics
from app.services import fee_engine
from app.services.channel_economics import (
    ChannelEconomics,
    EconomicsMisconfigured,
    channel_defaults,
    current_economics_row,
    economics_from_row,
    ensure_economics_row,
    resolve_channel_economics,
    resolve_economics_row,
    resolve_many,
    write_economics,
)
from app.services.costing import CostingService
from tests.fixtures import golden_case as golden
from tests.unit.pricing.conftest import make_channel, make_policy

#: Marked per class rather than per module: three of the classes below cost a
#: channel synchronously, with no session at all.
ASYNC = pytest.mark.asyncio

AS_OF = date(2026, 6, 1)

#: Two reserves far enough apart that a margin computed under one cannot be
#: mistaken for a margin computed under the other.
OLD_RESERVE = Decimal("2")
NEW_RESERVE = Decimal("20")

MAKE_COST = Decimal("20.30")


async def _channel(db_session, test_tenant, **overrides) -> SalesChannel:
    defaults = dict(
        tenant_id=test_tenant.id,
        name=f"Economics {id(overrides)}",
        platform_type="etsy",
        monthly_cost=Decimal("0"),
        tax_remitter="operator",
        currency_code="CAD",
        expected_discount_pct=Decimal("0"),
        expected_refund_pct=Decimal("0"),
        is_active=True,
    )
    defaults.update(overrides)
    row = SalesChannel(**defaults)
    db_session.add(row)
    await db_session.flush()
    return row


# ---------------------------------------------------------------------------
# The resolver reads the period in force
# ---------------------------------------------------------------------------


class TestTheFigureInForceIsTheOneReadBack:
    pytestmark = ASYNC

    async def test_a_past_date_reads_the_past_reserve(self, db_session, test_tenant) -> None:
        # The whole point. Two periods, two dates, two answers.
        channel = await _channel(db_session, test_tenant)
        await write_economics(
            db_session,
            test_tenant,
            channel,
            {"expected_refund_pct": OLD_RESERVE},
            effective_from=AS_OF - timedelta(days=60),
        )
        await write_economics(
            db_session,
            test_tenant,
            channel,
            {"expected_refund_pct": NEW_RESERVE},
            effective_from=AS_OF,
        )
        await db_session.commit()

        then = await resolve_channel_economics(db_session, channel, AS_OF - timedelta(days=30))
        now = await resolve_channel_economics(db_session, channel, AS_OF)

        assert then.expected_refund_pct == OLD_RESERVE
        assert now.expected_refund_pct == NEW_RESERVE

    async def test_a_date_before_every_period_falls_back_and_says_so(
        self, db_session, test_tenant
    ) -> None:
        # A channel planned against nothing on that date. Reporting the
        # earliest period instead would be inventing a decision the operator
        # had not made yet.
        channel = await _channel(db_session, test_tenant, expected_refund_pct=Decimal("7"))
        await write_economics(
            db_session,
            test_tenant,
            channel,
            {"expected_refund_pct": NEW_RESERVE},
            effective_from=AS_OF,
        )
        await db_session.commit()

        resolved = await resolve_channel_economics(db_session, channel, AS_OF - timedelta(days=1))

        assert resolved.origin == "channel_default"
        assert resolved.expected_refund_pct == Decimal("7")

    async def test_two_writes_on_one_day_resolve_to_the_later(
        self, db_session, test_tenant
    ) -> None:
        # The superseded row keeps a zero-length period rather than an invalid
        # one, and the open-row tiebreaker picks the write that stands.
        channel = await _channel(db_session, test_tenant)
        await write_economics(
            db_session,
            test_tenant,
            channel,
            {"expected_refund_pct": OLD_RESERVE},
            effective_from=AS_OF,
        )
        await write_economics(
            db_session,
            test_tenant,
            channel,
            {"expected_refund_pct": NEW_RESERVE},
            effective_from=AS_OF,
        )
        await db_session.commit()

        resolved = await resolve_channel_economics(db_session, channel, AS_OF)

        assert resolved.expected_refund_pct == NEW_RESERVE

    async def test_a_channel_with_no_period_reads_its_own_columns(
        self, db_session, test_tenant
    ) -> None:
        # A channel that predates the migration still plans -- with figures
        # that have no history, which `origin` states rather than implies.
        channel = await _channel(
            db_session,
            test_tenant,
            expected_discount_pct=Decimal("3"),
            rounding_rule="psychological_99",
        )
        await db_session.commit()

        resolved = await resolve_channel_economics(db_session, channel, AS_OF)

        assert resolved.origin == "channel_default"
        assert resolved.expected_discount_pct == Decimal("3")
        assert resolved.rounding_rule == "psychological_99"

    async def test_a_stored_period_says_it_came_from_a_row(self, db_session, test_tenant) -> None:
        channel = await _channel(db_session, test_tenant)
        await write_economics(db_session, test_tenant, channel, {}, effective_from=AS_OF)
        await db_session.commit()

        resolved = await resolve_channel_economics(db_session, channel, AS_OF)

        assert resolved.origin == "economics_row"
        assert resolved.effective_from == AS_OF


# ---------------------------------------------------------------------------
# FR-003: superseded, never updated in place
# ---------------------------------------------------------------------------


class TestAWriteSupersedes:
    pytestmark = ASYNC

    async def test_the_superseded_row_is_closed_not_edited(self, db_session, test_tenant) -> None:
        channel = await _channel(db_session, test_tenant)
        first = await write_economics(
            db_session,
            test_tenant,
            channel,
            {"expected_refund_pct": OLD_RESERVE},
            effective_from=AS_OF - timedelta(days=30),
        )
        first_id = first.id
        await write_economics(
            db_session,
            test_tenant,
            channel,
            {"expected_refund_pct": NEW_RESERVE},
            effective_from=AS_OF,
        )
        await db_session.commit()

        rows = list(
            (
                await db_session.execute(
                    select(SalesChannelEconomics)
                    .where(SalesChannelEconomics.sales_channel_id == channel.id)
                    .order_by(SalesChannelEconomics.effective_from)
                )
            )
            .scalars()
            .all()
        )

        assert len(rows) == 2
        assert rows[0].id == first_id
        # Still carrying what it always carried: the figure did not move.
        assert rows[0].expected_refund_pct == OLD_RESERVE
        assert rows[0].effective_to == AS_OF - timedelta(days=1)
        assert rows[1].effective_to is None

    async def test_the_periods_do_not_overlap(self, db_session, test_tenant) -> None:
        # An overlap would make the as-of read ambiguous, which is the one
        # thing a dated table must not be.
        channel = await _channel(db_session, test_tenant)
        for offset in (60, 30, 0):
            await write_economics(
                db_session,
                test_tenant,
                channel,
                {"expected_refund_pct": Decimal(str(offset))},
                effective_from=AS_OF - timedelta(days=offset),
            )
        await db_session.commit()

        rows = list(
            (
                await db_session.execute(
                    select(SalesChannelEconomics)
                    .where(SalesChannelEconomics.sales_channel_id == channel.id)
                    .order_by(SalesChannelEconomics.effective_from)
                )
            )
            .scalars()
            .all()
        )

        for earlier, later in zip(rows, rows[1:]):
            assert earlier.effective_to is not None
            assert earlier.effective_to < later.effective_from

    async def test_an_unchanged_figure_is_carried_forward(self, db_session, test_tenant) -> None:
        # A write that names one figure must not quietly zero the others: a
        # dropped reserve is one the operator believes they still hold.
        channel = await _channel(db_session, test_tenant)
        await write_economics(
            db_session,
            test_tenant,
            channel,
            {
                "expected_discount_pct": Decimal("4"),
                "expected_refund_pct": OLD_RESERVE,
                "free_shipping_threshold": Decimal("45.00"),
                "rounding_rule": "psychological_99",
            },
            effective_from=AS_OF - timedelta(days=30),
        )
        row = await write_economics(
            db_session,
            test_tenant,
            channel,
            {"expected_refund_pct": NEW_RESERVE},
            effective_from=AS_OF,
        )
        await db_session.commit()

        assert row.expected_discount_pct == Decimal("4")
        assert row.free_shipping_threshold == Decimal("45.00")
        assert row.rounding_rule == "psychological_99"
        assert row.expected_refund_pct == NEW_RESERVE

    async def test_the_first_write_carries_the_legacy_columns_forward(
        self, db_session, test_tenant
    ) -> None:
        # Opening a channel's first period must preserve what it was already
        # planning against, not reset it to the table's defaults.
        channel = await _channel(db_session, test_tenant, expected_discount_pct=Decimal("6"))
        row = await write_economics(
            db_session,
            test_tenant,
            channel,
            {"expected_refund_pct": NEW_RESERVE},
            effective_from=AS_OF,
        )
        await db_session.commit()

        assert row.expected_discount_pct == Decimal("6")

    async def test_only_one_period_is_ever_open(self, db_session, test_tenant) -> None:
        channel = await _channel(db_session, test_tenant)
        for offset in (60, 30, 0):
            await write_economics(
                db_session,
                test_tenant,
                channel,
                {},
                effective_from=AS_OF - timedelta(days=offset),
            )
        await db_session.commit()

        open_rows = list(
            (
                await db_session.execute(
                    select(SalesChannelEconomics).where(
                        SalesChannelEconomics.sales_channel_id == channel.id,
                        SalesChannelEconomics.effective_to.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )

        assert len(open_rows) == 1

    async def test_an_unknown_figure_is_refused(self, db_session, test_tenant) -> None:
        # Silently dropping it would leave the operator believing they had set
        # something.
        channel = await _channel(db_session, test_tenant)

        with pytest.raises(EconomicsMisconfigured, match="unknown"):
            await write_economics(
                db_session, test_tenant, channel, {"expected_profit_pct": Decimal("5")}
            )

    @pytest.mark.parametrize(
        "changes",
        [
            {"expected_refund_pct": Decimal("-1")},
            {"expected_refund_pct": Decimal("101")},
            {"expected_discount_pct": Decimal("-0.01")},
            {"free_shipping_threshold": Decimal("-10")},
        ],
    )
    async def test_a_figure_that_could_not_be_used_is_refused(
        self, db_session, test_tenant, changes
    ) -> None:
        channel = await _channel(db_session, test_tenant)

        with pytest.raises(EconomicsMisconfigured):
            await write_economics(db_session, test_tenant, channel, changes)

    async def test_ensure_is_idempotent(self, db_session, test_tenant) -> None:
        channel = await _channel(db_session, test_tenant)
        first = await ensure_economics_row(db_session, test_tenant, channel)
        second = await ensure_economics_row(db_session, test_tenant, channel)
        await db_session.commit()

        assert first.id == second.id

    async def test_the_writer_is_recorded(self, db_session, test_tenant, test_user) -> None:
        # FR-012: a cost screen says where a figure came from, which means
        # knowing who set it and in what role (FR-007a).
        channel = await _channel(db_session, test_tenant)
        row = await write_economics(
            db_session, test_tenant, channel, {}, user=test_user, role="admin"
        )
        await db_session.commit()

        assert row.set_by_user_id == test_user.id
        assert row.set_by_role == "admin"


# ---------------------------------------------------------------------------
# The engine takes the resolved value
# ---------------------------------------------------------------------------


def _margin(economics: ChannelEconomics | None):
    channel = make_channel()
    context, treatment = fee_engine.exclusive_context(
        item_subtotal=golden.LIST_PRICE,
        shipping_revenue=golden.CHANNEL_SHIPPING_REVENUE,
    )
    return CostingService.margin(
        context=context,
        make_cost=MAKE_COST,
        channel=channel,
        fees=fee_engine.compute(channel, context, AS_OF),
        policy=make_policy(),
        economics=economics,
        tax=treatment,
    )


class TestTheEngineUsesTheFigureItWasGiven:
    def test_two_reserves_give_two_margins(self) -> None:
        # The control for the whole change: if the engine still read the
        # channel's own columns, both of these would be the same figure.
        lean = _margin(ChannelEconomics(expected_refund_pct=OLD_RESERVE))
        heavy = _margin(ChannelEconomics(expected_refund_pct=NEW_RESERVE))

        assert lean.margin_pct is not None and heavy.margin_pct is not None
        assert heavy.margin_pct < lean.margin_pct

    def test_the_reserve_appears_as_its_own_deduction(self) -> None:
        # FR-026: a reserve reduces planned revenue and is named, not folded
        # into the cost where nobody can see it.
        result = _margin(ChannelEconomics(expected_refund_pct=NEW_RESERVE))

        keys = [deduction.key for deduction in result.deductions]
        assert "expected_refund" in keys

    def test_no_economics_falls_back_to_the_channel(self) -> None:
        # The fallback keeps a stand-in without a session working, which is how
        # every unit test in this directory costs a channel.
        from_channel = _margin(None)
        explicit = _margin(channel_defaults(make_channel()))

        assert from_channel.margin_pct == explicit.margin_pct

    def test_an_absent_reserve_is_no_deduction_rather_than_a_zero_one(self) -> None:
        result = _margin(ChannelEconomics())

        assert [d.key for d in result.deductions if d.key.startswith("expected_")] == []


# ---------------------------------------------------------------------------
# Reading many channels at once
# ---------------------------------------------------------------------------


class TestResolveMany:
    pytestmark = ASYNC

    async def test_each_channel_gets_its_own_period(self, db_session, test_tenant) -> None:
        first = await _channel(db_session, test_tenant, name="Many A")
        second = await _channel(db_session, test_tenant, name="Many B")
        await write_economics(
            db_session,
            test_tenant,
            first,
            {"expected_refund_pct": OLD_RESERVE},
            effective_from=AS_OF,
        )
        await write_economics(
            db_session,
            test_tenant,
            second,
            {"expected_refund_pct": NEW_RESERVE},
            effective_from=AS_OF,
        )
        await db_session.commit()

        resolved = await resolve_many(db_session, [first, second], AS_OF)

        assert resolved[first.id].expected_refund_pct == OLD_RESERVE
        assert resolved[second.id].expected_refund_pct == NEW_RESERVE

    async def test_it_agrees_with_the_single_read(self, db_session, test_tenant) -> None:
        # Two resolvers that disagree would be two authorities, which is what
        # Constitution III forbids. The list screen and the detail screen must
        # show one figure.
        channel = await _channel(db_session, test_tenant, name="Many C")
        for offset in (60, 30, 0):
            await write_economics(
                db_session,
                test_tenant,
                channel,
                {"expected_refund_pct": Decimal(str(offset))},
                effective_from=AS_OF - timedelta(days=offset),
            )
        await db_session.commit()

        for reference in (AS_OF, AS_OF - timedelta(days=45), AS_OF - timedelta(days=60)):
            many = await resolve_many(db_session, [channel], reference)
            one = await resolve_channel_economics(db_session, channel, reference)
            assert many[channel.id] == one, reference

    async def test_a_channel_with_no_period_still_appears(self, db_session, test_tenant) -> None:
        # Missing from the map would be a KeyError on the list screen.
        channel = await _channel(db_session, test_tenant, name="Many D")
        await db_session.commit()

        resolved = await resolve_many(db_session, [channel], AS_OF)

        assert resolved[channel.id].origin == "channel_default"

    async def test_no_channels_is_no_query_and_no_rows(self, db_session, test_tenant) -> None:
        assert await resolve_many(db_session, [], AS_OF) == {}


# ---------------------------------------------------------------------------
# The value itself
# ---------------------------------------------------------------------------


class TestTheResolvedValue:
    def test_the_deduction_share_is_discount_plus_refund(self) -> None:
        economics = ChannelEconomics(
            expected_discount_pct=Decimal("4"), expected_refund_pct=Decimal("2.5")
        )

        assert economics.deduction_pct == Decimal("6.5")

    def test_it_is_frozen(self) -> None:
        # A cost computed from it must stay explainable by it.
        economics = ChannelEconomics()

        with pytest.raises(Exception):
            economics.expected_refund_pct = NEW_RESERVE  # type: ignore[misc]

    @ASYNC
    async def test_every_figure_the_table_holds_is_carried(self, db_session, test_tenant) -> None:
        # If a figure is added to the table and not to the value, the engine
        # would read it as absent and nobody would be told.
        channel = await _channel(db_session, test_tenant, name="Fields")
        row = await write_economics(db_session, test_tenant, channel, {}, effective_from=AS_OF)
        await db_session.commit()

        value = economics_from_row(row)

        for field in ECONOMICS_FIELDS:
            assert hasattr(value, field), field

    @ASYNC
    async def test_the_amounts_are_decimal(self, db_session, test_tenant) -> None:
        # Constitution IV: never a float.
        channel = await _channel(db_session, test_tenant, name="Exact")
        await write_economics(
            db_session,
            test_tenant,
            channel,
            {"expected_refund_pct": Decimal("2.5"), "free_shipping_threshold": Decimal("45")},
            effective_from=AS_OF,
        )
        await db_session.commit()

        resolved = await resolve_channel_economics(db_session, channel, AS_OF)

        assert isinstance(resolved.expected_refund_pct, Decimal)
        assert isinstance(resolved.free_shipping_threshold, Decimal)


class TestTheOpenRow:
    pytestmark = ASYNC

    async def test_it_is_the_one_with_no_end(self, db_session, test_tenant) -> None:
        channel = await _channel(db_session, test_tenant, name="Open")
        await write_economics(
            db_session, test_tenant, channel, {}, effective_from=AS_OF - timedelta(days=30)
        )
        latest = await write_economics(db_session, test_tenant, channel, {}, effective_from=AS_OF)
        await db_session.commit()

        assert (await current_economics_row(db_session, channel.id)).id == latest.id
        assert latest.is_current

    async def test_a_channel_with_no_period_has_none(self, db_session, test_tenant) -> None:
        channel = await _channel(db_session, test_tenant, name="Empty")
        await db_session.commit()

        assert await current_economics_row(db_session, channel.id) is None
        assert await resolve_economics_row(db_session, channel.id, AS_OF) is None


# ---------------------------------------------------------------------------
# A period-scale read sees every figure in force across it (task T214)
# ---------------------------------------------------------------------------


class TestEconomicsOver:
    pytestmark = ASYNC

    async def test_one_open_period_covers_the_whole_range(self, db_session, test_tenant) -> None:
        from app.services.channel_economics import economics_over

        channel = await _channel(db_session, test_tenant)
        await write_economics(
            db_session,
            test_tenant,
            channel,
            {"monthly_cost": Decimal("30")},
            effective_from=date(2026, 1, 1),
        )

        segments = await economics_over(db_session, channel, date(2026, 6, 1), date(2026, 6, 30))

        assert [(e.monthly_cost, lo, hi) for e, lo, hi in segments] == [
            (Decimal("30"), date(2026, 6, 1), date(2026, 6, 30))
        ]

    async def test_a_change_mid_range_splits_it_at_the_change(
        self, db_session, test_tenant
    ) -> None:
        from app.services.channel_economics import economics_over

        channel = await _channel(db_session, test_tenant)
        await write_economics(
            db_session,
            test_tenant,
            channel,
            {"monthly_cost": Decimal("30")},
            effective_from=date(2026, 1, 1),
        )
        await write_economics(
            db_session,
            test_tenant,
            channel,
            {"tax_remitter": "marketplace"},
            effective_from=date(2026, 6, 16),
        )

        segments = await economics_over(db_session, channel, date(2026, 6, 1), date(2026, 6, 30))

        assert [(e.tax_remitter, lo, hi) for e, lo, hi in segments] == [
            ("operator", date(2026, 6, 1), date(2026, 6, 15)),
            ("marketplace", date(2026, 6, 16), date(2026, 6, 30)),
        ]

    async def test_days_before_the_first_period_fall_back_to_the_channel(
        self, db_session, test_tenant
    ) -> None:
        from app.services.channel_economics import economics_over

        channel = await _channel(db_session, test_tenant, monthly_cost=Decimal("5"))
        await write_economics(
            db_session,
            test_tenant,
            channel,
            {"monthly_cost": Decimal("50")},
            effective_from=date(2026, 6, 11),
        )

        segments = await economics_over(db_session, channel, date(2026, 6, 1), date(2026, 6, 30))

        assert [(e.origin, e.monthly_cost, lo, hi) for e, lo, hi in segments] == [
            ("channel_default", Decimal("5"), date(2026, 6, 1), date(2026, 6, 10)),
            ("economics_row", Decimal("50"), date(2026, 6, 11), date(2026, 6, 30)),
        ]

    async def test_two_changes_on_one_day_read_as_the_later(self, db_session, test_tenant) -> None:
        from app.services.channel_economics import economics_over

        channel = await _channel(db_session, test_tenant)
        for cost in ("10", "20"):
            await write_economics(
                db_session,
                test_tenant,
                channel,
                {"monthly_cost": Decimal(cost)},
                effective_from=date(2026, 6, 1),
            )

        segments = await economics_over(db_session, channel, date(2026, 6, 1), date(2026, 6, 30))

        assert [(e.monthly_cost, lo, hi) for e, lo, hi in segments] == [
            (Decimal("20"), date(2026, 6, 1), date(2026, 6, 30))
        ]

    async def test_the_new_levers_are_validated(self, db_session, test_tenant) -> None:
        from app.services.channel_economics import EconomicsMisconfigured

        channel = await _channel(db_session, test_tenant)
        for bad in (
            {"monthly_cost": Decimal("-1")},
            {"tax_remitter": "nobody"},
            {"currency_code": "POUNDS"},
        ):
            with pytest.raises(EconomicsMisconfigured):
                await write_economics(db_session, test_tenant, channel, bad)
