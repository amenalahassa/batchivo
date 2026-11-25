"""The rules two shipping profiles must keep with each other.

Two profiles for the same zone and size class must not claim the same parcel
on the same day: overlapping brackets would make an order's postage depend on
which row was read first. Gaps are allowed -- a carrier's table may have them.

The rule lives here, not in a route, because two writers apply it: the
shipping-profile endpoints an operator uses and the catalogue seeding that adds
a carrier's tariff (spec 006, research D3). One rule, so the two cannot drift
(Constitution III). The route turns a clash into a 422; seeding skips the row
and reports it.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.shipping_profile import ShippingProfile
from app.schemas.shipping_profile import SIZE_LIMIT_FIELDS


def size_class(source: object) -> Optional[tuple[Decimal, ...]]:
    """A profile's size class, sorted, or None for a weight-only profile."""
    values = [getattr(source, name, None) for name in SIZE_LIMIT_FIELDS]
    if any(v is None for v in values):
        return None
    return tuple(sorted((Decimal(str(v)) for v in values), reverse=True))


def brackets_overlap(
    min_a: Decimal,
    max_a: Optional[Decimal],
    min_b: Decimal,
    max_b: Optional[Decimal],
) -> bool:
    """Whether two weight brackets claim any parcel in common.

    Half-open above, matching :meth:`ShippingProfile.covers`, so 0-250 and
    250-500 do not overlap -- which is how carriers publish them.
    """
    if max_a is not None and max_a <= min_b:
        return False
    if max_b is not None and max_b <= min_a:
        return False
    return True


def dates_overlap(from_a: date, to_a: Optional[date], from_b: date, to_b: Optional[date]) -> bool:
    """Whether two effective ranges (inclusive, open-ended when ``to`` is None) share a day."""
    if to_a is not None and to_a < from_b:
        return False
    if to_b is not None and to_b < from_a:
        return False
    return True


def _decimal(value: object) -> Optional[Decimal]:
    return Decimal(str(value)) if value is not None else None


@dataclass(frozen=True)
class Candidate:
    """The fields of a profile the overlap rule reads."""

    zone: str
    minimum: Decimal
    maximum: Optional[Decimal]
    effective_from: date
    effective_to: Optional[date] = None
    limits: Optional[tuple[Decimal, ...]] = None


def first_overlap(
    candidate: Candidate,
    existing: Iterable[ShippingProfile],
    *,
    exclude_id: Optional[UUID] = None,
) -> Optional[ShippingProfile]:
    """The first profile in ``existing`` that would claim a parcel ``candidate`` claims.

    Same zone, same size class, a day in common and a weight in common. A
    large-letter service and a parcel service may both cover 0-100 g in one
    zone: the size decides between them (research D9).
    """
    for profile in existing:
        if profile.id is not None and profile.id == exclude_id:
            continue
        if profile.destination_zone != candidate.zone or size_class(profile) != candidate.limits:
            continue
        if not dates_overlap(
            candidate.effective_from,
            candidate.effective_to,
            profile.effective_from,
            profile.effective_to,
        ):
            continue
        if brackets_overlap(
            candidate.minimum,
            candidate.maximum,
            Decimal(str(profile.weight_bracket_min_grams)),
            _decimal(profile.weight_bracket_max_grams),
        ):
            return profile
    return None


async def zone_profiles(db: AsyncSession, tenant_id: UUID, zone: str) -> list[ShippingProfile]:
    """Every profile of one tenant in one zone."""
    result = await db.execute(
        select(ShippingProfile).where(
            ShippingProfile.tenant_id == tenant_id,
            ShippingProfile.destination_zone == zone,
        )
    )
    return list(result.scalars().all())


async def has_been_used(db: AsyncSession, profile: ShippingProfile) -> bool:
    """Whether any order was placed while this postage was in force."""
    statement = select(Order.id).where(
        Order.tenant_id == profile.tenant_id,
        Order.created_at >= datetime.combine(profile.effective_from, time.min, tzinfo=timezone.utc),
    )
    if profile.effective_to is not None:
        statement = statement.where(
            Order.created_at
            < datetime.combine(
                profile.effective_to + timedelta(days=1), time.min, tzinfo=timezone.utc
            )
        )
    return (await db.execute(statement.limit(1))).first() is not None


def service_key(profile: ShippingProfile) -> Optional[str]:
    """The service a profile prices, as products and the shop default name it.

    ``"<carrier>:<service>"`` for a row seeded from a carrier tariff; an
    operator row that names a service is known by that name alone.
    """
    if profile.service is None:
        return None
    if profile.catalogue_carrier:
        return f"{profile.catalogue_carrier}:{profile.service}"
    return profile.service


__all__ = [
    "Candidate",
    "SIZE_LIMIT_FIELDS",
    "brackets_overlap",
    "dates_overlap",
    "first_overlap",
    "has_been_used",
    "service_key",
    "size_class",
    "zone_profiles",
]
