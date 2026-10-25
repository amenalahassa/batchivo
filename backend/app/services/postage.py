"""What the operator paid to post a parcel (FR-024).

`Order.shipping_cost` is revenue -- what the customer was charged. This module
answers the other side of that sale: what the postage actually cost, read from
the shipping profiles the operator recorded.

It lives here rather than beside a route because every sale path needs the
same answer -- the console's margin, solve and ladder screens and the three
storefront checkouts that freeze a snapshot -- and a postage figure that
differs between them would put two margins on one order (Constitution III).

An order is **one parcel**, weighed as the sum of its lines (T257). Pricing
each line as its own parcel and multiplying by quantity charged a three-item
order three parcels' postage.

A gap is reported, never priced at zero (FR-019): no weight, or no profile
covering the parcel on the date asked, comes back as :class:`Postage` with no
amount and a reason, which callers turn into an incomplete reason or leave the
order's postage unrecorded.

Customer-facing shipping *quotes* are a separate concern and stay in
`shipping_service.py`: that asks what to charge, this asks what was paid.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models.shipping_profile import ShippingProfile

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.tenant import Tenant

ZERO = Decimal("0")


@dataclass(frozen=True)
class Postage:
    """The postage for one parcel, or why it is not known.

    ``amount`` is ``None`` for a gap. ``zone`` names the profile's destination
    zone that priced it, so a screen can say which one it assumed.
    """

    amount: Optional[Decimal]
    reason: Optional[str] = None
    zone: Optional[str] = None

    @property
    def known(self) -> bool:
        return self.amount is not None

    @property
    def incomplete_reasons(self) -> list[str]:
        return [self.reason] if self.amount is None and self.reason else []

    def or_zero(self) -> Decimal:
        """The amount, or zero for a figure that must carry its reason elsewhere."""
        return self.amount if self.amount is not None else ZERO


def zone_for_destination(
    destination: Optional[str], profiles: Sequence[ShippingProfile]
) -> Optional[str]:
    """The profile zone a destination names, if the operator used it as a zone.

    Zones are the operator's own words ('domestic', 'us', 'United Kingdom'), so
    a destination resolves to a zone only when one is spelled the same way;
    otherwise the destination is treated as unknown rather than guessed.
    """
    if not destination:
        return None
    wanted = destination.strip().casefold()
    for profile in profiles:
        if profile.destination_zone.strip().casefold() == wanted:
            return profile.destination_zone
    return None


async def _profiles(db: AsyncSession, tenant: "Tenant") -> list[ShippingProfile]:
    return list(
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


def _price(
    profiles: Iterable[ShippingProfile],
    grams: Decimal,
    *,
    zone: Optional[str],
    as_of: date,
) -> Postage:
    for profile in profiles:
        if zone is not None and profile.destination_zone != zone:
            continue
        if profile.applies_on(as_of) and profile.covers(grams):
            return Postage(Decimal(str(profile.postage_cost)), zone=profile.destination_zone)
    where = f" to zone '{zone}'" if zone is not None else ""
    return Postage(
        None,
        reason=(
            f"no shipping profile in force on {as_of} covers a {grams} g parcel{where}, "
            "so postage is unknown rather than zero"
        ),
    )


async def postage_for_grams(
    db: AsyncSession,
    tenant: "Tenant",
    grams: Optional[Decimal],
    as_of: Optional[date] = None,
    *,
    zone: Optional[str] = None,
) -> Postage:
    """Postage for one parcel of ``grams``, from the profiles in force on ``as_of``.

    ``as_of`` defaults to today: a carrier repricing supersedes a profile
    rather than editing it (task T233), so a past date still reads the postage
    that applied then. ``zone`` limits the profiles to one destination zone;
    without one, the first profile covering the weight is used.
    """
    if grams is None:
        return Postage(None, reason="no parcel weight is recorded, so postage is unknown")
    return _price(
        await _profiles(db, tenant),
        Decimal(str(grams)),
        zone=zone,
        as_of=as_of or clock.today(),
    )


async def postage_for_product(
    db: AsyncSession,
    tenant: "Tenant",
    product: "Product",
    *,
    quantity: int = 1,
    as_of: Optional[date] = None,
    zone: Optional[str] = None,
) -> Postage:
    """Postage for one parcel holding ``quantity`` of ``product``."""
    return await postage_for_order(
        db, tenant, [(product, quantity)], as_of=as_of, destination=None, zone=zone
    )


async def postage_for_order(
    db: AsyncSession,
    tenant: "Tenant",
    lines: Sequence[tuple["Product", int]],
    *,
    as_of: Optional[date] = None,
    destination: Optional[str] = None,
    zone: Optional[str] = None,
) -> Postage:
    """Postage for one parcel holding every line of an order.

    The parcel weighs the sum of each product's weight times its quantity. A
    product with no recorded weight makes the parcel's weight unknown, and so
    its postage. ``destination`` is resolved to a zone where the operator named
    one the same way (:func:`zone_for_destination`).
    """
    grams = ZERO
    for product, quantity in lines:
        weight = getattr(product, "weight_grams", None)
        if weight is None:
            sku = getattr(product, "sku", None) or getattr(product, "id", "")
            return Postage(
                None,
                reason=f"product {sku} has no recorded weight, so the parcel's postage is unknown",
            )
        grams += Decimal(str(weight)) * Decimal(quantity)

    profiles = await _profiles(db, tenant)
    resolved_zone = zone or zone_for_destination(destination, profiles)
    return _price(profiles, grams, zone=resolved_zone, as_of=as_of or clock.today())


async def freeze_order_postage(
    db: AsyncSession,
    tenant: "Tenant",
    order: object,
    lines: Sequence[tuple[Optional["Product"], int]],
) -> Postage:
    """Record what posting a storefront order cost, as one parcel (T257).

    The one place every storefront checkout -- the shop's own and both Square
    paths -- sets ``postage_paid``, so the three cannot disagree about one
    order. A line whose product is not in the catalogue has no weight, so the
    parcel's postage is unknown and stays unrecorded rather than zero.
    """
    if any(product is None for product, _ in lines):
        found = Postage(
            None,
            reason="an order line names no catalogue product, so the parcel's weight is unknown",
        )
    else:
        found = await postage_for_order(
            db,
            tenant,
            [(product, quantity) for product, quantity in lines if product is not None],
            destination=getattr(order, "shipping_country", None),
        )
    setattr(order, "postage_paid", found.amount)
    if found.known:
        # From the operator's own shipping profiles, not a person or a feed
        # (T241, FR-041e).
        setattr(order, "actuals_source", "derived")
    return found


__all__ = [
    "Postage",
    "freeze_order_postage",
    "postage_for_grams",
    "postage_for_order",
    "postage_for_product",
    "zone_for_destination",
]
