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
"""

import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireAdmin, TenantDB
from app.models.shipping_profile import ShippingProfile
from app.schemas.fee_rule import (
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


async def _refuse_overlapping_bracket(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    zone: str,
    minimum: Decimal,
    maximum: Optional[Decimal],
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
    )

    profile = ShippingProfile(tenant_id=tenant.id, **payload.model_dump())
    db.add(profile)
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
    """Change a shipping profile. Requires admin or owner (FR-007a)."""
    profile = await _profile_or_404(db, tenant.id, profile_id)
    changes = payload.changes()

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

    await _refuse_overlapping_bracket(
        db,
        tenant.id,
        zone=changes.get("destination_zone", profile.destination_zone),
        minimum=Decimal(str(minimum)),
        maximum=Decimal(str(maximum)) if maximum is not None else None,
        exclude_id=profile.id,
    )

    for field, value in changes.items():
        setattr(profile, field, value)
    await db.commit()
    await db.refresh(profile)
    logger.info(f"Updated shipping profile {profile.id}")
    return ShippingProfileResponse.model_validate(profile)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shipping_profile(
    profile_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> None:
    """Remove a shipping profile. Requires admin or owner (FR-007a)."""
    profile = await _profile_or_404(db, tenant.id, profile_id)
    await db.delete(profile)
    await db.commit()
    logger.info(f"Deleted shipping profile {profile_id}")
