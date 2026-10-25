"""`/models/{id}/cost-profile` — the printed item's operational figures (T147).

Tier 1 put waste, yield, the failure mode and the four-way labor split on
`Model` and taught the engine to read all of them. Nothing could write them:
every item in every tenant sat at its migration defaults, which are the
superseded model's answer — no purge line, no failure premium, no plate/item
split — dressed as neutral starting values. These routes are the write path
FR-007b requires.

The role rule is the interesting part. A purge weight is a *measurement*, so a
member may record it (FR-007b), while the labor rate and overhead percentage on
the same table are monetary *policy* and need an administrator (FR-007a). A
viewer may read every figure, because visibility of a cost is never restricted
(FR-007c). And a write records where the figure came from (FR-001), which is
what keeps the breakdown able to say how much of a cost is evidence (FR-046).
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model import Model
from app.models.pricing_input_provenance import PricingInputProvenance
from app.models.user import UserRole

pytestmark = pytest.mark.asyncio


def _url(model: Model) -> str:
    return f"/api/v1/models/{model.id}/cost-profile"


async def _origin(
    db_session: AsyncSession, model: Model, field_name: str
) -> PricingInputProvenance | None:
    return (
        await db_session.execute(
            select(PricingInputProvenance).where(
                PricingInputProvenance.tenant_id == model.tenant_id,
                PricingInputProvenance.entity_type == "model",
                PricingInputProvenance.entity_id == model.id,
                PricingInputProvenance.field_name == field_name,
            )
        )
    ).scalar_one_or_none()


# ============================================================================
# Reading
# ============================================================================


class TestReadingTheProfile:
    async def test_it_returns_every_figure_the_engine_reads(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        response = await client.get(_url(test_model))

        assert response.status_code == 200
        body = response.json()
        for field in (
            "print_time_minutes",
            "prints_per_plate",
            "waste_grams",
            "expected_yield",
            "failure_mode",
            "labor_hours_per_plate",
            "labor_hours_per_item",
            "finishing_hours_per_item",
            "packing_hours_per_item",
        ):
            assert field in body, f"{field} is costed by the engine and must be readable"

    async def test_every_numeric_figure_carries_an_origin(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        """FR-001: a figure without a provenance is a figure nobody can weigh."""
        response = await client.get(_url(test_model))

        origins = {entry["field_name"]: entry for entry in response.json()["origins"]}
        assert "failure_mode" not in origins, (
            "the failure mode is a declaration about how a yield is read, "
            "not a measurement, so it has no origin to record"
        )
        for field in ("waste_grams", "expected_yield", "finishing_hours_per_item"):
            assert field in origins
            assert origins[field]["source"] in ("policy", "observed", "measured", "assumed")

    async def test_a_defaulted_figure_reads_as_assumed_rather_than_measured(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        """A migration default is a guess, and must say so (FR-001, FR-046)."""
        origins = {
            e["field_name"]: e for e in (await client.get(_url(test_model))).json()["origins"]
        }

        assert origins["waste_grams"]["source"] == "assumed"
        assert origins["waste_grams"]["as_of"] is None

    async def test_a_missing_print_time_is_reported_not_costed_at_zero(
        self, client: AsyncClient, db_session: AsyncSession, test_model: Model
    ) -> None:
        """FR-019. A zero print time removes the machine line without a word."""
        test_model.print_time_minutes = None
        await db_session.commit()

        body = (await client.get(_url(test_model))).json()

        assert body["incomplete_reasons"], "a missing print time must be named"
        assert any("print time" in reason.lower() for reason in body["incomplete_reasons"])

    async def test_a_viewer_may_read_it(self, as_role, test_model: Model) -> None:
        """FR-007c: visibility of a cost is never restricted by role."""
        async with as_role(UserRole.VIEWER) as ac:
            response = await ac.get(_url(test_model))

        assert response.status_code == 200

    async def test_an_unknown_model_is_404(self, client: AsyncClient) -> None:
        response = await client.get(f"/api/v1/models/{uuid4()}/cost-profile")

        assert response.status_code == 404

    async def test_it_needs_authentication(
        self, unauthenticated_client: AsyncClient, test_model: Model
    ) -> None:
        response = await unauthenticated_client.get(_url(test_model))

        assert response.status_code == 401


# ============================================================================
# Writing
# ============================================================================


class TestWritingTheProfile:
    async def test_it_records_the_figures_the_engine_had_no_way_to_receive(
        self, client: AsyncClient, db_session: AsyncSession, test_model: Model
    ) -> None:
        response = await client.put(
            _url(test_model),
            json={
                "waste_grams": "3.00",
                "expected_yield": "0.92",
                "failure_mode": "per_plate",
                "labor_hours_per_plate": "0.250",
                "finishing_hours_per_item": "0.100",
                "packing_hours_per_item": "0.083",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert Decimal(body["waste_grams"]) == Decimal("3.00")
        assert Decimal(body["expected_yield"]) == Decimal("0.92")
        assert body["failure_mode"] == "per_plate"
        assert Decimal(body["labor_hours_per_plate"]) == Decimal("0.250")

        await db_session.refresh(test_model)
        assert test_model.waste_grams == Decimal("3.00")
        assert test_model.failure_mode == "per_plate"

    async def test_a_field_the_body_does_not_name_is_left_alone(
        self, client: AsyncClient, db_session: AsyncSession, test_model: Model
    ) -> None:
        """Recording the finishing time next week must not erase today's purge."""
        await client.put(_url(test_model), json={"waste_grams": "3.00"})
        await client.put(_url(test_model), json={"finishing_hours_per_item": "0.100"})

        await db_session.refresh(test_model)
        assert test_model.waste_grams == Decimal("3.00")
        assert test_model.finishing_hours_per_item == Decimal("0.100")

    async def test_a_written_figure_records_where_it_came_from(
        self, client: AsyncClient, db_session: AsyncSession, test_model: Model
    ) -> None:
        """FR-001: measured by a person, dated, and attributed."""
        await client.put(_url(test_model), json={"waste_grams": "3.00"})

        origin = await _origin(db_session, test_model, "waste_grams")
        assert origin is not None
        assert origin.source == "measured", (
            "an operator weighing the purge has measured it, not decided it"
        )
        assert origin.as_of is not None
        assert origin.measured_by_user_id is not None

    async def test_it_does_not_record_an_origin_for_a_field_it_did_not_change(
        self, client: AsyncClient, db_session: AsyncSession, test_model: Model
    ) -> None:
        await client.put(_url(test_model), json={"waste_grams": "3.00"})

        assert await _origin(db_session, test_model, "finishing_hours_per_item") is None

    async def test_a_member_may_write_it(
        self, as_role, db_session: AsyncSession, test_model: Model
    ) -> None:
        """FR-007b. These are measurements, not monetary decisions."""
        async with as_role(UserRole.MEMBER) as ac:
            response = await ac.put(_url(test_model), json={"waste_grams": "4.00"})

        assert response.status_code == 200
        await db_session.refresh(test_model)
        assert test_model.waste_grams == Decimal("4.00")

    async def test_the_engine_costs_the_figures_once_they_are_recorded(
        self, client: AsyncClient, db_session: AsyncSession, test_model: Model, test_spool
    ) -> None:
        """The point of the route: a waste line that was absent now exists.

        Purge is costed at the item's own average per-gram filament cost, so
        the model needs a bill of materials for the line to have a price —
        without one the engine reports no waste line rather than costing it at
        zero, which is FR-019 working, not the figure going missing.
        """
        from app.models.model_material import ModelMaterial

        db_session.add(
            ModelMaterial(
                id=uuid4(),
                model_id=test_model.id,
                spool_id=test_spool.id,
                weight_grams=Decimal("142.00"),
                cost_per_gram=Decimal("0.0310"),
            )
        )
        await db_session.commit()

        before = (await client.get(f"/api/v1/models/{test_model.id}/cost")).json()
        assert all(line["key"] != "waste" for line in before["lines"])

        await client.put(_url(test_model), json={"waste_grams": "3.00"})

        after = (await client.get(f"/api/v1/models/{test_model.id}/cost")).json()
        waste = [line for line in after["lines"] if line["key"] == "waste"]
        assert waste, "the waste the operator recorded must appear as its own line (FR-009)"
        # The line is divided across the plate, so it rests on the purge weight
        # *and* on how many parts share the plate. It is only as good as its
        # weaker input, and `prints_per_plate` is still a default here — which
        # is the breakdown being honest, not the origin going missing.
        assert waste[0]["source"] == "assumed"

        await client.put(_url(test_model), json={"prints_per_plate": 1})

        settled = (await client.get(f"/api/v1/models/{test_model.id}/cost")).json()
        waste = [line for line in settled["lines"] if line["key"] == "waste"]
        assert waste[0]["source"] == "measured", (
            "with both of its inputs measured the line must say so (FR-001, FR-018)"
        )

    async def test_a_yield_raises_the_cost_it_was_absent_from(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        """FR-015: a yield below 1.0 must raise the at-risk portion."""
        before = Decimal(
            (await client.get(f"/api/v1/models/{test_model.id}/cost")).json()["total_make_cost"]
        )

        await client.put(_url(test_model), json={"expected_yield": "0.80"})

        after = Decimal(
            (await client.get(f"/api/v1/models/{test_model.id}/cost")).json()["total_make_cost"]
        )
        assert after > before, "a 20% failure rate cannot leave the cost unchanged"

    async def test_a_mode_change_stops_an_observed_yield_claiming_the_new_mode(
        self, client: AsyncClient, db_session: AsyncSession, test_model: Model
    ) -> None:
        """FR-015d: the same figure means different things under each mode.

        The yield stays in use — pricing cannot stop because a mode changed —
        but it must no longer be presented as evidence for a mode it was never
        measured under.
        """
        await client.put(_url(test_model), json={"expected_yield": "0.92"})
        assert (await _origin(db_session, test_model, "expected_yield")).source == "measured"

        await client.put(_url(test_model), json={"failure_mode": "per_plate"})

        await db_session.refresh(test_model)
        assert test_model.expected_yield == Decimal("0.92"), "the figure stays in use"
        origin = await _origin(db_session, test_model, "expected_yield")
        assert origin.source == "assumed", (
            "an observation made under per-part must not read as evidence for per-plate"
        )

    async def test_a_mode_change_reverts_an_observed_yield_to_assumed(
        self, client: AsyncClient, db_session: AsyncSession, test_model: Model, test_tenant
    ) -> None:
        """The "yield observed under one failure mode" edge case (T256).

        An observed yield is read-only to the operator (FR-004), which used to
        mean the mode change logged a warning and left it claiming to be
        evidence. It reverts, and the learning sweep reads only runs completed
        from the day of the change.
        """
        from app.core import clock
        from app.services.provenance import record_origin

        await record_origin(
            db_session,
            test_tenant,
            entity_type="model",
            entity_id=test_model.id,
            field_name="expected_yield",
            source="observed",
            automated=True,
        )
        await db_session.commit()

        response = await client.put(_url(test_model), json={"failure_mode": "per_plate"})

        assert response.status_code == 200
        await db_session.refresh(test_model)
        assert test_model.failure_mode_since == clock.today()
        origin = await _origin(db_session, test_model, "expected_yield")
        await db_session.refresh(origin)
        assert origin.source == "assumed"

    async def test_a_mode_change_with_a_new_yield_keeps_that_yield_measured(
        self, client: AsyncClient, db_session: AsyncSession, test_model: Model
    ) -> None:
        """Supplying both is the operator saying the figure is for the new mode."""
        await client.put(
            _url(test_model),
            json={"failure_mode": "per_plate", "expected_yield": "0.88"},
        )

        origin = await _origin(db_session, test_model, "expected_yield")
        assert origin.source == "measured"

    async def test_an_empty_body_changes_nothing(
        self, client: AsyncClient, db_session: AsyncSession, test_model: Model
    ) -> None:
        response = await client.put(_url(test_model), json={})

        assert response.status_code == 200
        assert await _origin(db_session, test_model, "waste_grams") is None

    async def test_an_unknown_model_is_404(self, client: AsyncClient) -> None:
        response = await client.put(
            f"/api/v1/models/{uuid4()}/cost-profile", json={"waste_grams": "3.00"}
        )

        assert response.status_code == 404

    async def test_it_needs_authentication(
        self, unauthenticated_client: AsyncClient, test_model: Model
    ) -> None:
        response = await unauthenticated_client.put(_url(test_model), json={"waste_grams": "3.00"})

        assert response.status_code == 401


# ============================================================================
# Validation
# ============================================================================


class TestValidation:
    @pytest.mark.parametrize(
        "payload",
        [
            {"expected_yield": "0"},
            {"expected_yield": "1.5"},
            {"expected_yield": "-0.5"},
        ],
    )
    async def test_a_yield_outside_the_open_unit_interval_is_refused(
        self, client: AsyncClient, test_model: Model, payload: dict
    ) -> None:
        """A yield of zero means nothing succeeds, which has no cost per part."""
        response = await client.put(_url(test_model), json=payload)

        assert response.status_code == 422

    async def test_an_unknown_failure_mode_is_refused(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        response = await client.put(_url(test_model), json={"failure_mode": "per_build"})

        assert response.status_code == 422

    async def test_a_negative_waste_is_refused(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        response = await client.put(_url(test_model), json={"waste_grams": "-1.00"})

        assert response.status_code == 422

    async def test_a_plate_holding_no_parts_is_refused(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        """Dividing per-plate labor across zero parts has no answer (FR-013)."""
        response = await client.put(_url(test_model), json={"prints_per_plate": 0})

        assert response.status_code == 422

    async def test_a_mistyped_field_is_refused_rather_than_ignored(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        """A field that silently did nothing would leave the operator sure they
        had entered a yield."""
        response = await client.put(_url(test_model), json={"expected_yeild": "0.92"})

        assert response.status_code == 422
