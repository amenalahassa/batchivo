"""Filament purchase endpoints, with the landed cost each spool inherits (T048).

FR-008a records the buying event rather than a per-gram figure the operator
worked out by hand; FR-008b allocates its inbound shipping across the spools by
weight, because weight is what drove the postage. Nothing here is stored: the
allocation is derived on read (Constitution V), so adding a spool to a purchase
corrects every sibling's share at once.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import CurrentTenant, CurrentUser, TenantDB
from app.models.filament_purchase import FilamentPurchase
from app.schemas.filament_purchase import (
    FilamentPurchaseCreate,
    FilamentPurchaseListResponse,
    FilamentPurchaseResponse,
    FilamentPurchaseUpdate,
    SpoolLandedCostResponse,
)
from app.services.landed_cost import allocate_purchase, spool_landed_cost

logger = logging.getLogger(__name__)

router = APIRouter()


def _render(purchase: FilamentPurchase) -> FilamentPurchaseResponse:
    """A purchase with its spools' landed costs, from one allocation.

    One allocation for the whole purchase rather than one per spool: the shares
    are only coherent if they were computed together.
    """
    spools = list(purchase.spools)
    allocation = allocate_purchase(purchase, spools)

    entries = []
    for spool in spools:
        landed = spool_landed_cost(spool, purchase, allocation=allocation)
        entries.append(
            SpoolLandedCostResponse(
                spool_id=spool.id,
                spool_label=spool.spool_id,
                purchase_price=landed.purchase_price,
                allocated_shipping=landed.allocated_shipping,
                allocated_tax=landed.allocated_tax,
                tax_recoverable=landed.tax_recoverable,
                nominal_weight_grams=landed.nominal_weight_grams,
                unusable_remainder_grams=landed.unusable_remainder_grams,
                usable_weight_grams=landed.usable_weight_grams,
                total_landed_cost=landed.total_landed_cost,
                cost_per_gram=landed.cost_per_gram,
                even_split_fallback=landed.even_split_fallback,
                incomplete_reasons=list(landed.incomplete_reasons),
                derivation=list(landed.derivation),
            )
        )

    return FilamentPurchaseResponse(
        id=purchase.id,
        supplier=purchase.supplier,
        purchase_date=purchase.purchase_date,
        inbound_shipping_cost=purchase.inbound_shipping_cost,
        tax_amount=purchase.tax_amount,
        tax_recoverable=purchase.tax_recoverable,
        order_reference=purchase.order_reference,
        notes=purchase.notes,
        spools=entries,
        allocation_notes=list(allocation.notes),
    )


async def _load(db: AsyncSession, tenant, purchase_id: UUID) -> FilamentPurchase:
    """One purchase with its spools eager-loaded, or a 404."""
    result = await db.execute(
        select(FilamentPurchase)
        .where(
            FilamentPurchase.id == purchase_id,
            FilamentPurchase.tenant_id == tenant.id,
        )
        .options(selectinload(FilamentPurchase.spools))
    )
    purchase = result.scalars().first()
    if purchase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Filament purchase not found",
        )
    return purchase


@router.post("", response_model=FilamentPurchaseResponse, status_code=status.HTTP_201_CREATED)
async def create_filament_purchase(
    purchase_data: FilamentPurchaseCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> FilamentPurchaseResponse:
    """Record a purchase. Spools are attached to it afterwards."""
    purchase = FilamentPurchase(tenant_id=tenant.id, **purchase_data.model_dump())
    db.add(purchase)
    await db.commit()
    await db.refresh(purchase, attribute_names=["spools"])
    logger.info(f"Recorded filament purchase {purchase.id} for tenant {tenant.id}")
    return _render(purchase)


@router.get("", response_model=FilamentPurchaseListResponse)
async def list_filament_purchases(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> FilamentPurchaseListResponse:
    """Purchases, most recent first, each with its per-spool allocation."""
    total_result = await db.execute(
        select(func.count())
        .select_from(FilamentPurchase)
        .where(FilamentPurchase.tenant_id == tenant.id)
    )
    total = int(total_result.scalar_one())

    result = await db.execute(
        select(FilamentPurchase)
        .where(FilamentPurchase.tenant_id == tenant.id)
        .options(selectinload(FilamentPurchase.spools))
        .order_by(FilamentPurchase.purchase_date.desc(), FilamentPurchase.created_at.desc())
        .offset(skip)
        .limit(limit)
    )

    return FilamentPurchaseListResponse(
        purchases=[_render(purchase) for purchase in result.scalars().all()],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{purchase_id}", response_model=FilamentPurchaseResponse)
async def get_filament_purchase(
    purchase_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> FilamentPurchaseResponse:
    """One purchase, with each spool's landed cost and its derivation."""
    return _render(await _load(db, tenant, purchase_id))


@router.put("/{purchase_id}", response_model=FilamentPurchaseResponse)
async def update_filament_purchase(
    purchase_id: UUID,
    purchase_data: FilamentPurchaseUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> FilamentPurchaseResponse:
    """Correct a purchase; every spool's share follows from the new figures."""
    purchase = await _load(db, tenant, purchase_id)

    for field, value in purchase_data.model_dump(exclude_none=True).items():
        setattr(purchase, field, value)

    db.add(purchase)
    await db.commit()
    await db.refresh(purchase, attribute_names=["spools"])
    return _render(purchase)


@router.delete("/{purchase_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_filament_purchase(
    purchase_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> None:
    """Delete a purchase. Its spools survive and cost from their own price.

    FR-008e: a spool with no parent purchase stays valid. Detaching explicitly
    rather than relying on the foreign key's behaviour keeps that promise
    whichever database the deployment runs on.
    """
    purchase = await _load(db, tenant, purchase_id)

    for spool in purchase.spools:
        spool.filament_purchase_id = None
        db.add(spool)

    await db.delete(purchase)
    await db.commit()
    logger.info(f"Deleted filament purchase {purchase_id} for tenant {tenant.id}")
