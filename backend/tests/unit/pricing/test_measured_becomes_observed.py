"""A hand-measured figure becomes an observed one, losing nothing (T207).

FR-006 is the promise that instrumenting a workshop is worth doing: a figure
the operator measured by hand must be able to become ``observed`` once its
source is instrumented, "with no data loss and no manual re-entry". The
operator should not have to re-type a print time because a printer started
reporting it.

The mechanism exists and is used. ``record_origin`` upserts on
``(tenant_id, entity_type, entity_id, field_name)``, and
``variance_service`` writes ``source="observed"`` over whatever the field
carried before -- on the automatic update (FR-042a) and on an accepted
proposal (FR-042f) alike.

**Nothing asserted it.** FR-006 was the only one of this feature's
requirements whose id appeared nowhere in ``app/`` or ``tests/``, and no test
anywhere named the transition. So the property was carried entirely by
``record_origin`` happening to be an upsert: making it insert-only, or having
it skip where a row already exists, would leave an instrumented printer's
figure permanently labelled ``measured``, and the suite would stay green.

What "no data loss" means here is stated rather than assumed, because the two
readings differ:

* The **figure itself** moves to the observed value, on the same entity, with
  no second entity and no re-entry. That is the whole of FR-006's promise.
* The **provenance row** is updated in place, not duplicated -- one row per
  (entity, field), so "where did this come from" has one answer.
* ``measured_by_user_id`` is **cleared**, deliberately. The figure is no
  longer that person's measurement; it is the printer's reading. Keeping their
  id on it would attribute a machine's figure to an operator, which is the
  relabelling `Constitution` IV's provenance rule forbids in the other
  direction. The assertion below pins this so it is a decision rather than an
  accident.
* ``as_of`` moves to the observation's date, so staleness is measured against
  the reading, not against the hand measurement it replaced.
"""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core import clock
from app.models.model import Model
from app.models.pricing_input_provenance import PricingInputProvenance
from app.services.provenance import ProvenanceNotEditable, record_origin
from app.services.variance_service import (
    Outcome,
    accept_revision,
    consider_outcomes,
)

pytestmark = pytest.mark.asyncio

TODAY = clock.today()
MEASURED_ON = TODAY - timedelta(days=90)

#: A model's machine occupancy: learnable, and the figure a print log measures.
FIELD = "print_time_minutes"
ENTITY_TYPE = "model"


@pytest_asyncio.fixture
async def measured_model(db_session, test_tenant, test_user) -> Model:
    """A model whose print time the operator measured by hand, 90 days ago.

    Measured, not assumed: this is the figure FR-006 is about -- somebody stood
    at the printer with a stopwatch, and the system recorded who and when.
    """
    model = Model(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku=f"MEAS-{uuid4().hex[:6]}",
        name="Hand-measured subject",
        print_time_minutes=100,
        prints_per_plate=1,
        is_active=True,
    )
    db_session.add(model)
    await db_session.flush()

    await record_origin(
        db_session,
        test_tenant,
        entity_type=ENTITY_TYPE,
        entity_id=model.id,
        field_name=FIELD,
        source="measured",
        as_of=MEASURED_ON,
        measured_by_user_id=test_user.id,
        confidence=Decimal("0.80"),
    )
    await db_session.flush()
    return model


async def _rows_for(db_session, tenant, model) -> list[PricingInputProvenance]:
    """Every provenance row on this one field, to catch a duplicate.

    The stored row rather than `origins_for_entity`'s `FieldOrigin`, because
    `measured_by_user_id` and `authorised_by_role` are what this file is
    about and the read model does not carry them.
    """
    result = await db_session.execute(
        select(PricingInputProvenance).where(
            PricingInputProvenance.tenant_id == tenant.id,
            PricingInputProvenance.entity_type == ENTITY_TYPE,
            PricingInputProvenance.entity_id == model.id,
            PricingInputProvenance.field_name == FIELD,
        )
    )
    return list(result.scalars().all())


async def _origin(db_session, tenant, model) -> PricingInputProvenance:
    rows = await _rows_for(db_session, tenant, model)
    assert len(rows) == 1, f"{FIELD} has {len(rows)} recorded origins, not one"
    return rows[0]


def _outcomes(*values: str) -> list[Outcome]:
    return [
        Outcome(
            run_id=f"instrumented-{index}",
            value=Decimal(value),
            observed_on=TODAY - timedelta(days=len(values) - index),
        )
        for index, value in enumerate(values)
    ]


class TestTheStartingPointIsGenuinelyMeasured:
    """A test that began from `assumed` would prove nothing about FR-006."""

    async def test_the_figure_starts_measured_with_a_measurer_and_a_date(
        self, db_session, test_tenant, test_user, measured_model
    ) -> None:
        origin = await _origin(db_session, test_tenant, measured_model)

        assert origin.source == "measured"
        assert origin.measured_by_user_id == test_user.id
        assert origin.as_of == MEASURED_ON
        assert measured_model.print_time_minutes == 100


class TestInstrumentingTheSourcePromotesTheFigure:
    """FR-006: measured becomes observed, with no manual re-entry."""

    async def test_enough_agreeing_readings_make_the_figure_observed(
        self, db_session, test_tenant, measured_model
    ) -> None:
        """The printer starts reporting, and the label follows the evidence.

        If `record_origin` were insert-only, or skipped an existing row, this
        would still read `measured` -- the figure would be a printer's reading
        wearing an operator's label, and nothing else in the suite would say
        so.
        """
        decision = await consider_outcomes(
            db_session,
            test_tenant,
            measured_model,
            entity_type=ENTITY_TYPE,
            field_name=FIELD,
            outcomes=_outcomes("102", "104", "103"),
            min_outcomes=3,
            divergence_threshold_pct=Decimal("25"),
        )

        assert decision.applied, f"the update was not applied: {decision}"
        origin = await _origin(db_session, test_tenant, measured_model)
        assert origin.source == "observed", (
            "a figure measured by hand stayed labelled measured after its "
            "source was instrumented (FR-006)"
        )

    async def test_the_figure_itself_moves_without_being_re_entered(
        self, db_session, test_tenant, measured_model
    ) -> None:
        """ "No manual re-entry": the value on the entity is the observed one."""
        await consider_outcomes(
            db_session,
            test_tenant,
            measured_model,
            entity_type=ENTITY_TYPE,
            field_name=FIELD,
            outcomes=_outcomes("102", "104", "103"),
            min_outcomes=3,
            divergence_threshold_pct=Decimal("25"),
        )

        await db_session.refresh(measured_model)
        assert measured_model.print_time_minutes == 103, (
            "the observed average did not reach the field, so the operator "
            "would still have to type it in (FR-006)"
        )

    async def test_the_date_moves_to_the_observation(
        self, db_session, test_tenant, measured_model
    ) -> None:
        """Staleness is measured against the reading, not the old measurement."""
        await consider_outcomes(
            db_session,
            test_tenant,
            measured_model,
            entity_type=ENTITY_TYPE,
            field_name=FIELD,
            outcomes=_outcomes("102", "104", "103"),
            min_outcomes=3,
            divergence_threshold_pct=Decimal("25"),
        )

        origin = await _origin(db_session, test_tenant, measured_model)
        assert origin.as_of is not None
        assert origin.as_of > MEASURED_ON, (
            f"the origin is still dated {origin.as_of}, the day of the hand "
            f"measurement, so a fresh reading reads as ninety days stale"
        )

    async def test_the_promotion_updates_one_row_rather_than_adding_a_second(
        self, db_session, test_tenant, measured_model
    ) -> None:
        """One row per (entity, field), so provenance has one answer.

        A second row would make "where did this figure come from" depend on
        which row a reader happened to find, and `origins_for_entity` would
        start returning whichever the database handed back first.
        """
        before = await _rows_for(db_session, test_tenant, measured_model)
        assert len(before) == 1
        row_id = before[0].id

        await consider_outcomes(
            db_session,
            test_tenant,
            measured_model,
            entity_type=ENTITY_TYPE,
            field_name=FIELD,
            outcomes=_outcomes("102", "104", "103"),
            min_outcomes=3,
            divergence_threshold_pct=Decimal("25"),
        )

        after = await _rows_for(db_session, test_tenant, measured_model)
        assert len(after) == 1, (
            f"the promotion left {len(after)} provenance rows on one field; "
            f"the upsert has become an insert"
        )
        assert after[0].id == row_id, (
            "the row was replaced rather than updated, so anything holding a "
            "reference to the provenance of this figure now holds a dead one"
        )

    async def test_the_measurer_is_no_longer_credited_with_the_machines_reading(
        self, db_session, test_tenant, measured_model
    ) -> None:
        """What is deliberately *not* carried over.

        The figure is the printer's now. Leaving the operator's id on it would
        attribute a machine reading to a person, which is the relabelling the
        provenance rule forbids -- the same rule that bans calling an
        operator's figure observed, read the other way.
        """
        origin = await _origin(db_session, test_tenant, measured_model)
        assert origin.measured_by_user_id is not None

        await consider_outcomes(
            db_session,
            test_tenant,
            measured_model,
            entity_type=ENTITY_TYPE,
            field_name=FIELD,
            outcomes=_outcomes("102", "104", "103"),
            min_outcomes=3,
            divergence_threshold_pct=Decimal("25"),
        )

        origin = await _origin(db_session, test_tenant, measured_model)
        assert origin.measured_by_user_id is None, (
            "the operator who hand-measured this figure is still recorded as "
            "having measured a figure that now comes from a printer"
        )


class TestAnAcceptedProposalPromotesItTheSameWay:
    """FR-042f: the held path must end in the same place as the automatic one.

    A reading far from the estimate is held for a person to accept, and a
    hand-measured figure is exactly the case where that happens -- a stopwatch
    and a printer rarely agree to within a quarter. If acceptance did not
    promote the label, instrumenting a workshop would work only for the
    readings that happened to be close.
    """

    async def test_accepting_a_held_reading_makes_the_figure_observed(
        self, db_session, test_tenant, test_user, measured_model
    ) -> None:
        decision = await consider_outcomes(
            db_session,
            test_tenant,
            measured_model,
            entity_type=ENTITY_TYPE,
            field_name=FIELD,
            # 100 minutes measured against 180 observed: well past 25%.
            outcomes=_outcomes("178", "180", "182"),
            min_outcomes=3,
            divergence_threshold_pct=Decimal("25"),
        )

        assert not decision.applied, "a 80% divergence should have been held"
        assert decision.proposal is not None, "nothing was raised for a person to decide"

        # Held, so the figure is still the operator's measurement (FR-042e).
        origin = await _origin(db_session, test_tenant, measured_model)
        assert origin.source == "measured"
        assert measured_model.print_time_minutes == 100

        await accept_revision(db_session, test_tenant, decision.proposal.id, user=test_user)
        await db_session.flush()

        origin = await _origin(db_session, test_tenant, measured_model)
        assert origin.source == "observed", (
            "an accepted reading left the figure labelled measured, so the "
            "held path and the automatic path disagree (FR-006, FR-042f)"
        )
        await db_session.refresh(measured_model)
        assert measured_model.print_time_minutes == 180
        assert len(await _rows_for(db_session, test_tenant, measured_model)) == 1


class TestThePromotedFigureIsThenReadOnly:
    """FR-004: once observed, the figure is refreshed only from its source.

    This is the other half of FR-006 and it is deliberate rather than a
    limitation. A figure the printer reports must not be quietly typed over,
    because the next reading would overwrite the typing and nobody would know
    which they were pricing against. So a manual write is refused, and the
    refusal leaves the figure exactly as it was -- the same shape FR-007d
    requires of a permission refusal.

    An operator who disagrees with their instrumentation stops the figure
    being observed at its source; they do not overwrite its label.
    """

    async def test_a_manual_write_over_a_promoted_figure_is_refused(
        self, db_session, test_tenant, measured_model
    ) -> None:
        await consider_outcomes(
            db_session,
            test_tenant,
            measured_model,
            entity_type=ENTITY_TYPE,
            field_name=FIELD,
            outcomes=_outcomes("102", "104", "103"),
            min_outcomes=3,
            divergence_threshold_pct=Decimal("25"),
        )
        before = await _origin(db_session, test_tenant, measured_model)
        assert before.source == "observed"
        as_of_before = before.as_of

        with pytest.raises(ProvenanceNotEditable):
            await record_origin(
                db_session,
                test_tenant,
                entity_type=ENTITY_TYPE,
                entity_id=measured_model.id,
                field_name=FIELD,
                source="policy",
                authorised_by_role="owner",
            )

        after = await _origin(db_session, test_tenant, measured_model)
        assert after.source == "observed", "the refused write changed the label anyway"
        assert after.as_of == as_of_before, "the refused write moved the date anyway"
        assert after.authorised_by_role is None

    async def test_a_fresh_reading_still_refreshes_it(
        self, db_session, test_tenant, measured_model
    ) -> None:
        """Read-only to a person is not frozen: the source keeps updating it."""
        await consider_outcomes(
            db_session,
            test_tenant,
            measured_model,
            entity_type=ENTITY_TYPE,
            field_name=FIELD,
            outcomes=_outcomes("102", "104", "103"),
            min_outcomes=3,
            divergence_threshold_pct=Decimal("25"),
        )

        await consider_outcomes(
            db_session,
            test_tenant,
            measured_model,
            entity_type=ENTITY_TYPE,
            field_name=FIELD,
            outcomes=_outcomes("106", "108", "107"),
            min_outcomes=3,
            divergence_threshold_pct=Decimal("25"),
        )

        await db_session.refresh(measured_model)
        assert measured_model.print_time_minutes == 107
        origin = await _origin(db_session, test_tenant, measured_model)
        assert origin.source == "observed"
        assert len(await _rows_for(db_session, test_tenant, measured_model)) == 1
