"""Which box an item fits in, and how much filler it needs (research D6, D7).

The advisor is pure: :func:`suggest` and :func:`suggest_for_order` take values
and return values, with no database and no cost. It never computes, shows or
stores a cost (FR-021, FR-022); a container's unit cost appears only as a
tie-break key, taken from ``costing.consumable_unit_cost`` -- the function the
cost breakdown itself uses -- so no second cost path exists.

:func:`load_packaging_context` is the thin async loader that turns the
tenant's consumables and settings into those values, and
:func:`get_packaging_settings` is the only reader of the clearance settings.
"""

import logging
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal
from itertools import permutations
from typing import TYPE_CHECKING, Iterable, Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.consumable import CONTAINER_KINDS, ConsumableType
from app.services.dims import Dims

if TYPE_CHECKING:
    from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

#: Shown, and labelled as defaults, until the operator saves their own (D8).
DEFAULT_CLEARANCE_MM = Decimal("10.0")
DEFAULT_FRAGILE_CLEARANCE_MM = Decimal("20.0")

DIMENSIONS_REQUIRED = "dimensions_required"
NOTHING_FITS = "nothing_fits"
ACCEPTED_DOES_NOT_FIT = "accepted_packaging_does_not_fit"


# ============================================
# Values
# ============================================


@dataclass(frozen=True)
class Container:
    """A box or mailer the operator stocks. ``inner`` is ``None`` when incomplete."""

    id: UUID
    name: str
    kind: str
    inner: Optional[Dims]
    in_stock: bool
    wall: Optional[Decimal] = None
    empty_weight: Optional[Decimal] = None
    #: ``consumable_unit_cost`` as a sort key only; ``None`` when no cost is recorded.
    unit_cost_key: Optional[Decimal] = None


@dataclass(frozen=True)
class Filler:
    """Void fill: one unit fills ``fill_volume_ml``."""

    id: UUID
    name: str
    fill_volume_ml: Optional[Decimal]
    in_stock: bool


@dataclass(frozen=True)
class Wrap:
    """Protective wrap, suggested for fragile items (FR-020)."""

    id: UUID
    name: str
    in_stock: bool


@dataclass(frozen=True)
class VoidFill:
    filler: Filler
    quantity: int


@dataclass(frozen=True)
class Suggestion:
    container: Container
    #: For each of the container's axes, which of the item's lies along it.
    orientation: tuple[str, str, str]
    #: Room left on each container axis beyond the clearance.
    room: Dims
    empty_volume_ml: Decimal
    void_fill: Optional[VoidFill] = None
    wrap: Optional[Wrap] = None


@dataclass(frozen=True)
class Advice:
    suggestions: tuple[Suggestion, ...]
    minimum_inner: Optional[Dims]
    warnings: tuple[str, ...]
    clearance: Decimal
    fragile: bool


@dataclass(frozen=True)
class PackagingContext:
    containers: tuple[Container, ...]
    fillers: tuple[Filler, ...]
    wraps: tuple[Wrap, ...]
    clearance: Decimal
    fragile_clearance: Decimal

    def clearance_for(self, fragile: bool) -> Decimal:
        return self.fragile_clearance if fragile else self.clearance


# ============================================
# Settings (research D8)
# ============================================


def get_packaging_settings(tenant: "Tenant") -> tuple[Decimal, Decimal, bool]:
    """``(clearance, fragile clearance, configured)`` -- the only reader of the setting.

    The defaults apply only while the operator has saved nothing, and the
    third value says so; a saved figure is always the one used (FR-015).
    """
    saved = (getattr(tenant, "settings", None) or {}).get("packaging")
    if not isinstance(saved, dict):
        return DEFAULT_CLEARANCE_MM, DEFAULT_FRAGILE_CLEARANCE_MM, False
    return (
        Decimal(str(saved.get("clearance_mm", DEFAULT_CLEARANCE_MM))),
        Decimal(str(saved.get("fragile_clearance_mm", DEFAULT_FRAGILE_CLEARANCE_MM))),
        True,
    )


# ============================================
# One item (FR-014 to FR-020)
# ============================================


def _rank_key(container: Container) -> tuple:
    assert container.inner is not None
    cost = container.unit_cost_key
    # In stock first; then smallest; then cheaper, with no cost recorded last;
    # then by name (FR-016).
    return (
        not container.in_stock,
        container.inner.volume_ml,
        cost is None,
        cost if cost is not None else ZERO,
        container.name.casefold(),
    )


def _room(item: Dims, inner: Dims, orientation: tuple[str, str, str], clearance: Decimal) -> Dims:
    along = [getattr(item, axis) for axis in orientation]
    extra = clearance * 2
    return Dims(*(inner.as_tuple()[i] - along[i] - extra for i in range(3)))


def _void_fill(empty_ml: Decimal, fillers: Sequence[Filler]) -> Optional[VoidFill]:
    usable = [f for f in fillers if f.in_stock and f.fill_volume_ml and f.fill_volume_ml > ZERO]
    if not usable or empty_ml <= ZERO:
        return None
    best = max(usable, key=lambda f: (f.fill_volume_ml, f.name.casefold()))
    assert best.fill_volume_ml is not None
    units = (empty_ml / best.fill_volume_ml).to_integral_value(rounding=ROUND_CEILING)
    return VoidFill(best, int(units))


def _wrap(wraps: Sequence[Wrap]) -> Optional[Wrap]:
    stocked = sorted((w for w in wraps if w.in_stock), key=lambda w: w.name.casefold())
    return stocked[0] if stocked else None


def suggest(
    item: Optional[Dims],
    containers: Iterable[Container],
    *,
    clearance: Decimal,
    fragile: bool = False,
    fillers: Sequence[Filler] = (),
    wraps: Sequence[Wrap] = (),
) -> Advice:
    """Every container ``item`` fits in with ``clearance`` all round, best first.

    ``clearance`` is the one in force for this item -- the caller passes the
    fragile clearance for a fragile item. Incomplete containers are never
    suggested and are named in the warnings; with nothing fitting, the
    minimum inner size a container would need is given (FR-018).
    """
    containers = list(containers)
    warnings = [
        f"incomplete_container:{c.name}"
        for c in sorted(containers, key=lambda c: c.name.casefold())
        if c.inner is None
    ]
    if item is None:
        return Advice((), None, (DIMENSIONS_REQUIRED, *warnings), clearance, fragile)

    needed = item.plus(clearance)
    wrap = _wrap(wraps) if fragile else None
    fits: list[Suggestion] = []
    for container in sorted((c for c in containers if c.inner is not None), key=_rank_key):
        assert container.inner is not None
        orientation = needed.fits_in(container.inner)
        if orientation is None:
            continue
        empty = container.inner.volume_ml - item.volume_ml
        fits.append(
            Suggestion(
                container=container,
                orientation=orientation,
                room=_room(item, container.inner, orientation, clearance),
                empty_volume_ml=empty,
                void_fill=_void_fill(empty, fillers),
                wrap=wrap,
            )
        )

    if not fits:
        return Advice(
            (),
            item.sorted_desc().plus(clearance),
            (NOTHING_FITS, *warnings),
            clearance,
            fragile,
        )
    return Advice(tuple(fits), None, tuple(warnings), clearance, fragile)


def accepted_packaging_warnings(
    item: Optional[Dims], consumable: Optional[ConsumableType], clearance: Decimal
) -> list[str]:
    """``["accepted_packaging_does_not_fit"]`` when the accepted box no longer fits (FR-024).

    Computed on read, never stored. Silent when either size is unknown: there
    is nothing to compare, and saying "does not fit" would be a guess.
    """
    if item is None or consumable is None or consumable.packaging_kind not in CONTAINER_KINDS:
        return []
    inner = Dims.from_row(consumable, prefix="inner_")
    if inner is None:
        return []
    return [] if item.plus(clearance).fits_in(inner) else [ACCEPTED_DOES_NOT_FIT]


# ============================================
# Several items (research D7, FR-031)
# ============================================


@dataclass(frozen=True)
class Placement:
    """One unit placed in a container: its key, position and placed size."""

    key: str
    position: tuple[Decimal, Decimal, Decimal]
    size: Dims


@dataclass(frozen=True)
class PackedParcel:
    container: Container
    placements: tuple[Placement, ...]
    empty_volume_ml: Decimal
    void_fill: Optional[VoidFill] = None

    @property
    def contents(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for placement in self.placements:
            counts[placement.key] = counts.get(placement.key, 0) + 1
        return counts


@dataclass(frozen=True)
class OrderAdvice:
    parcels: tuple[PackedParcel, ...]
    warnings: tuple[dict, ...] = field(default_factory=tuple)


def _overlaps(a_pos: tuple[Decimal, ...], a: Dims, b_pos: tuple[Decimal, ...], b: Dims) -> bool:
    return all(
        a_pos[i] < b_pos[i] + b.as_tuple()[i] and b_pos[i] < a_pos[i] + a.as_tuple()[i]
        for i in range(3)
    )


def _rotations(size: Dims) -> list[Dims]:
    seen: list[Dims] = []
    for order in permutations(size.as_tuple()):
        candidate = Dims(*order)
        if candidate not in seen:
            seen.append(candidate)
    return seen


def _try_place(space: Dims, placed: list[Placement], key: str, size: Dims) -> Optional[Placement]:
    """Place ``size`` at the first extreme point it fits, in any rotation."""
    points = {(ZERO, ZERO, ZERO)}
    for p in placed:
        x, y, z = p.position
        sx, sy, sz = p.size.as_tuple()
        points |= {(x + sx, y, z), (x, y + sy, z), (x, y, z + sz)}
    # Lowest first, then nearest the back corner: a deterministic order.
    for point in sorted(points, key=lambda pt: (pt[2], pt[1], pt[0])):
        for rotated in _rotations(size):
            if any(point[i] + rotated.as_tuple()[i] > space.as_tuple()[i] for i in range(3)):
                continue
            if any(_overlaps(point, rotated, p.position, p.size) for p in placed):
                continue
            return Placement(key, point, rotated)
    return None


def _pack(space: Dims, units: Sequence[tuple[str, Dims]]) -> tuple[list[Placement], list[int]]:
    """Place as many ``units`` as fit (in the order given); return placements and leftovers."""
    placed: list[Placement] = []
    leftover: list[int] = []
    for index, (key, size) in enumerate(units):
        placement = _try_place(space, placed, key, size)
        if placement is None:
            leftover.append(index)
        else:
            placed.append(placement)
    return placed, leftover


def _parcel(
    container: Container,
    placements: list[Placement],
    units: Sequence[tuple[str, Dims]],
    fillers: Sequence[Filler],
) -> PackedParcel:
    assert container.inner is not None
    used = sum((p.size.volume_ml for p in placements), ZERO)
    empty = container.inner.volume_ml - used
    return PackedParcel(container, tuple(placements), empty, _void_fill(empty, fillers))


def suggest_for_order(
    items: Sequence[tuple[str, Dims]],
    containers: Iterable[Container],
    *,
    clearance: Decimal,
    fillers: Sequence[Filler] = (),
) -> OrderAdvice:
    """Pack every unit into one container, or the fewest that hold them (D7).

    ``items`` is one entry per **unit** (a line of quantity 3 is three
    entries), keyed by whatever the caller wants back in the contents. The
    clearance is kept around the group, not between items. First-fit
    decreasing over extreme points with six rotations: practical, not optimal
    (spec Assumptions), and deterministic for the same input.
    """
    usable = sorted((c for c in containers if c.inner is not None), key=_rank_key)
    units = sorted(
        items, key=lambda unit: (-unit[1].volume_ml, unit[0], unit[1].sorted_desc().as_tuple())
    )
    if not units:
        return OrderAdvice(())

    def space_of(container: Container) -> Optional[Dims]:
        assert container.inner is not None
        extra = clearance * 2
        inner = container.inner
        space = Dims(inner.length - extra, inner.width - extra, inner.height - extra)
        return space if min(space.as_tuple()) > ZERO else None

    # One container for everything, best ranked first.
    for container in usable:
        space = space_of(container)
        if space is None:
            continue
        placed, leftover = _pack(space, units)
        if not leftover:
            return OrderAdvice((_parcel(container, placed, units, fillers),))

    # Split: the smallest container holding the largest remaining unit, filled
    # with as many of the rest as fit, until every unit is placed.
    remaining = list(units)
    parcels: list[PackedParcel] = []
    while remaining:
        largest = remaining[0]
        chosen: Optional[tuple[Container, list[Placement], list[int]]] = None
        for container in usable:
            space = space_of(container)
            if space is None or largest[1].fits_in(space) is None:
                continue
            placed, leftover = _pack(space, remaining)
            chosen = (container, placed, leftover)
            break
        if chosen is None:
            return OrderAdvice((), ({"code": NOTHING_FITS, "key": largest[0]},))
        container, placed, leftover = chosen
        parcels.append(_parcel(container, placed, remaining, fillers))
        remaining = [remaining[i] for i in leftover]
    return OrderAdvice(tuple(parcels))


# ============================================
# Loading (the only database access)
# ============================================


def _unit_cost_key(consumable: ConsumableType) -> Optional[Decimal]:
    from app.services.costing import consumable_unit_cost, pricing_purchase

    if pricing_purchase(consumable) is None and consumable.current_cost_per_unit is None:
        return None
    return consumable_unit_cost(consumable)


def container_of(consumable: ConsumableType) -> Container:
    return Container(
        id=consumable.id,
        name=consumable.name,
        kind=consumable.packaging_kind or "box",
        inner=Dims.from_row(consumable, prefix="inner_"),
        in_stock=(consumable.quantity_on_hand or 0) > 0,
        wall=consumable.wall_mm,
        empty_weight=consumable.empty_weight_grams,
        unit_cost_key=_unit_cost_key(consumable),
    )


async def load_packaging_context(db: AsyncSession, tenant: "Tenant") -> PackagingContext:
    """The tenant's active packaging consumables and clearances, as advisor values."""
    rows = (
        (
            await db.execute(
                select(ConsumableType)
                .where(
                    ConsumableType.tenant_id == tenant.id,
                    ConsumableType.packaging_kind.is_not(None),
                    ConsumableType.is_active.is_(True),
                )
                .options(selectinload(ConsumableType.purchases))
            )
        )
        .scalars()
        .all()
    )
    containers = tuple(container_of(c) for c in rows if c.packaging_kind in CONTAINER_KINDS)
    fillers = tuple(
        Filler(c.id, c.name, c.fill_volume_ml, (c.quantity_on_hand or 0) > 0)
        for c in rows
        if c.packaging_kind == "void_fill"
    )
    wraps = tuple(
        Wrap(c.id, c.name, (c.quantity_on_hand or 0) > 0)
        for c in rows
        if c.packaging_kind == "wrap"
    )
    clearance, fragile_clearance, _configured = get_packaging_settings(tenant)
    return PackagingContext(containers, fillers, wraps, clearance, fragile_clearance)


__all__ = [
    "ACCEPTED_DOES_NOT_FIT",
    "Advice",
    "Container",
    "DIMENSIONS_REQUIRED",
    "Filler",
    "NOTHING_FITS",
    "OrderAdvice",
    "PackagingContext",
    "Suggestion",
    "Wrap",
    "accepted_packaging_warnings",
    "container_of",
    "get_packaging_settings",
    "load_packaging_context",
    "suggest",
    "suggest_for_order",
]
