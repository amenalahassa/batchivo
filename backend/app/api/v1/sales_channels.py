"""Sales Channels API endpoints.

## The planning economics are not columns on this resource any more

``expected_discount_pct``, ``expected_refund_pct``,
``free_shipping_threshold``, ``rounding_rule`` and -- since task T216 --
``monthly_cost``, ``tax_remitter``, ``offsite_ads_opt_in`` and
``currency_code`` are operator decisions (FR-002) and are effective-dated
(FR-003, task T136): they live in ``sales_channel_economics``, one row per
period, and ``app/services/channel_economics.py`` is the only thing that reads
or writes them. Every one of them needs the owner or admin, on create as on
update (FR-007a).

They still appear on this resource's body, because to an operator they are
part of "the channel" and splitting the screen in two would be a storage
decision imposed on them. What changed is underneath: a write opens a new
period rather than editing the old one, and a read resolves the period in
force on ``as_of`` -- so the figures a quote was built on stay readable after
the operator changes their mind.
"""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.auth.dependencies import (
    CurrentTenant,
    CurrentUser,
    TenantDB,
    MONETARY_ROLES,
    role_in_tenant,
)
from app.models.sales_channel import SalesChannel
from app.models.sales_channel_economics import ECONOMICS_FIELDS
from app.schemas.sales_channel import (
    SalesChannelCreate,
    SalesChannelListResponse,
    SalesChannelResponse,
    SalesChannelUpdate,
)
from app.services.channel_economics import (
    ChannelEconomics,
    EconomicsMisconfigured,
    economics_from_row,
    resolve_channel_economics,
    resolve_many,
    write_economics,
)

router = APIRouter()

# Changing a reserve or a rounding rule is monetary policy, which FR-007a
# reserves to the owner and the admin (`MONETARY_ROLES`). The rest of a channel
# -- its name, its platform, whether it is active -- is operational, so the
# gate is on the figures rather than on the endpoint.


def _response(channel: SalesChannel, economics: ChannelEconomics) -> SalesChannelResponse:
    """The channel, with its planning figures as at the resolved date.

    The four figures come from the resolved period rather than from the
    channel's own columns, which are a fallback for a channel with no period
    at all (Constitution III: one authority).
    """
    return SalesChannelResponse.model_validate(channel).model_copy(
        update={field: getattr(economics, field) for field in ECONOMICS_FIELDS}
    )


@router.post("", response_model=SalesChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_sales_channel(
    channel_data: SalesChannelCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> SalesChannelResponse:
    """
    Create a new sales channel.

    Requires authentication.
    Channel will be associated with current tenant.
    Name must be unique per tenant.
    """
    # Check if name already exists for this tenant
    existing = await db.execute(
        select(SalesChannel).where(
            SalesChannel.tenant_id == tenant.id,
            SalesChannel.name == channel_data.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Sales channel with name '{channel_data.name}' already exists",
        )

    # Validate platform type
    valid_platforms = ["fair", "online_shop", "shopify", "ebay", "etsy", "amazon", "other"]
    if channel_data.platform_type not in valid_platforms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid platform type. Must be one of: {', '.join(valid_platforms)}",
        )

    # The levers are monetary policy (FR-007a): a body that names any of them
    # needs the owner or admin, refused before anything is written. A member
    # may still create a channel with the defaults -- naming it and choosing
    # its platform is operational, and the defaults decide nothing.
    body = channel_data.model_dump()
    named = channel_data.model_fields_set
    economics_values = {field: body.pop(field) for field in ECONOMICS_FIELDS}
    role = await role_in_tenant(db, user.id, tenant.id)
    if named & set(ECONOMICS_FIELDS) and role not in MONETARY_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setting a channel's economics requires the owner or admin role",
        )

    # The levers are not written onto the channel's own columns, which are a
    # fallback for a channel with no period (task T216); the first period
    # carries them, with who set them.
    channel = SalesChannel(tenant_id=tenant.id, **body)

    db.add(channel)
    await db.flush()

    # The channel's first period, dated from today and carrying the figures the
    # body asked for. Every channel gets one, which is what keeps the
    # legacy-column fallback unreachable in a live database.
    try:
        economics = await write_economics(
            db,
            tenant,
            channel,
            economics_values,
            user=user,
            role=role,
        )
    except EconomicsMisconfigured as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    await db.commit()
    await db.refresh(channel)
    await db.refresh(economics)

    return _response(channel, economics_from_row(economics))


@router.get("", response_model=SalesChannelListResponse)
async def list_sales_channels(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max items to return"),
    search: Optional[str] = Query(None, description="Search by name"),
    platform_type: Optional[str] = Query(None, description="Filter by platform type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    as_of: Optional[date] = Query(
        None,
        description=(
            "Read each channel's planning economics as they stood on this date "
            "instead of today (FR-003)"
        ),
    ),
) -> SalesChannelListResponse:
    """
    List all sales channels for current tenant with pagination and filtering.

    The planning economics are the ones in force on ``as_of``, today by
    default.
    """
    # Build query
    query = select(SalesChannel).where(SalesChannel.tenant_id == tenant.id)

    # Apply filters
    if search:
        search_pattern = f"%{search}%"
        query = query.where(SalesChannel.name.ilike(search_pattern))

    if platform_type:
        query = query.where(SalesChannel.platform_type == platform_type)

    if is_active is not None:
        query = query.where(SalesChannel.is_active == is_active)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Apply pagination and fetch
    query = query.order_by(SalesChannel.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    channels = result.scalars().all()

    # One query for every channel's period rather than one per channel.
    resolved = await resolve_many(db, list(channels), as_of)
    return SalesChannelListResponse(
        channels=[_response(c, resolved[c.id]) for c in channels],
        total=total or 0,
    )


@router.get("/{channel_id}", response_model=SalesChannelResponse)
async def get_sales_channel(
    channel_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    as_of: Optional[date] = Query(
        None,
        description=(
            "Read the planning economics as they stood on this date instead of today (FR-003)"
        ),
    ),
) -> SalesChannelResponse:
    """
    Get sales channel detail.

    Requires authentication.
    Channel must belong to current tenant.

    The planning economics are the ones in force on ``as_of``, today by
    default -- so a quote dated last month can be explained with the reserves
    that were set then.
    """
    query = select(SalesChannel).where(
        SalesChannel.id == channel_id,
        SalesChannel.tenant_id == tenant.id,
    )

    result = await db.execute(query)
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sales channel not found",
        )

    return _response(channel, await resolve_channel_economics(db, channel, as_of))


@router.put("/{channel_id}", response_model=SalesChannelResponse)
async def update_sales_channel(
    channel_id: UUID,
    channel_data: SalesChannelUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> SalesChannelResponse:
    """
    Update an existing sales channel.

    Requires authentication.
    Channel must belong to current tenant.
    """
    # Fetch channel
    query = select(SalesChannel).where(
        SalesChannel.id == channel_id,
        SalesChannel.tenant_id == tenant.id,
    )

    result = await db.execute(query)
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sales channel not found",
        )

    # Check name uniqueness if changing
    if channel_data.name and channel_data.name != channel.name:
        existing = await db.execute(
            select(SalesChannel).where(
                SalesChannel.tenant_id == tenant.id,
                SalesChannel.name == channel_data.name,
                SalesChannel.id != channel_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Sales channel with name '{channel_data.name}' already exists",
            )

    # Validate platform type if provided
    if channel_data.platform_type:
        valid_platforms = ["fair", "online_shop", "shopify", "ebay", "etsy", "amazon", "other"]
        if channel_data.platform_type not in valid_platforms:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid platform type. Must be one of: {', '.join(valid_platforms)}",
            )

    update_data = channel_data.model_dump(exclude_unset=True)
    update_data.pop("effective_from", None)

    # The planning figures are superseded, never set (FR-003). The rest of the
    # channel is ordinary mutable configuration and is set in place.
    economics_changes = {
        field: update_data.pop(field) for field in ECONOMICS_FIELDS if field in update_data
    }
    for field, value in update_data.items():
        setattr(channel, field, value)

    if economics_changes:
        role = await role_in_tenant(db, user.id, tenant.id)
        if role not in MONETARY_ROLES:
            # FR-007a: a reserve is monetary policy. Refused before anything is
            # written, so a member's attempt leaves nothing half-applied.
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=("Changing a channel's planning economics requires the owner or admin role"),
            )
        try:
            await write_economics(
                db,
                tenant,
                channel,
                economics_changes,
                user=user,
                role=role,
                effective_from=channel_data.effective_from,
            )
        except EconomicsMisconfigured as exc:
            # A figure that could not be used once stored is a validation
            # failure: the operator can fix the body and try again.
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    await db.commit()
    await db.refresh(channel)

    return _response(
        channel,
        await resolve_channel_economics(db, channel, channel_data.effective_from),
    )


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sales_channel(
    channel_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    permanent: bool = Query(False, description="Permanently delete instead of soft delete"),
):
    """
    Delete a sales channel.

    By default, performs a soft delete (sets is_active=False).
    Use ?permanent=true to permanently remove the channel from the database.

    Requires authentication.
    Channel must belong to current tenant.
    """
    query = select(SalesChannel).where(
        SalesChannel.id == channel_id,
        SalesChannel.tenant_id == tenant.id,
    )

    result = await db.execute(query)
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sales channel not found",
        )

    if permanent:
        # Hard delete - permanently remove from database
        await db.delete(channel)
    else:
        # Soft delete - just mark as inactive
        channel.is_active = False
    await db.commit()
