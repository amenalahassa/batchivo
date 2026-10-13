"""When an observation may move an estimate, and when a person must decide (T101).

FR-042's seven clauses are one mechanism with one exception, and the exception
is the point. An observed outcome normally improves an estimate, so once enough
outcomes agree the figure updates itself (FR-042a). But **an observation that
disagrees with the estimate by a large margin is more often a faulty
measurement than a discovery** — a smart plug reporting kilowatts instead of
watts, a print logged at 95 hours instead of 9.5, a spool weighed before it was
dried. Each of those would move a price, and the price would be wrong in a way
nobody could trace back to a sensor. So beyond the operator's threshold the
update is held as a proposal (FR-042b) and a person decides.

The rules tested here, each with a wrong answer that looks reasonable:

* **FR-042a** — enough outcomes, close value: applied on its own, origin
  becomes ``observed``, dated, carrying the outcomes it came from.
* **FR-042b** — beyond the divergence threshold: held, and **pricing keeps
  using the current estimate** while it is held (FR-042e). The tempting wrong
  answer is to apply it and flag it; that prices against a reading nobody has
  checked.
* **FR-042c** — the proposal states the current estimate, the observed value,
  the divergence and the outcomes.
* **FR-042d** — a rejected proposal is not re-raised from the same outcomes,
  but does not suppress a later one from new outcomes. Both halves matter: the
  first wrong answer nags forever, the second silences the field for good.
* **FR-042g** — an operator decision is never updated by this mechanism,
  whatever the divergence. This is the one with no override.

And one rule from data-model.md: a later proposal **supersedes** a pending one
rather than queueing, because two pending proposals on one figure make "accept"
ambiguous.
"""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core import clock
from app.models.estimate_revision import EstimateRevision
from app.models.model import Model
from app.services import variance_service
from app.services.provenance import origins_for_entity, record_origin
from app.services.variance_service import (
    NotLearnable,
    Outcome,
    accept_revision,
    consider_outcomes,
    divergence_pct,
    pending_revision,
    reject_revision,
    rolling_average,
)

TODAY = clock.today()

#: The field used throughout: a model's machine occupancy. Learnable, and the
#: one a print log actually measures.
FIELD = "print_time_minutes"
ENTITY_TYPE = "model"


def outcomes(*values: str, start: int = 0) -> list[Outcome]:
    """Outcomes with distinct ids, so FR-042d's set comparison is meaningful."""
    return [
        Outcome(
            run_id=f"run-{start + index}",
            value=Decimal(value),
            observed_on=TODAY - timedelta(days=len(values) - index),
        )
        for index, value in enumerate(values)
    ]


@pytest_asyncio.fixture
async def estimated_model(db_session, test_tenant) -> Model:
    """A model whose print time is an estimate of 100 minutes."""
    model = Model(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku=f"VAR-{uuid4().hex[:6]}",
        name="Variance subject",
        print_time_minutes=100,
        prints_per_plate=1,
        is_active=True,
    )
    db_session.add(model)
    await db_session.flush()
    return model


async def consider(
    db,
    tenant,
    model,
    *,
    values: list[str],
    threshold: str = "25",
    minimum: int = 3,
    start: int = 0,
    user=None,
):
    """Run the mechanism with an explicit threshold and minimum.

    Both come from the operator's policy (FR-042a, FR-042b), and both are
    passed explicitly here: a test that relied on a default would stop testing
    the setting the moment the default changed.
    """
    return await consider_outcomes(
        db,
        tenant,
        model,
        entity_type=ENTITY_TYPE,
        field_name=FIELD,
        outcomes=outcomes(*values, start=start),
        min_outcomes=minimum,
        divergence_threshold_pct=Decimal(threshold),
        user=user,
    )


# ---------------------------------------------------------------------------
# The arithmetic, before any of the rules
# ---------------------------------------------------------------------------


class TestTheArithmetic:
    def test_a_rolling_average_is_the_mean_of_the_outcomes(self) -> None:
        assert rolling_average(outcomes("90", "100", "110")) == Decimal("100")

    def test_the_average_is_exact_rather_than_rounded_early(self) -> None:
        """Rounding here would seed a divergence comparison with an error."""
        average = rolling_average(outcomes("100", "101"))
        assert average == Decimal("100.5")

    def test_an_empty_set_of_outcomes_has_no_average(self) -> None:
        assert rolling_average([]) is None

    @pytest.mark.parametrize(
        "current,observed,expected",
        [
            ("100", "100", "0"),
            ("100", "110", "10"),
            ("100", "90", "10"),
            ("100", "200", "100"),
            ("100", "0", "100"),
            ("8", "10", "25"),
        ],
    )
    def test_divergence_is_an_unsigned_percentage_of_the_estimate(
        self, current, observed, expected
    ) -> None:
        """Unsigned: a reading 30% low is as suspect as one 30% high."""
        assert divergence_pct(Decimal(current), Decimal(observed)) == Decimal(expected)

    def test_divergence_from_a_zero_estimate_is_unbounded_rather_than_a_crash(
        self,
    ) -> None:
        """A figure nobody set is not 0% different from every observation.

        Returning ``None`` makes the caller decide; dividing by zero would
        either raise on a sale path or, worse, be caught and read as "no
        divergence", which would apply any reading at all.
        """
        assert divergence_pct(Decimal("0"), Decimal("42")) is None


# ---------------------------------------------------------------------------
# FR-042a: enough outcomes, close value, applied on its own
# ---------------------------------------------------------------------------


class TestAnAgreeingObservationUpdatesTheEstimate:
    async def test_it_applies_once_the_minimum_is_reached(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        decision = await consider(
            db_session, test_tenant, estimated_model, values=["108", "110", "112"]
        )

        assert decision.applied is True
        assert decision.proposal is None
        assert estimated_model.print_time_minutes == 110

    async def test_it_does_nothing_below_the_minimum(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        """Two agreeing prints are not evidence; the operator sets how many are.

        Applying early is the quiet failure: one unusual print would move the
        price of everything made from this model.
        """
        decision = await consider(
            db_session, test_tenant, estimated_model, values=["108", "110"], minimum=3
        )

        assert decision.applied is False
        assert decision.proposal is None
        assert estimated_model.print_time_minutes == 100
        assert "3" in decision.reason

    async def test_the_minimum_is_the_operators_setting_not_a_constant(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        decision = await consider(
            db_session, test_tenant, estimated_model, values=["108", "110"], minimum=2
        )

        assert decision.applied is True
        assert estimated_model.print_time_minutes == 109

    async def test_applying_sets_the_origin_to_observed_and_dates_it(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        """FR-042f. A figure that moved on its own must say so.

        Dated with the **newest outcome**, not with today. The evidence is as
        old as it is: stamping it with today would make a figure derived from
        last month's prints look freshly measured, and FR-005's staleness
        threshold reads exactly this date.
        """
        recorded = outcomes("108", "110", "112")
        await consider_outcomes(
            db_session,
            test_tenant,
            estimated_model,
            entity_type=ENTITY_TYPE,
            field_name=FIELD,
            outcomes=recorded,
            min_outcomes=3,
            divergence_threshold_pct=Decimal("25"),
        )

        origins = await origins_for_entity(
            db_session, test_tenant, ENTITY_TYPE, estimated_model.id
        )
        assert origins[FIELD].source == "observed"
        assert origins[FIELD].as_of == max(o.observed_on for o in recorded)
        assert origins[FIELD].as_of < TODAY

    async def test_applying_records_the_outcomes_it_came_from(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        """FR-042f's other half: *which* outcomes, not just that there were some."""
        decision = await consider(
            db_session, test_tenant, estimated_model, values=["108", "110", "112"]
        )

        assert decision.run_ids == frozenset({"run-0", "run-1", "run-2"})

    async def test_an_observation_equal_to_the_estimate_is_still_recorded(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        """Evidence that the estimate was right is evidence.

        Treating a zero-divergence observation as "nothing to do" would leave
        a well-corroborated figure looking like an assumption for ever.
        """
        decision = await consider(
            db_session, test_tenant, estimated_model, values=["100", "100", "100"]
        )

        assert decision.applied is True
        origins = await origins_for_entity(
            db_session, test_tenant, ENTITY_TYPE, estimated_model.id
        )
        assert origins[FIELD].source == "observed"

    async def test_an_integer_field_is_not_left_holding_a_fraction(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        """``print_time_minutes`` is an integer column.

        The average of 109, 110 and 112 is 110.33. Writing that to an integer
        column would either raise or be silently truncated by the driver, and a
        truncation nobody chose is a figure nobody can explain.
        """
        decision = await consider(
            db_session, test_tenant, estimated_model, values=["109", "110", "112"]
        )

        assert decision.applied is True
        assert isinstance(estimated_model.print_time_minutes, int)
        assert estimated_model.print_time_minutes == 110


# ---------------------------------------------------------------------------
# FR-042b and FR-042e: beyond the threshold, held — and not priced against
# ---------------------------------------------------------------------------


class TestADivergentObservationIsHeld:
    async def test_it_is_not_applied(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        decision = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )

        assert decision.applied is False
        assert decision.proposal is not None

    async def test_pricing_keeps_using_the_current_estimate(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        """FR-042e. The whole point: a held reading does not reach a price.

        If the figure moved and was merely flagged, every price computed while
        the proposal sat there would be based on a reading nobody had checked.
        """
        await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )

        assert estimated_model.print_time_minutes == 100

    async def test_the_origin_is_not_moved_to_observed(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )

        origins = await origins_for_entity(
            db_session, test_tenant, ENTITY_TYPE, estimated_model.id
        )
        assert origins[FIELD].source != "observed"

    async def test_the_figure_is_flagged_as_having_a_pending_revision(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        """FR-042e's second half: held, and visibly held.

        A divergence nobody is told about is a divergence nobody acts on.
        """
        await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )

        pending = await pending_revision(
            db_session,
            test_tenant,
            entity_type=ENTITY_TYPE,
            entity_id=estimated_model.id,
            field_name=FIELD,
        )
        assert pending is not None
        assert pending.is_pending is True

    @pytest.mark.parametrize(
        "values,threshold,held",
        [
            # 10% divergence under a 25% threshold: applied.
            (["110", "110", "110"], "25", False),
            # Exactly at the threshold: applied. "Beyond" is beyond (FR-042b).
            (["125", "125", "125"], "25", False),
            # A hair past it: held.
            (["126", "126", "126"], "25", True),
            # A tighter threshold catches what a loose one allows.
            (["110", "110", "110"], "5", True),
        ],
    )
    async def test_the_threshold_boundary_is_inclusive(
        self, db_session, test_tenant, estimated_model, values, threshold, held
    ) -> None:
        """At exactly the threshold the update applies.

        Stated as its own test because the boundary is the operator's setting:
        somebody who sets 25% means "up to a quarter out is plausible", and a
        proposal at exactly 25% would contradict what they chose.
        """
        decision = await consider(
            db_session, test_tenant, estimated_model, values=values, threshold=threshold
        )

        assert (decision.proposal is not None) is held
        assert decision.applied is not held

    async def test_the_proposal_states_everything_a_reviewer_needs(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        """FR-042c, item by item."""
        decision = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )
        proposal = decision.proposal

        assert proposal is not None
        assert Decimal(str(proposal.current_value)) == Decimal("100")
        assert Decimal(str(proposal.observed_value)) == Decimal("910")
        assert Decimal(str(proposal.divergence_pct)) == Decimal("810")
        assert proposal.run_ids == frozenset({"run-0", "run-1", "run-2"})
        assert proposal.entity_type == ENTITY_TYPE
        assert proposal.entity_id == estimated_model.id
        assert proposal.field_name == FIELD

    async def test_a_pending_proposal_has_no_reviewer_yet(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        decision = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )

        assert decision.proposal is not None
        assert decision.proposal.reviewed_by_user_id is None
        assert decision.proposal.reviewed_at is None

    async def test_the_stored_divergence_is_not_recomputed_later(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        """The comparison the operator sees is the one that was actually made.

        If the estimate moves for an unrelated reason, re-deriving the
        divergence would show a proposal that appears to have been raised for
        no reason.
        """
        decision = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )
        stored = Decimal(str(decision.proposal.divergence_pct))

        estimated_model.print_time_minutes = 905
        db_session.add(estimated_model)
        await db_session.flush()

        again = await pending_revision(
            db_session,
            test_tenant,
            entity_type=ENTITY_TYPE,
            entity_id=estimated_model.id,
            field_name=FIELD,
        )
        assert Decimal(str(again.divergence_pct)) == stored
        assert Decimal(str(again.current_value)) == Decimal("100")


# ---------------------------------------------------------------------------
# Accepting and rejecting, whole (FR-042c)
# ---------------------------------------------------------------------------


class TestDecidingAProposal:
    @pytest_asyncio.fixture
    async def held(self, db_session, test_tenant, estimated_model):
        decision = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )
        assert decision.proposal is not None
        return decision.proposal

    async def test_accepting_applies_the_observed_value(
        self, db_session, test_tenant, estimated_model, held, test_user
    ) -> None:
        await accept_revision(db_session, test_tenant, held.id, user=test_user)

        assert estimated_model.print_time_minutes == 910

    async def test_accepting_sets_the_origin_to_observed(
        self, db_session, test_tenant, estimated_model, held, test_user
    ) -> None:
        """FR-042f applies on acceptance exactly as it does automatically."""
        await accept_revision(db_session, test_tenant, held.id, user=test_user)

        origins = await origins_for_entity(
            db_session, test_tenant, ENTITY_TYPE, estimated_model.id
        )
        assert origins[FIELD].source == "observed"
        assert origins[FIELD].as_of == held.observed_as_of

    async def test_accepting_records_who_decided_and_when(
        self, db_session, test_tenant, held, test_user
    ) -> None:
        accepted = await accept_revision(
            db_session, test_tenant, held.id, user=test_user
        )

        assert accepted.state == "accepted"
        assert accepted.reviewed_by_user_id == test_user.id
        assert accepted.reviewed_at is not None

    async def test_rejecting_leaves_the_estimate_alone(
        self, db_session, test_tenant, estimated_model, held, test_user
    ) -> None:
        await reject_revision(db_session, test_tenant, held.id, user=test_user)

        assert estimated_model.print_time_minutes == 100

    async def test_rejecting_records_who_decided_and_when(
        self, db_session, test_tenant, held, test_user
    ) -> None:
        rejected = await reject_revision(
            db_session, test_tenant, held.id, user=test_user
        )

        assert rejected.state == "rejected"
        assert rejected.reviewed_by_user_id == test_user.id
        assert rejected.reviewed_at is not None

    async def test_a_decided_proposal_is_no_longer_pending(
        self, db_session, test_tenant, estimated_model, held, test_user
    ) -> None:
        await reject_revision(db_session, test_tenant, held.id, user=test_user)

        assert (
            await pending_revision(
                db_session,
                test_tenant,
                entity_type=ENTITY_TYPE,
                entity_id=estimated_model.id,
                field_name=FIELD,
            )
            is None
        )

    async def test_a_decided_proposal_cannot_be_decided_again(
        self, db_session, test_tenant, held, test_user
    ) -> None:
        """Terminal states are terminal.

        Its fate is part of the record FR-042d reads to decide whether to
        propose again, so reopening it would change what that rule sees.
        """
        await accept_revision(db_session, test_tenant, held.id, user=test_user)

        with pytest.raises(ValueError):
            await accept_revision(db_session, test_tenant, held.id, user=test_user)
        with pytest.raises(ValueError):
            await reject_revision(db_session, test_tenant, held.id, user=test_user)

    async def test_another_tenants_proposal_is_not_decidable(
        self, db_session, test_tenant, held, test_user
    ) -> None:
        """Constitution I, at the one place an id arrives from a request."""
        from app.models.tenant import Tenant

        other = Tenant(id=uuid4(), name="Elsewhere", slug=f"elsewhere-{uuid4().hex[:6]}")
        db_session.add(other)
        await db_session.flush()

        with pytest.raises(LookupError):
            await accept_revision(db_session, other, held.id, user=test_user)


# ---------------------------------------------------------------------------
# FR-042d: rejected once, not nagged — but not silenced either
# ---------------------------------------------------------------------------


class TestARejectedProposalIsNotReRaised:
    async def test_the_same_outcomes_do_not_raise_it_again(
        self, db_session, test_tenant, estimated_model, test_user
    ) -> None:
        """Otherwise the operator is asked the same question for ever."""
        first = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )
        await reject_revision(
            db_session, test_tenant, first.proposal.id, user=test_user
        )

        again = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )

        assert again.proposal is None
        assert again.applied is False
        assert "rejected" in again.reason

    async def test_new_outcomes_do_raise_it_again(
        self, db_session, test_tenant, estimated_model, test_user
    ) -> None:
        """FR-042d's second half, and the more dangerous one to get wrong.

        Suppressing for ever would silence a field that really has changed --
        a new nozzle, a new filament, a re-sliced model.
        """
        first = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )
        await reject_revision(
            db_session, test_tenant, first.proposal.id, user=test_user
        )

        later = await consider(
            db_session,
            test_tenant,
            estimated_model,
            values=["900", "910", "920", "930"],
            start=0,
        )

        assert later.proposal is not None
        assert "run-3" in later.proposal.run_ids

    async def test_an_entirely_new_set_of_outcomes_raises_it_again(
        self, db_session, test_tenant, estimated_model, test_user
    ) -> None:
        first = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )
        await reject_revision(
            db_session, test_tenant, first.proposal.id, user=test_user
        )

        later = await consider(
            db_session,
            test_tenant,
            estimated_model,
            values=["900", "910", "920"],
            start=10,
        )

        assert later.proposal is not None

    async def test_a_subset_of_rejected_outcomes_does_not_raise_it(
        self, db_session, test_tenant, estimated_model, test_user
    ) -> None:
        """Fewer of the same readings is not new information."""
        first = await consider(
            db_session,
            test_tenant,
            estimated_model,
            values=["900", "910", "920", "930"],
        )
        await reject_revision(
            db_session, test_tenant, first.proposal.id, user=test_user
        )

        later = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )

        assert later.proposal is None

    async def test_a_rejection_does_not_block_an_agreeing_observation(
        self, db_session, test_tenant, estimated_model, test_user
    ) -> None:
        """A rejection is about a divergence, not about the field.

        Once observations come back into line there is nothing to review, and
        nothing to suppress.
        """
        first = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )
        await reject_revision(
            db_session, test_tenant, first.proposal.id, user=test_user
        )

        later = await consider(
            db_session,
            test_tenant,
            estimated_model,
            values=["102", "104", "106"],
            start=20,
        )

        assert later.applied is True
        assert estimated_model.print_time_minutes == 104

    async def test_an_accepted_proposal_does_not_suppress_a_later_one(
        self, db_session, test_tenant, estimated_model, test_user
    ) -> None:
        """Only rejections suppress. An acceptance moved the figure."""
        first = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )
        await accept_revision(
            db_session, test_tenant, first.proposal.id, user=test_user
        )
        assert estimated_model.print_time_minutes == 910

        later = await consider(
            db_session,
            test_tenant,
            estimated_model,
            values=["9000", "9100", "9200"],
            start=30,
        )

        assert later.proposal is not None


# ---------------------------------------------------------------------------
# data-model.md: supersede, never queue
# ---------------------------------------------------------------------------


class TestALaterProposalSupersedesAPendingOne:
    async def test_only_one_proposal_is_pending_at_a_time(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        """Two pending proposals on one figure make "accept" ambiguous."""
        await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )
        await consider(
            db_session,
            test_tenant,
            estimated_model,
            values=["900", "910", "920", "940"],
        )

        rows = (
            (
                await db_session.execute(
                    select(EstimateRevision).where(
                        EstimateRevision.tenant_id == test_tenant.id,
                        EstimateRevision.state == "pending",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    async def test_the_pending_proposal_is_the_newer_one(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )
        second = await consider(
            db_session,
            test_tenant,
            estimated_model,
            values=["900", "910", "920", "940"],
        )

        pending = await pending_revision(
            db_session,
            test_tenant,
            entity_type=ENTITY_TYPE,
            entity_id=estimated_model.id,
            field_name=FIELD,
        )
        assert pending.id == second.proposal.id
        assert "run-3" in pending.run_ids

    async def test_superseding_is_reported_rather_than_silent(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        first = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )
        second = await consider(
            db_session,
            test_tenant,
            estimated_model,
            values=["900", "910", "920", "940"],
        )

        assert second.superseded_id == first.proposal.id

    async def test_a_proposal_on_another_field_does_not_collide(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )

        other = await consider_outcomes(
            db_session,
            test_tenant,
            estimated_model,
            entity_type=ENTITY_TYPE,
            field_name="waste_grams",
            outcomes=outcomes("90", "91", "92", start=50),
            min_outcomes=3,
            divergence_threshold_pct=Decimal("25"),
        )

        assert other.proposal is not None
        assert other.proposal.field_name == "waste_grams"


# ---------------------------------------------------------------------------
# FR-042g: an operator decision is never moved
# ---------------------------------------------------------------------------


class TestAnOperatorDecisionIsNeverUpdated:
    async def test_an_unlearnable_field_is_refused_outright(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        """Not held as a proposal -- refused. There is nothing to review.

        A proposal to change a figure the operator decided would invite them to
        accept it, which is exactly what FR-002 says must not happen through
        this mechanism.
        """
        with pytest.raises(NotLearnable):
            await consider_outcomes(
                db_session,
                test_tenant,
                estimated_model,
                entity_type="tenant_pricing_policy",
                field_name="print_labor_rate",
                outcomes=outcomes("90", "91", "92"),
                min_outcomes=3,
                divergence_threshold_pct=Decimal("25"),
            )

    async def test_a_field_whose_origin_is_policy_is_refused(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        """Whatever the divergence, and whatever the registry says is learnable.

        An operator who states a figure has overridden the estimate. That is a
        decision, and this mechanism does not touch decisions.
        """
        await record_origin(
            db_session,
            test_tenant,
            entity_type=ENTITY_TYPE,
            entity_id=estimated_model.id,
            field_name=FIELD,
            source="policy",
        )
        await db_session.flush()

        with pytest.raises(NotLearnable):
            await consider(
                db_session, test_tenant, estimated_model, values=["101", "102", "103"]
            )

        assert estimated_model.print_time_minutes == 100

    async def test_a_hand_measured_field_may_still_be_updated(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        """A measurement is evidence, not a decision.

        Observed outcomes supersede a hand measurement, which is the whole
        point of recording outcomes.
        """
        await record_origin(
            db_session,
            test_tenant,
            entity_type=ENTITY_TYPE,
            entity_id=estimated_model.id,
            field_name=FIELD,
            source="measured",
        )
        await db_session.flush()

        decision = await consider(
            db_session, test_tenant, estimated_model, values=["108", "110", "112"]
        )

        assert decision.applied is True
        assert estimated_model.print_time_minutes == 110

    async def test_an_unknown_field_is_refused_rather_than_written(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        """A typo would otherwise move a figure nothing reads."""
        from app.services.provenance import UnknownProvenanceField

        with pytest.raises(UnknownProvenanceField):
            await consider_outcomes(
                db_session,
                test_tenant,
                estimated_model,
                entity_type=ENTITY_TYPE,
                field_name="print_time_minuets",
                outcomes=outcomes("90", "91", "92"),
                min_outcomes=3,
                divergence_threshold_pct=Decimal("25"),
            )


# ---------------------------------------------------------------------------
# Exactness and tenant scope
# ---------------------------------------------------------------------------


class TestTheMechanismIsExactAndScoped:
    async def test_no_float_reaches_a_stored_figure(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        decision = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )

        assert isinstance(decision.observed_value, Decimal)
        assert isinstance(decision.divergence, Decimal)
        assert isinstance(
            Decimal(str(decision.proposal.observed_value)), Decimal
        )

    async def test_a_proposal_carries_its_tenant(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        decision = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )

        assert decision.proposal.tenant_id == test_tenant.id

    async def test_pending_revisions_are_listed_per_tenant(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        from app.models.tenant import Tenant

        await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )
        other = Tenant(id=uuid4(), name="Elsewhere", slug=f"elsewhere-{uuid4().hex[:6]}")
        db_session.add(other)
        await db_session.flush()

        mine = await variance_service.list_revisions(
            db_session, test_tenant, state="pending"
        )
        theirs = await variance_service.list_revisions(
            db_session, other, state="pending"
        )

        assert len(mine) == 1
        assert theirs == []
