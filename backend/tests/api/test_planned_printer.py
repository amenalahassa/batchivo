"""An item is costed on the machine it is planned on (T243, FR-011).

The engine used a printer only when a caller passed `printer_id` to
`GET /models/{id}/cost`, so every product cost, margin, solve, snapshot and the
queue ranking used the policy's default machine rate. The cost profile now
records a planned machine, every cost read uses it, and a queue job assigned to
another machine is costed on that one.
"""

from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model import Model
from app.models.printer import Printer
from app.models.product import Product
from app.models.product_model import ProductModel
from app.models.tenant import Tenant
from app.models.user import UserRole

API = "/api/v1"


async def _costly(db_session: AsyncSession, printer: Printer) -> Printer:
    printer.purchase_price = Decimal("1100.00")
    printer.expected_lifetime_hours = 6000
    await db_session.commit()
    return printer


async def _product_of(db_session: AsyncSession, tenant: Tenant, model: Model) -> Product:
    product = Product(
        id=uuid4(),
        tenant_id=tenant.id,
        sku=f"PLAN-{uuid4().hex[:6]}",
        name="Planned product",
        is_active=True,
    )
    product.product_models.append(ProductModel(id=uuid4(), model_id=model.id, quantity=1))
    db_session.add(product)
    await db_session.commit()
    return product


async def _plan(client: AsyncClient, model_id, printer_id) -> dict:
    response = await client.put(
        f"{API}/models/{model_id}/cost-profile",
        json={"planned_printer_id": str(printer_id) if printer_id else None},
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestRecordingThePlannedMachine:
    async def test_a_member_plans_an_item_on_a_machine(
        self, as_role, test_model: Model, test_printer: Printer
    ) -> None:
        model_id, printer_id = test_model.id, test_printer.id
        async with as_role(UserRole.MEMBER) as member:
            body = await _plan(member, model_id, printer_id)
        assert body["planned_printer_id"] == str(printer_id)
        assert body["planned_printer_name"] == "Bambu A1 Mini"

    async def test_a_viewer_cannot(self, as_role, test_model: Model, test_printer: Printer) -> None:
        model_id, printer_id = test_model.id, test_printer.id
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.put(
                f"{API}/models/{model_id}/cost-profile",
                json={"planned_printer_id": str(printer_id)},
            )
        assert response.status_code == 403

    async def test_an_unknown_printer_is_a_404(
        self, client: AsyncClient, test_model: Model
    ) -> None:
        response = await client.put(
            f"{API}/models/{test_model.id}/cost-profile",
            json={"planned_printer_id": str(uuid4())},
        )
        assert response.status_code == 404

    async def test_null_clears_it_and_omitting_it_leaves_it(
        self, client: AsyncClient, test_model: Model, test_printer: Printer
    ) -> None:
        model_id = test_model.id
        await _plan(client, model_id, test_printer.id)
        kept = await client.put(f"{API}/models/{model_id}/cost-profile", json={"waste_grams": "2"})
        assert kept.json()["planned_printer_id"] == str(test_printer.id)
        cleared = await _plan(client, model_id, None)
        assert cleared["planned_printer_id"] is None


class TestEveryReadUsesIt:
    async def test_the_item_cost_carries_the_machine_line_without_being_asked(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_model: Model,
        test_printer: Printer,
    ) -> None:
        await _costly(db_session, test_printer)
        model_id = test_model.id
        default = (await client.get(f"{API}/models/{model_id}/cost")).json()
        await _plan(client, model_id, test_printer.id)
        planned = (await client.get(f"{API}/models/{model_id}/cost")).json()

        assert "machine" in {line["key"] for line in planned["lines"]}
        assert Decimal(planned["total_make_cost"]) > Decimal(default["total_make_cost"])

    async def test_a_product_of_that_item_costs_more_and_every_read_agrees(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_model: Model,
        test_printer: Printer,
    ) -> None:
        await _costly(db_session, test_printer)
        product = await _product_of(db_session, test_tenant, test_model)
        product_id = product.id
        before = Decimal(
            (await client.get(f"{API}/products/{product_id}/cost")).json()["total_make_cost"]
        )

        await _plan(client, test_model.id, test_printer.id)
        engine = Decimal(
            (await client.get(f"{API}/products/{product_id}/cost")).json()["total_make_cost"]
        )
        detail = Decimal(
            (await client.get(f"{API}/products/{product_id}")).json()["cost_breakdown"][
                "total_make_cost"
            ]
        )
        assert engine > before
        assert engine.quantize(Decimal("0.01")) == detail

    async def test_an_explicit_printer_still_overrides_the_plan(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_model: Model,
        test_printer: Printer,
    ) -> None:
        await _costly(db_session, test_printer)
        cheap = Printer(
            id=uuid4(),
            tenant_id=test_tenant.id,
            name="Cheap printer",
            purchase_price=Decimal("120.00"),
            expected_lifetime_hours=6000,
            is_active=True,
        )
        db_session.add(cheap)
        await db_session.commit()
        model_id = test_model.id

        await _plan(client, model_id, test_printer.id)
        planned = (await client.get(f"{API}/models/{model_id}/cost")).json()
        asked = (
            await client.get(f"{API}/models/{model_id}/cost", params={"printer_id": str(cheap.id)})
        ).json()
        assert Decimal(asked["total_make_cost"]) < Decimal(planned["total_make_cost"])
