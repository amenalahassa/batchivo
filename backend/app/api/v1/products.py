"""Product catalog API endpoints (sellable items composed of models)."""

import re
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

import ipaddress
import socket


def _slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug.strip("-")


import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import clock
from app.api.provenance_http import record_operator_origins, refuse_observed_or_409
from app.auth.dependencies import (
    CurrentTenant,
    CurrentUser,
    RequireAdmin,
    RequireMember,
    TenantDB,
    role_in_tenant,
)
from app.models.designer import Designer
from app.models.fee_rule import FeeRule
from app.models.model import Model
from app.models.product import Product
from app.models.product_component import ProductComponent
from app.models.product_image import ProductImage
from app.models.product_model import ProductModel
from app.models.product_pricing import ProductPricing
from app.models.product_variant import ProductVariant
from app.models.sales_channel import SalesChannel
from app.models.tenant import Tenant
from app.schemas.fee_rule import FeeChargeResponse
from app.schemas.price_ladder import PriceLadderResponse, PriceLadderRungResponse
from app.schemas.price_solve import (
    PriceAdjustmentResponse,
    PriceSolveRequest,
    PriceSolveResponse,
)
from app.schemas.product_margin import ProductMarginResponse, RevenueDeductionResponse
from app.schemas.model import CostBreakdown
from app.schemas.product import (
    ProductComponentCreate,
    ProductComponentResponse,
    ProductComponentUpdate,
    ProductCreate,
    ProductDetailResponse,
    ProductListResponse,
    ProductModelCreate,
    ProductModelResponse,
    ProductPricingCreate,
    ProductPricingResponse,
    ProductPricingUpdate,
    ProductResponse,
    ProductUpdate,
    ProductVariantCreate,
    ProductVariantResponse,
    ProductVariantUpdate,
)
from app.schemas.product_image import (
    ImportImageFromUrlRequest,
    ProductImageResponse,
    ProductImageUpdate,
    ProductImageListResponse,
)
from app.services.currency_edge import CostConversion, books_to_channel
from app.services import fee_engine, pricing_solver, temporal_pricing
from app.services.channel_economics import ChannelEconomics, resolve_channel_economics
from app.services.cost_resolution import cost_load_options, product_cost_breakdown
from app.services.costing import (
    MARGIN_BASIS_LABELS,
    CircularReferenceError,
    CostingService,
    MaxDepthExceededError,
    resolve_margin_basis,
)
from app.services.postage import postage_for_product
from app.services.pricing_policy import CostPolicy, resolve_cost_policy
from app.services.etsy_sync import EtsySyncService, EtsySyncError
from app.services.shopify_sync import (
    ShopifySyncService,
    ShopifySyncError,
    ShopifyNotConfiguredError,
)
from app.services.image_storage import ImageStorage, ImageStorageError, get_image_storage
from app.services.search_service import SearchService, get_search_service
from app.schemas.external_listing import (
    ExternalListingResponse,
    SyncToEtsyRequest,
    SyncToEtsyResponse,
    SyncToShopifyRequest,
    SyncToShopifyResponse,
    ProductSyncStatusResponse,
    SyncStatusChannel,
)

router = APIRouter()


def _get_product_load_options():
    """Everything a product response needs loaded.

    The cost-bearing tree comes from `cost_load_options()`, which the catalogue
    sweep behind a scenario uses as well: one declaration, so a relationship
    added to the engine's reach cannot be eager-loaded on one path and
    lazy-loaded into a 500 on the other (Constitution III). The extras below
    are presentation only.
    """
    return [
        *cost_load_options(),
        # Load pricing with sales channels
        selectinload(Product.pricing).selectinload(ProductPricing.sales_channel),
        # Load designer for attribution
        selectinload(Product.designer),
        # Load categories
        selectinload(Product.categories),
    ]


# Helper function to calculate and attach cost breakdown
async def product_with_cost(product: Product, db: AsyncSession, tenant: Tenant) -> dict:
    """Convert Product model to response dict with cost breakdown.

    The policy is resolved from the database once per response, so no two
    figures in one payload can disagree, and the flat total here is built from
    the same snapshot `GET /products/{id}/cost` itemises (Constitution III).
    """
    policy = await resolve_cost_policy(db, tenant)

    cost_breakdown = CostingService.calculate_product_cost(product, policy=policy)

    # Build model responses with details
    model_responses = []
    for pm in product.product_models:
        model_cost = (
            CostingService.calculate_model_cost(pm.model, policy=policy) if pm.model else None
        )
        model_responses.append(
            {
                "id": pm.id,
                "product_id": pm.product_id,
                "model_id": pm.model_id,
                "quantity": pm.quantity,
                "model_name": pm.model.name if pm.model else None,
                "model_sku": pm.model.sku if pm.model else None,
                "model_cost": model_cost.total_cost if model_cost else None,
                "created_at": pm.created_at,
            }
        )

    # Build child product responses with details (for bundles)
    child_product_responses = []
    for pc in getattr(product, "child_products", []):
        child = pc.child_product
        if child:
            child_cost = CostingService.calculate_product_cost(child, policy=policy)
            child_product_responses.append(
                {
                    "id": pc.id,
                    "parent_product_id": pc.parent_product_id,
                    "child_product_id": pc.child_product_id,
                    "quantity": pc.quantity,
                    "child_product_name": child.name,
                    "child_product_sku": child.sku,
                    "child_product_cost": child_cost.total_make_cost,
                    "created_at": pc.created_at,
                }
            )

    # Build pricing responses with profit calculations.
    #
    # `current_pricing` rather than `pricing`: since Tier 3 the second is the
    # full history, and the detail screen wants what the product sells for now
    # (task T097). The history has its own endpoint, which deliberately reports
    # no profit figures -- valuing a past price against today's cost is the
    # restatement FR-038 exists to prevent.
    pricing_responses = []
    for pricing in product.current_pricing:
        channel = pricing.sales_channel
        profit_data = (
            await _row_profit(
                db, tenant, product, channel, Decimal(str(pricing.list_price)), policy
            )
            if channel
            else None
        )
        pricing_responses.append(
            {
                "id": pricing.id,
                "product_id": pricing.product_id,
                "sales_channel_id": pricing.sales_channel_id,
                "list_price": pricing.list_price,
                "is_active": pricing.is_active,
                # The period and tier this price belongs to. Required on the
                # response since Tier 3: a price without its period reads as
                # though it had always applied, which is the ambiguity FR-039
                # removes.
                "valid_from": pricing.valid_from,
                "valid_to": pricing.valid_to,
                "is_current": pricing.is_current,
                "min_quantity": pricing.min_quantity,
                "channel_name": channel.name if channel else None,
                "platform_type": channel.platform_type if channel else None,
                "platform_fee": profit_data["platform_fee"],
                "net_revenue": profit_data["net_revenue"],
                "profit": profit_data["profit"],
                "margin_percentage": profit_data["margin_percentage"],
                "profit_per_machine_hour": profit_data["profit_per_machine_hour"],
                "created_at": pricing.created_at,
                "updated_at": pricing.updated_at,
            }
        )

    # Get packaging consumable info if linked
    packaging_consumable = getattr(product, "packaging_consumable", None)

    # Get designer info if linked
    designer = getattr(product, "designer", None)

    # Get categories
    categories = getattr(product, "categories", [])
    category_responses = [{"id": cat.id, "name": cat.name, "slug": cat.slug} for cat in categories]

    return {
        **{k: v for k, v in product.__dict__.items() if not k.startswith("_")},
        "models": model_responses,
        "child_products": child_product_responses,
        "pricing": pricing_responses,
        "cost_breakdown": cost_breakdown,
        "packaging_consumable_name": packaging_consumable.name if packaging_consumable else None,
        "packaging_consumable_sku": packaging_consumable.sku if packaging_consumable else None,
        "packaging_consumable_cost": packaging_consumable.current_cost_per_unit
        if packaging_consumable
        else None,
        # Designer info for attribution
        "designer_name": designer.name if designer else None,
        "designer_slug": designer.slug if designer else None,
        "designer_logo_url": designer.logo_url if designer else None,
        # Categories
        "categories": category_responses,
    }


@router.post("", response_model=ProductDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    product_data: ProductCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _: RequireAdmin,
    db: TenantDB,
) -> ProductDetailResponse:
    """
    Create a new product (sellable item).

    Requires admin role or higher.
    Product will be associated with current tenant.
    SKU must be unique per tenant.
    Can optionally include models (product_models) and child products (bundles) in creation.
    """
    # Check if SKU already exists for this tenant
    existing = await db.execute(
        select(Product).where(
            Product.tenant_id == tenant.id,
            Product.sku == product_data.sku,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Product with SKU '{product_data.sku}' already exists",
        )

    # Validate designer if provided
    if product_data.designer_id:
        designer = await db.get(Designer, product_data.designer_id)
        if not designer or designer.tenant_id != tenant.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Designer {product_data.designer_id} not found",
            )

    # Extract models and child products for separate processing
    models_data = product_data.models or []
    child_products_data = product_data.child_products or []
    product_dict = product_data.model_dump(exclude={"models", "child_products"})

    fields = await refuse_observed_or_409(
        db,
        tenant,
        entity_type="product",
        entity=None,
        changes=product_data.model_dump(exclude_unset=True),
    )

    # Create product instance
    product = Product(
        tenant_id=tenant.id,
        **product_dict,
    )

    # Auto-generate seo_slug from name if not explicitly provided
    if not product.seo_slug:
        product.seo_slug = _slugify(product.name)

    db.add(product)
    await db.flush()  # Get the product ID
    # Packaging and assembly figures the body named are this person's
    # measurement, not an assumption (FR-001, task T229).
    await record_operator_origins(
        db,
        tenant,
        entity_type="product",
        entity_id=product.id,
        fields=fields,
        user=user,
        role=await role_in_tenant(db, user.id, tenant.id),
    )

    # Add models if provided
    for model_data in models_data:
        # Verify model exists and belongs to tenant
        model = await db.get(Model, model_data.model_id)
        if not model or model.tenant_id != tenant.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Model {model_data.model_id} not found",
            )

        product_model = ProductModel(
            product_id=product.id,
            model_id=model_data.model_id,
            quantity=model_data.quantity,
        )
        db.add(product_model)

    # Add child products if provided (for bundles)
    for child_data in child_products_data:
        # Verify child product exists and belongs to tenant
        child_product = await db.get(Product, child_data.child_product_id)
        if not child_product or child_product.tenant_id != tenant.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Child product {child_data.child_product_id} not found",
            )

        # Prevent self-reference
        if child_data.child_product_id == product.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A product cannot contain itself",
            )

        product_component = ProductComponent(
            parent_product_id=product.id,
            child_product_id=child_data.child_product_id,
            quantity=child_data.quantity,
        )
        db.add(product_component)

    await db.commit()

    # Reload with relationships
    query = select(Product).where(Product.id == product.id).options(*_get_product_load_options())
    result = await db.execute(query)
    product = result.scalar_one()

    return ProductDetailResponse(**await product_with_cost(product, db, tenant))


@router.get("", response_model=ProductListResponse)
async def list_products(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max items to return"),
    search: Optional[str] = Query(
        None, description="Full-text search by name, SKU, or description"
    ),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    designer_id: Optional[UUID] = Query(None, description="Filter by designer"),
    search_service: SearchService = Depends(get_search_service),
) -> ProductListResponse:
    """
    List all products for current tenant with pagination and filtering.

    Includes calculated make cost and suggested price for each product.
    Uses PostgreSQL full-text search when search parameter is provided.
    """
    # If search is provided, use the search service for FTS
    if search:
        # Use full-text search service
        products, total = await search_service.search_products(
            query=search,
            tenant_id=tenant.id,
            active_only=is_active if is_active is not None else True,
            limit=limit,
            offset=skip,
        )

        # Apply designer filter if provided (post-filter since FTS doesn't support it)
        if designer_id:
            products = [p for p in products if p.designer_id == designer_id]
            # Note: total might be inaccurate with post-filtering, but acceptable for search

        # Load relationships for cost calculation
        product_ids = [p.id for p in products]
        if product_ids:
            query = (
                select(Product)
                .where(Product.id.in_(product_ids))
                .options(*_get_product_load_options())
            )
            result = await db.execute(query)
            products_with_rels = {p.id: p for p in result.scalars().all()}
            products = [
                products_with_rels.get(p.id, p) for p in products if p.id in products_with_rels
            ]

        # Resolve the operator's policy once per request, not once per row: a
        # rejected setting would otherwise log a warning for every product, and
        # two rows in one list must never be costed at two different rates.
        policy = await resolve_cost_policy(db, tenant)

        # Build response with calculated costs
        product_responses = []
        for product in products:
            cost_breakdown = CostingService.calculate_product_cost(
                product,
                policy=policy,
            )
            total_make_cost = cost_breakdown.total_make_cost

            designer = getattr(product, "designer", None)

            product_dict = {
                "id": product.id,
                "tenant_id": product.tenant_id,
                "sku": product.sku,
                "name": product.name,
                "description": product.description,
                "designer_id": product.designer_id,
                "packaging_cost": product.packaging_cost,
                "packaging_consumable_id": product.packaging_consumable_id,
                "packaging_quantity": product.packaging_quantity,
                "assembly_minutes": product.assembly_minutes,
                "units_in_stock": product.units_in_stock,
                "is_active": product.is_active,
                "shop_visible": product.shop_visible,
                "print_to_order": product.print_to_order,
                "free_shipping": product.free_shipping,
                "shop_description": product.shop_description,
                "is_featured": product.is_featured,
                "is_dragon": product.is_dragon,
                "feature_title": product.feature_title,
                "backstory": product.backstory,
                "weight_grams": product.weight_grams,
                "size_cm": product.size_cm,
                "print_time_hours": product.print_time_hours,
                "tags": product.tags,
                "product_type": product.product_type,
                "seo_slug": product.seo_slug,
                "seo_title": product.seo_title,
                "seo_description": product.seo_description,
                "material": product.material,
                "colour_options": product.colour_options,
                "etsy_taxonomy_id": product.etsy_taxonomy_id,
                "created_at": product.created_at,
                "updated_at": product.updated_at,
                "total_make_cost": total_make_cost,
                "incomplete_reasons": cost_breakdown.incomplete_reasons,
                "designer_name": designer.name if designer else None,
                "designer_slug": designer.slug if designer else None,
                "designer_logo_url": designer.logo_url if designer else None,
            }
            product_responses.append(ProductResponse(**product_dict))

        return ProductListResponse(
            products=product_responses,
            total=total,
            skip=skip,
            limit=limit,
        )

    # Standard query without FTS
    # Build base query
    base_query = select(Product).where(Product.tenant_id == tenant.id)

    if is_active is not None:
        base_query = base_query.where(Product.is_active == is_active)

    if designer_id is not None:
        base_query = base_query.where(Product.designer_id == designer_id)

    # Get total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total = await db.scalar(count_query)

    # Apply pagination and fetch with relationships for cost calculation
    query = (
        base_query.options(*_get_product_load_options())
        .order_by(Product.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    products = result.scalars().all()

    # Resolve the operator's policy once per request, not once per row: a
    # rejected setting would otherwise log a warning for every product, and two
    # rows in one list must never be costed at two different rates.
    policy = await resolve_cost_policy(db, tenant)

    # Build response with calculated costs
    product_responses = []
    for product in products:
        # Calculate cost breakdown
        cost_breakdown = CostingService.calculate_product_cost(
            product,
            policy=policy,
        )
        total_make_cost = cost_breakdown.total_make_cost

        # Get designer info
        designer = getattr(product, "designer", None)

        # Build response dict
        product_dict = {
            "id": product.id,
            "tenant_id": product.tenant_id,
            "sku": product.sku,
            "name": product.name,
            "description": product.description,
            "designer_id": product.designer_id,
            "packaging_cost": product.packaging_cost,
            "packaging_consumable_id": product.packaging_consumable_id,
            "packaging_quantity": product.packaging_quantity,
            "assembly_minutes": product.assembly_minutes,
            "units_in_stock": product.units_in_stock,
            "is_active": product.is_active,
            "shop_visible": product.shop_visible,
            "print_to_order": product.print_to_order,
            "free_shipping": product.free_shipping,
            "shop_description": product.shop_description,
            "is_featured": product.is_featured,
            "is_dragon": product.is_dragon,
            "feature_title": product.feature_title,
            "backstory": product.backstory,
            "weight_grams": product.weight_grams,
            "size_cm": product.size_cm,
            "print_time_hours": product.print_time_hours,
            "tags": product.tags,
            "product_type": product.product_type,
            "seo_slug": product.seo_slug,
            "seo_title": product.seo_title,
            "seo_description": product.seo_description,
            "material": product.material,
            "colour_options": product.colour_options,
            "etsy_taxonomy_id": product.etsy_taxonomy_id,
            "created_at": product.created_at,
            "updated_at": product.updated_at,
            "total_make_cost": total_make_cost,
            "incomplete_reasons": cost_breakdown.incomplete_reasons,
            # Designer info
            "designer_name": designer.name if designer else None,
            "designer_slug": designer.slug if designer else None,
            "designer_logo_url": designer.logo_url if designer else None,
        }
        product_responses.append(ProductResponse(**product_dict))

    return ProductListResponse(
        products=product_responses,
        total=total or 0,
        skip=skip,
        limit=limit,
    )


@router.get("/{product_id}", response_model=ProductDetailResponse)
async def get_product(
    product_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> ProductDetailResponse:
    """
    Get product detail with models, child products (bundles), pricing, and cost breakdown.
    """
    query = (
        select(Product)
        .where(
            Product.id == product_id,
            Product.tenant_id == tenant.id,
            Product.is_active.is_(True),
        )
        .options(*_get_product_load_options())
    )

    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    return ProductDetailResponse(**await product_with_cost(product, db, tenant))


@router.get("/{product_id}/cost", response_model=CostBreakdown)
async def get_product_cost(
    product_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> CostBreakdown:
    """The itemised make-cost of one sellable unit (task T049).

    Bundles cost recursively. A cycle in the operator's own bill of materials
    is a 409 naming the chain it found, and so is a hierarchy deeper than the
    engine will walk: both are data the operator can fix, and neither is a
    figure worth serving (FR-017).
    """
    query = (
        select(Product)
        .where(
            Product.id == product_id,
            Product.tenant_id == tenant.id,
            Product.is_active.is_(True),
        )
        .options(*_get_product_load_options())
    )
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    try:
        return await product_cost_breakdown(db, tenant, product)
    except CircularReferenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": "circular_reference",
                "message": str(exc),
                "product_id": str(exc.product_id),
                "chain": [str(visited) for visited in exc.visited],
            },
        ) from exc
    except MaxDepthExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": "max_depth_exceeded",
                "message": str(exc),
                "depth": exc.depth,
                "max_depth": exc.max_depth,
            },
        ) from exc


@router.get(
    "/{product_id}/pricing/{channel_id}/margin",
    response_model=ProductMarginResponse,
)
async def get_product_margin(
    product_id: UUID,
    channel_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    as_of: Optional[date] = Query(
        None, description="Read the fee rules and policy in effect on this date"
    ),
    quantity: int = Query(1, ge=1, description="Units on the hypothetical line"),
) -> ProductMarginResponse:
    """What one unit earns on one channel at the price in effect (task T079).

    Everything behind the figure is returned, because a margin an operator
    cannot explain is a margin they cannot act on (FR-018): the itemised fees
    with their bases and clamps, the reserves, postage paid against shipping
    revenue, the margin basis that produced the percentage (FR-031b), and the
    share of the make-cost resting on observation rather than assumption.

    A product that is not priced on this channel is a ``404``, not a zero
    margin. A zero looks like a real figure, and a product nobody has priced is
    not earning nothing -- it is not for sale.
    """
    reference = as_of or clock.today()

    product = (
        await db.execute(
            select(Product)
            .where(
                Product.id == product_id,
                Product.tenant_id == tenant.id,
                Product.is_active.is_(True),
            )
            .options(*_get_product_load_options())
        )
    ).scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    channel = (
        await db.execute(
            select(SalesChannel).where(
                SalesChannel.id == channel_id,
                SalesChannel.tenant_id == tenant.id,
            )
        )
    ).scalar_one_or_none()
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sales channel not found",
        )

    # Resolved as at `reference`, not "the" price: since Tier 3 this product
    # may carry several periods and several quantity tiers on this channel, and
    # a margin asked for as at a past date must use the price that applied then
    # (task T097, FR-039). `ProductPricing` carries no tenant_id of its own --
    # it is scoped through the product and the channel, both already checked
    # against the tenant above.
    pricing = await temporal_pricing.price_as_of(
        db,
        product.id,
        channel.id,
        as_of=reference,
        quantity=quantity,
    )
    if not pricing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"This product was not priced on that channel on {reference}, so "
                f"it has no margin there -- which is not the same as a margin of zero"
            ),
        )

    policy = await resolve_cost_policy(db, tenant, reference)
    try:
        breakdown = await product_cost_breakdown(db, tenant, product, policy=policy)
    except CircularReferenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "circular_reference", "message": str(exc)},
        ) from exc
    except MaxDepthExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "max_depth_exceeded", "message": str(exc)},
        ) from exc

    rules = list(
        (
            await db.execute(
                select(FeeRule).where(
                    FeeRule.sales_channel_id == channel.id,
                    FeeRule.tenant_id == tenant.id,
                )
            )
        )
        .scalars()
        .all()
    )

    # Shipping revenue is what this channel charges the customer. Until an
    # order exists there is none to read, so a planned margin is computed at
    # zero shipping revenue -- which is the free-shipping case FR-024 exists
    # for, and the case the acceptance scenario uses.
    context, treatment = fee_engine.exclusive_context(
        item_subtotal=Decimal(str(pricing.list_price)),
        quantity=quantity,
    )
    stack = fee_engine.compute(channel, context, reference, rules=rules)

    conversion = await _costs_in_channel_currency(db, tenant, channel, reference)
    postage = conversion.apply(await _postage_for(db, tenant, product))

    result = CostingService.margin(
        context=context,
        make_cost=conversion.apply(breakdown.total_make_cost),
        channel=channel,
        fees=stack,
        policy=policy,
        economics=await resolve_channel_economics(db, channel, reference),
        tax=treatment,
        postage_paid=postage,
        machine_hours=breakdown.machine_hours,
        observed_share=breakdown.observed_share,
        assumed_share=breakdown.assumed_share,
        incomplete_reasons=[*breakdown.incomplete_reasons, *conversion.reasons],
    )

    return ProductMarginResponse(
        product_id=product.id,
        sales_channel_id=channel.id,
        as_of=reference,
        list_price=result.list_price,
        shipping_revenue=result.shipping_revenue,
        postage_paid=result.postage_paid,
        shipping_net=result.shipping_net,
        make_cost=result.make_cost,
        fees=[FeeChargeResponse.model_validate(charge) for charge in result.fees],
        fee_total=result.fee_total,
        deductions=[
            RevenueDeductionResponse(
                key=deduction.key,
                label=deduction.label,
                amount=deduction.amount,
                rate_pct=deduction.rate_pct,
                basis_amount=deduction.basis_amount,
            )
            for deduction in result.deductions
        ],
        deduction_total=result.deduction_total,
        net_revenue=result.net_revenue,
        profit=result.profit,
        margin_pct=result.margin_pct,
        margin_basis=result.margin_basis,
        margin_basis_label=result.margin_basis_label,
        margin_basis_amount=result.margin_basis_amount,
        profit_per_machine_hour=result.profit_per_machine_hour,
        machine_hours=result.machine_hours,
        sales_tax_collected=result.sales_tax_collected,
        sales_tax_liability=result.sales_tax_liability,
        tax_remitter=result.tax_remitter,
        tax_exclusive_derived=result.tax_exclusive_derived,
        revenue_tax_exclusive=result.revenue_tax_exclusive,
        observed_share=result.observed_share,
        assumed_share=result.assumed_share,
        incomplete_reasons=result.incomplete_reasons,
    )


async def _costs_in_channel_currency(
    db: AsyncSession, tenant: Tenant, channel: SalesChannel, reference: date
) -> CostConversion:
    """How book-currency costs become the channel's currency, or a ``409``.

    Task T231: a cost kept in one currency is never subtracted from a price in
    another. Where no rate between them is recorded the answer is a question
    for the operator -- enter a rate -- never parity and never a figure.
    """
    conversion = await books_to_channel(db, tenant, channel, reference)
    if not conversion.known:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "no_exchange_rate", "message": conversion.reasons[0]},
        )
    return conversion


async def _postage_for(
    db: AsyncSession,
    tenant: Tenant,
    product: Product,
) -> Decimal:
    """Postage for one parcel of this product.

    Delegates to :func:`app.services.postage.postage_for_product`, which the
    storefront checkout reads too (task T157). A route keeping its own copy
    would let the margin this screen reports and the postage frozen onto a
    settled order disagree about one parcel (Constitution III).
    """
    return await postage_for_product(db, tenant, product)


async def _planned_profit(
    db: AsyncSession,
    tenant: Tenant,
    product: Product,
    channel: SalesChannel,
    list_price: Decimal,
    make_cost: Decimal,
    *,
    policy: Optional[CostPolicy] = None,
    machine_hours: Optional[Decimal] = None,
) -> dict:
    """The fee, net revenue, profit and margin one price row carries.

    And profit per machine-hour beside the margin (task T234, FR-043): null,
    never zero, where nobody has timed the print.

    Through the fee engine and `CostingService.margin` -- the same path the
    margin endpoint uses. It was previously a blended percentage read from the
    channel's `fee_percentage` and `fee_fixed` columns, which made this response
    a second fee implementation (Constitution III): the product detail screen
    and the margin screen could show two different margins for one price, and
    the one here was always the optimistic figure, because a single percentage
    cannot represent a marketplace that also charges processing, a regulatory
    fee and postage.

    Shipping revenue is zero: until an order exists there is none to read, which
    is the free-shipping case of FR-024 and what the acceptance scenario uses.
    """
    rules = list(
        (
            await db.execute(
                select(FeeRule).where(
                    FeeRule.sales_channel_id == channel.id,
                    FeeRule.tenant_id == tenant.id,
                )
            )
        )
        .scalars()
        .all()
    )

    context, treatment = fee_engine.exclusive_context(item_subtotal=list_price)
    reference = clock.today()
    # A price row on a channel selling in another currency, with no rate on
    # record, has no profit to state (task T231) -- not a profit at parity.
    conversion = await books_to_channel(db, tenant, channel, reference)
    if not conversion.known:
        return {
            "platform_fee": None,
            "net_revenue": None,
            "profit": None,
            "margin_percentage": None,
            "profit_per_machine_hour": None,
        }
    result = CostingService.margin(
        context=context,
        make_cost=conversion.apply(make_cost),
        channel=channel,
        fees=fee_engine.compute(channel, context, reference, rules=rules),
        policy=policy if policy is not None else await resolve_cost_policy(db, tenant),
        economics=await resolve_channel_economics(db, channel, reference),
        tax=treatment,
        postage_paid=conversion.apply(await _postage_for(db, tenant, product)),
        machine_hours=machine_hours,
    )

    return {
        "platform_fee": result.fee_total,
        "net_revenue": result.net_revenue,
        "profit": result.profit,
        "margin_percentage": result.margin_pct,
        "profit_per_machine_hour": result.profit_per_machine_hour,
    }


async def _row_profit(
    db: AsyncSession,
    tenant: Tenant,
    product: Product,
    channel: SalesChannel,
    list_price: Decimal,
    policy: CostPolicy,
) -> dict:
    """One price row's figures, from the engine's structured breakdown.

    The make cost and machine time come from `product_cost_breakdown`, the
    breakdown the margin endpoint, the solver, the ladder and the queue ranking
    all read. The row used the flat `calculate_product_cost` traversal, a
    second derivation that disagreed with the margin screen by a cent (T234).
    """
    breakdown = await product_cost_breakdown(db, tenant, product, policy=policy)
    return await _planned_profit(
        db,
        tenant,
        product,
        channel,
        list_price,
        breakdown.total_make_cost,
        policy=policy,
        machine_hours=breakdown.machine_hours,
    )


# ---------------------------------------------------------------------------
# The target-margin solver and the price ladder (tasks T088, T088a)
# ---------------------------------------------------------------------------


class _PricingContext:
    """Everything a price question about one product on one channel needs.

    The solver and the ladder ask the same five things of the database -- the
    product, the channel, the policy and economics in effect and the fee rules
    -- and both
    then need the make-cost and the postage. Resolving that once here is what
    keeps them from drifting apart, and from drifting away from the margin
    endpoint above, which resolves the same figures the same way.
    """

    def __init__(
        self,
        product: Product,
        channel: SalesChannel,
        pricing: ProductPricing,
        policy,
        rules: list[FeeRule],
        breakdown: CostBreakdown,
        postage: Decimal,
        economics: ChannelEconomics,
    ) -> None:
        self.product = product
        self.channel = channel
        self.pricing = pricing
        self.policy = policy
        self.rules = rules
        self.breakdown = breakdown
        self.postage = postage
        # The channel's planning figures as at the reference date (FR-003,
        # task T136), not as the channel row stands today: a quote dated last
        # month must still explain itself under the reserves then in force.
        self.economics = economics


async def _pricing_context(
    db: AsyncSession,
    tenant: Tenant,
    product_id: UUID,
    channel_id: UUID,
    reference: date,
) -> _PricingContext:
    """Load and cost one product on one channel, or raise the right error.

    A missing product or channel is a ``404``, and so is a product the operator
    has not listed on that channel: every route under
    ``/products/{id}/pricing/{channel_id}/`` describes that listing, and asking
    what to charge somewhere the product is not sold has no answer to give. The
    message names the prior step rather than leaving the caller to guess it.

    A cycle or an over-deep bundle in the operator's own bill of materials is a
    ``409`` naming what was found, exactly as the cost and margin endpoints
    report them -- a price solved from a cost the engine refused to compute
    would be a number with nothing behind it.
    """
    product = (
        await db.execute(
            select(Product)
            .where(
                Product.id == product_id,
                Product.tenant_id == tenant.id,
                Product.is_active.is_(True),
            )
            .options(*_get_product_load_options())
        )
    ).scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    channel = (
        await db.execute(
            select(SalesChannel).where(
                SalesChannel.id == channel_id,
                SalesChannel.tenant_id == tenant.id,
            )
        )
    ).scalar_one_or_none()
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sales channel not found",
        )

    # Resolved as at `reference` rather than read as "the" price: a product may
    # carry several periods and tiers on this channel (task T097, FR-039).
    # `ProductPricing` carries no tenant_id of its own; it is scoped through the
    # product and the channel, both already checked against the tenant above.
    pricing = await temporal_pricing.price_as_of(
        db,
        product.id,
        channel.id,
        as_of=reference,
    )
    if not pricing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "This product is not sold on that channel, so there is no "
                "price there to solve for or to vary -- list it on the channel "
                "first, then ask what it should charge"
            ),
        )

    policy = await resolve_cost_policy(db, tenant, reference)
    try:
        breakdown = await product_cost_breakdown(db, tenant, product, policy=policy)
    except CircularReferenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "circular_reference", "message": str(exc)},
        ) from exc
    except MaxDepthExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "max_depth_exceeded", "message": str(exc)},
        ) from exc

    rules = list(
        (
            await db.execute(
                select(FeeRule).where(
                    FeeRule.sales_channel_id == channel.id,
                    FeeRule.tenant_id == tenant.id,
                )
            )
        )
        .scalars()
        .all()
    )

    # The solver and the ladder are handed costs already in the channel's
    # currency, so a solved price is a price there (task T231).
    conversion = await _costs_in_channel_currency(db, tenant, channel, reference)
    postage = conversion.apply(await _postage_for(db, tenant, product))
    economics = await resolve_channel_economics(db, channel, reference)
    if conversion.rate != 1:
        breakdown = breakdown.model_copy(
            update={
                "total_make_cost": conversion.apply(breakdown.total_make_cost),
                "incomplete_reasons": [*breakdown.incomplete_reasons, *conversion.reasons],
            }
        )
    return _PricingContext(product, channel, pricing, policy, rules, breakdown, postage, economics)


def _reasons_for(ctx: "_PricingContext", reference: date) -> list[str]:
    """What a solved price or a ladder rests on that is not certain.

    The cost breakdown's own gaps, the exchange rate's, and a channel whose fee
    rules have all lapsed on the date asked about (task T236) -- a price solved
    over zero fees that are really unknown would look cheaper than it is.
    """
    return list(
        dict.fromkeys(
            [
                *ctx.breakdown.incomplete_reasons,
                *fee_engine.lapsed_rules_reasons(ctx.rules, reference),
            ]
        )
    )


def _rendered_inputs(inputs: dict) -> dict[str, str]:
    """FR-034's inputs as strings, so no money crosses the wire as a number.

    A `Decimal` serialised into a JSON number is exactly the lossiness
    Constitution IV exists to prevent, and this payload is a free-form map that
    no field annotation can police -- so every value is rendered here.
    """
    rendered: dict[str, str] = {}
    for key, value in inputs.items():
        if value is None:
            continue
        if isinstance(value, dict):
            rendered[key] = ", ".join(f"{name}={amount}" for name, amount in value.items())
        else:
            rendered[key] = str(value)
    return rendered


@router.post(
    "/{product_id}/pricing/{channel_id}/solve",
    response_model=PriceSolveResponse,
)
async def solve_product_price(
    product_id: UUID,
    channel_id: UUID,
    request: PriceSolveRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> PriceSolveResponse:
    """The price that achieves a target margin on one channel (task T088).

    The arithmetic an operator cannot do with a calculator: the percentage fees
    a marketplace charges are charged on the price being solved for, so cost
    plus a markup less the fees leaves a margin several points below the one
    asked for. FR-032 is this endpoint, and FR-034 is why it returns every
    figure behind the answer rather than the answer alone.

    A target no price can achieve is a ``422`` naming the binding constraint
    (FR-035), never a very large number -- which would read as an answer.

    **The result is a proposal.** Nothing is published to any channel; applying
    it is a separate write on the price (US4 scenario 5). This endpoint is a
    ``POST`` because the body carries the target, not because it changes
    anything: it writes nothing at all.
    """
    reference = request.as_of or clock.today()
    ctx = await _pricing_context(db, tenant, product_id, channel_id, reference)

    result = pricing_solver.solve(
        channel=ctx.channel,
        make_cost=ctx.breakdown.total_make_cost,
        target_margin_pct=request.target_margin_pct,
        as_of=reference,
        rules=ctx.rules,
        postage_paid=ctx.postage,
        shipping_revenue=request.shipping_revenue,
        extras=request.extras,
        quantity=request.quantity,
        policy=ctx.policy,
        economics=ctx.economics,
        margin_basis=request.margin_basis,
        # `apply_rounding=False` still quantises to the cent; what it turns off
        # is the operator's rule, which is the part that moves the price by
        # more than a rounding boundary.
        rounding_rule=(request.rounding_rule if request.apply_rounding else "nearest_cent"),
        snap_to_free_shipping=request.snap_to_free_shipping,
    )

    fees: list[FeeChargeResponse] = []
    if result.price is not None:
        context = fee_engine.OrderContext(
            item_subtotal=result.price,
            shipping_revenue=request.shipping_revenue,
            extras=request.extras,
            quantity=request.quantity,
        )
        stack = fee_engine.compute(ctx.channel, context, reference, rules=ctx.rules)
        fees = [FeeChargeResponse.model_validate(charge) for charge in stack.charges]

    payload = PriceSolveResponse(
        product_id=ctx.product.id,
        sales_channel_id=ctx.channel.id,
        as_of=reference,
        achievable=result.achievable,
        reason=result.reason,
        binding_constraint=result.binding_constraint,
        target_margin_pct=result.target_margin_pct,
        margin_basis=result.margin_basis,
        margin_basis_label=result.margin_basis_label,
        required_price_raw=result.raw_price,
        required_price_rounded=result.price,
        adjustments=[
            PriceAdjustmentResponse(
                key=adjustment.key,
                label=adjustment.label,
                from_price=adjustment.from_price,
                to_price=adjustment.to_price,
                delta=adjustment.delta,
            )
            for adjustment in result.adjustments
        ],
        binding_clamps=result.binding_clamps,
        margin_pct_at_price=result.margin_pct_at_price,
        profit_at_price=result.profit_at_price,
        make_cost=ctx.breakdown.total_make_cost,
        postage_paid=ctx.postage,
        incomplete_reasons=_reasons_for(ctx, reference),
        fees=fees,
        inputs=_rendered_inputs(result.inputs),
        passes=result.passes,
    )

    if not result.achievable:
        # 422 rather than 200-with-a-null-price: the request asked for a figure
        # that does not exist, and an interface that has to inspect a boolean
        # inside a 200 to discover that will eventually forget to.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=payload.model_dump(mode="json"),
        )

    return payload


@router.get(
    "/{product_id}/pricing/{channel_id}/ladder",
    response_model=PriceLadderResponse,
)
async def get_product_price_ladder(
    product_id: UUID,
    channel_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    price_from: Decimal = Query(..., gt=0, description="First price on the ladder"),
    price_to: Decimal = Query(..., gt=0, description="Last price on the ladder"),
    step: Decimal = Query(..., gt=0, description="Distance between rungs"),
    quantity: int = Query(1, ge=1, description="Units on the hypothetical line"),
    shipping_revenue: Decimal = Query(
        Decimal("0"), ge=0, description="Shipping revenue charged to the customer"
    ),
    as_of: Optional[date] = Query(
        None, description="Read the fee rules and policy in effect on this date"
    ),
) -> PriceLadderResponse:
    """Margin at each of a range of prices (task T088a).

    FR-007 forbids storing or computing a market judgement as a single number:
    what a customer will pay is not derivable from any data this system holds,
    so a single "recommended price" would be a figure resting on nothing while
    sitting beside figures that are real.

    This is the alternative. The operator names the range and the step -- there
    are no defaults, because a default range's midpoint would function as a
    recommendation wearing a different hat -- and the system reports margin,
    profit and profit per machine-hour at each point. Nothing is written.

    ``price_from`` above ``price_to``, or a step of zero, is a ``422``: an
    empty ladder would read as "no price works".
    """
    reference = as_of or clock.today()
    ctx = await _pricing_context(db, tenant, product_id, channel_id, reference)

    try:
        rungs = pricing_solver.ladder(
            channel=ctx.channel,
            make_cost=ctx.breakdown.total_make_cost,
            start=price_from,
            stop=price_to,
            step=step,
            as_of=reference,
            rules=ctx.rules,
            postage_paid=ctx.postage,
            shipping_revenue=shipping_revenue,
            quantity=quantity,
            machine_hours=ctx.breakdown.machine_hours,
            policy=ctx.policy,
            economics=ctx.economics,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    basis = resolve_margin_basis(ctx.policy)
    return PriceLadderResponse(
        product_id=ctx.product.id,
        sales_channel_id=ctx.channel.id,
        as_of=reference,
        price_from=price_from,
        price_to=price_to,
        step=step,
        margin_basis=basis,
        margin_basis_label=MARGIN_BASIS_LABELS[basis],
        make_cost=ctx.breakdown.total_make_cost,
        postage_paid=ctx.postage,
        incomplete_reasons=_reasons_for(ctx, reference),
        machine_hours=ctx.breakdown.machine_hours,
        rungs=[PriceLadderRungResponse.model_validate(rung) for rung in rungs],
    )


@router.put("/{product_id}", response_model=ProductDetailResponse)
async def update_product(
    product_id: UUID,
    product_data: ProductUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ProductDetailResponse:
    """
    Update an existing product.

    Requires the member role (FR-007c). A packaging cost or quantity, or the
    assembly minutes, that moves has its origin recorded as `measured` against
    the person who moved it, and an observed one is refused (task T229).
    """
    # Fetch product
    query = (
        select(Product)
        .where(
            Product.id == product_id,
            Product.tenant_id == tenant.id,
        )
        .options(*_get_product_load_options())
    )

    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Check SKU uniqueness if changing
    if product_data.sku and product_data.sku != product.sku:
        existing = await db.execute(
            select(Product).where(
                Product.tenant_id == tenant.id,
                Product.sku == product_data.sku,
                Product.id != product_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product with SKU '{product_data.sku}' already exists",
            )

    # Validate designer if being updated
    if product_data.designer_id is not None:
        designer = await db.get(Designer, product_data.designer_id)
        if not designer or designer.tenant_id != tenant.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Designer {product_data.designer_id} not found",
            )

    # Update fields
    update_data = product_data.model_dump(exclude_unset=True)
    fields = await refuse_observed_or_409(
        db, tenant, entity_type="product", entity=product, changes=update_data
    )
    for field, value in update_data.items():
        setattr(product, field, value)
    await record_operator_origins(
        db,
        tenant,
        entity_type="product",
        entity_id=product.id,
        fields=fields,
        user=user,
        role=await role_in_tenant(db, user.id, tenant.id),
    )

    # Auto-generate seo_slug from (new) name if name changed and seo_slug wasn't explicitly set
    if "name" in update_data and "seo_slug" not in update_data and not product.seo_slug:
        product.seo_slug = _slugify(product.name)

    await db.commit()
    await db.refresh(product)

    return ProductDetailResponse(**await product_with_cost(product, db, tenant))


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _: RequireAdmin,
    db: TenantDB,
    purge: bool = Query(
        False,
        description="Hard-delete the product from the database. Only allowed on inactive products.",
    ),
):
    """
    Delete a product.

    Without ?purge=true: soft delete by setting is_active=False.
    With ?purge=true: hard delete from the database. Only allowed on inactive products.

    Requires admin role or higher.
    """
    query = select(Product).where(
        Product.id == product_id,
        Product.tenant_id == tenant.id,
    )

    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if purge:
        if product.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot purge an active product. Deactivate it first.",
            )
        await db.delete(product)
    else:
        product.is_active = False

    await db.commit()


# ==================== Product Models (Composition) Management ====================


@router.post(
    "/{product_id}/models", response_model=ProductModelResponse, status_code=status.HTTP_201_CREATED
)
async def add_product_model(
    product_id: UUID,
    model_data: ProductModelCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ProductModelResponse:
    """
    Add a model to product composition.
    """
    # Verify product exists and belongs to tenant
    product = await db.get(Product, product_id)
    if not product or product.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Verify model exists and belongs to tenant
    model = await db.get(Model, model_data.model_id)
    if not model or model.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    # Check if this model is already in the product
    existing = await db.execute(
        select(ProductModel).where(
            ProductModel.product_id == product_id,
            ProductModel.model_id == model_data.model_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This model is already in the product",
        )

    # Create product-model entry
    product_model = ProductModel(
        product_id=product_id,
        model_id=model_data.model_id,
        quantity=model_data.quantity,
    )

    db.add(product_model)
    await db.commit()
    await db.refresh(product_model)

    # Calculate model cost
    model_cost = CostingService.calculate_model_cost(
        model,
        policy=await resolve_cost_policy(db, tenant),
    )

    return ProductModelResponse(
        id=product_model.id,
        product_id=product_model.product_id,
        model_id=product_model.model_id,
        quantity=product_model.quantity,
        model_name=model.name,
        model_sku=model.sku,
        model_cost=model_cost.total_cost,
        created_at=product_model.created_at,
    )


@router.put("/{product_id}/models/{product_model_id}", response_model=ProductModelResponse)
async def update_product_model(
    product_id: UUID,
    product_model_id: UUID,
    model_data: ProductModelCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ProductModelResponse:
    """
    Update a model's quantity in product composition.
    """
    # Fetch product-model with related model
    query = (
        select(ProductModel)
        .join(Product)
        .where(
            ProductModel.id == product_model_id,
            ProductModel.product_id == product_id,
            Product.tenant_id == tenant.id,
        )
        .options(selectinload(ProductModel.model))
    )

    result = await db.execute(query)
    product_model = result.scalar_one_or_none()

    if not product_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product model not found",
        )

    product_model.quantity = model_data.quantity
    await db.commit()
    await db.refresh(product_model)

    model_cost = CostingService.calculate_model_cost(
        product_model.model,
        policy=await resolve_cost_policy(db, tenant),
    )

    return ProductModelResponse(
        id=product_model.id,
        product_id=product_model.product_id,
        model_id=product_model.model_id,
        quantity=product_model.quantity,
        model_name=product_model.model.name,
        model_sku=product_model.model.sku,
        model_cost=model_cost.total_cost,
        created_at=product_model.created_at,
    )


@router.delete("/{product_id}/models/{product_model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_product_model(
    product_id: UUID,
    product_model_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
):
    """
    Remove a model from product composition.
    """
    query = (
        select(ProductModel)
        .join(Product)
        .where(
            ProductModel.id == product_model_id,
            ProductModel.product_id == product_id,
            Product.tenant_id == tenant.id,
        )
    )

    result = await db.execute(query)
    product_model = result.scalar_one_or_none()

    if not product_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product model not found",
        )

    await db.delete(product_model)
    await db.commit()


# ==================== Product Pricing Management ====================


def _pricing_response(
    pricing: ProductPricing,
    channel: Optional[SalesChannel],
    profit_data: Optional[dict],
) -> ProductPricingResponse:
    """One price row as the API serves it, period included.

    ``profit_data`` is omitted for a historical row: computing its margin would
    mean valuing a past price against today's costs, which is the restatement
    FR-038 exists to prevent. A settled order's own snapshot is where a
    historical margin lives.
    """
    return ProductPricingResponse(
        id=pricing.id,
        product_id=pricing.product_id,
        sales_channel_id=pricing.sales_channel_id,
        list_price=pricing.list_price,
        is_active=pricing.is_active,
        min_quantity=pricing.min_quantity,
        valid_from=pricing.valid_from,
        valid_to=pricing.valid_to,
        is_current=pricing.is_current,
        channel_name=channel.name if channel else None,
        platform_type=channel.platform_type if channel else None,
        platform_fee=profit_data["platform_fee"] if profit_data else None,
        net_revenue=profit_data["net_revenue"] if profit_data else None,
        profit=profit_data["profit"] if profit_data else None,
        margin_percentage=profit_data["margin_percentage"] if profit_data else None,
        profit_per_machine_hour=(profit_data["profit_per_machine_hour"] if profit_data else None),
        created_at=pricing.created_at,
        updated_at=pricing.updated_at,
    )


@router.post(
    "/{product_id}/pricing",
    response_model=ProductPricingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_product_pricing(
    product_id: UUID,
    pricing_data: ProductPricingCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ProductPricingResponse:
    """
    Add pricing for a product on a sales channel.
    """
    # Fetch product with models for cost calculation
    query = (
        select(Product)
        .where(
            Product.id == product_id,
            Product.tenant_id == tenant.id,
        )
        .options(
            selectinload(Product.product_models)
            .selectinload(ProductModel.model)
            .selectinload(Model.materials),
            selectinload(Product.product_models)
            .selectinload(ProductModel.model)
            .selectinload(Model.components),
        )
    )

    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Verify sales channel exists and belongs to tenant
    channel = await db.get(SalesChannel, pricing_data.sales_channel_id)
    if not channel or channel.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sales channel not found",
        )

    # A price already in effect for this channel and tier is no longer a
    # conflict -- it is the period this one supersedes. `set_price` closes it
    # and opens the new one, so the old figure stays readable as at its own
    # dates (task T097, FR-039). What is still refused is backdating behind the
    # current period's start, which would make two prices apply to the same
    # days; `PriceOverlapError` says so and names the row it collided with.
    try:
        pricing = await temporal_pricing.set_price(
            db,
            product_id=product_id,
            sales_channel_id=pricing_data.sales_channel_id,
            list_price=pricing_data.list_price,
            valid_from=pricing_data.valid_from,
            min_quantity=pricing_data.min_quantity,
            is_active=pricing_data.is_active,
        )
    except temporal_pricing.PriceOverlapError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    await db.commit()
    await db.refresh(pricing)

    # Calculate profit
    profit_data = await _row_profit(
        db,
        tenant,
        product,
        channel,
        Decimal(str(pricing.list_price)),
        await resolve_cost_policy(db, tenant),
    )

    return _pricing_response(pricing, channel, profit_data)


@router.get(
    "/{product_id}/pricing/{channel_id}/history",
    response_model=list[ProductPricingResponse],
)
async def get_product_pricing_history(
    product_id: UUID,
    channel_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> list[ProductPricingResponse]:
    """Every price this product has carried on this channel (task T097).

    FR-039 makes the history readable, and this is where it is read: newest
    first, each row carrying the period it applied over. Open to every role,
    like every other cost and price figure (FR-007c) -- what a product used to
    sell for is not privileged information, and hiding it is how an operator
    ends up unable to explain a margin that moved.
    """
    product = (
        await db.execute(
            select(Product).where(
                Product.id == product_id,
                Product.tenant_id == tenant.id,
            )
        )
    ).scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    channel = (
        await db.execute(
            select(SalesChannel).where(
                SalesChannel.id == channel_id,
                SalesChannel.tenant_id == tenant.id,
            )
        )
    ).scalar_one_or_none()
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sales channel not found",
        )

    rows = list(
        (
            await db.execute(
                select(ProductPricing)
                .where(
                    ProductPricing.product_id == product_id,
                    ProductPricing.sales_channel_id == channel_id,
                )
                .order_by(
                    ProductPricing.valid_from.desc(),
                    ProductPricing.min_quantity,
                )
            )
        )
        .scalars()
        .all()
    )

    # No profit figures here, deliberately. A historical price's margin would
    # have to be computed from today's costs, which is exactly the restatement
    # FR-038 forbids -- a settled order's own snapshot is where that margin
    # lives. This endpoint reports prices and periods, nothing derived.
    return [_pricing_response(row, channel, None) for row in rows]


@router.put("/{product_id}/pricing/{pricing_id}", response_model=ProductPricingResponse)
async def update_product_pricing(
    product_id: UUID,
    pricing_id: UUID,
    pricing_data: ProductPricingUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ProductPricingResponse:
    """Change a product's price, or delist it (task T097).

    **A price change opens a new period rather than editing this one.** The row
    addressed by ``pricing_id`` is closed the day before the new price applies
    and a new row is returned, so an order placed last month still reports the
    price it was actually charged (FR-039, Constitution VI). A caller that
    expected the same ``id`` back is getting the honest answer instead: that
    price is now a historical fact and a different row holds the current one.

    **Delisting is not a price change.** ``is_active`` edits the current row,
    because whether a product is listed is a status rather than an amount, and
    recording a period for it would clutter the history with rows whose price
    never changed.

    A superseded row cannot be repriced at all: its period has passed, and
    rewriting it would restate what customers were charged.
    """
    query = (
        select(ProductPricing)
        .join(Product)
        .where(
            ProductPricing.id == pricing_id,
            ProductPricing.product_id == product_id,
            Product.tenant_id == tenant.id,
        )
        .options(
            selectinload(ProductPricing.sales_channel),
            selectinload(ProductPricing.product)
            .selectinload(Product.product_models)
            .selectinload(ProductModel.model),
        )
    )

    result = await db.execute(query)
    pricing = result.scalar_one_or_none()

    if not pricing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pricing not found",
        )

    channel = pricing.sales_channel
    product = pricing.product
    update_data = pricing_data.model_dump(exclude_unset=True)
    new_price = update_data.get("list_price")

    if new_price is not None and Decimal(str(new_price)) != Decimal(str(pricing.list_price)):
        if not pricing.is_current:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"this price applied from {pricing.valid_from} to "
                    f"{pricing.valid_to} and has been superseded, so it cannot be "
                    f"changed -- rewriting it would restate what customers were "
                    f"actually charged. Price the product again to open a new period"
                ),
            )
        try:
            pricing = await temporal_pricing.set_price(
                db,
                product_id=product_id,
                sales_channel_id=pricing.sales_channel_id,
                list_price=new_price,
                valid_from=update_data.get("valid_from"),
                min_quantity=pricing.min_quantity,
                is_active=update_data.get("is_active", pricing.is_active),
            )
        except temporal_pricing.PriceOverlapError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
    elif "is_active" in update_data:
        pricing.is_active = update_data["is_active"]
        db.add(pricing)

    await db.commit()
    await db.refresh(pricing)

    profit_data = None
    if product is not None:
        profit_data = await _row_profit(
            db,
            tenant,
            product,
            channel,
            Decimal(str(pricing.list_price)),
            await resolve_cost_policy(db, tenant),
        )

    return _pricing_response(pricing, channel, profit_data)


@router.delete("/{product_id}/pricing/{pricing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_product_pricing(
    product_id: UUID,
    pricing_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
):
    """Delist a product from a channel by closing its current price period.

    Not a delete, for the current row. An order placed yesterday has to keep
    reporting the price it was charged, and deleting the row would leave it
    reporting nothing (FR-039, Constitution VI). So the period is closed as of
    today and the product stops being priced on that channel from tomorrow.

    A **superseded** row is deleted outright when asked: it is already closed,
    nothing reads it as current, and an operator cleaning up a mistyped
    historical period should be able to. What they cannot do is rewrite one.
    """
    query = (
        select(ProductPricing)
        .join(Product)
        .where(
            ProductPricing.id == pricing_id,
            ProductPricing.product_id == product_id,
            Product.tenant_id == tenant.id,
        )
    )

    result = await db.execute(query)
    pricing = result.scalar_one_or_none()

    if not pricing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pricing not found",
        )

    if pricing.is_current:
        today = clock.today()
        if pricing.valid_from >= today:
            # Opened today and withdrawn today: there is no day of history to
            # keep, so removing it is the coherent answer rather than closing
            # it to a period that ends before it begins.
            await db.delete(pricing)
        else:
            pricing.valid_to = today
            pricing.is_active = False
            db.add(pricing)
    else:
        await db.delete(pricing)

    await db.commit()


# ==================== Product Components (Bundle Composition) Management ====================


async def _check_circular_reference(
    db: AsyncSession,
    parent_id: UUID,
    child_id: UUID,
    visited: set | None = None,
) -> bool:
    """
    Check if adding child_id as a component of parent_id would create a circular reference.

    Returns True if circular reference would be created, False otherwise.
    """
    if visited is None:
        visited = set()

    if parent_id == child_id:
        return True

    if child_id in visited:
        return True

    visited.add(child_id)

    # Check if parent_id appears anywhere in child's descendants
    query = select(ProductComponent).where(ProductComponent.parent_product_id == child_id)
    result = await db.execute(query)
    child_components = result.scalars().all()

    for component in child_components:
        if component.child_product_id == parent_id:
            return True
        if await _check_circular_reference(db, parent_id, component.child_product_id, visited):
            return True

    return False


@router.post(
    "/{product_id}/components",
    response_model=ProductComponentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_product_component(
    product_id: UUID,
    component_data: ProductComponentCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ProductComponentResponse:
    """
    Add a child product to this product (create a bundle/set).

    The child product's cost will be included in the parent product's total make cost.
    Circular references are not allowed (A cannot contain B if B contains A).
    """
    # Verify parent product exists and belongs to tenant
    parent_product = await db.get(Product, product_id)
    if not parent_product or parent_product.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Verify child product exists and belongs to tenant
    child_product = await db.get(Product, component_data.child_product_id)
    if not child_product or child_product.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Child product not found",
        )

    # Prevent self-reference
    if component_data.child_product_id == product_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A product cannot contain itself",
        )

    # Check for circular references
    if await _check_circular_reference(db, product_id, component_data.child_product_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Adding this product would create a circular reference",
        )

    # Check if this child product is already in the parent
    existing = await db.execute(
        select(ProductComponent).where(
            ProductComponent.parent_product_id == product_id,
            ProductComponent.child_product_id == component_data.child_product_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This product is already a component of the parent product",
        )

    # Create product component entry
    product_component = ProductComponent(
        parent_product_id=product_id,
        child_product_id=component_data.child_product_id,
        quantity=component_data.quantity,
    )

    db.add(product_component)
    await db.commit()
    await db.refresh(product_component)

    # Calculate child product cost
    # Need to load child product with its relationships for cost calculation
    query = (
        select(Product)
        .where(Product.id == component_data.child_product_id)
        .options(*_get_product_load_options())
    )
    result = await db.execute(query)
    child_product_loaded = result.scalar_one()

    child_cost = CostingService.calculate_product_cost(
        child_product_loaded,
        policy=await resolve_cost_policy(db, tenant),
    )

    return ProductComponentResponse(
        id=product_component.id,
        parent_product_id=product_component.parent_product_id,
        child_product_id=product_component.child_product_id,
        quantity=product_component.quantity,
        child_product_name=child_product.name,
        child_product_sku=child_product.sku,
        child_product_cost=child_cost.total_make_cost,
        created_at=product_component.created_at,
    )


@router.put(
    "/{product_id}/components/{component_id}",
    response_model=ProductComponentResponse,
)
async def update_product_component(
    product_id: UUID,
    component_id: UUID,
    component_data: ProductComponentUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ProductComponentResponse:
    """
    Update a child product's quantity in the bundle.
    """
    # Fetch product component with related child product
    query = (
        select(ProductComponent)
        .join(Product, ProductComponent.parent_product_id == Product.id)
        .where(
            ProductComponent.id == component_id,
            ProductComponent.parent_product_id == product_id,
            Product.tenant_id == tenant.id,
        )
        .options(selectinload(ProductComponent.child_product))
    )

    result = await db.execute(query)
    product_component = result.scalar_one_or_none()

    if not product_component:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product component not found",
        )

    product_component.quantity = component_data.quantity
    await db.commit()
    await db.refresh(product_component)

    # Calculate child product cost
    query = (
        select(Product)
        .where(Product.id == product_component.child_product_id)
        .options(*_get_product_load_options())
    )
    result = await db.execute(query)
    child_product_loaded = result.scalar_one()

    child_cost = CostingService.calculate_product_cost(
        child_product_loaded,
        policy=await resolve_cost_policy(db, tenant),
    )

    return ProductComponentResponse(
        id=product_component.id,
        parent_product_id=product_component.parent_product_id,
        child_product_id=product_component.child_product_id,
        quantity=product_component.quantity,
        child_product_name=product_component.child_product.name,
        child_product_sku=product_component.child_product.sku,
        child_product_cost=child_cost.total_make_cost,
        created_at=product_component.created_at,
    )


@router.delete(
    "/{product_id}/components/{component_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_product_component(
    product_id: UUID,
    component_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
):
    """
    Remove a child product from the bundle.
    """
    query = (
        select(ProductComponent)
        .join(Product, ProductComponent.parent_product_id == Product.id)
        .where(
            ProductComponent.id == component_id,
            ProductComponent.parent_product_id == product_id,
            Product.tenant_id == tenant.id,
        )
    )

    result = await db.execute(query)
    product_component = result.scalar_one_or_none()

    if not product_component:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product component not found",
        )

    await db.delete(product_component)
    await db.commit()


# ==================== Product Images Management ====================


@router.get("/{product_id}/images", response_model=ProductImageListResponse)
async def list_product_images(
    product_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> ProductImageListResponse:
    """
    List all images for a product.
    """
    # Verify product exists and belongs to tenant
    product = await db.get(Product, product_id)
    if not product or product.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Get images ordered by display_order
    query = (
        select(ProductImage)
        .where(ProductImage.product_id == product_id)
        .order_by(ProductImage.display_order)
    )
    result = await db.execute(query)
    images = result.scalars().all()

    return ProductImageListResponse(
        images=[ProductImageResponse.model_validate(img) for img in images],
        total=len(images),
    )


@router.post(
    "/{product_id}/images",
    response_model=ProductImageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_product_image(
    product_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    file: UploadFile = File(..., description="Image file (JPEG, PNG, or WebP)"),
    alt_text: str = Query("", max_length=255, description="Alt text for accessibility"),
    image_storage: ImageStorage = Depends(get_image_storage),
) -> ProductImageResponse:
    """
    Upload an image for a product.

    Accepts JPEG, PNG, and WebP images up to 10MB.
    Automatically generates a thumbnail version.
    First image uploaded becomes the primary image.
    """
    # Verify product exists and belongs to tenant
    product = await db.get(Product, product_id)
    if not product or product.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Read file content
    content = await file.read()

    # Validate and save image
    try:
        storage_result = await image_storage.save_image(
            file_content=content,
            content_type=file.content_type or "application/octet-stream",
            product_id=str(product_id),
            original_filename=file.filename,
        )
    except ImageStorageError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Get next display order
    max_order_query = select(func.coalesce(func.max(ProductImage.display_order), -1)).where(
        ProductImage.product_id == product_id
    )
    max_order = await db.scalar(max_order_query)
    next_order = (max_order or -1) + 1

    # Check if this is the first image (make it primary)
    count_query = select(func.count()).where(ProductImage.product_id == product_id)
    existing_count = await db.scalar(count_query)
    is_primary = existing_count == 0

    # Create image record
    image = ProductImage(
        tenant_id=tenant.id,
        product_id=product_id,
        image_url=storage_result["image_url"],
        thumbnail_url=storage_result["thumbnail_url"],
        alt_text=alt_text,
        display_order=next_order,
        is_primary=is_primary,
        original_filename=file.filename,
        file_size=storage_result["file_size"],
        content_type=storage_result["content_type"],
    )

    db.add(image)
    await db.commit()
    await db.refresh(image)

    return ProductImageResponse.model_validate(image)


def _is_private_ip(hostname: str) -> bool:
    """Return True if the hostname resolves to a private/loopback IP (SSRF guard)."""
    try:
        addr = ipaddress.ip_address(socket.gethostbyname(hostname))
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except Exception:
        return True


@router.post(
    "/{product_id}/images/import-url",
    response_model=ProductImageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_product_image_from_url(
    product_id: UUID,
    body: ImportImageFromUrlRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    image_storage: ImageStorage = Depends(get_image_storage),
) -> ProductImageResponse:
    """
    Import a product image by fetching it from a remote URL.

    Useful for intake pipelines (e.g. Telegram bot photo URLs).
    Only HTTPS URLs are accepted. Private/loopback IPs are blocked.
    """
    from urllib.parse import urlparse

    parsed = urlparse(body.url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="Only HTTPS URLs are accepted")
    if not parsed.hostname or _is_private_ip(parsed.hostname):
        raise HTTPException(status_code=400, detail="URL resolves to a private or disallowed host")

    product = await db.get(Product, product_id)
    if not product or product.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Product not found")

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(body.url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch image: {exc}") from exc

    content = resp.content
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image exceeds 10 MB limit")

    content_type = (
        resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    )
    filename = parsed.path.rstrip("/").split("/")[-1] or "import.jpg"

    try:
        storage_result = await image_storage.save_image(
            file_content=content,
            content_type=content_type,
            product_id=str(product_id),
            original_filename=filename,
        )
    except ImageStorageError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    max_order = await db.scalar(
        select(func.coalesce(func.max(ProductImage.display_order), -1)).where(
            ProductImage.product_id == product_id
        )
    )
    existing_count = await db.scalar(
        select(func.count()).where(ProductImage.product_id == product_id)
    )
    is_primary = body.is_primary or existing_count == 0

    if is_primary:
        # Clear existing primary flag
        await db.execute(
            select(ProductImage).where(
                ProductImage.product_id == product_id, ProductImage.is_primary.is_(True)
            )
        )

    image = ProductImage(
        tenant_id=tenant.id,
        product_id=product_id,
        image_url=storage_result["image_url"],
        thumbnail_url=storage_result["thumbnail_url"],
        alt_text=body.alt_text,
        display_order=(max_order or -1) + 1,
        is_primary=is_primary,
        original_filename=filename,
        file_size=storage_result["file_size"],
        content_type=storage_result["content_type"],
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)

    return ProductImageResponse.model_validate(image)


@router.patch("/{product_id}/images/{image_id}", response_model=ProductImageResponse)
async def update_product_image(
    product_id: UUID,
    image_id: UUID,
    image_data: ProductImageUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> ProductImageResponse:
    """
    Update image alt text or display order.
    """
    # Fetch image
    query = select(ProductImage).where(
        ProductImage.id == image_id,
        ProductImage.product_id == product_id,
        ProductImage.tenant_id == tenant.id,
    )
    result = await db.execute(query)
    image = result.scalar_one_or_none()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found",
        )

    # Update fields
    update_data = image_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(image, field, value)

    await db.commit()
    await db.refresh(image)

    return ProductImageResponse.model_validate(image)


@router.post("/{product_id}/images/{image_id}/set-primary", response_model=ProductImageResponse)
async def set_primary_image(
    product_id: UUID,
    image_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> ProductImageResponse:
    """
    Set an image as the primary image for the product.
    Unsets any existing primary image.
    """
    # Fetch image
    query = select(ProductImage).where(
        ProductImage.id == image_id,
        ProductImage.product_id == product_id,
        ProductImage.tenant_id == tenant.id,
    )
    result = await db.execute(query)
    image = result.scalar_one_or_none()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found",
        )

    # Unset existing primary images (using Core for efficiency)
    await db.execute(
        ProductImage.__table__.update()
        .where(ProductImage.product_id == product_id)
        .where(ProductImage.is_primary.is_(True))
        .values(is_primary=False)
    )

    # Expire the ORM object to pick up the Core update, then set as primary
    await db.refresh(image)
    image.is_primary = True
    await db.commit()
    await db.refresh(image)

    return ProductImageResponse.model_validate(image)


@router.delete("/{product_id}/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product_image(
    product_id: UUID,
    image_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    image_storage: ImageStorage = Depends(get_image_storage),
):
    """
    Delete a product image.
    If this was the primary image, the next image becomes primary.
    """
    # Fetch image
    query = select(ProductImage).where(
        ProductImage.id == image_id,
        ProductImage.product_id == product_id,
        ProductImage.tenant_id == tenant.id,
    )
    result = await db.execute(query)
    image = result.scalar_one_or_none()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found",
        )

    was_primary = image.is_primary
    image_url = image.image_url
    thumbnail_url = image.thumbnail_url

    # Delete from database
    await db.delete(image)
    await db.commit()

    # Delete from storage
    try:
        await image_storage.delete_image(image_url, thumbnail_url)
    except ImageStorageError:
        pass  # Log but don't fail if file deletion fails

    # If was primary, set next image as primary
    if was_primary:
        next_image_query = (
            select(ProductImage)
            .where(ProductImage.product_id == product_id)
            .order_by(ProductImage.display_order)
            .limit(1)
        )
        next_result = await db.execute(next_image_query)
        next_image = next_result.scalar_one_or_none()
        if next_image:
            next_image.is_primary = True
            await db.commit()


@router.post("/{product_id}/images/{image_id}/rotate", response_model=ProductImageResponse)
async def rotate_product_image(
    product_id: UUID,
    image_id: UUID,
    db: TenantDB,
    degrees: int = Query(default=90, description="Rotation degrees (90, 180, or 270 clockwise)"),
    user: CurrentUser = None,
    tenant: CurrentTenant = None,
    image_storage: ImageStorage = Depends(get_image_storage),
) -> ProductImageResponse:
    """
    Rotate an image clockwise by 90, 180, or 270 degrees.
    """
    # Validate degrees
    if degrees not in (90, 180, 270):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Degrees must be 90, 180, or 270",
        )

    # Fetch image
    query = select(ProductImage).where(
        ProductImage.id == image_id,
        ProductImage.product_id == product_id,
        ProductImage.tenant_id == tenant.id,
    )
    result = await db.execute(query)
    image = result.scalar_one_or_none()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found",
        )

    # Rotate the image files
    try:
        await image_storage.rotate_image(image.image_url, image.thumbnail_url, degrees)
    except ImageStorageError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

    # Update the record to trigger updated_at timestamp change
    from datetime import datetime, timezone

    new_timestamp = datetime.now(timezone.utc)
    image.updated_at = new_timestamp
    db.add(image)  # Ensure it's tracked
    await db.commit()
    await db.refresh(image)

    return ProductImageResponse.model_validate(image)


# ==================== Etsy Sync ====================


@router.post("/{product_id}/sync/etsy", response_model=SyncToEtsyResponse)
async def sync_product_to_etsy(
    product_id: UUID,
    db: TenantDB,
    request: SyncToEtsyRequest = SyncToEtsyRequest(),
    tenant: CurrentTenant = None,
    user: CurrentUser = None,
    _admin: RequireAdmin = None,
):
    """
    Sync a product to Etsy.

    Creates a new Etsy listing if one doesn't exist, or updates the existing listing.
    Batchivo is always the source of truth - sync overwrites Etsy data.

    Note: Full Etsy API integration pending. This endpoint prepares the listing
    data and creates a tracking record.
    """
    # Get product with all relationships needed for sync
    query = (
        select(Product)
        .where(
            Product.id == product_id,
            Product.tenant_id == tenant.id,
        )
        .options(
            selectinload(Product.images),
            selectinload(Product.pricing).selectinload(ProductPricing.sales_channel),
            selectinload(Product.external_listings),
            selectinload(Product.variants),
        )
    )
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if not product.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot sync inactive product",
        )

    # Perform sync
    try:
        sync_service = EtsySyncService(db, tenant.id)
        success, message, listing = await sync_service.sync_product(product, force=request.force)

        await db.commit()

        return SyncToEtsyResponse(
            success=success,
            message=message,
            listing=ExternalListingResponse.model_validate(listing) if listing else None,
            etsy_url=listing.external_url if listing else None,
        )

    except EtsySyncError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ==================== Shopify Sync ====================


@router.post("/{product_id}/sync/shopify", response_model=SyncToShopifyResponse)
async def sync_product_to_shopify(
    product_id: UUID,
    db: TenantDB,
    request: SyncToShopifyRequest = SyncToShopifyRequest(),
    tenant: CurrentTenant = None,
    user: CurrentUser = None,
    _admin: RequireAdmin = None,
):
    """
    Sync a product to Shopify.

    Creates a new Shopify listing if one doesn't exist, or updates the existing one.
    Batchivo is always the source of truth — sync overwrites Shopify data.
    """
    query = (
        select(Product)
        .where(
            Product.id == product_id,
            Product.tenant_id == tenant.id,
        )
        .options(
            selectinload(Product.images),
            selectinload(Product.pricing).selectinload(ProductPricing.sales_channel),
            selectinload(Product.external_listings),
            selectinload(Product.variants),
            selectinload(Product.categories),
        )
    )
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if not product.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot sync inactive product",
        )

    try:
        sync_service = ShopifySyncService(db, tenant.id)
        success, message, listing = await sync_service.sync_product(product, force=request.force)
        await db.commit()

        return SyncToShopifyResponse(
            success=success,
            message=message,
            listing=ExternalListingResponse.model_validate(listing) if listing else None,
            shopify_url=listing.external_url if listing else None,
        )

    except ShopifyNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except ShopifySyncError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ==================== Sync Status ====================


@router.get("/{product_id}/sync-status", response_model=ProductSyncStatusResponse)
async def get_product_sync_status(
    product_id: UUID,
    db: TenantDB,
    tenant: CurrentTenant = None,
    user: CurrentUser = None,
):
    """
    Get multi-channel sync status for a product.

    Returns sync health for: own shop, Shopify, and Etsy.
    """
    from app.models.external_listing import ExternalListing as ExternalListingModel

    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    # Fetch all external listings for this product
    listings_result = await db.execute(
        select(ExternalListingModel).where(
            ExternalListingModel.product_id == product_id,
            ExternalListingModel.tenant_id == tenant.id,
        )
    )
    listings = {lst.platform: lst for lst in listings_result.scalars().all()}

    def channel_status(listing) -> SyncStatusChannel:
        if listing is None:
            return SyncStatusChannel(synced=False)
        return SyncStatusChannel(
            synced=listing.sync_status == "synced",
            last_synced_at=listing.last_synced_at,
            external_url=listing.external_url,
            sync_status=listing.sync_status,
            last_sync_error=listing.last_sync_error,
        )

    return ProductSyncStatusResponse(
        product_id=product_id,
        shop=SyncStatusChannel(
            synced=product.shop_visible,
            external_url=f"https://www.mystmereforge.co.uk/product/{product.id}",
        ),
        shopify=channel_status(listings.get("shopify")),
        etsy=channel_status(listings.get("etsy")),
    )


# ==================== Product Variant Management ====================


async def _get_product_for_tenant(product_id: UUID, tenant_id: UUID, db: AsyncSession) -> Product:
    """Fetch a product scoped to tenant or raise 404."""
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.get(
    "/{product_id}/variants",
    response_model=list[ProductVariantResponse],
)
async def list_product_variants(
    product_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> list[ProductVariantResponse]:
    """List all size variants for a product."""
    await _get_product_for_tenant(product_id, tenant.id, db)

    result = await db.execute(
        select(ProductVariant)
        .where(
            ProductVariant.product_id == product_id,
            ProductVariant.tenant_id == tenant.id,
        )
        .order_by(ProductVariant.display_order)
    )
    variants = result.scalars().all()
    return [ProductVariantResponse.model_validate(v) for v in variants]


@router.post(
    "/{product_id}/variants",
    response_model=ProductVariantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_product_variant(
    product_id: UUID,
    data: ProductVariantCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ProductVariantResponse:
    """Add a size variant to a product."""
    product = await _get_product_for_tenant(product_id, tenant.id, db)

    # Check for duplicate size
    existing = await db.execute(
        select(ProductVariant).where(
            ProductVariant.product_id == product_id,
            ProductVariant.size == data.size,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Variant with size '{data.size}' already exists for this product",
        )

    # Auto-generate SKU if not provided
    sku = data.sku
    if not sku:
        size_slug = data.size.upper().replace(" ", "-").replace("/", "-")
        sku = f"{product.sku}-{size_slug}"

    variant = ProductVariant(
        tenant_id=tenant.id,
        product_id=product_id,
        size=data.size,
        display_order=data.display_order,
        sku=sku,
        price_adjustment_pence=data.price_adjustment_pence,
        units_in_stock=data.units_in_stock,
        fulfilment_type=data.fulfilment_type,
        lead_time_days=data.lead_time_days,
        material_cost_pence=data.material_cost_pence,
        print_time_hours=data.print_time_hours,
        is_active=data.is_active,
    )

    db.add(variant)
    await db.commit()
    await db.refresh(variant)
    return ProductVariantResponse.model_validate(variant)


@router.put(
    "/{product_id}/variants/{variant_id}",
    response_model=ProductVariantResponse,
)
async def update_product_variant(
    product_id: UUID,
    variant_id: UUID,
    data: ProductVariantUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ProductVariantResponse:
    """Update a size variant."""
    await _get_product_for_tenant(product_id, tenant.id, db)

    result = await db.execute(
        select(ProductVariant).where(
            ProductVariant.id == variant_id,
            ProductVariant.product_id == product_id,
            ProductVariant.tenant_id == tenant.id,
        )
    )
    variant = result.scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variant not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(variant, field, value)

    await db.commit()
    await db.refresh(variant)
    return ProductVariantResponse.model_validate(variant)


@router.delete(
    "/{product_id}/variants/{variant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_product_variant(
    product_id: UUID,
    variant_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> None:
    """Delete a size variant."""
    await _get_product_for_tenant(product_id, tenant.id, db)

    result = await db.execute(
        select(ProductVariant).where(
            ProductVariant.id == variant_id,
            ProductVariant.product_id == product_id,
            ProductVariant.tenant_id == tenant.id,
        )
    )
    variant = result.scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variant not found")

    await db.delete(variant)
    await db.commit()
