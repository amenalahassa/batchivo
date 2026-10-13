"""Resolve everything the cost engine needs, then call it once (task T049).

The engine in :mod:`app.services.costing` is synchronous and issues no queries:
it takes a frozen policy and a map of recorded origins and returns a
breakdown. That is what lets it recurse through a bill of materials without a
query per node — but somebody has to do the loading, and if every endpoint does
it its own way the figures drift apart again, which is the defect User Story 1
removed.

So this module is the one place that resolves policy and provenance for a cost
read. Endpoints call it; nothing here computes a cost of its own.
"""

import logging
import uuid
from typing import TYPE_CHECKING, Iterable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.model import CostBreakdown
from app.services.costing import CostingService
from app.services.pricing_policy import CostPolicy, resolve_cost_policy
from app.services.provenance import FieldOrigin, origins_for

if TYPE_CHECKING:
    from app.models.model import Model
    from app.models.printer import Printer
    from app.models.product import Product
    from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

OriginMap = dict[tuple[str, uuid.UUID, str], FieldOrigin]


def cost_load_options() -> list:
    """Eager-load options for every relationship a cost read walks.

    The engine issues no queries, which is what lets it recurse through a bill
    of materials cheaply -- but it also means a relationship nobody loaded
    raises in an async context, or worse, reads as absent and reports a cheaper
    product. So the cost-bearing tree is declared **once**, here, and every
    caller that costs a product uses it: the product endpoints, and the
    catalogue sweep behind a scenario.

    Three levels of bundle are loaded. The engine's own depth guard refuses
    deeper nesting with a 409 naming the chain, so a fourth level would be
    loading data only to refuse it.
    """
    from sqlalchemy.orm import selectinload

    from app.models.model import Model
    from app.models.product import Product
    from app.models.product_component import ProductComponent
    from app.models.product_model import ProductModel

    return [
        selectinload(Product.product_models)
        .selectinload(ProductModel.model)
        .selectinload(Model.materials),
        selectinload(Product.product_models)
        .selectinload(ProductModel.model)
        .selectinload(Model.components),
        selectinload(Product.product_models)
        .selectinload(ProductModel.model)
        .selectinload(Model.printer_configs),
        selectinload(Product.packaging_consumable),
        # Level 1: child products, with their own cost-bearing relationships.
        selectinload(Product.child_products)
        .selectinload(ProductComponent.child_product)
        .selectinload(Product.product_models)
        .selectinload(ProductModel.model)
        .selectinload(Model.materials),
        selectinload(Product.child_products)
        .selectinload(ProductComponent.child_product)
        .selectinload(Product.product_models)
        .selectinload(ProductModel.model)
        .selectinload(Model.components),
        selectinload(Product.child_products)
        .selectinload(ProductComponent.child_product)
        .selectinload(Product.product_models)
        .selectinload(ProductModel.model)
        .selectinload(Model.printer_configs),
        selectinload(Product.child_products)
        .selectinload(ProductComponent.child_product)
        .selectinload(Product.packaging_consumable),
        # Level 2: grandchildren.
        selectinload(Product.child_products)
        .selectinload(ProductComponent.child_product)
        .selectinload(Product.child_products)
        .selectinload(ProductComponent.child_product)
        .selectinload(Product.product_models)
        .selectinload(ProductModel.model)
        .selectinload(Model.materials),
        selectinload(Product.child_products)
        .selectinload(ProductComponent.child_product)
        .selectinload(Product.child_products)
        .selectinload(ProductComponent.child_product)
        .selectinload(Product.packaging_consumable),
    ]


def _model_entities(model: "Model") -> set[tuple[str, uuid.UUID]]:
    """Every entity whose recorded origins bear on this item's cost.

    Relationships are read only when they are already loaded: this runs on a
    request thread where a lazy load raises, and an item whose materials were
    not eager-loaded should report a thinner provenance rather than a 500.
    """
    entities: set[tuple[str, uuid.UUID]] = {("model", model.id)}

    for material in getattr(model, "materials", None) or []:
        entities.add(("model_material", material.id))
        spool_id = getattr(material, "spool_id", None)
        if spool_id is not None:
            entities.add(("spool", spool_id))

    for component in getattr(model, "components", None) or []:
        entities.add(("model_component", component.id))

    for config in getattr(model, "printer_configs", None) or []:
        entities.add(("model_printer_config", config.id))
        printer_id = getattr(config, "printer_id", None)
        if printer_id is not None:
            entities.add(("printer", printer_id))

    return entities


def _product_entities(
    product: "Product",
    *,
    _seen: Optional[set[uuid.UUID]] = None,
) -> set[tuple[str, uuid.UUID]]:
    """The same, for a sellable unit and everything below it in the bundle.

    Cycle-guarded independently of the engine: this walk happens before the
    engine runs, so a circular bundle must not hang here on its way to the
    409 the engine would have raised.
    """
    seen = _seen if _seen is not None else set()
    if product.id in seen:
        return set()
    seen.add(product.id)

    entities: set[tuple[str, uuid.UUID]] = {("product", product.id)}

    for product_model in getattr(product, "product_models", None) or []:
        model = getattr(product_model, "model", None)
        if model is not None:
            entities |= _model_entities(model)

    for component in getattr(product, "child_products", None) or []:
        child = getattr(component, "child_product", None)
        if child is not None:
            entities |= _product_entities(child, _seen=seen)

    return entities


async def resolve_origins(
    db: AsyncSession,
    tenant: "Tenant",
    entities: Iterable[tuple[str, uuid.UUID]],
) -> OriginMap:
    """Recorded origins for these entities, in one query."""
    return await origins_for(db, tenant, entities)


async def model_cost_breakdown(
    db: AsyncSession,
    tenant: "Tenant",
    model: "Model",
    *,
    printer: Optional["Printer"] = None,
    policy: Optional[CostPolicy] = None,
) -> CostBreakdown:
    """The structured breakdown for one printed item."""
    resolved = policy or await resolve_cost_policy(db, tenant)
    origins = await resolve_origins(db, tenant, _model_entities(model))
    return CostingService.item_breakdown(model, policy=resolved, printer=printer, origins=origins)


async def product_cost_breakdown(
    db: AsyncSession,
    tenant: "Tenant",
    product: "Product",
    *,
    policy: Optional[CostPolicy] = None,
) -> CostBreakdown:
    """The structured breakdown for one sellable unit, bundles included.

    Lets :class:`CircularReferenceError` and :class:`MaxDepthExceededError`
    out unchanged: a cycle in the operator's own data is theirs to fix, and the
    endpoint turns each into a 409 naming the offending chain.
    """
    resolved = policy or await resolve_cost_policy(db, tenant)
    origins = await resolve_origins(db, tenant, _product_entities(product))
    return CostingService.product_breakdown(product, policy=resolved, origins=origins)
