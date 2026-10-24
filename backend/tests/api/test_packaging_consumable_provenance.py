"""The packaging line says where the consumable's price came from (T249, FR-001).

A product linked to a packaging consumable takes the line's amount from the
consumable's unit cost, but took the line's origin from the product's
packaging quantity, so the figure that set the amount showed no source. The
unit cost now records who entered it, and the line reads that.
"""

from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consumable import ConsumableType
from app.models.product import Product
from app.models.tenant import Tenant
from app.models.user import UserRole

API = "/api/v1"


async def _packaged_product(
    db_session: AsyncSession, tenant: Tenant
) -> tuple[Product, ConsumableType]:
    box = ConsumableType(
        id=uuid4(),
        tenant_id=tenant.id,
        sku=f"BOX-{uuid4().hex[:6]}".upper(),
        name="Small box",
        unit_of_measure="each",
        current_cost_per_unit=Decimal("0.4500"),
        quantity_on_hand=100,
        is_active=True,
    )
    db_session.add(box)
    await db_session.flush()
    product = Product(
        id=uuid4(),
        tenant_id=tenant.id,
        sku=f"PACK-{uuid4().hex[:6]}",
        name="Packaged product",
        packaging_consumable_id=box.id,
        packaging_quantity=2,
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()
    return product, box


def _packaging_line(body: dict) -> dict:
    lines = [line for line in body["lines"] if line["key"] == "packaging"]
    assert lines, f"no packaging line in {body['lines']}"
    return lines[0]


class TestThePackagingLineCarriesTheConsumableOrigin:
    async def test_an_untouched_unit_cost_reads_as_assumed(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        product, _box = await _packaged_product(db_session, test_tenant)
        body = (await client.get(f"{API}/products/{product.id}/cost")).json()
        line = _packaging_line(body)
        assert Decimal(line["amount"]) == Decimal("0.90")
        assert line["source"] == "assumed"

    async def test_a_unit_cost_a_member_enters_reads_as_measured(
        self, as_role, client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        product, box = await _packaged_product(db_session, test_tenant)
        product_id, box_id = product.id, box.id
        async with as_role(UserRole.MEMBER) as member:
            response = await member.put(
                f"{API}/consumables/types/{box_id}", json={"current_cost_per_unit": "0.5000"}
            )
        assert response.status_code == 200, response.text

        line = _packaging_line((await client.get(f"{API}/products/{product_id}/cost")).json())
        assert Decimal(line["amount"]) == Decimal("1.00")
        assert line["source"] == "measured"
        assert line["as_of"] is not None

    async def test_changing_the_quantity_alone_does_not_claim_the_price_was_measured(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        product, _box = await _packaged_product(db_session, test_tenant)
        product_id = product.id
        await client.put(f"{API}/products/{product_id}", json={"packaging_quantity": 3})
        line = _packaging_line((await client.get(f"{API}/products/{product_id}/cost")).json())
        assert line["source"] == "assumed"
