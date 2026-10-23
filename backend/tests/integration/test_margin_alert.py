"""Realised margin against plan, and the alert it raises (task T134).

FR-042: "the operator MUST be alerted when a product's realised margin
diverges from plan beyond a threshold they set", and US7 scenario 3 fixes what
the alert has to say -- **which lines moved**. A shortfall whose cause is named
is a decision an operator makes this afternoon; one that is not sends them
through three screens to find out whether it was the fee schedule or the
filament.

## Why this reads the same sale as the accuracy test

``settled`` comes from ``tests/integration/conftest.py``, the fixture
``test_realised_margin_accuracy.py`` reads. A divergence test built on its own
settled order would be comparing against a different plan, and the two files
would drift until one of them was quietly wrong about the same engine.

## The control, without which this proves nothing

``TestTheDivergenceIsMeasuredNotAsserted`` makes a run use three times the
filament and requires the divergence to **grow**. Without it, every assertion
here passes for an implementation that returned a constant: the planned margin
is right by construction, so a reader that echoed it would report zero
divergence for ever and look correct.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.fee_actual import FeeActual
from app.models.production_run import ProductionRun
from app.models.tenant_pricing_policy import TenantPricingPolicy
from app.models.user import UserRole
from app.services import margin_alert

# The settled order itself comes from `tests/integration/conftest.py`.
from tests.integration.conftest import (
    FEES_ACTUALLY_CHARGED,
    GRAMS_ACTUALLY_USED,
    reload_item,
)

pytestmark = pytest.mark.asyncio

URL = "/api/v1/reconciliation/margin-divergence"

#: Low enough that this fixture's real divergence passes it, so the threshold
#: is being read rather than assumed. The default is five points.
A_THRESHOLD_THIS_SALE_PASSES = Decimal("0.5")

#: High enough that nothing this fixture can produce reaches it.
A_THRESHOLD_NOTHING_REACHES = Decimal("500")


async def set_threshold(db_session, test_tenant, points: Decimal) -> None:
    """Put the operator's alert threshold at ``points``.

    The fixture's policy row is the one in force, and this is the operator
    setting their own threshold before any sale is judged -- not a rate change
    reaching back over history, which would have to supersede (FR-039).
    """
    row = (
        (
            await db_session.execute(
                select(TenantPricingPolicy).where(TenantPricingPolicy.tenant_id == test_tenant.id)
            )
        )
        .scalars()
        .first()
    )
    assert row is not None, "the fixture must have a policy row to set a threshold on"
    row.margin_alert_threshold_pct = points
    db_session.add(row)
    await db_session.commit()


# ---------------------------------------------------------------------------
# What the comparison is between
# ---------------------------------------------------------------------------


class TestThePlannedMarginComesFromTheSnapshot:
    async def test_it_is_the_margin_the_line_was_sold_at(
        self, db_session, test_tenant, settled
    ) -> None:
        # The snapshot is the plan (FR-036). Recomputed from its own frozen
        # parts rather than read back, because no percentage is stored.
        item = await reload_item(db_session, settled["order"])

        found = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        assert found.planned_margin_pct is not None
        assert found.planned_margin_pct > Decimal("0")
        assert found.margin_basis == "customer_total"

    async def test_the_two_percentages_are_on_one_basis(
        self, db_session, test_tenant, settled
    ) -> None:
        # FR-031b: two margins on different bases are two different questions,
        # and their difference is not a divergence.
        item = await reload_item(db_session, settled["order"])

        found = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        assert found.margin_basis == (item.margin_basis_at_sale or "customer_total")

    async def test_the_divergence_is_realised_less_planned_in_points(
        self, db_session, test_tenant, settled
    ) -> None:
        item = await reload_item(db_session, settled["order"])

        found = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        assert found.planned_margin_pct is not None
        assert found.realised_margin_pct is not None
        assert found.divergence_points == (
            found.realised_margin_pct - found.planned_margin_pct
        ).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# FR-042: the threshold is the operator's
# ---------------------------------------------------------------------------


class TestTheThresholdIsTheOperatorsOwn:
    async def test_a_line_past_the_threshold_alerts(self, db_session, test_tenant, settled) -> None:
        await set_threshold(db_session, test_tenant, A_THRESHOLD_THIS_SALE_PASSES)
        item = await reload_item(db_session, settled["order"])

        found = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        assert found.threshold_points == A_THRESHOLD_THIS_SALE_PASSES
        assert found.diverges, (
            f"{found.divergence_points} points should pass a "
            f"{A_THRESHOLD_THIS_SALE_PASSES}-point threshold"
        )

    async def test_the_same_line_inside_a_wider_threshold_does_not(
        self, db_session, test_tenant, settled
    ) -> None:
        # The same sale, the same figures: only the operator's own setting
        # differs. This is the pair that proves the threshold is read.
        await set_threshold(db_session, test_tenant, A_THRESHOLD_NOTHING_REACHES)
        item = await reload_item(db_session, settled["order"])

        found = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        assert found.threshold_points == A_THRESHOLD_NOTHING_REACHES
        assert not found.diverges
        # Still reported, with its figures: not alerting is not nothing to say.
        assert found.divergence_points is not None

    async def test_an_overshoot_alerts_as_well_as_a_shortfall(
        self, db_session, test_tenant, settled
    ) -> None:
        # An item earning far more than planned is as much a sign that the
        # estimate is wrong as one earning far less -- and it is the one that
        # silently loses sales to a price nobody needed to charge.
        await set_threshold(db_session, test_tenant, A_THRESHOLD_THIS_SALE_PASSES)
        await db_session.execute(delete(FeeActual))
        run = settled["run"]
        run.actual_total_weight_grams = Decimal("40")
        db_session.add(run)
        await db_session.commit()
        item = await reload_item(db_session, settled["order"])

        found = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        assert found.divergence_points is not None and found.divergence_points > 0
        assert found.diverges
        assert not found.shortfall


# ---------------------------------------------------------------------------
# US7 scenario 3: which lines moved
# ---------------------------------------------------------------------------


class TestTheAlertNamesTheLinesThatMoved:
    async def test_the_fee_line_is_named_when_the_statement_disagreed(
        self, db_session, test_tenant, settled
    ) -> None:
        # FR-041 exists because the planned fee and the statement disagree; on
        # a marketplace it is the line most likely to have moved.
        item = await reload_item(db_session, settled["order"])

        found = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        fees = [movement for movement in found.movements if movement.key == "fees"]
        assert fees, f"no fee movement among {[m.key for m in found.movements]}"
        assert fees[0].realised == FEES_ACTUALLY_CHARGED
        assert found.fees_source == "actual"

    async def test_the_material_line_is_named_when_the_run_used_more(
        self, db_session, test_tenant, settled
    ) -> None:
        item = await reload_item(db_session, settled["order"])

        found = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        material = [movement for movement in found.movements if movement.key == "material"]
        assert material, f"no material movement among {[m.key for m in found.movements]}"
        # 155 g actually used against 142 g planned: dearer, so positive.
        assert material[0].delta > 0

    async def test_the_heaviest_movement_comes_first(
        self, db_session, test_tenant, settled
    ) -> None:
        # The order is the point: an operator reads the top line and acts.
        item = await reload_item(db_session, settled["order"])

        found = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        deltas = [abs(movement.delta) for movement in found.movements]
        assert deltas == sorted(deltas, reverse=True)

    async def test_a_line_that_did_not_move_is_not_named(
        self, db_session, test_tenant, settled
    ) -> None:
        # Packaging has no observed counterpart on a run, so it stays as the
        # sale was costed. Naming it with a zero beside it would be noise.
        item = await reload_item(db_session, settled["order"])

        found = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        assert "packaging" not in [movement.key for movement in found.movements]

    async def test_with_no_run_no_cost_line_is_named(
        self, db_session, test_tenant, settled
    ) -> None:
        # Nothing was observed per line, so the honest statement is that no
        # *cost* line moved. The fee line survives: a reconciled statement
        # moves it without any run involved, which is the distinction the
        # alert has to keep.
        await db_session.execute(delete(ProductionRun))
        await db_session.commit()
        item = await reload_item(db_session, settled["order"])

        found = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        assert [movement.key for movement in found.movements] == ["fees"]
        assert found.gaps


# ---------------------------------------------------------------------------
# The control
# ---------------------------------------------------------------------------


class TestTheDivergenceIsMeasuredNotAsserted:
    """Without this, every assertion above passes for an implementation that
    echoed the snapshot -- which is the plan, and right by construction."""

    async def test_three_times_the_filament_widens_the_divergence(
        self, db_session, test_tenant, settled
    ) -> None:
        item = await reload_item(db_session, settled["order"])
        before = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        run = settled["run"]
        run.actual_total_weight_grams = GRAMS_ACTUALLY_USED * 3
        db_session.add(run)
        await db_session.commit()

        after = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        assert before.divergence_points is not None
        assert after.divergence_points is not None
        assert after.divergence_points < before.divergence_points
        material = [m for m in after.movements if m.key == "material"][0]
        assert material.delta > [m for m in before.movements if m.key == "material"][0].delta

    async def test_the_planned_figure_does_not_move_with_it(
        self, db_session, test_tenant, settled
    ) -> None:
        # FR-038: the plan is what the operator decided to sell at, and a
        # worse run does not change that decision after the fact.
        item = await reload_item(db_session, settled["order"])
        before = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        run = settled["run"]
        run.actual_total_weight_grams = GRAMS_ACTUALLY_USED * 3
        db_session.add(run)
        await db_session.commit()

        after = await margin_alert.divergence_for_item(db_session, test_tenant, item)

        assert after.planned_margin_pct == before.planned_margin_pct
        assert after.planned_profit == before.planned_profit


# ---------------------------------------------------------------------------
# Constitution V: nothing is written
# ---------------------------------------------------------------------------


class TestItWritesNothing:
    async def test_the_snapshot_is_unchanged(self, db_session, test_tenant, settled) -> None:
        item = await reload_item(db_session, settled["order"])
        before = (
            item.make_cost_at_sale,
            item.list_price_at_sale,
            item.margin_basis_at_sale,
            item.fees_json,
            item.cost_breakdown_json,
        )

        await margin_alert.divergences(db_session, test_tenant)
        await db_session.commit()

        after = await reload_item(db_session, settled["order"])
        assert (
            after.make_cost_at_sale,
            after.list_price_at_sale,
            after.margin_basis_at_sale,
            after.fees_json,
            after.cost_breakdown_json,
        ) == before

    async def test_the_sweep_writes_nothing_either(self, db_session, test_tenant, settled) -> None:
        from app.tasks.margin_alerts import sweep_tenant

        item = await reload_item(db_session, settled["order"])
        before = item.make_cost_at_sale

        await sweep_tenant(db_session, test_tenant)
        await db_session.commit()

        after = await reload_item(db_session, settled["order"])
        assert after.make_cost_at_sale == before


# ---------------------------------------------------------------------------
# The sweep that notices without being asked
# ---------------------------------------------------------------------------


class TestTheSweep:
    async def test_it_finds_the_diverging_line(self, db_session, test_tenant, settled) -> None:
        from app.tasks.margin_alerts import sweep_tenant

        await set_threshold(db_session, test_tenant, A_THRESHOLD_THIS_SALE_PASSES)

        found = await sweep_tenant(db_session, test_tenant)

        assert [row.order_item_id for row in found] == [
            (await reload_item(db_session, settled["order"])).id
        ]

    async def test_it_finds_nothing_inside_the_threshold(
        self, db_session, test_tenant, settled
    ) -> None:
        from app.tasks.margin_alerts import sweep_tenant

        await set_threshold(db_session, test_tenant, A_THRESHOLD_NOTHING_REACHES)

        assert await sweep_tenant(db_session, test_tenant) == []

    async def test_the_description_names_the_lines_that_moved(
        self, db_session, test_tenant, settled
    ) -> None:
        # The log line is the alert until a notifier is wired to it, so what it
        # says is part of the requirement, not a formatting detail.
        from app.tasks.margin_alerts import describe, sweep_tenant

        await set_threshold(db_session, test_tenant, A_THRESHOLD_THIS_SALE_PASSES)

        line = describe((await sweep_tenant(db_session, test_tenant))[0])

        assert "Settled product" in line
        assert "fees" in line
        assert "threshold" in line

    async def test_it_logs_the_divergence_at_warning(
        self, db_session, test_tenant, settled, caplog
    ) -> None:
        # Warning, not error: a divergence is a fact about the business, and an
        # error level would train the operator to ignore it.
        import logging

        from app.tasks.margin_alerts import sweep_tenant

        await set_threshold(db_session, test_tenant, A_THRESHOLD_THIS_SALE_PASSES)

        with caplog.at_level(logging.WARNING, logger="app.tasks.margin_alerts"):
            await sweep_tenant(db_session, test_tenant)

        assert any(
            record.levelno == logging.WARNING and "diverges" in record.getMessage()
            for record in caplog.records
        )


# ---------------------------------------------------------------------------
# GET /reconciliation/margin-divergence
# ---------------------------------------------------------------------------


class TestTheEndpoint:
    async def test_it_reports_the_settled_line_with_its_movements(
        self, client: AsyncClient, db_session, test_tenant, settled
    ) -> None:
        await set_threshold(db_session, test_tenant, A_THRESHOLD_THIS_SALE_PASSES)

        response = await client.get(URL)

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["alerting"] == 1
        assert body["threshold_points"] == "0.5000"
        row = body["divergences"][0]
        assert row["product_name"] == "Settled product"
        assert row["diverges"] is True
        assert "fees" in [movement["key"] for movement in row["movements"]]

    async def test_every_amount_crosses_the_wire_as_a_string(
        self, client: AsyncClient, db_session, test_tenant, settled
    ) -> None:
        # Constitution IV: a money figure as a JSON number is a float by the
        # time the console reads it.
        response = await client.get(URL)

        row = response.json()["divergences"][0]
        for key in (
            "planned_margin_pct",
            "realised_margin_pct",
            "divergence_points",
            "threshold_points",
            "planned_profit",
            "realised_profit",
        ):
            assert isinstance(row[key], str), f"{key} came back as {type(row[key])}"
        for movement in row["movements"]:
            for key in ("planned", "realised", "delta"):
                assert isinstance(movement[key], str)

    async def test_only_alerting_narrows_to_what_passed_the_threshold(
        self, client: AsyncClient, db_session, test_tenant, settled
    ) -> None:
        await set_threshold(db_session, test_tenant, A_THRESHOLD_NOTHING_REACHES)

        reported = await client.get(URL)
        alerting = await client.get(URL, params={"only_alerting": "true"})

        assert reported.json()["total"] == 1
        assert alerting.json()["total"] == 0
        # The threshold still comes back, so a console showing nothing can say
        # what it was measuring against.
        assert alerting.json()["threshold_points"] == "500.0000"

    async def test_an_unknown_product_reports_nothing_rather_than_everything(
        self, client: AsyncClient, settled
    ) -> None:
        from uuid import uuid4

        response = await client.get(URL, params={"product_id": str(uuid4())})

        assert response.status_code == 200
        assert response.json()["total"] == 0

    async def test_a_viewer_may_read_it(
        self, client: AsyncClient, db_session, test_tenant, settled, as_role
    ) -> None:
        # FR-007c: the threshold is monetary policy and is set elsewhere;
        # reading the consequence of it is open to every role.
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.get(URL)

        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_unauthenticated_is_a_401(
        self, unauthenticated_client: AsyncClient, settled
    ) -> None:
        response = await unauthenticated_client.get(URL)

        assert response.status_code == 401

    async def test_a_line_sold_before_the_snapshot_existed_is_not_reported(
        self, client: AsyncClient, db_session, test_tenant, settled
    ) -> None:
        # A line with no plan has nothing to diverge from, and reporting it as
        # a total shortfall would be an artefact of the migration rather than a
        # finding about the business.
        item = await reload_item(db_session, settled["order"])
        item.make_cost_at_sale = None
        db_session.add(item)
        await db_session.commit()

        response = await client.get(URL)

        assert response.json()["total"] == 0
