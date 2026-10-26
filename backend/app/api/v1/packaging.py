"""Packaging advisor API: item dimensions, box suggestions and accepting one.

Kept apart from `products.py` so that file does not grow further (plan,
Structure Decision). Routes are thin: dimensions are written by
`item_dimensions`, suggestions come from the pure `packaging_advisor`, and no
route computes a cost (FR-021).
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.provenance_http import record_operator_origins, refuse_observed_or_409
from app.auth.dependencies import (
    CurrentTenant,
    CurrentUser,
    RequireMember,
    TenantDB,
    role_in_tenant,
)
from app.models.consumable import CONTAINER_KINDS, ConsumableType
from app.models.model import Model
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.tenant import Tenant
from app.schemas.dimensions import DimensionsIn, DimensionsOut
from app.schemas.packaging import (
    AcceptPackagingRequest,
    AcceptPackagingResponse,
    ItemSizeOut,
    PackagingSuggestionsResponse,
    RoomOut,
    SizeOut,
    SuggestionOut,
    VoidFillOut,
    WrapOut,
)
from app.schemas.product import EffectivePackaging, ProductVariantResponse
from app.services import item_dimensions, packaging_advisor
from app.services.dims import Dims

logger = logging.getLogger(__name__)

router = APIRouter()


async def load_product(db: AsyncSession, tenant: Tenant, product_id: UUID) -> Product:
    """The tenant's product, or a 404 -- another tenant's reads as missing."""
    product = (
        await db.execute(
            select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id)
        )
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


def find_variant(product: Product, variant_id: Optional[UUID]) -> Optional[ProductVariant]:
    """The product's own variant, or a 404; ``None`` when no variant was asked for."""
    if variant_id is None:
        return None
    for variant in product.variants or []:
        if variant.id == variant_id:
            return variant
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variant not found")


VARIANT_PACKAGING_NOT_COSTED = "variant_packaging_not_costed"


def product_packaging_fields(product: Product, tenant: Tenant) -> dict:
    """The packaging advisor's additions to a product response, computed on read.

    ``packaging_warnings`` flags an accepted box the item no longer fits, at
    the clearance in force for it (FR-024); nothing here is stored.
    """
    clearance, fragile_clearance, _ = packaging_advisor.get_packaging_settings(tenant)
    dims, shown = item_dimensions.effective_dimensions(product)
    consumable, _quantity = item_dimensions.effective_packaging(product)
    return {
        "dimensions": shown,
        "is_fragile": bool(product.is_fragile),
        "packaging_warnings": packaging_advisor.accepted_packaging_warnings(
            dims, consumable, fragile_clearance if product.is_fragile else clearance
        ),
    }


def variant_response(
    product: Product, variant: ProductVariant, tenant: Tenant
) -> ProductVariantResponse:
    """A variant with its effective dimensions and packaging (research D11).

    A variant whose packaging differs from the product's says that its cost
    breakdown uses the product's packaging, because costing has no variant
    path (FR-039); no variant packaging cost is computed anywhere.
    """
    clearance, fragile_clearance, _ = packaging_advisor.get_packaging_settings(tenant)
    dims, shown = item_dimensions.effective_dimensions(product, variant)
    consumable, quantity = item_dimensions.effective_packaging(product, variant)
    product_consumable, product_quantity = item_dimensions.effective_packaging(product)
    differs = (getattr(consumable, "id", None), quantity) != (
        getattr(product_consumable, "id", None),
        product_quantity,
    )
    inherited = variant.packaging_consumable_id is None and variant.packaging_quantity is None
    response = ProductVariantResponse.model_validate(variant)
    return response.model_copy(
        update={
            "dimensions": shown,
            "effective_packaging": (
                EffectivePackaging(
                    consumable_id=consumable.id,
                    name=consumable.name,
                    quantity=quantity,
                    inherited=inherited,
                )
                if consumable is not None
                else None
            ),
            "packaging_notes": [VARIANT_PACKAGING_NOT_COSTED] if differs else [],
            "packaging_warnings": packaging_advisor.accepted_packaging_warnings(
                dims, consumable, fragile_clearance if product.is_fragile else clearance
            ),
        }
    )


async def _save(
    db: AsyncSession,
    tenant: Tenant,
    item: item_dimensions.DimensionedItem,
    body: DimensionsIn,
    *,
    product: Optional[Product] = None,
) -> None:
    try:
        await item_dimensions.set_dimensions(db, tenant, item, body, product=product)
    except item_dimensions.MeasurementNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except item_dimensions.MeasurementUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    await db.commit()


@router.put("/products/{product_id}/dimensions", response_model=DimensionsOut)
async def set_product_dimensions(
    product_id: UUID,
    body: DimensionsIn,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    _member: RequireMember,
) -> DimensionsOut:
    """Record a product's length × width × height (FR-001), or clear them."""
    product = await load_product(db, tenant, product_id)
    await _save(db, tenant, product, body)
    return item_dimensions.dimensions_out(product) or DimensionsOut()


@router.put("/models/{model_id}/dimensions", response_model=DimensionsOut)
async def set_model_dimensions(
    model_id: UUID,
    body: DimensionsIn,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    _member: RequireMember,
) -> DimensionsOut:
    """Record a model's length × width × height (FR-001), or clear them."""
    model = (
        await db.execute(select(Model).where(Model.id == model_id, Model.tenant_id == tenant.id))
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    await _save(db, tenant, model, body)
    return item_dimensions.dimensions_out(model) or DimensionsOut()


@router.put("/products/{product_id}/variants/{variant_id}/dimensions", response_model=DimensionsOut)
async def set_variant_dimensions(
    product_id: UUID,
    variant_id: UUID,
    body: DimensionsIn,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    _member: RequireMember,
) -> DimensionsOut:
    """Override a size variant's dimensions; clearing returns it to the product's."""
    product = await load_product(db, tenant, product_id)
    variant = find_variant(product, variant_id)
    assert variant is not None
    await _save(db, tenant, variant, body, product=product)
    _dims, shown = item_dimensions.effective_dimensions(product, variant)
    return shown or DimensionsOut()


# ============================================
# Suggestions and accepting one (US2, US4)
# ============================================


def _size(dims: Dims) -> SizeOut:
    return SizeOut(length_mm=dims.length, width_mm=dims.width, height_mm=dims.height)


def _suggestion_out(s: packaging_advisor.Suggestion, current_id: Optional[UUID]) -> SuggestionOut:
    assert s.container.inner is not None
    return SuggestionOut(
        consumable_id=s.container.id,
        name=s.container.name,
        kind=s.container.kind,
        in_stock=s.container.in_stock,
        inner=_size(s.container.inner),
        orientation=list(s.orientation),
        room_mm=RoomOut(length=s.room.length, width=s.room.width, height=s.room.height),
        empty_volume_ml=s.empty_volume_ml,
        void_fill=(
            VoidFillOut(
                consumable_id=s.void_fill.filler.id,
                name=s.void_fill.filler.name,
                quantity=s.void_fill.quantity,
            )
            if s.void_fill is not None
            else None
        ),
        wrap=WrapOut(consumable_id=s.wrap.id, name=s.wrap.name) if s.wrap is not None else None,
        is_current=s.container.id == current_id,
    )


@router.get(
    "/products/{product_id}/packaging-suggestions",
    response_model=PackagingSuggestionsResponse,
)
async def get_packaging_suggestions(
    product_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    variant_id: Optional[UUID] = Query(None, description="Suggest for this size variant"),
) -> PackagingSuggestionsResponse:
    """Every stocked box or mailer the item fits in, best first (FR-014 to FR-020).

    Computed on request and never stored (FR-022). Open to every role: a
    viewer may see suggestions but not accept one. No cost is returned
    (FR-021).
    """
    product = await load_product(db, tenant, product_id)
    variant = find_variant(product, variant_id)
    dims, shown = item_dimensions.effective_dimensions(product, variant)
    context = await packaging_advisor.load_packaging_context(db, tenant)
    fragile = bool(product.is_fragile)
    clearance = context.clearance_for(fragile)
    advice = packaging_advisor.suggest(
        dims,
        context.containers,
        clearance=clearance,
        fragile=fragile,
        fillers=context.fillers,
        wraps=context.wraps,
    )
    current, _quantity = item_dimensions.effective_packaging(product, variant)
    current_id = current.id if current is not None else None
    warnings = list(advice.warnings)
    warnings += packaging_advisor.accepted_packaging_warnings(dims, current, clearance)
    return PackagingSuggestionsResponse(
        item=(
            ItemSizeOut(
                length_mm=dims.length,
                width_mm=dims.width,
                height_mm=dims.height,
                source=shown.source if shown is not None else None,
            )
            if dims is not None
            else None
        ),
        clearance_mm=clearance,
        fragile=fragile,
        suggestions=[_suggestion_out(s, current_id) for s in advice.suggestions],
        minimum_inner=_size(advice.minimum_inner) if advice.minimum_inner is not None else None,
        warnings=warnings,
    )


@router.post("/products/{product_id}/packaging", response_model=AcceptPackagingResponse)
async def accept_packaging(
    product_id: UUID,
    body: AcceptPackagingRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    _member: RequireMember,
) -> AcceptPackagingResponse:
    """Make a box or mailer the product's packaging, or a size variant's (FR-023).

    The container need not fit -- the operator may override the advisor --
    and a product whose accepted box does not fit says so on read (FR-024).
    The packaging cost then comes from the existing costing of that box.
    """
    product = await load_product(db, tenant, product_id)
    variant = find_variant(product, body.variant_id)
    consumable = (
        await db.execute(
            select(ConsumableType).where(
                ConsumableType.id == body.consumable_id,
                ConsumableType.tenant_id == tenant.id,
            )
        )
    ).scalar_one_or_none()
    if consumable is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consumable not found")
    if consumable.packaging_kind not in CONTAINER_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{consumable.name} is not a box or mailer, so it cannot be the packaging",
        )

    target = variant if variant is not None else product
    fields: list[str] = []
    if variant is None:
        # The product's quantity is a cost input (T229): record who set it.
        fields = await refuse_observed_or_409(
            db,
            tenant,
            entity_type="product",
            entity=product,
            changes={"packaging_quantity": body.quantity},
        )
    target.packaging_consumable_id = consumable.id
    target.packaging_consumable = consumable
    target.packaging_quantity = body.quantity
    if fields:
        await record_operator_origins(
            db,
            tenant,
            entity_type="product",
            entity_id=product.id,
            fields=fields,
            user=user,
            role=await role_in_tenant(db, user.id, tenant.id),
        )
    await db.commit()
    logger.info(
        f"Accepted {consumable.name} x{body.quantity} as packaging of "
        f"{'variant ' + str(variant.id) if variant is not None else 'product ' + str(product.id)}"
    )

    clearance, fragile_clearance, _ = packaging_advisor.get_packaging_settings(tenant)
    dims, _shown = item_dimensions.effective_dimensions(product, variant)
    return AcceptPackagingResponse(
        consumable_id=consumable.id,
        quantity=body.quantity,
        variant_id=variant.id if variant is not None else None,
        packaging_warnings=packaging_advisor.accepted_packaging_warnings(
            dims, consumable, fragile_clearance if product.is_fragile else clearance
        ),
    )
