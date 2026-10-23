"""What the operator paid to post a parcel (FR-024).

`Order.shipping_cost` is revenue -- what the customer was charged. This module
answers the other side of that sale: what the postage actually cost, read from
the shipping profiles the operator recorded.

It lives here rather than beside a route because two sale paths need the same
answer -- the console's margin and solve screens, and the storefront checkout
that freezes a snapshot -- and a postage figure that differs between them would
put two margins on one order (Constitution III).

Customer-facing shipping *quotes* are a separate concern and stay in
`shipping_service.py`: that asks what to charge, this asks what was paid.
"""

from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shipping_profile import ShippingProfile

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.tenant import Tenant

ZERO = Decimal("0")


async def postage_for_grams(
    db: AsyncSession,
    tenant: "Tenant",
    grams: Optional[Decimal],
) -> Decimal:
    """Postage for one parcel of ``grams``, from the shipping profiles.

    Returns zero when the operator has recorded no profile covering the weight,
    or no weight at all. That is a gap rather than a figure, and it is reported
    through the breakdown's own incomplete reasons rather than guessed at here:
    inventing postage would put a number on a screen that no carrier ever
    quoted.
    """
    if grams is None:
        return ZERO

    profiles = (
        (
            await db.execute(
                select(ShippingProfile)
                .where(ShippingProfile.tenant_id == tenant.id)
                .order_by(ShippingProfile.weight_bracket_min_grams)
            )
        )
        .scalars()
        .all()
    )

    weight = Decimal(str(grams))
    for profile in profiles:
        if profile.covers(weight):
            return Decimal(str(profile.postage_cost))
    return ZERO


async def postage_for_product(
    db: AsyncSession,
    tenant: "Tenant",
    product: "Product",
) -> Decimal:
    """Postage for one parcel of ``product``, by its recorded weight."""
    grams = getattr(product, "weight_grams", None)
    return await postage_for_grams(db, tenant, None if grams is None else Decimal(str(grams)))


__all__ = ["postage_for_grams", "postage_for_product"]
