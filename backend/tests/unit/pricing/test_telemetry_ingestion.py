"""Telemetry feeding the estimates (T110, FR-042, SC-010).

What a printer reports is the only cheap source of evidence this system has.
Every figure it can replace -- the weight of a part, the hours a plate occupied
a machine, the watts the machine actually draws -- is otherwise a guess the
operator typed once and never revisited.

So the four behaviours pinned here are the four ways that pipeline can go
wrong:

1. **A reading reaches the run.** Grams and print hours from the machine land
   on the production run, where variance analysis and the learning mechanism
   can reach them.
2. **A silent machine falls back to the slicer.** When the printer reports
   nothing, the 3MF metadata the operator already uploaded supplies the
   figures.

   It fills the run's **estimate** columns, never the actual ones, and that is
   a deliberate reading of the task. A slicer prediction is a prediction: put
   in `actual_total_weight_grams` it would destroy the one comparison the
   production run exists to make, and it would let the learning mechanism
   relabel a guess as an observation -- which is exactly what FR-001 and
   Constitution VI forbid. The fallback supplies figures; it does not
   manufacture evidence.
3. **An offline printer changes nothing.** Not the run, not the estimate, not
   the provenance. A machine that cannot be reached is not evidence of
   anything, and the dangerous failure is an ingestion pass that treats
   "nothing came back" as "nothing was used".
4. **A smart plug moves the power draw, as an observation.** `measured_watts`
   is the one input where a cheap sensor beats any estimate, and once it moves
   the figure must say it came from a machine rather than from a person.

Outcomes always go through `variance_service`, never straight onto the field.
That is what keeps a tenfold reading -- a plug reporting kilowatts as watts --
from silently repricing a catalogue (FR-042b).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core import clock
from app.models.model import Model
from app.models.pricing_input_provenance import PricingInputProvenance
from app.models.printer import Printer
from app.models.production_run import ProductionRun
from app.services.printer_adapter import JobActuals, PrinterAdapterState
from app.services.provenance import record_origin
from app.tasks.power import ingest_power_readings
from app.tasks.telemetry import ingest_run_actuals, learn_from_runs

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 6, 15)
PLATE_MINUTES = 570
PLATE_HOURS = Decimal("9.5")
PART_GRAMS = Decimal("142")


@pytest.fixture(autouse=True)
def _pinned_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold "today" still for every test (T264).

    ``TODAY`` used to be ``clock.today()`` at import, so a run that crossed
    midnight UTC compared yesterday's date with the code's today. The code
    reads the date through ``clock.now``, so pinning that pins both sides.
    """
    monkeypatch.setattr(
        clock, "now", lambda: datetime.combine(TODAY, time(12, 0), tzinfo=timezone.utc)
    )


# ---------------------------------------------------------------------------
# Stand-in machines
#
# Each one pins a boundary rather than imitating a printer. The protocol is
# structural (`PrinterAdapter` is a Protocol), so none of these inherit
# anything -- which is the point: a telemetry source is anything that can
# answer, including a device nobody has written an adapter for yet.
# ---------------------------------------------------------------------------


@dataclass
class ReportingPrinter:
    """A machine that reports what the finished job actually used."""

    grams: Optional[Decimal] = PART_GRAMS + Decimal("3")
    print_hours: Optional[Decimal] = PLATE_HOURS
    status: str = "idle"
    status_calls: int = 0
    actuals_calls: int = 0

    async def get_status(self) -> PrinterAdapterState:
        self.status_calls += 1
        return PrinterAdapterState(status=self.status)

    async def get_job_actuals(self) -> JobActuals:
        self.actuals_calls += 1
        return JobActuals(grams=self.grams, print_hours=self.print_hours)


@dataclass
class OfflinePrinter:
    """A machine nobody can reach.

    It still answers `get_status`, because that is how an adapter reports
    being offline. `get_job_actuals` raises: anything that calls it after
    reading the status has ignored the status, and this makes that loud rather
    than letting a zero through.
    """

    status_calls: int = 0

    async def get_status(self) -> PrinterAdapterState:
        self.status_calls += 1
        return PrinterAdapterState(status="offline")

    async def get_job_actuals(self) -> JobActuals:  # pragma: no cover - must not run
        raise AssertionError("an offline printer must not be asked for actuals")


@dataclass
class SilentPrinter:
    """Reachable, but reports no usage figures.

    The common real case: a printer whose firmware exposes progress and
    temperatures and nothing about filament. It is not offline, so the run is
    still processed -- from the slicer instead.
    """

    async def get_status(self) -> PrinterAdapterState:
        return PrinterAdapterState(status="idle", progress_percent=100.0)

    async def get_job_actuals(self) -> JobActuals:
        return JobActuals(grams=None, print_hours=None)


@dataclass
class UnreachablePrinter:
    """An adapter whose transport fails outright.

    A connection error is not a reading of zero, and the ingestion pass must
    survive one machine being down without losing the rest of the sweep.
    """

    async def get_status(self) -> PrinterAdapterState:
        raise ConnectionError("mqtt: connection refused")


@dataclass
class SlicerMetadata:
    """What `parse_3mf_metadata` hands back, reduced to the two fields used."""

    filament_weight_grams: Optional[float] = None
    print_time_minutes: Optional[int] = None
    plate_count: int = 1


# ---------------------------------------------------------------------------
# The world
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def model(db_session, test_tenant) -> Model:
    """An item whose print time is an estimate somebody typed."""
    row = Model(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku=f"TELEM-{uuid4().hex[:8]}",
        name="Instrumented part",
        print_time_minutes=PLATE_MINUTES,
        prints_per_plate=1,
        waste_grams=Decimal("3"),
        expected_yield=Decimal("0.92"),
        failure_mode="per_part",
        is_active=True,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest_asyncio.fixture
async def printer(db_session, test_tenant) -> Printer:
    """A machine whose power draw starts as an assumption."""
    row = Printer(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Instrumented printer",
        manufacturer="Bambu Lab",
        model="A1 Mini",
        purchase_price=Decimal("1100.00"),
        expected_lifetime_hours=6000,
        maintenance_reserve_total=Decimal("220.00"),
        measured_watts=Decimal("95"),
        is_active=True,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def make_run(db_session, test_tenant, printer: Printer, **overrides) -> ProductionRun:
    """A finished run with nothing recorded against it yet."""
    started = datetime.now(timezone.utc) - timedelta(hours=10)
    defaults = dict(
        id=uuid4(),
        tenant_id=test_tenant.id,
        printer_id=printer.id,
        run_number=f"TEL-{uuid4().hex[:6]}",
        started_at=started,
        completed_at=started + timedelta(hours=10),
        status="completed",
        total_plates=1,
        completed_plates=1,
    )
    defaults.update(overrides)
    row = ProductionRun(**defaults)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def origin_of(db_session, test_tenant, entity_type, entity_id, field_name):
    return (
        await db_session.execute(
            select(PricingInputProvenance).where(
                PricingInputProvenance.tenant_id == test_tenant.id,
                PricingInputProvenance.entity_type == entity_type,
                PricingInputProvenance.entity_id == entity_id,
                PricingInputProvenance.field_name == field_name,
            )
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# 1. A reading reaches the run
# ---------------------------------------------------------------------------


class TestTelemetryReachesTheRun:
    async def test_it_writes_the_actual_grams(self, db_session, test_tenant, printer) -> None:
        run = await make_run(db_session, test_tenant, printer)
        machine = ReportingPrinter(grams=Decimal("145"))

        await ingest_run_actuals(db_session, test_tenant, run, adapter=machine)

        assert run.actual_total_weight_grams == Decimal("145")

    async def test_it_writes_the_actual_print_hours(self, db_session, test_tenant, printer) -> None:
        run = await make_run(db_session, test_tenant, printer)
        machine = ReportingPrinter(print_hours=Decimal("9.5"))

        await ingest_run_actuals(db_session, test_tenant, run, adapter=machine)

        assert run.duration_hours == Decimal("9.5")

    async def test_it_names_the_machine_as_the_source(
        self, db_session, test_tenant, printer
    ) -> None:
        # A figure whose source is unknown cannot be learned from, so the
        # result says where it came from rather than leaving the caller to
        # infer it from which columns moved.
        run = await make_run(db_session, test_tenant, printer)

        result = await ingest_run_actuals(db_session, test_tenant, run, adapter=ReportingPrinter())

        assert result.source == "telemetry"
        assert result.written

    async def test_it_leaves_the_estimates_alone(self, db_session, test_tenant, printer) -> None:
        # The run exists to compare the two. Overwriting the estimate with the
        # actual would make every variance zero.
        run = await make_run(
            db_session,
            test_tenant,
            printer,
            estimated_total_weight_grams=Decimal("145"),
            estimated_print_time_hours=PLATE_HOURS,
        )

        await ingest_run_actuals(
            db_session,
            test_tenant,
            run,
            adapter=ReportingPrinter(grams=Decimal("151"), print_hours=Decimal("10.25")),
        )

        assert run.estimated_total_weight_grams == Decimal("145")
        assert run.estimated_print_time_hours == PLATE_HOURS

    async def test_it_does_not_overwrite_a_figure_already_recorded(
        self, db_session, test_tenant, printer
    ) -> None:
        # Somebody weighed the plate. A later sweep must not quietly replace a
        # hand measurement with a machine's guess at the same thing.
        run = await make_run(
            db_session, test_tenant, printer, actual_total_weight_grams=Decimal("150")
        )

        result = await ingest_run_actuals(
            db_session, test_tenant, run, adapter=ReportingPrinter(grams=Decimal("145"))
        )

        assert run.actual_total_weight_grams == Decimal("150")
        assert "actual_total_weight_grams" not in result.written

    async def test_it_writes_the_half_it_was_given(self, db_session, test_tenant, printer) -> None:
        # A machine reporting time but not weight is common, and the time is
        # still worth having.
        run = await make_run(db_session, test_tenant, printer)

        result = await ingest_run_actuals(
            db_session,
            test_tenant,
            run,
            adapter=ReportingPrinter(grams=None, print_hours=Decimal("9.5")),
        )

        assert run.duration_hours == Decimal("9.5")
        assert run.actual_total_weight_grams is None
        assert result.source == "telemetry"

    async def test_it_refuses_a_negative_reading(self, db_session, test_tenant, printer) -> None:
        # A sensor fault, not a measurement.
        run = await make_run(db_session, test_tenant, printer)

        result = await ingest_run_actuals(
            db_session,
            test_tenant,
            run,
            adapter=ReportingPrinter(grams=Decimal("-5"), print_hours=Decimal("0")),
        )

        assert run.actual_total_weight_grams is None
        assert run.duration_hours is None
        assert not result.written

    async def test_it_asks_the_status_before_the_figures(
        self, db_session, test_tenant, printer
    ) -> None:
        run = await make_run(db_session, test_tenant, printer)
        machine = ReportingPrinter()

        await ingest_run_actuals(db_session, test_tenant, run, adapter=machine)

        assert machine.status_calls == 1
        assert machine.actuals_calls == 1


# ---------------------------------------------------------------------------
# 2. The slicer is the fallback
# ---------------------------------------------------------------------------


class TestTheSlicerIsTheFallback:
    async def test_it_fills_the_estimate_from_the_3mf(
        self, db_session, test_tenant, printer
    ) -> None:
        run = await make_run(db_session, test_tenant, printer)

        result = await ingest_run_actuals(
            db_session,
            test_tenant,
            run,
            adapter=SilentPrinter(),
            slicer_metadata=SlicerMetadata(
                filament_weight_grams=145.0, print_time_minutes=PLATE_MINUTES
            ),
        )

        assert run.estimated_total_weight_grams == Decimal("145")
        assert run.estimated_print_time_hours == PLATE_HOURS
        assert result.source == "slicer"

    async def test_it_never_calls_a_slicer_figure_an_actual(
        self, db_session, test_tenant, printer
    ) -> None:
        # The line this file exists to hold. A prediction in an `actual_`
        # column destroys the comparison and lets a guess be learned from as
        # though a machine had measured it.
        run = await make_run(db_session, test_tenant, printer)

        await ingest_run_actuals(
            db_session,
            test_tenant,
            run,
            adapter=SilentPrinter(),
            slicer_metadata=SlicerMetadata(
                filament_weight_grams=145.0, print_time_minutes=PLATE_MINUTES
            ),
        )

        assert run.actual_total_weight_grams is None
        assert run.duration_hours is None

    async def test_it_prefers_the_machine_over_the_slicer(
        self, db_session, test_tenant, printer
    ) -> None:
        run = await make_run(db_session, test_tenant, printer)

        result = await ingest_run_actuals(
            db_session,
            test_tenant,
            run,
            adapter=ReportingPrinter(grams=Decimal("151")),
            slicer_metadata=SlicerMetadata(filament_weight_grams=145.0),
        )

        assert run.actual_total_weight_grams == Decimal("151")
        assert run.estimated_total_weight_grams is None
        assert result.source == "telemetry"

    async def test_it_does_not_overwrite_an_estimate_already_there(
        self, db_session, test_tenant, printer
    ) -> None:
        run = await make_run(
            db_session, test_tenant, printer, estimated_total_weight_grams=Decimal("140")
        )

        await ingest_run_actuals(
            db_session,
            test_tenant,
            run,
            adapter=SilentPrinter(),
            slicer_metadata=SlicerMetadata(filament_weight_grams=145.0),
        )

        assert run.estimated_total_weight_grams == Decimal("140")

    async def test_it_reports_having_nothing_when_neither_speaks(
        self, db_session, test_tenant, printer
    ) -> None:
        run = await make_run(db_session, test_tenant, printer)

        result = await ingest_run_actuals(
            db_session, test_tenant, run, adapter=SilentPrinter(), slicer_metadata=None
        )

        assert not result.written
        assert result.reason


# ---------------------------------------------------------------------------
# 3. An offline printer changes nothing
# ---------------------------------------------------------------------------


class TestAnOfflinePrinterChangesNothing:
    async def test_it_writes_no_figure_to_the_run(self, db_session, test_tenant, printer) -> None:
        run = await make_run(db_session, test_tenant, printer)

        await ingest_run_actuals(db_session, test_tenant, run, adapter=OfflinePrinter())

        assert run.actual_total_weight_grams is None
        assert run.duration_hours is None

    async def test_it_says_why_it_wrote_nothing(self, db_session, test_tenant, printer) -> None:
        # "Nothing happened" and "the machine was off" are different facts, and
        # an operator chasing a missing figure needs the second.
        run = await make_run(db_session, test_tenant, printer)

        result = await ingest_run_actuals(db_session, test_tenant, run, adapter=OfflinePrinter())

        assert not result.written
        assert "offline" in (result.reason or "")

    async def test_it_does_not_fall_back_to_the_slicer(
        self, db_session, test_tenant, printer
    ) -> None:
        # An offline machine is a failed read, not a missing capability. Taking
        # the slicer's figure here would hide a printer that has been
        # unreachable for a week.
        run = await make_run(db_session, test_tenant, printer)

        await ingest_run_actuals(
            db_session,
            test_tenant,
            run,
            adapter=OfflinePrinter(),
            slicer_metadata=SlicerMetadata(filament_weight_grams=145.0),
        )

        assert run.estimated_total_weight_grams is None

    async def test_it_moves_no_estimate(self, db_session, test_tenant, printer, model) -> None:
        run = await make_run(db_session, test_tenant, printer)
        before = model.print_time_minutes

        await ingest_run_actuals(db_session, test_tenant, run, adapter=OfflinePrinter())

        assert model.print_time_minutes == before

    async def test_it_records_no_provenance(self, db_session, test_tenant, printer, model) -> None:
        run = await make_run(db_session, test_tenant, printer)

        await ingest_run_actuals(db_session, test_tenant, run, adapter=OfflinePrinter())
        await db_session.commit()

        assert (
            await origin_of(db_session, test_tenant, "model", model.id, "print_time_minutes")
            is None
        )

    async def test_an_unreachable_adapter_is_reported_not_raised(
        self, db_session, test_tenant, printer
    ) -> None:
        # One machine being down must not abort a sweep over thirty of them.
        run = await make_run(db_session, test_tenant, printer)

        result = await ingest_run_actuals(
            db_session, test_tenant, run, adapter=UnreachablePrinter()
        )

        assert not result.written
        assert result.reason


# ---------------------------------------------------------------------------
# Learning from what the runs recorded
# ---------------------------------------------------------------------------


class TestLearningFromRuns:
    async def test_agreeing_runs_move_the_estimate(
        self, db_session, test_tenant, printer, model
    ) -> None:
        runs = []
        for _ in range(5):
            run = await make_run(
                db_session,
                test_tenant,
                printer,
                duration_hours=Decimal("10.0"),
                actual_total_weight_grams=Decimal("145"),
            )
            runs.append(run)

        decisions = await learn_from_runs(
            db_session,
            test_tenant,
            model,
            runs,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )
        await db_session.commit()

        assert decisions["print_time_minutes"].applied is True
        assert model.print_time_minutes == 600

    async def test_the_moved_estimate_says_it_was_observed(
        self, db_session, test_tenant, printer, model
    ) -> None:
        # FR-042f. A figure that moved on evidence must stop claiming to be an
        # assumption, or the next reader cannot tell the two apart.
        runs = [
            await make_run(db_session, test_tenant, printer, duration_hours=Decimal("10.0"))
            for _ in range(5)
        ]

        await learn_from_runs(
            db_session,
            test_tenant,
            model,
            runs,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )
        await db_session.commit()

        origin = await origin_of(db_session, test_tenant, "model", model.id, "print_time_minutes")
        assert origin is not None
        assert origin.source == "observed"
        assert origin.as_of is not None

    async def test_a_wild_reading_is_held_rather_than_applied(
        self, db_session, test_tenant, printer, model
    ) -> None:
        # 95 hours instead of 9.5: the decimal-point failure the threshold
        # exists for (FR-042b).
        runs = [
            await make_run(db_session, test_tenant, printer, duration_hours=Decimal("95.0"))
            for _ in range(5)
        ]
        before = model.print_time_minutes

        decisions = await learn_from_runs(
            db_session,
            test_tenant,
            model,
            runs,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )
        await db_session.commit()

        decision = decisions["print_time_minutes"]
        assert decision.applied is False
        assert decision.proposal is not None
        assert model.print_time_minutes == before

    async def test_too_few_runs_change_nothing(
        self, db_session, test_tenant, printer, model
    ) -> None:
        runs = [await make_run(db_session, test_tenant, printer, duration_hours=Decimal("10.0"))]
        before = model.print_time_minutes

        decisions = await learn_from_runs(
            db_session,
            test_tenant,
            model,
            runs,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )

        assert decisions["print_time_minutes"].applied is False
        assert model.print_time_minutes == before

    async def test_runs_with_no_figure_are_not_outcomes(
        self, db_session, test_tenant, printer, model
    ) -> None:
        # A run nobody recorded anything against is not evidence of a zero.
        runs = [await make_run(db_session, test_tenant, printer) for _ in range(5)]
        before = model.print_time_minutes

        decisions = await learn_from_runs(
            db_session,
            test_tenant,
            model,
            runs,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )

        assert decisions["print_time_minutes"].applied is False
        assert model.print_time_minutes == before

    async def test_an_operator_decision_is_not_moved(
        self, db_session, test_tenant, printer, model
    ) -> None:
        # FR-042g, through the learning path rather than the service's own
        # unit test: somebody set this deliberately and the machinery must
        # leave it alone.
        await record_origin(
            db_session,
            test_tenant,
            entity_type="model",
            entity_id=model.id,
            field_name="print_time_minutes",
            source="policy",
        )
        await db_session.commit()
        runs = [
            await make_run(db_session, test_tenant, printer, duration_hours=Decimal("10.0"))
            for _ in range(5)
        ]
        before = model.print_time_minutes

        decisions = await learn_from_runs(
            db_session,
            test_tenant,
            model,
            runs,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )

        assert decisions["print_time_minutes"].applied is False
        assert model.print_time_minutes == before


# ---------------------------------------------------------------------------
# 4. The smart plug
# ---------------------------------------------------------------------------


class TestASmartPlugMovesThePowerDraw:
    async def test_enough_readings_update_the_watts(self, db_session, test_tenant, printer) -> None:
        readings = [(f"plug-{i}", Decimal("104"), TODAY) for i in range(5)]

        decision = await ingest_power_readings(
            db_session,
            test_tenant,
            printer,
            readings,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )
        await db_session.commit()

        assert decision.applied is True
        assert printer.measured_watts == Decimal("104")

    async def test_the_updated_watts_are_labelled_observed(
        self, db_session, test_tenant, printer
    ) -> None:
        # The assertion T110 names. A plug reading that lands as "assumed" is
        # indistinguishable from the number it replaced.
        readings = [(f"plug-{i}", Decimal("104"), TODAY) for i in range(5)]

        await ingest_power_readings(
            db_session,
            test_tenant,
            printer,
            readings,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )
        await db_session.commit()

        origin = await origin_of(db_session, test_tenant, "printer", printer.id, "measured_watts")
        assert origin is not None
        assert origin.source == "observed"

    async def test_the_origin_carries_the_day_it_was_read(
        self, db_session, test_tenant, printer
    ) -> None:
        yesterday = TODAY - timedelta(days=1)
        readings = [(f"plug-{i}", Decimal("104"), yesterday) for i in range(5)]

        await ingest_power_readings(
            db_session,
            test_tenant,
            printer,
            readings,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )
        await db_session.commit()

        origin = await origin_of(db_session, test_tenant, "printer", printer.id, "measured_watts")
        assert origin is not None
        assert origin.as_of == yesterday

    async def test_a_tenfold_reading_is_held_for_review(
        self, db_session, test_tenant, printer
    ) -> None:
        # A plug reporting kilowatts as watts. Applied, it would reprice every
        # product this machine prints.
        readings = [(f"plug-{i}", Decimal("950"), TODAY) for i in range(5)]

        decision = await ingest_power_readings(
            db_session,
            test_tenant,
            printer,
            readings,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )
        await db_session.commit()

        assert decision.applied is False
        assert decision.proposal is not None
        assert printer.measured_watts == Decimal("95")

    async def test_one_reading_is_not_enough(self, db_session, test_tenant, printer) -> None:
        decision = await ingest_power_readings(
            db_session,
            test_tenant,
            printer,
            [("plug-1", Decimal("104"), TODAY)],
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )

        assert decision.applied is False
        assert printer.measured_watts == Decimal("95")

    async def test_a_zero_reading_is_discarded(self, db_session, test_tenant, printer) -> None:
        # A plug reporting zero while a print ran is a disconnected plug. Taken
        # as a measurement it would cost every print at no power.
        readings = [(f"plug-{i}", Decimal("0"), TODAY) for i in range(5)]

        decision = await ingest_power_readings(
            db_session,
            test_tenant,
            printer,
            readings,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )

        assert decision.applied is False
        assert printer.measured_watts == Decimal("95")

    async def test_an_operator_set_draw_is_left_alone(
        self, db_session, test_tenant, printer
    ) -> None:
        await record_origin(
            db_session,
            test_tenant,
            entity_type="printer",
            entity_id=printer.id,
            field_name="measured_watts",
            source="policy",
        )
        await db_session.commit()
        readings = [(f"plug-{i}", Decimal("104"), TODAY) for i in range(5)]

        decision = await ingest_power_readings(
            db_session,
            test_tenant,
            printer,
            readings,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )

        assert decision.applied is False
        assert printer.measured_watts == Decimal("95")

    async def test_the_readings_are_averaged_not_taken_last(
        self, db_session, test_tenant, printer
    ) -> None:
        # A rolling average (FR-042a). The last reading alone would make the
        # figure jitter with whatever the plug happened to report at the end.
        readings = [
            ("plug-1", Decimal("100"), TODAY),
            ("plug-2", Decimal("102"), TODAY),
            ("plug-3", Decimal("104"), TODAY),
            ("plug-4", Decimal("106"), TODAY),
            ("plug-5", Decimal("108"), TODAY),
        ]

        await ingest_power_readings(
            db_session,
            test_tenant,
            printer,
            readings,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )

        assert printer.measured_watts == Decimal("104")

    async def test_the_settings_come_from_the_policy_when_not_given(
        self, db_session, test_tenant, printer
    ) -> None:
        # The operator's thresholds, not the caller's. A task that passed its
        # own numbers would be deciding how much evidence is enough.
        readings = [(f"plug-{i}", Decimal("104"), TODAY) for i in range(5)]

        decision = await ingest_power_readings(db_session, test_tenant, printer, readings)
        await db_session.commit()

        assert decision.applied is True
        assert printer.measured_watts == Decimal("104")


class TestTheReadingDates:
    async def test_a_reading_with_no_date_is_dated_today(
        self, db_session, test_tenant, printer
    ) -> None:
        readings = [(f"plug-{i}", Decimal("104"), None) for i in range(5)]

        await ingest_power_readings(
            db_session,
            test_tenant,
            printer,
            readings,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )
        await db_session.commit()

        origin = await origin_of(db_session, test_tenant, "printer", printer.id, "measured_watts")
        assert origin is not None
        assert origin.as_of == TODAY

    async def test_the_origin_date_is_the_most_recent_reading(
        self, db_session, test_tenant, printer
    ) -> None:
        readings = [
            ("plug-1", Decimal("104"), date(2026, 1, 1)),
            ("plug-2", Decimal("104"), date(2026, 3, 1)),
            ("plug-3", Decimal("104"), date(2026, 2, 1)),
            ("plug-4", Decimal("104"), date(2026, 1, 15)),
            ("plug-5", Decimal("104"), date(2026, 2, 20)),
        ]

        await ingest_power_readings(
            db_session,
            test_tenant,
            printer,
            readings,
            min_outcomes=5,
            divergence_threshold_pct=Decimal("25"),
        )
        await db_session.commit()

        origin = await origin_of(db_session, test_tenant, "printer", printer.id, "measured_watts")
        assert origin is not None
        assert origin.as_of == date(2026, 3, 1)
