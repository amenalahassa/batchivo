"""An observed figure says how far to believe it (T259, FR-001, US6/AC1).

`pricing_input_provenance.confidence` existed and nothing set it. An estimate
that becomes observed from N outcomes is exactly where a confidence means
something: five prints that agree are better evidence than five that scatter,
and fifty better than five. The figure is set there, frozen onto a held
proposal, and carried onto the cost lines built from it.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest_asyncio

from app.models.model import Model

from app.services import costing
from app.services.provenance import origins_for_entity
from app.services.variance_service import Outcome, accept_revision, estimate_confidence
from tests.unit.pricing.test_variance import ENTITY_TYPE, FIELD, consider, outcomes

ON = date(2026, 6, 1)


@pytest_asyncio.fixture
async def estimated_model(db_session, test_tenant) -> Model:
    """A model whose print time is an estimate of 100 minutes."""
    model = Model(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku=f"CONF-{uuid4().hex[:6]}",
        name="Confidence subject",
        print_time_minutes=100,
        prints_per_plate=1,
        is_active=True,
    )
    db_session.add(model)
    await db_session.flush()
    return model


def _values(*values: str) -> list[Outcome]:
    return [Outcome(run_id=f"r{i}", value=Decimal(v), observed_on=ON) for i, v in enumerate(values)]


# ============================================================================
# The figure
# ============================================================================


class TestTheConfidenceFigure:
    def test_five_agreeing_outcomes_earn_a_half(self) -> None:
        assert estimate_confidence(_values("110", "110", "110", "110", "110")) == Decimal("0.5000")

    def test_more_agreeing_outcomes_earn_more(self) -> None:
        five = estimate_confidence(_values(*["110"] * 5))
        fifty = estimate_confidence(_values(*["110"] * 50))
        assert five is not None and fifty is not None
        assert fifty > five
        assert fifty == Decimal("0.9091")  # 50 / 55

    def test_scattered_outcomes_earn_less_than_agreeing_ones(self) -> None:
        agreeing = estimate_confidence(_values("100", "100", "100", "100", "100"))
        scattered = estimate_confidence(_values("60", "80", "100", "120", "140"))
        assert agreeing is not None and scattered is not None
        assert scattered < agreeing

    def test_it_is_exact_until_the_edge(self) -> None:
        # Mean 100, population deviation sqrt(800) = 28.284..., cv 0.28284...;
        # 0.5 / 1.28284... = 0.38976..., rounded once.
        assert estimate_confidence(_values("60", "80", "100", "120", "140")) == Decimal("0.3898")

    def test_no_outcomes_means_no_confidence_rather_than_none_at_all(self) -> None:
        assert estimate_confidence([]) is None

    def test_any_evidence_is_never_reported_as_zero(self) -> None:
        wild = estimate_confidence(_values("0", "1000"))
        assert wild is not None and wild > Decimal("0")

    def test_outcomes_of_zero_that_agree_are_still_agreement(self) -> None:
        assert estimate_confidence(_values("0", "0", "0", "0", "0")) == Decimal("0.5000")


# ============================================================================
# Where it is set
# ============================================================================


class TestAnObservedFigureCarriesItsConfidence:
    async def test_an_applied_update_records_the_confidence_of_its_outcomes(
        self, db_session, test_tenant, estimated_model
    ) -> None:
        await consider(db_session, test_tenant, estimated_model, values=["108", "110", "112"])

        origins = await origins_for_entity(db_session, test_tenant, ENTITY_TYPE, estimated_model.id)
        assert origins[FIELD].source == "observed"
        assert origins[FIELD].confidence == estimate_confidence(outcomes("108", "110", "112"))

    async def test_a_held_proposal_freezes_the_confidence_and_acceptance_records_it(
        self, db_session, test_tenant, estimated_model, test_user
    ) -> None:
        decision = await consider(
            db_session, test_tenant, estimated_model, values=["900", "910", "920"]
        )
        assert decision.proposal is not None
        expected = estimate_confidence(outcomes("900", "910", "920"))
        assert decision.proposal.confidence == expected

        await accept_revision(db_session, test_tenant, decision.proposal.id, user=test_user)

        origins = await origins_for_entity(db_session, test_tenant, ENTITY_TYPE, estimated_model.id)
        assert origins[FIELD].confidence == expected


# ============================================================================
# Where it is shown
# ============================================================================


class TestACostLineCarriesTheConfidenceOfItsInputs:
    def test_a_recorded_confidence_reaches_the_lines_origin(self) -> None:
        from uuid import uuid4

        from app.services.provenance import FieldOrigin

        entity_id = uuid4()
        recorded = FieldOrigin(source="observed", as_of=ON, confidence=Decimal("0.7500"))
        origin = costing._origin_of(
            {("model", entity_id, "print_time_minutes"): recorded},
            None,
            "model",
            entity_id,
            "print_time_minutes",
        )
        assert origin.confidence == Decimal("0.7500")

    def test_a_line_is_as_believable_as_its_least_believable_observed_input(self) -> None:
        line = costing._weakest(
            [
                costing._Origin("observed", ON, confidence=Decimal("0.8")),
                costing._Origin("observed", ON, confidence=Decimal("0.6")),
                costing._Origin("policy", ON),
            ]
        )
        assert line.confidence == Decimal("0.6")

    def test_a_line_with_no_observed_input_claims_no_confidence(self) -> None:
        line = costing._weakest([costing._Origin("policy", ON), costing._Origin("measured", ON)])
        assert line.confidence is None

    def test_the_served_line_carries_it(self) -> None:
        lines = costing._rounded_lines(
            [
                costing._RawLine(
                    "machine", Decimal("2.5"), "observed", ON, False, Decimal("0.7500")
                ),
            ]
        )
        assert lines[0].confidence == Decimal("0.7500")
