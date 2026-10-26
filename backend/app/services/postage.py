"""What the operator paid to post a parcel (FR-024).

`Order.shipping_cost` is revenue -- what the customer was charged. This module
answers the other side of that sale: what the postage actually cost, read from
the shipping profiles the operator recorded.

It lives here rather than beside a route because every sale path needs the
same answer -- the console's margin, solve and ladder screens and the three
storefront checkouts that freeze a snapshot -- and a postage figure that
differs between them would put two margins on one order (Constitution III).

An order's units go into as few parcels as hold them (T257, packaging advisor
US6). Pricing each line as its own parcel and multiplying by quantity charged
a three-item order three parcels' postage.

A gap is reported, never priced at zero (FR-019): no weight, or no profile
covering the parcel on the date asked, comes back as :class:`Postage` with no
amount and a reason, which callers turn into an incomplete reason or leave the
order's postage unrecorded.

## The packed parcel (packaging advisor, research D9)

Postage is priced from a :class:`~app.services.dims.Parcel`: its packed weight
and, when a container is known, its outer size. :func:`build_parcel` is the
only place a parcel is assembled -- item weights plus the packaging's empty
weight, outer size from the container's inner size and wall -- so no route,
report or dispatch path keeps its own arithmetic (Constitution III). A
size-limited profile (a carrier's size class) is tried before a weight-only
one, cheapest first; a tenant with no size-limited profile sees the same
profile chosen as before.

Customer-facing shipping *quotes* are a separate concern and stay in
`shipping_service.py`: that asks what to charge, this asks what was paid.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Iterable, Optional, Sequence, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models.consumable import CONTAINER_KINDS, ConsumableType
from app.models.shipping_profile import ShippingProfile
from app.services.dims import Dims, Parcel

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.product_variant import ProductVariant
    from app.models.tenant import Tenant

ZERO = Decimal("0")

#: Notes a postage carries about how its parcel was assembled.
NO_PACKAGING_RECORDED = "no_packaging_recorded"
ORDER_PACKING_UNAVAILABLE = "order_packing_unavailable"
CONTENTS_NOT_ASSIGNED = "contents_not_assigned"

#: An order line: a product and quantity, optionally the SKU it was sold as
#: (a variant's SKU picks that variant's dimensions and packaging, D11).
OrderLine = Union[tuple["Product", int], tuple["Product", int, Optional[str]]]


@dataclass(frozen=True)
class Postage:
    """The postage for an order's parcels, or why it is not known.

    ``amount`` is ``None`` for a gap. ``zone`` names the profile's destination
    zone that priced it, so a screen can say which one it assumed.
    """

    amount: Optional[Decimal]
    reason: Optional[str] = None
    zone: Optional[str] = None
    #: How the parcel was assembled when that is worth saying, e.g.
    #: ``no_packaging_recorded`` for a weight-only parcel.
    notes: tuple[str, ...] = ()

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


# ============================================
# Assembling a parcel
# ============================================


def build_parcel(
    contents: Sequence[tuple[Optional[Decimal], int]],
    packing: Sequence[tuple[ConsumableType, int]],
) -> Parcel:
    """The one place a parcel is assembled (research D9, FR-025, FR-030).

    ``contents`` is each item's weight in grams with its quantity; ``packing``
    each packaging consumable with its quantity. The packed weight is their
    sum. A missing item weight, or a missing container weight, makes the
    weight unknown -- never zero. Void fill and wrap without a weight count as
    nothing, and say so. The outer size is the container's inner size plus
    twice its wall on each axis; a wall not recorded is taken as 0 mm, and
    said.
    """
    reasons: list[str] = []
    item_grams = ZERO
    grams: Optional[Decimal] = ZERO
    for weight, quantity in contents:
        if weight is None:
            grams = None
            reasons.append("an item in the parcel has no recorded weight")
            break
        item_grams += Decimal(str(weight)) * Decimal(quantity)
    if grams is not None:
        grams = item_grams

    outer: Optional[Dims] = None
    for consumable, quantity in packing:
        is_container = consumable.packaging_kind in CONTAINER_KINDS
        if consumable.empty_weight_grams is None:
            if is_container:
                grams = None
                reasons.append(f"{consumable.name} has no empty weight recorded")
            else:
                reasons.append(f"{consumable.name} has no weight recorded; counted as 0 g")
        elif grams is not None:
            grams += Decimal(str(consumable.empty_weight_grams)) * Decimal(quantity)
        if is_container and outer is None:
            inner = Dims.from_row(consumable, prefix="inner_")
            if inner is None:
                reasons.append(f"{consumable.name} has no inner size recorded")
                continue
            if consumable.wall_mm is None:
                reasons.append(f"{consumable.name} has no wall thickness; taken as 0 mm")
            outer = inner.plus(Decimal(str(consumable.wall_mm or 0)))
    return Parcel(grams=grams, outer=outer, reasons=tuple(reasons))


def _price(
    profiles: Iterable[ShippingProfile],
    parcel: Parcel,
    *,
    zone: Optional[str],
    as_of: date,
) -> Postage:
    """The postage for one parcel from the profiles in force for ``zone``.

    Size-limited profiles first, cheapest first; then weight-only profiles in
    the order they were read (by bracket), so a tenant without size classes
    gets the profile it always did (FR-026).
    """
    if parcel.grams is None:
        why = parcel.reasons[0] if parcel.reasons else "no parcel weight is recorded"
        return Postage(None, reason=f"{why}, so postage is unknown rather than zero")
    candidates = [
        p for p in profiles if (zone is None or p.destination_zone == zone) and p.applies_on(as_of)
    ]
    sized = sorted(
        (p for p in candidates if p.size_limits is not None),
        key=lambda p: Decimal(str(p.postage_cost)),
    )
    weight_only = [p for p in candidates if p.size_limits is None]
    for profile in [*sized, *weight_only]:
        if profile.covers(parcel):
            return Postage(Decimal(str(profile.postage_cost)), zone=profile.destination_zone)
    where = f" to zone '{zone}'" if zone is not None else ""
    size = ""
    if parcel.outer is not None:
        o = parcel.outer
        size = f" measuring {o.length} × {o.width} × {o.height} mm"
    return Postage(
        None,
        reason=(
            f"no shipping profile in force on {as_of} covers a {parcel.grams} g parcel"
            f"{size}{where}, so postage is unknown rather than zero"
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
    """Postage for one weight-only parcel of ``grams``, from the profiles in force on ``as_of``.

    ``as_of`` defaults to today: a carrier repricing supersedes a profile
    rather than editing it (task T233), so a past date still reads the postage
    that applied then. ``zone`` limits the profiles to one destination zone;
    without one, the first profile covering the weight is used.
    """
    if grams is None:
        return Postage(None, reason="no parcel weight is recorded, so postage is unknown")
    return _price(
        await _profiles(db, tenant),
        Parcel(grams=Decimal(str(grams)), outer=None),
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
    """Postage for ``quantity`` of ``product``, packed as an order of them would be."""
    return await postage_for_order(
        db, tenant, [(product, quantity)], as_of=as_of, destination=None, zone=zone
    )


# ============================================
# Orders
# ============================================


@dataclass(frozen=True)
class PlannedParcel:
    """One parcel of an order as packed: what is in it and the parcel postage sees."""

    container: ConsumableType
    packing: tuple[tuple[ConsumableType, int], ...]
    #: (line index, units of that line) in this parcel.
    contents: tuple[tuple[int, int], ...]
    parcel: Parcel


@dataclass(frozen=True)
class OrderPlan:
    """How an order's units are packed, or why they cannot be (FR-027).

    ``parcels`` is empty when the order could not be packed; ``warnings`` then
    names the line, and ``reason`` is the note a weight-only postage carries
    instead.
    """

    parcels: tuple[PlannedParcel, ...]
    warnings: tuple[dict, ...] = field(default_factory=tuple)
    reason: Optional[str] = None


def order_line(line: OrderLine) -> tuple["Product", int, Optional[str]]:
    """A line as (product, quantity, sku), whichever shape it came in."""
    if len(line) == 3:
        return line  # type: ignore[return-value]
    product, quantity = line  # type: ignore[misc]
    return product, quantity, None


def _sku(product: "Product") -> str:
    return str(getattr(product, "sku", None) or getattr(product, "id", ""))


def item_weight(product: "Product") -> Optional[Decimal]:
    """One unit's weight in grams, or None when it is not recorded."""
    weight = getattr(product, "weight_grams", None)
    return Decimal(str(weight)) if weight is not None else None


async def plan_order_parcels(
    db: AsyncSession, tenant: "Tenant", lines: Sequence[OrderLine]
) -> OrderPlan:
    """Pack an order: one unit into its accepted packaging, several through the advisor.

    One unit uses the packaging accepted for it (variant's, else product's).
    Several units -- several lines, or one line of quantity > 1 (H2) -- are
    packed by :func:`packaging_advisor.suggest_for_order`, never the
    single-unit box. A line without dimensions, or units nothing holds, leave
    the order unpacked with the advisor's warning.
    """
    from app.services import packaging_advisor
    from app.services.item_dimensions import (
        effective_dimensions,
        effective_packaging,
        variant_for_order_line,
    )

    resolved: list[tuple["Product", int, Optional["ProductVariant"]]] = [
        (product, quantity, variant_for_order_line(product, sku))
        for product, quantity, sku in map(order_line, lines)
    ]
    units = sum(quantity for _, quantity, _ in resolved)
    if units == 1:
        index = next(i for i, r in enumerate(resolved) if r[1] == 1)
        product, _, variant = resolved[index]
        consumable, quantity = effective_packaging(product, variant)
        if consumable is None or consumable.packaging_kind not in CONTAINER_KINDS:
            return OrderPlan((), reason=NO_PACKAGING_RECORDED)
        packing = ((consumable, quantity),)
        parcel = build_parcel([(item_weight(product), 1)], packing)
        return OrderPlan((PlannedParcel(consumable, packing, ((index, 1),), parcel),))

    items: list[tuple[str, Dims]] = []
    fragile = False
    for index, (product, quantity, variant) in enumerate(resolved):
        dims, _ = effective_dimensions(product, variant)
        if dims is None:
            sku = variant.sku if variant is not None else _sku(product)
            return OrderPlan(
                (),
                ({"code": packaging_advisor.DIMENSIONS_REQUIRED, "sku": sku},),
                reason=ORDER_PACKING_UNAVAILABLE,
            )
        fragile = fragile or bool(getattr(product, "is_fragile", False))
        items.extend((str(index), dims) for _ in range(quantity))

    context = await packaging_advisor.load_packaging_context(db, tenant)
    advice = packaging_advisor.suggest_for_order(
        items,
        context.containers,
        clearance=context.clearance_for(fragile),
        fillers=context.fillers,
    )
    if not advice.parcels:
        warnings = tuple(
            {"code": w["code"], "sku": _sku(resolved[int(w["key"])][0])} if "key" in w else w
            for w in advice.warnings
        ) or ({"code": packaging_advisor.NOTHING_FITS},)
        return OrderPlan((), warnings, reason=ORDER_PACKING_UNAVAILABLE)

    planned: list[PlannedParcel] = []
    for packed in advice.parcels:
        container = await db.get(ConsumableType, packed.container.id)
        assert container is not None  # loaded by the context a moment ago
        packing_list: list[tuple[ConsumableType, int]] = [(container, 1)]
        if packed.void_fill is not None:
            filler = await db.get(ConsumableType, packed.void_fill.filler.id)
            if filler is not None:
                packing_list.append((filler, packed.void_fill.quantity))
        contents = tuple(sorted((int(key), n) for key, n in packed.contents.items()))
        parcel = build_parcel([(item_weight(resolved[i][0]), n) for i, n in contents], packing_list)
        planned.append(PlannedParcel(container, tuple(packing_list), contents, parcel))
    return OrderPlan(tuple(planned))


def price_parcels(
    profiles: Sequence[ShippingProfile],
    parcels: Sequence[Parcel],
    *,
    zone: Optional[str],
    as_of: date,
) -> Postage:
    """The postage for several parcels: their sum, or unknown if any one is."""
    total = ZERO
    priced_zone: Optional[str] = None
    for parcel in parcels:
        one = _price(profiles, parcel, zone=zone, as_of=as_of)
        if not one.known:
            return one
        total += one.or_zero()
        priced_zone = priced_zone or one.zone
    return Postage(total, zone=priced_zone)


async def postage_for_parcels(
    db: AsyncSession,
    tenant: "Tenant",
    parcels: Sequence[Parcel],
    *,
    as_of: Optional[date] = None,
    destination: Optional[str] = None,
) -> Postage:
    """Postage for parcels already assembled -- the ones confirmed at dispatch."""
    profiles = await _profiles(db, tenant)
    return price_parcels(
        profiles,
        parcels,
        zone=zone_for_destination(destination, profiles),
        as_of=as_of or clock.today(),
    )


async def postage_for_order(
    db: AsyncSession,
    tenant: "Tenant",
    lines: Sequence[OrderLine],
    *,
    as_of: Optional[date] = None,
    destination: Optional[str] = None,
    zone: Optional[str] = None,
) -> Postage:
    """Postage for an order's parcels, packed as :func:`plan_order_parcels` packs them.

    A product with no recorded weight makes the postage unknown. An order that
    cannot be packed, or a unit with no accepted packaging, is priced as one
    weight-only parcel -- the figure before packed parcels -- and says so in
    ``notes``. ``destination`` is resolved to a zone where the operator named
    one the same way (:func:`zone_for_destination`).
    """
    grams = ZERO
    for product, quantity, _ in map(order_line, lines):
        weight = item_weight(product)
        if weight is None:
            return Postage(
                None,
                reason=(
                    f"product {_sku(product)} has no recorded weight, "
                    "so the parcel's postage is unknown"
                ),
            )
        grams += weight * Decimal(quantity)

    profiles = await _profiles(db, tenant)
    resolved_zone = zone or zone_for_destination(destination, profiles)
    on = as_of or clock.today()

    plan = await plan_order_parcels(db, tenant, lines)
    if not plan.parcels:
        found = _price(profiles, Parcel(grams=grams, outer=None), zone=resolved_zone, as_of=on)
        notes = (plan.reason,) if plan.reason else ()
        return Postage(found.amount, found.reason, found.zone, notes)
    return price_parcels(profiles, [p.parcel for p in plan.parcels], zone=resolved_zone, as_of=on)


async def freeze_order_postage(
    db: AsyncSession,
    tenant: "Tenant",
    order: object,
    lines: Sequence[tuple[Optional["Product"], int]],
) -> Postage:
    """Record what posting a storefront order cost (T257).

    The one place every storefront checkout -- the shop's own and both Square
    paths -- sets ``postage_paid``, so the three cannot disagree about one
    order. A line whose product is not in the catalogue has no weight, so the
    parcel's postage is unknown and stays unrecorded rather than zero. The
    figure is an estimate until the parcels are confirmed at dispatch.
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
    "CONTENTS_NOT_ASSIGNED",
    "NO_PACKAGING_RECORDED",
    "ORDER_PACKING_UNAVAILABLE",
    "OrderLine",
    "OrderPlan",
    "PlannedParcel",
    "Postage",
    "build_parcel",
    "freeze_order_postage",
    "item_weight",
    "order_line",
    "plan_order_parcels",
    "postage_for_grams",
    "postage_for_order",
    "postage_for_parcels",
    "postage_for_product",
    "price_parcels",
    "zone_for_destination",
]
