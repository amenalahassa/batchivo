"""The observed-data loop has a caller, and it is reachable (task T148).

FR-042 describes a loop: observed outcomes update the estimates used for future
pricing, automatically within the operator's threshold and as a held proposal
beyond it. Tier 4 built every piece of it — `variance_service`, the proposals,
the accept and reject endpoints, the two ingestion modules — and then left the
arc open. `app/tasks/telemetry.py` and `app/tasks/power.py` held plain async
functions with no `@celery_app.task`, were absent from `celery_app.include` and
from `beat_schedule`, and had no caller anywhere in `app/`. Since
`consider_outcomes` was reachable only through them, a running system could
never revise an estimate, never raise a proposal for the review list T106
built, and never give a cost line an observed origin — so SC-010's "at least
70% of the make-cost lines carry an observed origin" was unreachable by
construction, not by a shortage of printers.

These tests are deliberately split in two:

- **Registration** is checked against the Celery app, because a module nobody
  imports is the exact defect this task fixes and no behavioural test can see
  it: `learn_for_tenant` worked perfectly well while being unreachable.
- **The sweep** is checked end to end on real runs, because registration
  without a working sweep is the same defect with a decorator on it.

## The control

`test_a_single_run_moves_nothing` is what stops this passing for an
implementation that updates on any evidence at all. The operator's minimum
number of outcomes is a setting (FR-042a), and one run is not five.
"""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core import clock
from app.models.model import Model
from app.models.pricing_input_provenance import PricingInputProvenance
from app.models.production_run import ProductionRun, ProductionRunItem
from app.models.tenant import Tenant
from app.models.tenant_pricing_policy import TenantPricingPolicy

# The async classes carry the mark themselves. A module-level one would warn
# on every synchronous registration test below, and a warning nobody can act on
# trains a reader to skim the ones they can.


# ===========================================================================
# Registration — the defect a behavioural test cannot see
# ===========================================================================


class TestTheIngestionModulesAreRegistered:
    def test_the_celery_app_includes_both_of_them(self) -> None:
        from app.tasks.celery_app import celery_app

        include = list(celery_app.conf.include or [])
        assert "app.tasks.telemetry" in include, (
            "a module Celery does not import has no registered tasks, however "
            "many decorators it carries"
        )
        assert "app.tasks.power" in include

    def test_the_tasks_exist_under_the_names_something_can_dispatch(self) -> None:
        from app.tasks import power, telemetry  # noqa: F401  (registers them)
        from app.tasks.celery_app import celery_app

        for name in ("telemetry.learn", "telemetry.ingest_run", "power.ingest"):
            assert name in celery_app.tasks, f"{name} is not dispatchable"

    def test_the_learning_sweep_is_scheduled(self) -> None:
        """FR-042 is a loop, and a loop nothing turns is an arc."""
        from app.tasks.celery_app import celery_app

        scheduled = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
        assert "telemetry.learn" in scheduled

    def test_the_learning_sweep_runs_before_the_margin_sweep(self) -> None:
        """Otherwise the morning's divergence report is read against estimates
        that do not yet know what last night's runs showed."""
        from app.tasks.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule
        learn = next(e for e in schedule.values() if e["task"] == "telemetry.learn")
        alerts = next(e for e in schedule.values() if e["task"] == "margin_alerts.sweep")

        assert min(learn["schedule"].hour) < min(alerts["schedule"].hour)

    def test_nothing_without_a_source_is_scheduled(self) -> None:
        """A schedule over an empty source reads in the log as a working
        integration. No store of plug readings exists, so `power.ingest` takes
        its readings as an argument and waits to be dispatched."""
        from app.tasks.celery_app import celery_app

        scheduled = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
        assert "power.ingest" not in scheduled
        assert "telemetry.ingest_run" not in scheduled


# ===========================================================================
# The sweep, on real runs
# ===========================================================================


async def _policy(db, tenant: Tenant, **overrides) -> TenantPricingPolicy:
    """The tenant's thresholds, set to something a test can reason about."""
    row = (
        await db.execute(
            select(TenantPricingPolicy).where(
                TenantPricingPolicy.tenant_id == tenant.id,
                TenantPricingPolicy.effective_to.is_(None),
            )
        )
    ).scalar_one_or_none()

    if row is None:
        row = TenantPricingPolicy(
            id=uuid4(),
            tenant_id=tenant.id,
            print_labor_rate=Decimal("25.00"),
            finishing_labor_rate=Decimal("25.00"),
            overhead_method="per_machine_hour",
            overhead_monthly_pool=Decimal("180.00"),
            expected_monthly_machine_hours=Decimal("600"),
            margin_basis="customer_total",
            effective_from=clock.today() - timedelta(days=365),
        )
        db.add(row)

    row.min_outcomes_before_auto_update = overrides.get("min_outcomes", 3)
    row.estimate_divergence_threshold_pct = overrides.get("threshold_pct", Decimal("25"))
    await db.commit()
    return row


async def _completed_run(
    db,
    tenant: Tenant,
    model: Model,
    *,
    duration_hours: Decimal,
    run_number: str,
) -> ProductionRun:
    """One finished run, with the duration the operator recorded."""
    run = ProductionRun(
        tenant_id=tenant.id,
        run_number=run_number,
        status="completed",
        started_at=clock.now() - timedelta(hours=float(duration_hours)),
        completed_at=clock.now(),
        duration_hours=duration_hours,
        total_plates=1,
    )
    db.add(run)
    await db.flush()
    db.add(
        ProductionRunItem(
            production_run_id=run.id,
            model_id=model.id,
            quantity=1,
            successful_quantity=1,
        )
    )
    await db.commit()
    return run


async def _origin(db, model: Model, field_name: str) -> PricingInputProvenance | None:
    return (
        await db.execute(
            select(PricingInputProvenance).where(
                PricingInputProvenance.tenant_id == model.tenant_id,
                PricingInputProvenance.entity_type == "model",
                PricingInputProvenance.entity_id == model.id,
                PricingInputProvenance.field_name == field_name,
            )
        )
    ).scalar_one_or_none()


@pytest.mark.asyncio
class TestTheSweepLearnsFromCompletedRuns:
    async def test_enough_agreeing_runs_move_the_estimate(
        self, db_session, test_tenant: Tenant, test_model: Model
    ) -> None:
        """FR-042a: a rolling average, once the minimum is reached."""
        from app.tasks.telemetry import learn_for_tenant

        await _policy(db_session, test_tenant, min_outcomes=3)
        # The model estimates 60 minutes; three runs took 66 (1.1 h), which is
        # 10% out and well inside the divergence threshold.
        for index in range(3):
            await _completed_run(
                db_session,
                test_tenant,
                test_model,
                duration_hours=Decimal("1.1"),
                run_number=f"SWEEP-{index}",
            )

        decisions = await learn_for_tenant(db_session, test_tenant)
        await db_session.commit()

        key = f"{test_model.id}.print_time_minutes"
        assert key in decisions, "the sweep must reach the model its runs name"
        assert decisions[key].applied, decisions[key].reason

        await db_session.refresh(test_model)
        assert test_model.print_time_minutes == 66

    async def test_an_applied_update_marks_the_figure_observed(
        self, db_session, test_tenant: Tenant, test_model: Model
    ) -> None:
        """FR-042f, and the reason SC-010 is reachable at all: an origin of
        `observed` is what the breakdown counts as evidence."""
        from app.tasks.telemetry import learn_for_tenant

        await _policy(db_session, test_tenant, min_outcomes=3)
        for index in range(3):
            await _completed_run(
                db_session,
                test_tenant,
                test_model,
                duration_hours=Decimal("1.1"),
                run_number=f"OBSERVED-{index}",
            )

        await learn_for_tenant(db_session, test_tenant)
        await db_session.commit()

        origin = await _origin(db_session, test_model, "print_time_minutes")
        assert origin is not None
        assert origin.source == "observed"
        assert origin.as_of is not None

    async def test_a_single_run_moves_nothing(
        self, db_session, test_tenant: Tenant, test_model: Model
    ) -> None:
        """The control. One reading is not evidence, and how much is enough is
        the operator's setting, not this sweep's (FR-042a)."""
        from app.tasks.telemetry import learn_for_tenant

        await _policy(db_session, test_tenant, min_outcomes=5)
        await _completed_run(
            db_session,
            test_tenant,
            test_model,
            duration_hours=Decimal("1.1"),
            run_number="LONELY-0",
        )
        before = test_model.print_time_minutes

        decisions = await learn_for_tenant(db_session, test_tenant)
        await db_session.commit()

        key = f"{test_model.id}.print_time_minutes"
        assert not decisions[key].applied
        await db_session.refresh(test_model)
        assert test_model.print_time_minutes == before

    async def test_a_wildly_divergent_reading_is_held_not_applied(
        self, db_session, test_tenant: Tenant, test_model: Model
    ) -> None:
        """FR-042b: an outlier of that size usually means a faulty measurement,
        so it becomes a proposal and pricing keeps the current estimate."""
        from app.tasks.telemetry import learn_for_tenant

        await _policy(db_session, test_tenant, min_outcomes=3, threshold_pct=Decimal("20"))
        # The model estimates 60 minutes; these runs claim 600.
        for index in range(3):
            await _completed_run(
                db_session,
                test_tenant,
                test_model,
                duration_hours=Decimal("10"),
                run_number=f"OUTLIER-{index}",
            )

        decisions = await learn_for_tenant(db_session, test_tenant)
        await db_session.commit()

        decision = decisions[f"{test_model.id}.print_time_minutes"]
        assert not decision.applied
        assert decision.proposal is not None, "an outlier must reach the review list"

        await db_session.refresh(test_model)
        assert test_model.print_time_minutes == 60, (
            "pricing keeps the current estimate while a revision is pending (FR-042e)"
        )

    async def test_an_unfinished_run_is_not_evidence(
        self, db_session, test_tenant: Tenant, test_model: Model
    ) -> None:
        """An in-progress run's duration is how long it has been going."""
        from app.tasks.telemetry import learn_for_tenant

        await _policy(db_session, test_tenant, min_outcomes=1)
        run = await _completed_run(
            db_session,
            test_tenant,
            test_model,
            duration_hours=Decimal("1.1"),
            run_number="OPEN-0",
        )
        run.status = "in_progress"
        await db_session.commit()

        decisions = await learn_for_tenant(db_session, test_tenant)

        assert decisions == {}, "only a completed run says how long something took"

    async def test_a_tenant_with_no_runs_is_not_an_error(
        self, db_session, test_tenant: Tenant
    ) -> None:
        from app.tasks.telemetry import learn_for_tenant

        assert await learn_for_tenant(db_session, test_tenant) == {}

    async def test_the_sweep_does_not_reprice_anything(
        self, db_session, test_tenant: Tenant, test_model: Model
    ) -> None:
        """Telemetry proposes; it does not reprice. An estimate may move — that
        is the whole point — but no price, margin or stored figure does."""
        from app.tasks.telemetry import learn_for_tenant

        await _policy(db_session, test_tenant, min_outcomes=3)
        for index in range(3):
            await _completed_run(
                db_session,
                test_tenant,
                test_model,
                duration_hours=Decimal("1.1"),
                run_number=f"NOREPRICE-{index}",
            )
        before_rate = test_model.labor_rate_override
        before_overhead = test_model.overhead_percentage

        await learn_for_tenant(db_session, test_tenant)
        await db_session.commit()
        await db_session.refresh(test_model)

        assert test_model.labor_rate_override == before_rate
        assert test_model.overhead_percentage == before_overhead

    async def test_an_operator_decision_is_never_moved_by_the_sweep(
        self, db_session, test_tenant: Tenant, test_model: Model
    ) -> None:
        """FR-042g. The sweep learns measurements, never decisions — which is
        why `labor_rate_override` is not on `LEARNABLE_FROM_RUNS` at all."""
        from app.tasks.telemetry import LEARNABLE_FROM_RUNS

        learnable = {field.field_name for field in LEARNABLE_FROM_RUNS}
        assert "labor_rate_override" not in learnable
        assert "overhead_percentage" not in learnable


class TestThePowerEntryPoint:
    def test_it_drops_an_unreadable_reading_rather_than_the_batch(self) -> None:
        """One bad line from a plug must not discard the readings beside it."""
        from app.tasks.power import _parse

        parsed = _parse(
            [
                ["plug-1", "95.00", "2026-10-01"],
                ["plug-1", "not a number", "2026-10-02"],
                ["plug-1", "96.00", None],
            ]
        )

        assert len(parsed) == 2
        assert parsed[0][1] == Decimal("95.00")

    def test_a_wattage_crosses_the_broker_as_a_string(self) -> None:
        """A draw is multiplied by an electricity rate, so it must not arrive
        as a float (Constitution IV)."""
        from app.tasks.power import _parse

        parsed = _parse([["plug-1", "95.4", "2026-10-01"]])

        assert parsed[0][1] == Decimal("95.4")
        assert isinstance(parsed[0][1], Decimal)
