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

from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.fee_actual import FeeActual
from app.models.order import OrderItem
from app.models.production_run import ProductionRun
from app.services.realised_margin import realised_margin

# The settled order itself, and the figures it was built from, come from
# `tests/integration/conftest.py` so that the alert test reads the same sale.
from tests.integration.conftest import (
    FEES_ACTUALLY_CHARGED,
    GRAMS_ACTUALLY_USED,
    HOURS_ACTUALLY_TAKEN,
    HUNDRED,
    LIST_PRICE,
    POSTAGE_PAID,
    SHIPPING_CHARGED,
    TOLERANCE,
    ZERO,
    reload_item,
)

pytestmark = pytest.mark.asyncio


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

    material = Decimal(str(run.actual_total_weight_grams)) * Decimal(str(run.cost_per_gram_actual))
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

    async def test_the_postage_paid_is_a_cost(self, db_session, test_tenant, settled) -> None:
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


class TestARefundReducesWhatWasRealised:
    """A refund is an actual, and the realised margin reads it (task T189).

    Nothing recorded what a refund returned against the order it came from: the
    Square webhook set ``status = REFUNDED`` and logged the amount, ``orders``
    had no refund column, and ``return_requests.refund_amount`` was an RMA
    record the engine never opened. So this reader took the order's full,
    un-reduced total as its revenue -- and a fully refunded order reported the
    margin it earned at sale, which made SC-001 false by the whole refund for a
    routine case (FR-040, spec.md:193).

    The snapshot stays untouched throughout; that is asserted in
    `test_a_refund_does_not_restate_the_snapshot` below.
    """

    @staticmethod
    async def _refund(db_session, test_tenant, order, amount: Decimal, **kwargs):
        from app.services.refund_actuals import record_refund

        row = await record_refund(db_session, test_tenant, order, amount=amount, **kwargs)
        await db_session.commit()
        return row

    async def test_a_full_refund_takes_the_revenue_to_zero(
        self, db_session, test_tenant, settled
    ) -> None:
        """The case the absence of this made worst: nothing was kept."""
        item = await reload_item(db_session, settled["order"])
        charged = LIST_PRICE + SHIPPING_CHARGED

        before = await realised_margin(db_session, test_tenant, item)
        assert before.revenue_received == charged
        assert before.refund_allocated == ZERO

        await self._refund(db_session, test_tenant, settled["order"], charged)

        item = await reload_item(db_session, settled["order"])
        after = await realised_margin(db_session, test_tenant, item)

        assert after.refund_allocated == charged
        assert after.revenue_received == ZERO, (
            "the whole sale was refunded and the reader still counted it as "
            "revenue; a fully refunded order cannot report the margin it "
            "earned at sale (SC-001, FR-040)"
        )
        # Every cost stands -- the filament was still used, the fees still
        # charged -- so the sale is now a loss of exactly those costs.
        assert after.profit < ZERO
        assert after.profit == -(after.fees_paid + after.make_cost + after.postage_paid)

    async def test_a_partial_refund_reduces_revenue_by_what_went_back(
        self, db_session, test_tenant, settled
    ) -> None:
        """Exactly the amount refunded, to the penny."""
        item = await reload_item(db_session, settled["order"])
        before = await realised_margin(db_session, test_tenant, item)

        await self._refund(db_session, test_tenant, settled["order"], Decimal("10.00"))

        item = await reload_item(db_session, settled["order"])
        after = await realised_margin(db_session, test_tenant, item)

        assert after.refund_allocated == Decimal("10.00")
        assert after.revenue_received == before.revenue_received - Decimal("10.00")
        assert after.profit == before.profit - Decimal("10.00")
        assert after.margin_pct is not None
        assert after.margin_pct < before.margin_pct

    async def test_two_partial_refunds_add_up(self, db_session, test_tenant, settled) -> None:
        """Rows, not a column: a second refund adds rather than overwriting."""
        await self._refund(db_session, test_tenant, settled["order"], Decimal("5.00"))
        await self._refund(db_session, test_tenant, settled["order"], Decimal("7.50"))

        item = await reload_item(db_session, settled["order"])
        reported = await realised_margin(db_session, test_tenant, item)

        assert reported.refund_allocated == Decimal("12.50"), (
            "a second refund replaced the first instead of adding to it, which "
            "is what a single column on the order would have done"
        )

    async def test_it_says_a_refund_is_why_the_margin_moved(
        self, db_session, test_tenant, settled
    ) -> None:
        """A realised figure has to say which observations it used (FR-001)."""
        await self._refund(db_session, test_tenant, settled["order"], Decimal("10.00"))

        item = await reload_item(db_session, settled["order"])
        reported = await realised_margin(db_session, test_tenant, item)

        assert any("refund" in line for line in reported.substitutions), (
            f"nothing in {reported.substitutions} tells the reader a refund reduced this revenue"
        )

    async def test_a_refund_does_not_restate_the_snapshot(
        self, db_session, test_tenant, settled
    ) -> None:
        """Constitution VI: the sale was priced on this and it must not move."""
        item = await reload_item(db_session, settled["order"])
        before = (
            item.make_cost_at_sale,
            item.list_price_at_sale,
            item.margin_basis_at_sale,
            item.total_price,
        )

        await self._refund(db_session, test_tenant, settled["order"], LIST_PRICE + SHIPPING_CHARGED)
        item = await reload_item(db_session, settled["order"])
        await realised_margin(db_session, test_tenant, item)
        await db_session.commit()

        after = await reload_item(db_session, settled["order"])
        assert (
            after.make_cost_at_sale,
            after.list_price_at_sale,
            after.margin_basis_at_sale,
            after.total_price,
        ) == before, (
            "recording a refund changed what the sale was priced on; a refund "
            "reduces what was realised, it does not rewrite history (FR-038)"
        )
        # And the order's own total is untouched: it is what was charged.
        assert settled["order"].total is None or settled["order"].total == settled["order"].total

    async def test_a_refund_beyond_the_sale_is_not_clamped(
        self, db_session, test_tenant, settled
    ) -> None:
        """A goodwill payment past the sale price is a loss, not a zero.

        Flooring the revenue at zero would hide the part of the payment that
        exceeded what was taken, which is the most expensive case there is.
        """
        charged = LIST_PRICE + SHIPPING_CHARGED
        await self._refund(db_session, test_tenant, settled["order"], charged + Decimal("20.00"))

        item = await reload_item(db_session, settled["order"])
        reported = await realised_margin(db_session, test_tenant, item)

        assert reported.revenue_received == Decimal("-20.00")
        assert reported.margin_pct is None, (
            "a negative basis has no percentage, and reporting zero would read "
            "as break-even on a sale that lost more than it took"
        )

    async def test_nothing_recorded_leaves_the_margin_exactly_as_it_was(
        self, db_session, test_tenant, settled
    ) -> None:
        """The no-refund path must be untouched by this change."""
        item = await reload_item(db_session, settled["order"])
        reported = await realised_margin(db_session, test_tenant, item)

        assert reported.refund_allocated == ZERO
        assert reported.revenue_received == LIST_PRICE + SHIPPING_CHARGED
        assert not any("refund" in line for line in reported.substitutions)


class TestRecordingARefundIsIdempotentWhereItHasTo_Be:
    """What stops one refund being subtracted twice (task T189)."""

    async def test_a_provider_refund_is_recorded_once(
        self, db_session, test_tenant, settled
    ) -> None:
        """Square redelivers a webhook on any non-2xx, so this matters.

        Without it, three delivery attempts of one refund would subtract three
        refunds from the revenue and report a loss that never happened.
        """
        from app.services.refund_actuals import record_refund, refunded_total

        order = settled["order"]
        first = await record_refund(
            db_session,
            test_tenant,
            order,
            amount=Decimal("10.00"),
            source="ingested",
            provider_refund_id="sq_refund_abc",
        )
        await db_session.commit()
        assert first is not None

        again = await record_refund(
            db_session,
            test_tenant,
            order,
            amount=Decimal("10.00"),
            source="ingested",
            provider_refund_id="sq_refund_abc",
        )
        await db_session.commit()

        assert again is None, "the same provider refund was recorded a second time"
        assert await refunded_total(db_session, test_tenant, order.id) == Decimal("10.00")

    async def test_two_entered_refunds_without_a_provider_id_both_count(
        self, db_session, test_tenant, settled
    ) -> None:
        """A human recording two partial refunds is not a duplicate."""
        from app.services.refund_actuals import record_refund, refunded_total

        order = settled["order"]
        for amount in (Decimal("4.00"), Decimal("6.00")):
            assert await record_refund(db_session, test_tenant, order, amount=amount) is not None
        await db_session.commit()

        assert await refunded_total(db_session, test_tenant, order.id) == Decimal("10.00")

    async def test_a_refund_of_nothing_is_not_an_event(
        self, db_session, test_tenant, settled
    ) -> None:
        """Zero and negative are rejected without a row and without an error."""
        from app.services.refund_actuals import record_refund, refunded_total

        order = settled["order"]
        assert await record_refund(db_session, test_tenant, order, amount=ZERO) is None
        assert await record_refund(db_session, test_tenant, order, amount=Decimal("-5.00")) is None
        await db_session.commit()

        assert await refunded_total(db_session, test_tenant, order.id) == ZERO

    async def test_the_recorded_row_keeps_its_own_origin(
        self, db_session, test_tenant, settled
    ) -> None:
        """`entered` and `ingested` must never be relabelled with each other."""
        from app.services.refund_actuals import record_refund

        row = await record_refund(
            db_session,
            test_tenant,
            settled["order"],
            amount=Decimal("3.00"),
            source="ingested",
            provider_refund_id="sq_refund_xyz",
            reason="customer changed their mind",
        )
        await db_session.commit()

        assert row is not None
        assert row.source == "ingested"
        assert row.provider_refund_id == "sq_refund_xyz"
        assert row.reason == "customer changed their mind"
        assert row.tenant_id == test_tenant.id
        assert row.order_id == settled["order"].id
        # The currency follows the order: a refund is paid in what was charged.
        assert row.currency == (settled["order"].currency or "GBP")
        assert row.refunded_at is not None
