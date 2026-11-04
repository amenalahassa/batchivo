"""Which products and models use a consumable (spec 006, FR-003, FR-005).

The Packaging page lists, per item, the products that ship in it, and a
consumable still in use is not deleted: the operator is told which products and
models use it instead. One query per kind of reference for a whole page of
consumables, never one per row.
"""

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model import Model
from app.models.model_component import ModelComponent
from app.models.product import Product
from app.models.product_variant import ProductVariant

if TYPE_CHECKING:
    from app.models.tenant import Tenant


@dataclass(frozen=True)
class UsedBy:
    """One product (or model) that uses a consumable."""

    id: uuid.UUID
    sku: str
    name: str
    kind: str  # "product" or "model"

    def as_dict(self) -> dict:
        return {"id": self.id, "sku": self.sku, "name": self.name, "kind": self.kind}


async def products_using(
    db: AsyncSession, tenant: "Tenant", consumable_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[UsedBy]]:
    """Products whose packaging (or a variant's) is each consumable, by consumable id."""
    ids = list(set(consumable_ids))
    found: dict[uuid.UUID, dict[uuid.UUID, UsedBy]] = {i: {} for i in ids}
    if not ids:
        return {}
    direct = await db.execute(
        select(Product.packaging_consumable_id, Product.id, Product.sku, Product.name).where(
            Product.tenant_id == tenant.id, Product.packaging_consumable_id.in_(ids)
        )
    )
    for consumable_id, pid, sku, name in direct.all():
        found[consumable_id][pid] = UsedBy(pid, sku, name, "product")
    variants = await db.execute(
        select(ProductVariant.packaging_consumable_id, Product.id, Product.sku, Product.name)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(Product.tenant_id == tenant.id, ProductVariant.packaging_consumable_id.in_(ids))
    )
    for consumable_id, pid, sku, name in variants.all():
        found[consumable_id][pid] = UsedBy(pid, sku, name, "product")
    return {cid: sorted(products.values(), key=lambda u: u.sku) for cid, products in found.items()}


async def everything_using(
    db: AsyncSession, tenant: "Tenant", consumable_id: uuid.UUID
) -> list[UsedBy]:
    """Products and models that use one consumable: what blocks its deletion."""
    users = list((await products_using(db, tenant, [consumable_id])).get(consumable_id, []))
    models = await db.execute(
        select(Model.id, Model.sku, Model.name)
        .join(ModelComponent, ModelComponent.model_id == Model.id)
        .where(Model.tenant_id == tenant.id, ModelComponent.consumable_type_id == consumable_id)
        .distinct()
    )
    users.extend(UsedBy(mid, sku, name, "model") for mid, sku, name in models.all())
    return users


__all__ = ["UsedBy", "everything_using", "products_using"]
