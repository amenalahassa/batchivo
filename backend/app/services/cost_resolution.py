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
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.model import CostBreakdown
from app.services.costing import MAX_RECURSION_DEPTH, CostingService
from app.services.pricing_policy import CostPolicy, resolve_cost_policy
from app.services.provenance import FieldOrigin, origins_for

if TYPE_CHECKING:
    from app.models.model import Model
    from app.models.printer import Printer
    from app.models.product import Product
    from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

OriginMap = dict[tuple[str, uuid.UUID, str], FieldOrigin]

#: How many bundle levels `cost_load_options()` eager-loads.
#:
#: Kept equal to the engine's own `MAX_RECURSION_DEPTH` on purpose, so the
#: system has **one** limit on bundle nesting rather than two that can drift.
#: A bundle deeper than the loader reaches would otherwise meet an unloaded
#: collection inside the synchronous engine and fail with SQLAlchemy's
#: `MissingGreenlet` instead of the `MaxDepthExceededError` the guard exists to
#: raise -- so the guard would be unreachable and the real limit would be this
#: number, undocumented.
BUNDLE_LOAD_DEPTH = MAX_RECURSION_DEPTH


def cost_load_options() -> list:
    """Eager-load options for every relationship a cost read walks.

    The engine issues no queries, which is what lets it recurse through a bill
    of materials cheaply -- but it also means a relationship nobody loaded
    raises in an async context, or worse, reads as absent and reports a cheaper
    product. So the cost-bearing tree is declared **once**, here, and every
    caller that costs a product uses it: the product endpoints, and the
    catalogue sweep behind a scenario.

    The bundle chain is generated rather than written out, to the same depth the
    engine's own guard allows (`MAX_RECURSION_DEPTH`). Writing it out by hand is
    how the two fell out of step: the list stopped declaring `child_products`
    two levels down while the engine kept walking, so a three-level bundle
    reached an unloaded collection. `ProductComponent.child_product` is lazy
    precisely so that this declaration is the only thing that loads a bundle --
    an eager link on the model re-entered `Product` and its dozen `selectin`
    relationships at every level.

    Declaring the full depth is close to free: a `selectin` level issues no
    SELECT when the level above it returned no rows, so a flat catalogue pays
    for the levels it actually has, not for the limit.
    """
    from sqlalchemy.orm import selectinload

    from app.models.consumable import ConsumableType
    from app.models.filament_purchase import FilamentPurchase
    from app.models.model import Model
    from app.models.model_material import ModelMaterial
    from app.models.product import Product
    from app.models.product_component import ProductComponent
    from app.models.product_model import ProductModel
    from app.models.spool import Spool

    def chain(prefix: Optional[Any], *path: Any) -> Any:
        """Extend `prefix` (or start fresh when it is None) along `path`."""
        loader = prefix
        for relationship in path:
            loader = (
                selectinload(relationship) if loader is None else loader.selectinload(relationship)
            )
        return loader

    def cost_inputs(prefix: Optional[Any]) -> list:
        """What one product level costs from, whatever path reached it."""
        return [
            # The spool's purchase and that purchase's other spools, which its
            # landed per-gram cost is allocated across (T254).
            chain(
                prefix,
                Product.product_models,
                ProductModel.model,
                Model.materials,
                ModelMaterial.spool,
                Spool.filament_purchase,
                FilamentPurchase.spools,
            ),
            chain(prefix, Product.product_models, ProductModel.model, Model.components),
            chain(prefix, Product.product_models, ProductModel.model, Model.printer_configs),
            # The purchases price the unit (T273).
            chain(prefix, Product.packaging_consumable, ConsumableType.purchases),
        ]

    options: list = []
    prefix = None
    # One pass per bundle level the engine may descend into. Each level loads
    # its own cost inputs and the component rows that reach the next, so the
    # traversal never meets a collection it cannot read.
    for _ in range(BUNDLE_LOAD_DEPTH + 1):
        options.extend(cost_inputs(prefix))
        prefix = chain(prefix, Product.child_products, ProductComponent.child_product)
        options.append(prefix)

    return options


def with_landed_cost(materials_loader: Any) -> Any:
    """Extend a loader that reaches `Model.materials` to what landed cost reads.

    A bill-of-materials line costs at its spool's landed per-gram figure,
    allocated across every spool on the spool's purchase (T254). Eager loading
    does not follow that cycle back from the purchase on its own, so a caller
    that costs a model names it with this, and the engine never meets an
    unloaded purchase.
    """
    from app.models.filament_purchase import FilamentPurchase
    from app.models.model_material import ModelMaterial
    from app.models.spool import Spool

    return (
        materials_loader.selectinload(ModelMaterial.spool)
        .selectinload(Spool.filament_purchase)
        .selectinload(FilamentPurchase.spools)
    )


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
        # A derived per-gram figure stands on the purchase's shipping and tax
        # too (T254), so their origins are gathered with the spool's.
        spool = getattr(material, "__dict__", {}).get("spool")
        purchase_id = getattr(spool, "filament_purchase_id", None)
        if purchase_id is not None:
            entities.add(("filament_purchase", purchase_id))

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
    consumable = getattr(product, "packaging_consumable", None)
    if consumable is not None:
        entities.add(("consumable_type", consumable.id))

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


async def resolve_pending_revisions(
    db: AsyncSession,
    tenant: "Tenant",
    entities: Iterable[tuple[str, uuid.UUID]],
) -> frozenset[tuple[str, uuid.UUID, str]]:
    """Which of these entities' fields have a proposal awaiting review.

    Resolved here, beside the origins, for the same reason: the engine does
    not query. Both are gathered once over the whole bundle and handed in, so
    a breakdown costs two queries however many lines it has.
    """
    from app.services import variance_service

    return await variance_service.pending_revisions_for(db, tenant, entities)


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
    entities = _model_entities(model)
    origins = await resolve_origins(db, tenant, entities)
    pending = await resolve_pending_revisions(db, tenant, entities)
    return CostingService.item_breakdown(
        model, policy=resolved, printer=printer, origins=origins, pending=pending
    )


async def product_cost_breakdown(
    db: AsyncSession,
    tenant: "Tenant",
    product: "Product",
    *,
    policy: Optional[CostPolicy] = None,
    printer_for_model: Optional[Mapping[uuid.UUID, "Printer"]] = None,
) -> CostBreakdown:
    """The structured breakdown for one sellable unit, bundles included.

    ``printer_for_model`` overrides an item's planned machine, as a queue job's
    assigned printer does (FR-011).

    Lets :class:`CircularReferenceError` and :class:`MaxDepthExceededError`
    out unchanged: a cycle in the operator's own data is theirs to fix, and the
    endpoint turns each into a 409 naming the offending chain.
    """
    resolved = policy or await resolve_cost_policy(db, tenant)
    entities = _product_entities(product)
    origins = await resolve_origins(db, tenant, entities)
    pending = await resolve_pending_revisions(db, tenant, entities)
    return CostingService.product_breakdown(
        product,
        policy=resolved,
        printer_for_model=printer_for_model,
        origins=origins,
        pending=pending,
    )
