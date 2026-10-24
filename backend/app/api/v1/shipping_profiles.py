"""Shipping profile endpoints (task T078).

Postage is a cost the operator pays, so it is monetary policy: writing needs
admin or owner (FR-007a), reading is open to every role (FR-007c).

The one domain rule enforced here beyond the schema's own validation is that
two profiles for the same zone must not claim the same parcel. Overlapping
brackets would make the postage on an order depend on which row was read
first, which is the kind of non-determinism that turns a cost into a rumour.
Gaps between brackets are allowed: a carrier's published table may have them,
and inventing postage for a weight the operator has no price for would be
worse than reporting none.

A repricing supersedes a profile rather than editing it (FR-003, task T233):
changing the postage, a bracket or the zone closes the row the day before the
change applies and opens a new one, so a past date reads the postage that was
in force then. A profile is deleted only while no order has been placed during
its life; otherwise it is closed. Each figure written records its origin with
the administrator who set it (FR-001, task T229).
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.provenance_http import record_operator_origins, refuse_observed_or_409
from app.auth.dependencies import (
    CurrentTenant,
    CurrentUser,
    RequireAdmin,
    TenantDB,
    role_in_tenant,
)
from app.core import clock
from app.models.order import Order
from app.models.shipping_profile import ShippingProfile
from app.schemas.shipping_profile import (
    ShippingProfileCreate,
    ShippingProfileListResponse,
    ShippingProfileResponse,
    ShippingProfileUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _profile_or_404(
    db: AsyncSession,
    tenant_id: UUID,
    profile_id: UUID,
) -> ShippingProfile:
    result = await db.execute(
        select(ShippingProfile).where(
            ShippingProfile.id == profile_id,
            ShippingProfile.tenant_id == tenant_id,
        )
    )
    profile = result.scalars().first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shipping profile not found",
        )
    return profile


def _brackets_overlap(
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


#: The fields that say what a parcel costs to post. Changing any of them
#: supersedes the profile; a name or a carrier is corrected in place.
POSTAGE_FIELDS: frozenset[str] = frozenset(
    {"postage_cost", "weight_bracket_min_grams", "weight_bracket_max_grams", "destination_zone"}
)


def _dates_overlap(from_a: date, to_a: Optional[date], from_b: date, to_b: Optional[date]) -> bool:
    if to_a is not None and to_a < from_b:
        return False
    if to_b is not None and to_b < from_a:
        return False
    return True


async def _has_been_used(db: AsyncSession, profile: ShippingProfile) -> bool:
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


async def _refuse_overlapping_bracket(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    zone: str,
    minimum: Decimal,
    maximum: Optional[Decimal],
    effective_from: date,
    effective_to: Optional[date] = None,
    exclude_id: Optional[UUID] = None,
) -> None:
    result = await db.execute(
        select(ShippingProfile).where(
            ShippingProfile.tenant_id == tenant_id,
            ShippingProfile.destination_zone == zone,
        )
    )
    for existing in result.scalars().all():
        if existing.id == exclude_id:
            continue
        # Two profiles in force on different dates may claim the same parcel:
        # that is what a repricing is.
        if not _dates_overlap(
            effective_from, effective_to, existing.effective_from, existing.effective_to
        ):
            continue
        if _brackets_overlap(
            minimum,
            maximum,
            Decimal(str(existing.weight_bracket_min_grams)),
            (
                Decimal(str(existing.weight_bracket_max_grams))
                if existing.weight_bracket_max_grams is not None
                else None
            ),
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"{existing.name!r} already covers "
                    f"{existing.weight_bracket_min_grams}g to "
                    f"{existing.weight_bracket_max_grams or 'any weight'} in zone "
                    f"{zone!r}; two profiles claiming one parcel would make its "
                    "postage depend on which row was read first"
                ),
            )


@router.get("", response_model=ShippingProfileListResponse)
async def list_shipping_profiles(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    destination_zone: Optional[str] = Query(None, description="Filter to one carrier zone"),
) -> ShippingProfileListResponse:
    """Every shipping profile, ordered by zone then bracket."""
    statement = select(ShippingProfile).where(ShippingProfile.tenant_id == tenant.id)
    if destination_zone is not None:
        statement = statement.where(ShippingProfile.destination_zone == destination_zone)
    statement = statement.order_by(
        ShippingProfile.destination_zone,
        ShippingProfile.weight_bracket_min_grams,
    )

    profiles = list((await db.execute(statement)).scalars().all())
    return ShippingProfileListResponse(
        profiles=[ShippingProfileResponse.model_validate(p) for p in profiles],
        total=len(profiles),
    )


@router.get("/{profile_id}", response_model=ShippingProfileResponse)
async def get_shipping_profile(
    profile_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> ShippingProfileResponse:
    """One shipping profile."""
    profile = await _profile_or_404(db, tenant.id, profile_id)
    return ShippingProfileResponse.model_validate(profile)


@router.post("", response_model=ShippingProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_shipping_profile(
    payload: ShippingProfileCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> ShippingProfileResponse:
    """Add a shipping profile. Requires admin or owner (FR-007a)."""
    await _refuse_overlapping_bracket(
        db,
        tenant.id,
        zone=payload.destination_zone,
        minimum=payload.weight_bracket_min_grams,
        maximum=payload.weight_bracket_max_grams,
        effective_from=payload.effective_from,
    )

    profile = ShippingProfile(tenant_id=tenant.id, **payload.model_dump())
    db.add(profile)
    await db.flush()
    await record_operator_origins(
        db,
        tenant,
        entity_type="shipping_profile",
        entity_id=profile.id,
        fields=await refuse_observed_or_409(
            db, tenant, entity_type="shipping_profile", entity=None, changes=payload.model_dump()
        ),
        user=user,
        role=await role_in_tenant(db, user.id, tenant.id),
    )
    await db.commit()
    await db.refresh(profile)
    logger.info(f"Created shipping profile {profile.name} for tenant {tenant.id}")
    return ShippingProfileResponse.model_validate(profile)


@router.put("/{profile_id}", response_model=ShippingProfileResponse)
async def update_shipping_profile(
    profile_id: UUID,
    payload: ShippingProfileUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> ShippingProfileResponse:
    """Change a shipping profile. Requires admin or owner (FR-007a).

    A change to the postage, a bracket or the zone supersedes the profile
    (task T233): it closes the day before ``effective_from`` -- today by
    default -- and the response is the new profile. Only a profile no order
    has yet been placed under, changed from its own first day, is corrected
    in place, as is a change to its name or carrier alone.
    """
    profile = await _profile_or_404(db, tenant.id, profile_id)
    changes = payload.changes()
    role = await role_in_tenant(db, user.id, tenant.id)
    fields = await refuse_observed_or_409(
        db, tenant, entity_type="shipping_profile", entity=profile, changes=changes
    )
    # `fields` is the registered figures that actually move; the zone is not a
    # figure, but a profile moved to another zone prices other parcels.
    supersedes = bool(set(fields) & POSTAGE_FIELDS) or (
        "destination_zone" in changes and changes["destination_zone"] != profile.destination_zone
    )
    opens_on = (changes.pop("effective_from", None) if supersedes else None) or clock.today()
    if supersedes and opens_on <= profile.effective_from:
        if await _has_been_used(db, profile):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"orders have been placed under this postage since "
                    f"{profile.effective_from}, so a repricing must take effect after "
                    f"that day; give an effective_from later than {profile.effective_from}"
                ),
            )
        supersedes = False

    minimum = changes.get(
        "weight_bracket_min_grams", Decimal(str(profile.weight_bracket_min_grams))
    )
    maximum = changes.get(
        "weight_bracket_max_grams",
        (
            Decimal(str(profile.weight_bracket_max_grams))
            if profile.weight_bracket_max_grams is not None
            else None
        ),
    )
    if maximum is not None and Decimal(str(maximum)) <= Decimal(str(minimum)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="weight_bracket_max_grams must be above weight_bracket_min_grams",
        )

    if not supersedes:
        await _refuse_overlapping_bracket(
            db,
            tenant.id,
            zone=changes.get("destination_zone", profile.destination_zone),
            minimum=Decimal(str(minimum)),
            maximum=Decimal(str(maximum)) if maximum is not None else None,
            effective_from=changes.get("effective_from", profile.effective_from),
            effective_to=profile.effective_to,
            exclude_id=profile.id,
        )
        for field, value in changes.items():
            setattr(profile, field, value)
        await record_operator_origins(
            db,
            tenant,
            entity_type="shipping_profile",
            entity_id=profile.id,
            fields=fields,
            user=user,
            role=role,
        )
        await db.commit()
        await db.refresh(profile)
        logger.info(f"Corrected shipping profile {profile.id} in place")
        return ShippingProfileResponse.model_validate(profile)

    successor = ShippingProfile(
        tenant_id=tenant.id,
        name=changes.get("name", profile.name),
        destination_zone=changes.get("destination_zone", profile.destination_zone),
        weight_bracket_min_grams=Decimal(str(minimum)),
        weight_bracket_max_grams=Decimal(str(maximum)) if maximum is not None else None,
        postage_cost=changes.get("postage_cost", profile.postage_cost),
        carrier=changes.get("carrier", profile.carrier),
        effective_from=opens_on,
        effective_to=profile.effective_to,
    )
    profile.effective_to = opens_on - timedelta(days=1)
    await db.flush()
    await _refuse_overlapping_bracket(
        db,
        tenant.id,
        zone=successor.destination_zone,
        minimum=successor.weight_bracket_min_grams,
        maximum=successor.weight_bracket_max_grams,
        effective_from=successor.effective_from,
        effective_to=successor.effective_to,
        exclude_id=profile.id,
    )
    db.add(successor)
    await db.flush()
    await record_operator_origins(
        db,
        tenant,
        entity_type="shipping_profile",
        entity_id=successor.id,
        fields=fields,
        user=user,
        role=role,
    )
    await db.commit()
    await db.refresh(successor)
    logger.info(f"Superseded shipping profile {profile.id} from {opens_on}")
    return ShippingProfileResponse.model_validate(successor)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shipping_profile(
    profile_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> None:
    """Remove a shipping profile. Requires admin or owner (FR-007a).

    Deleted only while no order has been placed under it; otherwise closed
    from today, so the postage those orders were planned with stays readable
    (task T233).
    """
    profile = await _profile_or_404(db, tenant.id, profile_id)
    if await _has_been_used(db, profile):
        today = clock.today()
        if profile.effective_to is None or profile.effective_to > today:
            profile.effective_to = max(today, profile.effective_from)
        await db.commit()
        logger.info(f"Closed shipping profile {profile_id}: orders were placed under it")
        return
    await db.delete(profile)
    await db.commit()
    logger.info(f"Deleted shipping profile {profile_id}")
