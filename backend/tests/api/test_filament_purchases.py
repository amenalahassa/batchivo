"""`/filament-purchases` — buying events and their per-spool landed cost (T048a).

FR-008a records the purchase rather than the per-gram figure the operator
worked out by hand, and FR-008b allocates its inbound shipping across the
spools by weight. The allocation is the reason this resource exists, so it is
asserted in the response and not only in the service's unit tests.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.filament_purchase import FilamentPurchase
from app.models.spool import Spool
from app.models.tenant import Tenant

pytestmark = pytest.mark.asyncio

ENDPOINT = "/api/v1/filament-purchases"


async def _spool(
    db_session: AsyncSession,
    tenant: Tenant,
    filament_type,
    *,
    purchase: FilamentPurchase | None = None,
    initial_weight: Decimal = Decimal("1000"),
    purchase_price: Decimal = Decimal("25.00"),
    unusable_remainder_grams: Decimal | None = None,
) -> Spool:
    spool = Spool(
        id=uuid4(),
        tenant_id=tenant.id,
        filament_type_id=filament_type.id,
        spool_id=f"PURCHASE-{uuid4().hex[:8]}",
        initial_weight=initial_weight,
        current_weight=initial_weight,
        purchase_price=purchase_price,
        unusable_remainder_grams=unusable_remainder_grams,
        filament_purchase_id=purchase.id if purchase is not None else None,
    )
    db_session.add(spool)
    await db_session.commit()
    await db_session.refresh(spool)
    return spool


# ============================================================================
# Create
# ============================================================================


class TestCreatingAPurchase:
    async def test_a_purchase_is_created(self, client: AsyncClient) -> None:
        response = await client.post(
            ENDPOINT,
            json={
                "supplier": "Polymaker",
                "purchase_date": "2026-03-01",
                "inbound_shipping_cost": "18.00",
                "tax_amount": "6.50",
                "tax_recoverable": False,
                "order_reference": "PO-4471",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["supplier"] == "Polymaker"
        assert Decimal(body["inbound_shipping_cost"]) == Decimal("18.00")
        assert body["tax_recoverable"] is False
        assert body["spools"] == []

    async def test_unauthenticated_create_is_refused(
        self, unauthenticated_client: AsyncClient
    ) -> None:
        response = await unauthenticated_client.post(ENDPOINT, json={"purchase_date": "2026-03-01"})
        assert response.status_code == 401

    async def test_a_missing_purchase_date_is_refused(self, client: AsyncClient) -> None:
        response = await client.post(ENDPOINT, json={"supplier": "Polymaker"})
        assert response.status_code == 422

    async def test_negative_shipping_is_refused(self, client: AsyncClient) -> None:
        response = await client.post(
            ENDPOINT,
            json={"purchase_date": "2026-03-01", "inbound_shipping_cost": "-1.00"},
        )
        assert response.status_code == 422

    async def test_negative_tax_is_refused(self, client: AsyncClient) -> None:
        response = await client.post(
            ENDPOINT, json={"purchase_date": "2026-03-01", "tax_amount": "-1.00"}
        )
        assert response.status_code == 422


# ============================================================================
# Read, including the allocation
# ============================================================================


class TestTheAllocationShownPerSpool:
    async def test_four_equal_spools_split_shipping_evenly_and_land_at_31(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_filament_type,
    ) -> None:
        """The golden case's filament: CA$31.00 per 1000 g landed.

        Four 1 kg spools at CA$25.00 each, CA$18.00 inbound shipping and
        CA$6.00 of non-recoverable tax: every spool lands at CA$31.00, and
        with a 25 g unusable remainder its usable weight is 975 g.
        """
        purchase = FilamentPurchase(
            id=uuid4(),
            tenant_id=test_tenant.id,
            supplier="Polymaker",
            purchase_date=date(2026, 3, 1),
            inbound_shipping_cost=Decimal("18.00"),
            tax_amount=Decimal("6.00"),
            tax_recoverable=False,
        )
        db_session.add(purchase)
        await db_session.commit()

        for _ in range(4):
            await _spool(
                db_session,
                test_tenant,
                test_filament_type,
                purchase=purchase,
                unusable_remainder_grams=Decimal("25"),
            )

        response = await client.get(f"{ENDPOINT}/{purchase.id}")

        assert response.status_code == 200
        body = response.json()
        assert len(body["spools"]) == 4
        for entry in body["spools"]:
            assert Decimal(entry["allocated_shipping"]) == Decimal("4.50")
            assert Decimal(entry["allocated_tax"]) == Decimal("1.50")
            assert Decimal(entry["total_landed_cost"]) == Decimal("31.00")
            assert Decimal(entry["usable_weight_grams"]) == Decimal("975")
            assert Decimal(entry["cost_per_gram"]) == Decimal("31.00") / Decimal("975")

    async def test_shipping_is_allocated_by_weight_not_by_count(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_filament_type,
    ) -> None:
        """One 250 g spool beside three 1 kg spools pays a quarter-share."""
        shipping = Decimal("18.00")
        purchase = FilamentPurchase(
            id=uuid4(),
            tenant_id=test_tenant.id,
            purchase_date=date(2026, 3, 1),
            inbound_shipping_cost=shipping,
            tax_amount=Decimal("0"),
            tax_recoverable=False,
        )
        db_session.add(purchase)
        await db_session.commit()

        small = await _spool(
            db_session,
            test_tenant,
            test_filament_type,
            purchase=purchase,
            initial_weight=Decimal("250"),
        )
        for _ in range(3):
            await _spool(db_session, test_tenant, test_filament_type, purchase=purchase)

        total_weight = Decimal("250") + Decimal("3000")
        # Computed from the purchase's own inputs rather than approximated, and
        # left unrounded: rounding each share independently is how a cent goes
        # missing from the purchase total.
        expected_small = shipping * Decimal("250") / total_weight

        body = (await client.get(f"{ENDPOINT}/{purchase.id}")).json()
        by_id = {entry["spool_id"]: entry for entry in body["spools"]}

        assert Decimal(by_id[str(small.id)]["allocated_shipping"]) == expected_small
        assert sum(Decimal(entry["allocated_shipping"]) for entry in body["spools"]) == shipping, (
            "every cent of the shipping must land on some spool"
        )

    async def test_recoverable_tax_is_excluded_from_landed_cost(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_filament_type,
    ) -> None:
        purchase = FilamentPurchase(
            id=uuid4(),
            tenant_id=test_tenant.id,
            purchase_date=date(2026, 3, 1),
            inbound_shipping_cost=Decimal("0"),
            tax_amount=Decimal("6.00"),
            tax_recoverable=True,
        )
        db_session.add(purchase)
        await db_session.commit()
        await _spool(db_session, test_tenant, test_filament_type, purchase=purchase)

        body = (await client.get(f"{ENDPOINT}/{purchase.id}")).json()
        entry = body["spools"][0]

        assert Decimal(entry["allocated_tax"]) == Decimal("0")
        assert Decimal(entry["total_landed_cost"]) == Decimal("25.00")

    async def test_the_derivation_is_returned_so_the_figure_can_be_explained(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_filament_type,
    ) -> None:
        """FR-008f: nobody should have to recompute a per-gram cost to trust it."""
        purchase = FilamentPurchase(
            id=uuid4(),
            tenant_id=test_tenant.id,
            purchase_date=date(2026, 3, 1),
            inbound_shipping_cost=Decimal("18.00"),
            tax_amount=Decimal("0"),
            tax_recoverable=False,
        )
        db_session.add(purchase)
        await db_session.commit()
        await _spool(db_session, test_tenant, test_filament_type, purchase=purchase)

        body = (await client.get(f"{ENDPOINT}/{purchase.id}")).json()
        assert body["spools"][0]["derivation"], "a landed cost must carry its derivation"

    async def test_the_list_returns_purchases(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        db_session.add(
            FilamentPurchase(
                id=uuid4(),
                tenant_id=test_tenant.id,
                purchase_date=date(2026, 3, 1),
                inbound_shipping_cost=Decimal("0"),
                tax_amount=Decimal("0"),
            )
        )
        await db_session.commit()

        response = await client.get(ENDPOINT)

        assert response.status_code == 200
        assert response.json()["total"] >= 1

    async def test_an_unknown_purchase_is_a_404(self, client: AsyncClient) -> None:
        response = await client.get(f"{ENDPOINT}/{uuid4()}")
        assert response.status_code == 404


# ============================================================================
# Update and delete
# ============================================================================


class TestUpdatingAndDeleting:
    async def test_a_purchase_is_updated_and_the_allocation_follows(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_filament_type,
    ) -> None:
        purchase = FilamentPurchase(
            id=uuid4(),
            tenant_id=test_tenant.id,
            purchase_date=date(2026, 3, 1),
            inbound_shipping_cost=Decimal("18.00"),
            tax_amount=Decimal("0"),
        )
        db_session.add(purchase)
        await db_session.commit()
        await _spool(db_session, test_tenant, test_filament_type, purchase=purchase)

        response = await client.put(
            f"{ENDPOINT}/{purchase.id}", json={"inbound_shipping_cost": "36.00"}
        )

        assert response.status_code == 200
        assert Decimal(response.json()["spools"][0]["allocated_shipping"]) == Decimal("36.00")

    async def test_updating_an_unknown_purchase_is_a_404(self, client: AsyncClient) -> None:
        response = await client.put(f"{ENDPOINT}/{uuid4()}", json={"inbound_shipping_cost": "1.00"})
        assert response.status_code == 404

    async def test_a_purchase_is_deleted_and_its_spools_survive(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_filament_type,
    ) -> None:
        """FR-008e: a spool with no parent purchase stays valid."""
        purchase = FilamentPurchase(
            id=uuid4(),
            tenant_id=test_tenant.id,
            purchase_date=date(2026, 3, 1),
            inbound_shipping_cost=Decimal("18.00"),
            tax_amount=Decimal("0"),
        )
        db_session.add(purchase)
        await db_session.commit()
        spool = await _spool(db_session, test_tenant, test_filament_type, purchase=purchase)

        response = await client.delete(f"{ENDPOINT}/{purchase.id}")

        assert response.status_code == 204
        await db_session.refresh(spool)
        assert spool.filament_purchase_id is None
        assert spool.purchase_price == Decimal("25.00")

    async def test_deleting_an_unknown_purchase_is_a_404(self, client: AsyncClient) -> None:
        response = await client.delete(f"{ENDPOINT}/{uuid4()}")
        assert response.status_code == 404
