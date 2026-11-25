"""Recording a refund as an actual, once (task T189).

One place writes `RefundActual` rows, because three paths produce them -- the
console's own refund endpoint, the Square `refund.created` webhook and an RMA
completion -- and a refund counted twice reduces a margin twice. The webhook in
particular is redelivered by Square on any non-2xx response, so "record this
refund" has to mean "record it if it is not already recorded".

Nothing here derives or reprices anything. A refund is recorded; what it does
to a margin is computed on read by :mod:`app.services.realised_margin`
(Constitution V), and the sale snapshot is never touched (FR-038).
"""

import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.refund_actual import RefundActual

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

ZERO = Decimal("0")


async def record_refund(
    db: AsyncSession,
    tenant: "Tenant",
    order: Order,
    *,
    amount: Decimal,
    source: str = "entered",
    refunded_at: Optional[datetime] = None,
    provider_refund_id: Optional[str] = None,
    reason: Optional[str] = None,
    recorded_by_user_id: Optional[UUID] = None,
    commit: bool = False,
) -> Optional[RefundActual]:
    """Record one refund against ``order``, unless it is already recorded.

    Returns the row written, or ``None`` when nothing was written -- which
    happens for a non-positive amount (a refund of nothing is not an event) or
    for a ``provider_refund_id`` already on file.

    ``amount`` is in the order's currency and must be exact. Nothing is
    committed unless ``commit`` is set, so the refund joins the transaction of
    whatever recorded it: a refund the provider rejected must not leave a row
    reducing a margin.
    """
    exact = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    if exact <= ZERO:
        # Not an error and not worth a row. A zero refund is the absence of a
        # refund, and the check constraint would reject it anyway.
        return None

    if provider_refund_id is not None:
        existing = (
            await db.execute(
                select(RefundActual).where(
                    RefundActual.tenant_id == tenant.id,
                    RefundActual.provider_refund_id == provider_refund_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.info(
                f"Refund {provider_refund_id} is already recorded against order "
                f"{order.order_number}; not recording it twice"
            )
            return None

    row = RefundActual(
        tenant_id=tenant.id,
        order_id=order.id,
        amount=exact,
        currency=order.currency or "GBP",
        refunded_at=refunded_at or datetime.now(timezone.utc),
        source=source,
        provider_refund_id=provider_refund_id,
        reason=reason,
        recorded_by_user_id=recorded_by_user_id,
    )
    db.add(row)
    await db.flush()
    if commit:
        await db.commit()

    logger.info(
        f"Recorded a {source} refund of {exact} {row.currency} against order "
        f"{order.order_number} (FR-040)"
    )
    return row


async def refunded_total(db: AsyncSession, tenant: "Tenant", order_id: UUID) -> Decimal:
    """Everything recorded as refunded on one order.

    The sum of the rows, so a partial refund followed by another adds up rather
    than overwriting. Zero where nothing is recorded, which is the same answer
    as "no refund" -- the distinction between unknown and none does not arise
    here, because an unrecorded refund is indistinguishable from none by
    construction, and that is stated where it matters: `realised_margin`
    reports the figure it used.
    """
    rows = (
        (
            await db.execute(
                select(RefundActual).where(
                    RefundActual.tenant_id == tenant.id,
                    RefundActual.order_id == order_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return sum((Decimal(str(row.amount)) for row in rows), ZERO)


async def recorded_refund_totals(
    db: AsyncSession, tenant: "Tenant", order_ids: "Sequence[UUID]"
) -> dict[UUID, Decimal]:
    """The recorded refund total for each order that has one.

    An order with no `RefundActual` row is **absent from the mapping**, which
    is the distinction :func:`refunded_total` deliberately does not draw: it
    answers zero for "nothing recorded" because a margin nets nothing off
    either way. A report has to tell the two apart -- a blank cell says no
    refund was recorded, a `0.00` claims one of nothing was -- so this returns
    only what is on file (FR-040).

    One query for the whole page, so an export of a thousand orders does not
    run a thousand of them.
    """
    if not order_ids:
        return {}

    rows = await db.execute(
        select(RefundActual.order_id, func.sum(RefundActual.amount))
        .where(
            RefundActual.tenant_id == tenant.id,
            RefundActual.order_id.in_(list(order_ids)),
        )
        .group_by(RefundActual.order_id)
    )
    return {order_id: Decimal(str(total)) for order_id, total in rows.all()}


__all__ = ["record_refund", "recorded_refund_totals", "refunded_total"]
