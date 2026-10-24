"""Who may write a cost input, and what a write records (tasks T227, T229).

**A viewer is a reader (T227).** There was no member-level guard, so every
route that took only `CurrentUser` accepted a viewer: spools and their price,
consumables and their unit cost, filament purchases, the bill of materials on
products, printer power readings, production-run actuals, and the routes the
contract marks *member* -- `POST /scenarios`, the estimate-revision decisions
and the fee-rule preview. Each is walked here with a viewer, by a random id:
the role is refused before the record is looked up, so no fixture is needed
and none can mask a missing guard.

**A write says who made it (T229).** Every console writer of a registered
input records `measured` (or `policy` for an operator decision) with the user
and date, and refuses to type over an `observed` figure -- one test per
writer.
"""

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pricing_input_provenance import PricingInputProvenance
from app.models.user import UserRole
from app.services.provenance import record_origin

pytestmark = pytest.mark.asyncio

API = "/api/v1"
ANY = "00000000-0000-0000-0000-000000000001"

#: Every write route that touches a figure in scope and that FR-007b/c put
#: with the member. A viewer must be refused each one.
MEMBER_WRITES: list[tuple[str, str]] = [
    ("POST", "/spools"),
    ("PUT", f"/spools/{ANY}"),
    ("DELETE", f"/spools/{ANY}"),
    ("POST", f"/spools/{ANY}/duplicate"),
    ("POST", "/consumables/types"),
    ("PUT", f"/consumables/types/{ANY}"),
    ("DELETE", f"/consumables/types/{ANY}"),
    ("POST", f"/consumables/types/{ANY}/adjust-stock"),
    ("POST", "/consumables/purchases"),
    ("DELETE", f"/consumables/purchases/{ANY}"),
    ("POST", "/consumables/usage"),
    ("POST", "/filament-purchases"),
    ("PUT", f"/filament-purchases/{ANY}"),
    ("DELETE", f"/filament-purchases/{ANY}"),
    ("PUT", f"/products/{ANY}"),
    ("POST", f"/products/{ANY}/models"),
    ("PUT", f"/products/{ANY}/models/{ANY}"),
    ("DELETE", f"/products/{ANY}/models/{ANY}"),
    ("POST", f"/products/{ANY}/pricing"),
    ("PUT", f"/products/{ANY}/pricing/{ANY}"),
    ("DELETE", f"/products/{ANY}/pricing/{ANY}"),
    ("POST", f"/products/{ANY}/components"),
    ("PUT", f"/products/{ANY}/components/{ANY}"),
    ("DELETE", f"/products/{ANY}/components/{ANY}"),
    ("POST", "/printers"),
    ("PUT", f"/printers/{ANY}"),
    ("DELETE", f"/printers/{ANY}"),
    ("POST", f"/printers/{ANY}/power-readings"),
    ("POST", "/production-runs"),
    ("PATCH", f"/production-runs/{ANY}"),
    ("POST", f"/production-runs/{ANY}/items"),
    ("PATCH", f"/production-runs/{ANY}/items/{ANY}"),
    ("POST", f"/production-runs/{ANY}/materials"),
    ("PATCH", f"/production-runs/{ANY}/materials/{ANY}"),
    ("POST", f"/production-runs/{ANY}/complete"),
    ("POST", f"/production-runs/{ANY}/cancel"),
    ("POST", f"/production-runs/{ANY}/fail"),
    ("POST", f"/production-runs/{ANY}/plates"),
    ("PATCH", f"/production-runs/{ANY}/plates/{ANY}"),
    ("POST", f"/production-runs/{ANY}/plates/{ANY}/complete"),
    ("POST", "/scenarios"),
    ("POST", f"/estimate-revisions/{ANY}/accept"),
    ("POST", f"/estimate-revisions/{ANY}/reject"),
    ("POST", f"/sales-channels/{ANY}/fee-rules/preview"),
]


async def _call(client: AsyncClient, method: str, path: str):
    url = f"{API}{path}"
    if method == "DELETE":
        return await client.delete(url)
    return await client.request(method, url, json={})


class TestAViewerIsRefusedEveryCostWrite:
    @pytest.mark.parametrize(("method", "path"), MEMBER_WRITES)
    async def test_refused(self, as_role, method: str, path: str) -> None:
        async with as_role(UserRole.VIEWER) as viewer:
            response = await _call(viewer, method, path)

        assert response.status_code == 403, (
            f"{method} {path} accepted a viewer ({response.status_code}); FR-007c makes "
            f"the viewer a reader"
        )

    @pytest.mark.parametrize(("method", "path"), MEMBER_WRITES)
    async def test_every_listed_route_exists(self, client: AsyncClient, method, path) -> None:
        # A typo above would be refused for a viewer as surely as a real route
        # -- by a 404 or a 405 rather than a 403, but a sweep that only checked
        # "not allowed" would miss it. An administrator's call proves the route
        # is there: the framework's own "Not Found" and 405 mean it is not.
        response = await _call(client, method, path)

        assert response.status_code != 405, f"{method} {path} is not a route"
        assert not (response.status_code == 404 and response.json().get("detail") == "Not Found"), (
            f"{method} {path} is not a route"
        )


# ============================================================================
# Each writer records where its figures came from (T229)
# ============================================================================


async def _origin(db_session: AsyncSession, entity_type: str, entity_id, field_name: str):
    return (
        await db_session.execute(
            select(PricingInputProvenance).where(
                PricingInputProvenance.entity_type == entity_type,
                PricingInputProvenance.entity_id == entity_id,
                PricingInputProvenance.field_name == field_name,
            )
        )
    ).scalar_one_or_none()


async def _observe(db_session, tenant, entity_type: str, entity_id, field_name: str) -> None:
    await record_origin(
        db_session,
        tenant,
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        source="observed",
        automated=True,
    )
    await db_session.commit()


class TestSpoolWrites:
    async def test_create_records_the_price_and_weight(
        self, client: AsyncClient, db_session, test_spool
    ) -> None:
        response = await client.post(
            f"{API}/spools",
            json={
                "spool_id": f"FIL-{uuid4().hex[:6]}",
                "filament_type_id": str(test_spool.filament_type_id),
                "initial_weight": "1000",
                "current_weight": "1000",
                "purchase_price": "24.99",
            },
        )

        assert response.status_code == 201, response.text
        spool_id = UUID(response.json()["id"])
        for field in ("purchase_price", "initial_weight"):
            origin = await _origin(db_session, "spool", spool_id, field)
            assert origin is not None and origin.source == "measured", field

    async def test_update_records_a_changed_price(
        self, client: AsyncClient, db_session, test_spool
    ) -> None:
        response = await client.put(
            f"{API}/spools/{test_spool.id}", json={"purchase_price": "31.50"}
        )

        assert response.status_code == 200, response.text
        origin = await _origin(db_session, "spool", test_spool.id, "purchase_price")
        assert origin.source == "measured"
        assert origin.measured_by_user_id is not None

    async def test_update_refuses_an_observed_figure(
        self, client: AsyncClient, db_session, test_spool, test_tenant
    ) -> None:
        spool_id = test_spool.id
        await _observe(db_session, test_tenant, "spool", spool_id, "initial_weight")

        response = await client.put(f"{API}/spools/{spool_id}", json={"initial_weight": "1"})

        assert response.status_code == 409
        origin = await _origin(db_session, "spool", spool_id, "initial_weight")
        assert origin.source == "observed"

    async def test_duplicate_records_the_copy_as_this_persons(
        self, client: AsyncClient, db_session, test_spool
    ) -> None:
        response = await client.post(f"{API}/spools/{test_spool.id}/duplicate")

        assert response.status_code == 201, response.text
        origin = await _origin(db_session, "spool", UUID(response.json()["id"]), "initial_weight")
        assert origin.source == "measured"


class TestFilamentPurchaseWrites:
    async def test_create_and_update_record_the_shipping(
        self, client: AsyncClient, db_session
    ) -> None:
        created = await client.post(
            f"{API}/filament-purchases",
            json={
                "supplier": "Prusament",
                "purchase_date": "2026-06-01",
                "inbound_shipping_cost": "12.00",
                "tax_amount": "3.00",
            },
        )
        assert created.status_code == 201, created.text
        purchase_id = UUID(created.json()["id"])
        assert (
            await _origin(db_session, "filament_purchase", purchase_id, "inbound_shipping_cost")
        ).source == "measured"

        updated = await client.put(
            f"{API}/filament-purchases/{purchase_id}", json={"tax_amount": "4.00"}
        )

        assert updated.status_code == 200, updated.text
        assert (
            await _origin(db_session, "filament_purchase", purchase_id, "tax_amount")
        ).source == "measured"


class TestProductWrites:
    async def test_update_records_the_packaging_cost(
        self, client: AsyncClient, db_session, test_product
    ) -> None:
        response = await client.put(
            f"{API}/products/{test_product.id}", json={"packaging_cost": "1.35"}
        )

        assert response.status_code == 200, response.text
        origin = await _origin(db_session, "product", test_product.id, "packaging_cost")
        assert origin.source == "measured"

    async def test_update_refuses_an_observed_figure(
        self, client: AsyncClient, db_session, test_product, test_tenant
    ) -> None:
        await _observe(db_session, test_tenant, "product", test_product.id, "assembly_minutes")

        response = await client.put(
            f"{API}/products/{test_product.id}", json={"assembly_minutes": "45"}
        )

        assert response.status_code == 409


class TestPrinterCostPolicyWrites:
    async def test_policy_figures_are_policy_and_the_draw_is_measured(
        self, client: AsyncClient, db_session, test_printer
    ) -> None:
        response = await client.put(
            f"{API}/printers/{test_printer.id}/cost-policy",
            json={
                "purchase_price": "1200.00",
                "expected_lifetime_hours": 10000,
                "measured_watts": "140",
            },
        )

        assert response.status_code == 200, response.text
        price = await _origin(db_session, "printer", test_printer.id, "purchase_price")
        draw = await _origin(db_session, "printer", test_printer.id, "measured_watts")
        assert price.source == "policy"
        assert price.authorised_by_role in {"admin", "owner"}
        assert draw.source == "measured"

    async def test_an_observed_draw_is_refused(
        self, client: AsyncClient, db_session, test_printer, test_tenant
    ) -> None:
        await _observe(db_session, test_tenant, "printer", test_printer.id, "measured_watts")

        response = await client.put(
            f"{API}/printers/{test_printer.id}/cost-policy", json={"measured_watts": "300"}
        )

        assert response.status_code == 409


class TestModelPrinterConfigWrites:
    async def test_the_service_records_and_refuses(
        self, db_session, test_tenant, test_user, test_model, test_printer
    ) -> None:
        from app.schemas.model_printer_config import (
            ModelPrinterConfigCreate,
            ModelPrinterConfigUpdate,
        )
        from app.services.model_printer_config_service import ModelPrinterConfigService
        from app.services.provenance import ProvenanceNotEditable

        service = ModelPrinterConfigService(db_session, test_tenant, test_user)
        config = await service.create_config(
            ModelPrinterConfigCreate(
                model_id=test_model.id,
                printer_id=test_printer.id,
                prints_per_plate=4,
                print_time_minutes=90,
            )
        )
        config_id, user_id = config.id, test_user.id
        origin = await _origin(db_session, "model_printer_config", config_id, "print_time_minutes")
        assert origin.source == "measured"
        assert origin.measured_by_user_id == user_id

        await _observe(
            db_session, test_tenant, "model_printer_config", config_id, "prints_per_plate"
        )
        with pytest.raises(ProvenanceNotEditable):
            await service.update_config(config_id, ModelPrinterConfigUpdate(prints_per_plate=6))
        await db_session.rollback()
        await db_session.refresh(test_tenant)
        refreshed = await service.get_config(config_id)
        assert refreshed.prints_per_plate == 4


def test_the_member_write_list_names_a_router_per_area() -> None:
    # Guard against the list silently shrinking: every area T227 names keeps
    # at least one route here.
    areas = {path.split("/")[1] for _, path in MEMBER_WRITES}
    assert {
        "spools",
        "consumables",
        "filament-purchases",
        "products",
        "printers",
        "production-runs",
        "scenarios",
        "estimate-revisions",
        "sales-channels",
    } <= areas
