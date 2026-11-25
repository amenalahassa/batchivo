"""Suggesting and confirming the parcels an order is sent in (packaging advisor, US6, D10).

``suggest`` reads: it packs the order's lines through ``postage.plan_order_parcels``
and prices them, marked an estimate. ``confirm`` writes, once per order: the
parcels as sent, one ``consumable_usage`` row per packing item with the stock
it takes, and the postage those parcels determine.

No weight, size or postage arithmetic lives here (FR-030, Constitution III):
each parcel is assembled by ``postage.build_parcel`` and priced by
``postage.postage_for_parcels``. A postage an operator entered is never
replaced by a derived one (FR-041e).
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.consumable import CONTAINER_KINDS, PACKAGING_KINDS, ConsumableType, ConsumableUsage
from app.models.order import Order
from app.models.order_parcel import OrderParcel, OrderParcelItem
from app.models.product import Product
from app.services import postage
from app.services.costing import consumable_unit_cost
from app.services.dims import Parcel

if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.user import User

logger = logging.getLogger(__name__)


class ParcelsAlreadyConfirmed(Exception):
    """The order's parcels were confirmed before; they are written once (FR-036)."""


class InvalidParcels(Exception):
    """The parcels name something that is not this tenant's packaging."""


@dataclass(frozen=True)
class ParcelRequest:
    """One parcel as the operator confirms it: packing items, and optionally contents."""

    items: Sequence[tuple[UUID, int]]
    #: (sku, quantity) of the order's units in this parcel; None leaves it to the order.
    contents: Optional[Sequence[tuple[str, int]]] = None


@dataclass
class ConfirmedParcels:
    parcels: list[OrderParcel]
    postage: postage.Postage
    warnings: list[dict] = field(default_factory=list)


@dataclass
class OrderSuggestion:
    plan: postage.OrderPlan
    estimate: postage.Postage
    lines: list[tuple[Optional[Product], int, str]]


async def order_lines(
    db: AsyncSession, tenant: "Tenant", order: Order
) -> list[tuple[Optional[Product], int, str]]:
    """Each order line as (catalogue product or None, quantity, the SKU it was sold as)."""
    ids = {item.product_id for item in order.items if item.product_id is not None}
    products: dict[UUID, Product] = {}
    if ids:
        rows = await db.execute(
            select(Product).where(Product.id.in_(ids), Product.tenant_id == tenant.id)
        )
        products = {p.id: p for p in rows.scalars().all()}
    return [
        (
            products.get(item.product_id) if item.product_id else None,
            item.quantity,
            item.product_sku,
        )
        for item in order.items
    ]


class OrderParcelService:
    """The parcels of one tenant's orders."""

    def __init__(self, db: AsyncSession, tenant: "Tenant", user: Optional["User"] = None):
        self.db = db
        self.tenant = tenant
        self.user = user

    async def suggest(self, order: Order) -> OrderSuggestion:
        """How the order would be packed and what posting it would cost -- an estimate."""
        lines = await order_lines(self.db, self.tenant, order)
        missing = [sku for product, _, sku in lines if product is None]
        if missing:
            plan = postage.OrderPlan(
                (), ({"code": "dimensions_required", "sku": missing[0]},), reason=None
            )
            estimate = postage.Postage(
                None,
                reason="an order line names no catalogue product, so the parcel is unknown",
            )
            return OrderSuggestion(plan, estimate, lines)
        known = [(p, q, sku) for p, q, sku in lines if p is not None]
        plan = await postage.plan_order_parcels(self.db, self.tenant, known)
        estimate = await postage.postage_for_order(
            self.db, self.tenant, known, destination=order.shipping_country
        )
        return OrderSuggestion(plan, estimate, lines)

    async def _packaging(self, ids: set[UUID]) -> dict[UUID, ConsumableType]:
        rows = await self.db.execute(
            select(ConsumableType)
            .where(ConsumableType.id.in_(ids), ConsumableType.tenant_id == self.tenant.id)
            .options(selectinload(ConsumableType.purchases))
        )
        found = {c.id: c for c in rows.scalars().all()}
        for consumable_id in ids:
            consumable = found.get(consumable_id)
            if consumable is None or consumable.packaging_kind not in PACKAGING_KINDS:
                raise InvalidParcels(f"{consumable_id} is not one of your packaging consumables")
        return found

    async def confirm(self, order: Order, requests: Sequence[ParcelRequest]) -> ConfirmedParcels:
        """Record the parcels as sent, take their packaging from stock, and derive postage.

        One transaction: a refusal writes nothing.
        """
        existing = await self.db.execute(
            select(OrderParcel.id).where(
                OrderParcel.order_id == order.id, OrderParcel.tenant_id == self.tenant.id
            )
        )
        if existing.first() is not None:
            raise ParcelsAlreadyConfirmed(f"order {order.order_number} already has parcels")

        packaging = await self._packaging({cid for r in requests for cid, _ in r.items})
        for index, request in enumerate(requests, start=1):
            if not any(
                packaging[cid].packaging_kind in CONTAINER_KINDS for cid, _ in request.items
            ):
                raise InvalidParcels(f"parcel {index} has no box or mailer")

        lines = await order_lines(self.db, self.tenant, order)
        contents_by_parcel = self._assign_contents(lines, requests)
        now = datetime.now(UTC)
        parcels: list[OrderParcel] = []
        assembled: list[Parcel] = []
        warnings: list[dict] = []
        for sequence, (request, contents) in enumerate(zip(requests, contents_by_parcel), start=1):
            # Containers first, so the first one sets the outer size.
            packing = sorted(
                ((packaging[cid], quantity) for cid, quantity in request.items),
                key=lambda pair: pair[0].packaging_kind not in CONTAINER_KINDS,
            )
            parcel = postage.build_parcel(contents, packing)
            assembled.append(parcel)
            row = OrderParcel(
                tenant_id=self.tenant.id,
                order_id=order.id,
                sequence=sequence,
                outer_length_mm=parcel.outer.length if parcel.outer else None,
                outer_width_mm=parcel.outer.width if parcel.outer else None,
                outer_height_mm=parcel.outer.height if parcel.outer else None,
                packed_weight_grams=parcel.grams,
                confirmed_by_user_id=self.user.id if self.user else None,
                confirmed_at=now,
            )
            row.items = [
                OrderParcelItem(tenant_id=self.tenant.id, consumable_type_id=cid, quantity=quantity)
                for cid, quantity in request.items
            ]
            self.db.add(row)
            parcels.append(row)
            for cid, quantity in request.items:
                warning = self._use(order, packaging[cid], quantity)
                if warning:
                    warnings.append(warning)

        found = await postage.postage_for_parcels(
            self.db, self.tenant, assembled, destination=order.shipping_country
        )
        if order.actuals_source != "entered" and found.known:
            order.postage_paid = found.amount
            order.actuals_source = "derived"
        await self.db.commit()
        for row in parcels:
            await self.db.refresh(row, ["items"])
        logger.info(
            f"Confirmed {len(parcels)} parcel(s) for order {order.order_number}; "
            f"postage {found.amount if found.known else 'unknown'}"
        )
        return ConfirmedParcels(parcels, found, warnings)

    def _use(self, order: Order, consumable: ConsumableType, quantity: int) -> Optional[dict]:
        """One usage row and the stock it takes; a warning when stock goes below zero."""
        self.db.add(
            ConsumableUsage(
                tenant_id=self.tenant.id,
                consumable_type_id=consumable.id,
                order_id=order.id,
                quantity_used=quantity,
                cost_at_use=consumable_unit_cost(consumable),
                usage_type="shipping",
                notes=f"Packed order {order.order_number}",
            )
        )
        consumable.quantity_on_hand = (consumable.quantity_on_hand or 0) - quantity
        if consumable.quantity_on_hand < 0:
            return {
                "code": "stock_below_zero",
                "consumable_id": consumable.id,
                "on_hand": consumable.quantity_on_hand,
            }
        return None

    @staticmethod
    def _assign_contents(
        lines: Sequence[tuple[Optional[Product], int, str]],
        requests: Sequence[ParcelRequest],
    ) -> list[list[tuple[Optional[Decimal], int]]]:
        """Each parcel's item weights and quantities.

        One parcel holds the whole order. Several take the contents the
        operator gave for each; without them every unit is counted in the
        first parcel, so the order's weight is never lost.
        """
        weight_by_sku = {
            sku: postage.item_weight(product) if product is not None else None
            for product, _, sku in lines
        }
        whole = [(weight_by_sku[sku], quantity) for _, quantity, sku in lines]
        if len(requests) == 1 or not all(r.contents for r in requests):
            return [whole] + [[] for _ in requests[1:]]
        return [
            [(weight_by_sku.get(sku), quantity) for sku, quantity in (r.contents or ())]
            for r in requests
        ]


__all__ = [
    "ConfirmedParcels",
    "InvalidParcels",
    "OrderParcelService",
    "OrderSuggestion",
    "ParcelRequest",
    "ParcelsAlreadyConfirmed",
    "order_lines",
]
