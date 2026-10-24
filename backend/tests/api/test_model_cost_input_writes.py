"""Every path that writes a model's cost inputs (tasks T217, T225, T227, T229).

Four rules, each of which used to hold on one route and not on its siblings:

* **A per-item rate is policy (T217).** `labor_rate_override` replaces the
  tenant's labour rate for the item and `overhead_percentage` its overhead
  percentage. `POST /models`, `PUT /models/{id}` and the CSV import accepted
  both from any role and wrote no origin; they now need the owner or admin and
  record the figure as `policy` with the role that set it.
* **A viewer is a reader (T227).** Every write route here refuses one.
* **A measurement says who measured it (T229).** A plate time or a BOM weight
  a person entered is `measured`, dated, against them -- not `assumed` from
  the migration date forever -- and one telemetry observed is refused rather
  than typed over.
* **The import writes what the engine reads (T225).** Exact decimals, into
  the per-item labour column, with origins, and the columns it reads past
  reported as ignored.
"""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model import Model
from app.models.model_component import ModelComponent
from app.models.model_material import ModelMaterial
from app.models.pricing_input_provenance import PricingInputProvenance
from app.models.user import UserRole
from app.services.provenance import record_origin

pytestmark = pytest.mark.asyncio

URL = "/api/v1/models"


async def _origin(
    db_session: AsyncSession, entity_type: str, entity_id, field_name: str
) -> PricingInputProvenance | None:
    db_session.expire_all()
    return (
        await db_session.execute(
            select(PricingInputProvenance).where(
                PricingInputProvenance.entity_type == entity_type,
                PricingInputProvenance.entity_id == entity_id,
                PricingInputProvenance.field_name == field_name,
            )
        )
    ).scalar_one_or_none()


def _create_body(**overrides) -> dict:
    body = {"sku": f"CI-{uuid4().hex[:8]}", "name": "Cost input item"}
    body.update(overrides)
    return body


def _csv(rows: str) -> dict:
    return {"file": ("models.csv", rows.encode(), "text/csv")}


# ============================================================================
# Per-item rate and overhead: owner or admin only (T217)
# ============================================================================


class TestAPerItemRateNeedsAnAdministrator:
    @pytest.mark.parametrize(
        ("field", "value"), [("labor_rate_override", "45.00"), ("overhead_percentage", "15")]
    )
    @pytest.mark.parametrize("role", [UserRole.MEMBER, UserRole.VIEWER])
    async def test_create_refuses_it(self, as_role, db_session, field, value, role) -> None:
        body = _create_body(**{field: value})

        async with as_role(role) as caller:
            response = await caller.post(URL, json=body)

        assert response.status_code == 403
        found = await db_session.execute(select(Model).where(Model.sku == body["sku"]))
        assert found.scalar_one_or_none() is None

    @pytest.mark.parametrize(
        ("field", "value"), [("labor_rate_override", "45.00"), ("overhead_percentage", "15")]
    )
    @pytest.mark.parametrize("role", [UserRole.MEMBER, UserRole.VIEWER])
    async def test_update_refuses_it_and_leaves_figure_and_origin(
        self, as_role, db_session, test_model, field, value, role
    ) -> None:
        before = getattr(test_model, field)

        async with as_role(role) as caller:
            response = await caller.put(f"{URL}/{test_model.id}", json={field: value})

        assert response.status_code == 403
        await db_session.refresh(test_model)
        assert getattr(test_model, field) == before
        assert await _origin(db_session, "model", test_model.id, field) is None

    @pytest.mark.parametrize("role", [UserRole.MEMBER, UserRole.VIEWER])
    async def test_import_refuses_an_overhead_percentage(
        self, as_role, db_session, test_model, role
    ) -> None:
        async with as_role(role) as caller:
            response = await caller.post(
                f"{URL}/import",
                files=_csv(f"name,sku,overhead_percentage\nRenamed,{test_model.sku},15\n"),
            )

        if role == UserRole.VIEWER:
            assert response.status_code == 403
        else:
            assert response.status_code == 200
            assert response.json()["skipped"] == 1
            assert "owner or admin" in response.json()["errors"][0]
        await db_session.refresh(test_model)
        assert test_model.overhead_percentage != Decimal("15")

    async def test_an_admin_sets_it_and_it_is_recorded_as_policy(
        self, client: AsyncClient, db_session, test_model
    ) -> None:
        response = await client.put(f"{URL}/{test_model.id}", json={"labor_rate_override": "45.00"})

        assert response.status_code == 200, response.text
        origin = await _origin(db_session, "model", test_model.id, "labor_rate_override")
        assert origin.source == "policy"
        assert origin.authorised_by_role in {"admin", "owner"}
        assert origin.measured_by_user_id is not None

    async def test_a_member_may_still_change_an_operational_figure(
        self, as_role, test_model
    ) -> None:
        async with as_role(UserRole.MEMBER) as member:
            response = await member.put(f"{URL}/{test_model.id}", json={"name": "Member edit"})

        assert response.status_code == 200


# ============================================================================
# A viewer writes nothing (T227)
# ============================================================================


class TestAViewerIsRefusedEveryWrite:
    async def test_create(self, as_role) -> None:
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.post(URL, json=_create_body())
        assert response.status_code == 403

    async def test_update(self, as_role, test_model) -> None:
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.put(f"{URL}/{test_model.id}", json={"name": "Viewer"})
        assert response.status_code == 403

    async def test_cost_profile(self, as_role, test_model) -> None:
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.put(
                f"{URL}/{test_model.id}/cost-profile", json={"waste_grams": "3"}
            )
        assert response.status_code == 403

    async def test_bill_of_materials(self, as_role, test_model, test_spool) -> None:
        async with as_role(UserRole.VIEWER) as viewer:
            material = await viewer.post(
                f"{URL}/{test_model.id}/materials",
                json={
                    "spool_id": str(test_spool.id),
                    "weight_grams": "10",
                    "cost_per_gram": "0.03",
                },
            )
            component = await viewer.post(
                f"{URL}/{test_model.id}/components",
                json={"component_name": "Magnet", "quantity": 2, "unit_cost": "0.10"},
            )
        assert material.status_code == 403
        assert component.status_code == 403

    async def test_delete(self, as_role, test_model) -> None:
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.delete(f"{URL}/{test_model.id}")
        assert response.status_code == 403

    async def test_import(self, as_role) -> None:
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.post(f"{URL}/import", files=_csv("name,sku\nA,VIEW-1\n"))
        assert response.status_code == 403

    async def test_a_viewer_may_still_read(self, as_role, test_model) -> None:
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.get(f"{URL}/{test_model.id}")
        assert response.status_code == 200


# ============================================================================
# A measurement records who measured it; an observation is not typed over
# (T229)
# ============================================================================


class TestAMeasurementSaysWhoMeasuredIt:
    async def test_a_changed_print_time_is_recorded_as_measured(
        self, client: AsyncClient, db_session, test_model
    ) -> None:
        response = await client.put(
            f"{URL}/{test_model.id}", json={"print_time_minutes": test_model.print_time_minutes + 7}
        )

        assert response.status_code == 200, response.text
        origin = await _origin(db_session, "model", test_model.id, "print_time_minutes")
        assert origin.source == "measured"
        assert origin.measured_by_user_id is not None

    async def test_resending_an_unchanged_figure_does_not_restamp_it(
        self, client: AsyncClient, db_session, test_model
    ) -> None:
        response = await client.put(
            f"{URL}/{test_model.id}", json={"print_time_minutes": test_model.print_time_minutes}
        )

        assert response.status_code == 200
        assert await _origin(db_session, "model", test_model.id, "print_time_minutes") is None

    async def test_an_observed_figure_is_refused_and_keeps_its_label(
        self, client: AsyncClient, db_session, test_model, test_tenant
    ) -> None:
        await record_origin(
            db_session,
            test_tenant,
            entity_type="model",
            entity_id=test_model.id,
            field_name="print_time_minutes",
            source="observed",
            automated=True,
        )
        await db_session.commit()
        before = test_model.print_time_minutes

        response = await client.put(
            f"{URL}/{test_model.id}", json={"print_time_minutes": before + 30}
        )

        assert response.status_code == 409
        await db_session.refresh(test_model)
        assert test_model.print_time_minutes == before
        origin = await _origin(db_session, "model", test_model.id, "print_time_minutes")
        assert origin.source == "observed"

    async def test_a_created_model_records_the_figures_it_was_given(
        self, client: AsyncClient, db_session
    ) -> None:
        response = await client.post(URL, json=_create_body(print_time_minutes=95))

        assert response.status_code == 201, response.text
        model_id = UUID(response.json()["id"])
        origin = await _origin(db_session, "model", model_id, "print_time_minutes")
        assert origin.source == "measured"
        # A figure the body did not name stays an assumption.
        assert await _origin(db_session, "model", model_id, "prints_per_plate") is None

    async def test_a_bom_line_records_its_weight_and_rate(
        self, client: AsyncClient, db_session, test_model, test_spool
    ) -> None:
        response = await client.post(
            f"{URL}/{test_model.id}/materials",
            json={"spool_id": str(test_spool.id), "weight_grams": "10", "cost_per_gram": "0.03"},
        )

        assert response.status_code == 201, response.text
        material = (
            await db_session.execute(
                select(ModelMaterial).where(ModelMaterial.id == UUID(response.json()["id"]))
            )
        ).scalar_one()
        material_id = material.id
        for field in ("weight_grams", "cost_per_gram"):
            origin = await _origin(db_session, "model_material", material_id, field)
            assert origin.source == "measured", field

    async def test_a_component_records_its_quantity_and_unit_cost(
        self, client: AsyncClient, db_session, test_model
    ) -> None:
        response = await client.post(
            f"{URL}/{test_model.id}/components",
            json={"component_name": "Magnet", "quantity": 2, "unit_cost": "0.10"},
        )

        assert response.status_code == 201, response.text
        component = (
            await db_session.execute(
                select(ModelComponent).where(ModelComponent.id == UUID(response.json()["id"]))
            )
        ).scalar_one()
        component_id = component.id
        for field in ("quantity", "unit_cost"):
            origin = await _origin(db_session, "model_component", component_id, field)
            assert origin.source == "measured", field


# ============================================================================
# The import writes what the engine reads (T225)
# ============================================================================


class TestTheImportWritesWhatTheEngineReads:
    async def test_labour_hours_go_to_the_per_item_column_with_an_origin(
        self, client: AsyncClient, db_session, test_model
    ) -> None:
        response = await client.post(
            f"{URL}/import",
            files=_csv(f"name,sku,labor_hours\nImported,{test_model.sku},0.35\n"),
        )

        assert response.status_code == 200, response.text
        await db_session.refresh(test_model)
        # The engine reads the per-item figure; the deprecated one would have
        # changed nothing on a model with a profile.
        assert test_model.labor_hours_per_item == Decimal("0.35")
        origin = await _origin(db_session, "model", test_model.id, "labor_hours_per_item")
        assert origin.source == "measured"
        assert origin.measured_by_user_id is not None

    async def test_a_blank_cell_leaves_the_figure_alone(
        self, client: AsyncClient, db_session, test_model
    ) -> None:
        test_model.labor_hours_per_item = Decimal("0.5")
        await db_session.commit()

        response = await client.post(
            f"{URL}/import", files=_csv(f"name,sku,labor_hours\nImported,{test_model.sku},\n")
        )

        assert response.status_code == 200
        await db_session.refresh(test_model)
        assert test_model.labor_hours_per_item == Decimal("0.5")

    async def test_ignored_columns_are_reported(self, client: AsyncClient, test_model) -> None:
        response = await client.post(
            f"{URL}/import",
            files=_csv(f"name,sku,labor_rate,cost,sell\nImported,{test_model.sku},25,4,12\n"),
        )

        assert response.status_code == 200
        ignored = response.json()["ignored"]
        assert len(ignored) == 3
        assert any("labor_rate" in line for line in ignored)

    async def test_an_observed_figure_skips_the_row(
        self, client: AsyncClient, db_session, test_model, test_tenant
    ) -> None:
        await record_origin(
            db_session,
            test_tenant,
            entity_type="model",
            entity_id=test_model.id,
            field_name="print_time_minutes",
            source="observed",
            automated=True,
        )
        await db_session.commit()

        response = await client.post(
            f"{URL}/import", files=_csv(f"name,sku,print time\nImported,{test_model.sku},999\n")
        )

        assert response.json()["skipped"] == 1
        await db_session.refresh(test_model)
        assert test_model.print_time_minutes != 999
