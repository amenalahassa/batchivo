"""Creating a product: the one implementation the products route and idea conversion share.

Moved out of ``api/v1/products.py`` without behaviour change (spec 007, research
R3). A product's bill-of-materials lines (``ProductModel``) and bundle lines
(``ProductComponent``) are written here and nowhere else, so converting an idea
into a product cannot diverge from the products screen (principle III). This
module flushes; the caller commits.
"""

import logging
import re
import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.provenance_http import record_operator_origins, refuse_observed_or_409
from app.auth.dependencies import role_in_tenant
from app.models.designer import Designer
from app.models.model import Model
from app.models.product import Product
from app.models.product_component import ProductComponent
from app.models.product_model import ProductModel
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.product import ProductCreate

logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug.strip("-")


async def create_product(
    db: AsyncSession,
    tenant: Tenant,
    user: User,
    product_data: ProductCreate,
    *,
    source_idea_id: Optional[uuid.UUID] = None,
) -> Product:
    """
    Create a product with its models (BOM lines) and child products (bundles).

    SKU must be unique per tenant (400). Unknown designer, model or child
    product → 404; a product containing itself → 400. Flushes; the caller
    commits. ``source_idea_id`` is set only by idea conversion.
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

    product = Product(
        tenant_id=tenant.id,
        source_idea_id=source_idea_id,
        **product_dict,
    )

    # Auto-generate seo_slug from name if not explicitly provided
    if not product.seo_slug:
        product.seo_slug = slugify(product.name)

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

    for model_data in models_data:
        # Verify model exists and belongs to tenant
        model = await db.get(Model, model_data.model_id)
        if not model or model.tenant_id != tenant.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Model {model_data.model_id} not found",
            )
        db.add(
            ProductModel(
                product_id=product.id,
                model_id=model_data.model_id,
                quantity=model_data.quantity,
            )
        )

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
        db.add(
            ProductComponent(
                parent_product_id=product.id,
                child_product_id=child_data.child_product_id,
                quantity=child_data.quantity,
            )
        )

    await db.flush()
    return product
