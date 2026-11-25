"""A cost line says when its figure is under review (task T153, FR-042e).

`ProvenanceBadge` has accepted `hasPendingRevision` since T055a, and the
provenance resource has served it since T102. The cost breakdown — the screen
an operator actually reads a figure off — could not pass it, because `CostLine`
carried only `source` and `as_of`. So the one surface where the number appears
showed it as though nothing were in question, while a proposal disputing it sat
waiting in a list the operator had no reason to open.

## What this must not do

Flag the line and leave the amount out, or substitute the observed value.
Telemetry proposes and does not reprice (Constitution VII): the figure on the
line is the one in force until an operator accepts the proposal, and the flag
is the only thing that changes. `test_the_amount_is_still_the_figure_in_force`
is the guard.

## Why the flag is on the line and not inferred by the client

A line is an aggregate. `machine` combines a print time with a plate count;
`material` combines a weight with a per-gram price across every material in the
bill. A client holding a list of disputed *fields* cannot work out which lines
they reached without reimplementing the engine's own composition — a second
implementation of exactly the kind Constitution III forbids. So the engine,
which already reduces several origins to the one a line can claim, reduces the
dispute flags the same way: any disputed input makes the line disputed.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core import clock
from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.tenant_pricing_policy import TenantPricingPolicy
from app.services.cost_resolution import model_cost_breakdown
from app.services.provenance import record_origin
from app.services.variance_service import Outcome, consider_outcomes

pytestmark = pytest.mark.asyncio

TODAY = clock.today()


@pytest_asyncio.fixture
async def policy(db_session, test_tenant) -> TenantPricingPolicy:
    row = TenantPricingPolicy(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        print_labor_rate=Decimal("25.00"),
        finishing_labor_rate=Decimal("25.00"),
        overhead_method="per_machine_hour",
        overhead_monthly_pool=Decimal("180.00"),
        expected_monthly_machine_hours=Decimal("600"),
        default_machine_rate_per_hour=Decimal("1.50"),
        margin_basis="customer_total",
        effective_from=TODAY - timedelta(days=60),
    )
    db_session.add(row)
    await db_session.commit()
    return row


@pytest_asyncio.fixture
async def item(db_session, test_tenant, policy) -> Model:
    """A printed item with a measured print time and a measured labour figure.

    Two measured figures so that one can be disputed and the other used as the
    control: a flag that lands on every line carries no information.
    """
    model = Model(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        sku=f"REV-{uuid.uuid4().hex[:6]}",
        name="Item with a figure under review",
        print_time_minutes=60,
        prints_per_plate=1,
        labor_hours_per_item=Decimal("0.25"),
        expected_yield=Decimal("1.0"),
        failure_mode="per_part",
        is_active=True,
    )
    db_session.add(model)
    await db_session.commit()

    for field_name in ("print_time_minutes", "labor_hours_per_item"):
        await record_origin(
            db_session,
            test_tenant,
            entity_type="model",
            entity_id=model.id,
            field_name=field_name,
            source="measured",
            as_of=TODAY - timedelta(days=5),
        )
    await db_session.commit()
    return model


@pytest_asyncio.fixture
async def disputed_print_time(db_session, test_tenant, item) -> None:
    """Three runs agreeing that the print really takes 90 minutes, not 60.

    Enough to propose and far enough out to exceed the divergence threshold,
    so `consider_outcomes` raises a proposal rather than applying it (FR-042b).
    """
    decision = await consider_outcomes(
        db_session,
        test_tenant,
        item,
        entity_type="model",
        field_name="print_time_minutes",
        outcomes=[
            Outcome(run_id=f"run-{index}", value=Decimal("90"), observed_on=TODAY)
            for index in range(3)
        ],
        min_outcomes=3,
        divergence_threshold_pct=Decimal("25"),
    )
    assert decision.proposal is not None, (
        "the fixture must produce a *pending* proposal, not an applied update; "
        "if the engine started applying this the test below proves nothing"
    )
    assert decision.applied is False
    await db_session.commit()


async def _costed(db_session, test_tenant, model_id):
    """The breakdown for one item, from a model loaded the way the endpoint
    loads it.

    The engine never queries -- it reads the object graph it is handed -- so a
    model whose relationships are unloaded raises rather than silently costing
    an item with no bill of materials.
    """
    model = (
        await db_session.execute(
            select(Model)
            .where(Model.id == model_id, Model.tenant_id == test_tenant.id)
            .options(
                selectinload(Model.materials).selectinload(ModelMaterial.spool),
                selectinload(Model.components),
                selectinload(Model.printer_configs),
            )
        )
    ).scalar_one()
    return await model_cost_breakdown(db_session, test_tenant, model)


def _line(breakdown, key: str):
    return next(line for line in breakdown.lines if line.key == key)


class TestTheFlagReachesTheLine:
    async def test_the_line_built_from_the_disputed_figure_is_flagged(
        self, db_session, test_tenant, item, disputed_print_time
    ) -> None:
        """The machine line is priced from the print time under review."""
        breakdown = await _costed(db_session, test_tenant, item.id)

        assert _line(breakdown, "machine").has_pending_revision is True

    async def test_a_line_from_an_undisputed_figure_is_not_flagged(
        self, db_session, test_tenant, item, disputed_print_time
    ) -> None:
        """The control. The labour figure is measured and nobody disputes it."""
        breakdown = await _costed(db_session, test_tenant, item.id)

        assert _line(breakdown, "labor_handling").has_pending_revision is False

    async def test_nothing_is_flagged_when_no_proposal_is_waiting(
        self, db_session, test_tenant, item
    ) -> None:
        """Without the `disputed_print_time` fixture: the same item, no
        proposal, and the same machine line reads clean."""
        breakdown = await _costed(db_session, test_tenant, item.id)

        assert [line.key for line in breakdown.lines if line.has_pending_revision] == []

    async def test_the_amount_is_still_the_figure_in_force(
        self, db_session, test_tenant, item, disputed_print_time
    ) -> None:
        """Constitution VII. 60 minutes at 1.50/hour is 1.50, and the observed
        90 minutes would be 2.25. A sensor that moved this on its own would be
        repricing, which is the whole reason the proposal is pending."""
        breakdown = await _costed(db_session, test_tenant, item.id)

        assert _line(breakdown, "machine").amount == Decimal("1.50")

    async def test_the_dispute_survives_the_same_reduction_that_weakens_the_source(
        self, db_session, test_tenant, item, disputed_print_time
    ) -> None:
        """The two travel together but mean different things.

        The machine line combines the measured print time with a plate count
        nobody has recorded and a rate from policy, so it honestly claims
        `assumed` -- a line is only as good as its weakest input. The dispute
        reduces the other way: *any* disputed input makes the line disputed,
        because the operator needs to know a proposal is waiting even if the
        line it reached was already a weak one.

        Collapsing the two -- treating a disputed figure as no longer measured,
        or an assumed line as beyond dispute -- would lose one fact to the
        other."""
        line = _line(await _costed(db_session, test_tenant, item.id), "machine")

        assert line.source == "assumed", "weakest input wins, and the plate count is unrecorded"
        assert line.has_pending_revision is True, "while the dispute still reaches the line"

    async def test_the_disputed_field_itself_is_still_measured(
        self, db_session, test_tenant, item, disputed_print_time
    ) -> None:
        """The other half of the above, read where the field is reported on its
        own: a measurement does not stop being one because somebody questioned
        it."""
        from app.services.provenance import origins_for_entity

        origins = await origins_for_entity(db_session, test_tenant, "model", item.id)

        assert origins["print_time_minutes"].source == "measured"
        assert origins["print_time_minutes"].as_of == TODAY - timedelta(days=5)

    async def test_accepting_the_proposal_clears_the_flag(
        self, db_session, test_tenant, item, disputed_print_time
    ) -> None:
        """Nothing is pending once it has been reviewed, and the figure the
        operator accepted is the one the line is now priced from."""
        from app.services import variance_service

        pending = await variance_service.list_revisions(
            db_session, test_tenant, state="pending", entity_type="model", entity_id=item.id
        )
        await variance_service.accept_revision(db_session, test_tenant, pending[0].id, user=None)
        await db_session.commit()
        await db_session.refresh(item)

        breakdown = await _costed(db_session, test_tenant, item.id)
        machine = _line(breakdown, "machine")

        assert machine.has_pending_revision is False
        assert machine.amount == Decimal("2.25"), (
            "90 minutes at 1.50/hour once the operator has accepted the reading"
        )


class TestItTravelsOverTheWire:
    async def test_the_breakdown_endpoint_serves_the_flag(
        self, client, item, disputed_print_time
    ) -> None:
        """The field has to be on the response or the badge has nothing to
        read, which is exactly the state this task found it in."""
        response = await client.get(f"/api/v1/models/{item.id}/cost")

        assert response.status_code == 200, response.text
        lines = {line["key"]: line for line in response.json()["lines"]}
        assert lines["machine"]["has_pending_revision"] is True
        assert lines["labor_handling"]["has_pending_revision"] is False
