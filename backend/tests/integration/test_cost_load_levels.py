"""Bundle levels load on demand, and cost exactly as a full eager load did.

Regression for `.specify/bugs/cost-load-options-depth-slow`: `cost_load_options()`
declared every bundle level to the engine's depth (21 levels, 105 options), and
SQLAlchemy keyed and compiled that tree on every sub-load -- about a second of CPU
for one flat product, 18 s for a one-product scenario. It now declares one level,
and `load_bundle_levels()` walks down only as far as the catalogue goes.

These tests pin the three things that change must not cost: the figures (identical
to a full eager load), the single depth limit (a chain deeper than
`MAX_RECURSION_DEPTH` still raises the engine's own error), and the speed (a flat
product walks no level, and the option list no longer grows with the limit).
"""

from decimal import Decimal
from typing import Any, Optional

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.consumable import ConsumableType
from app.models.filament_purchase import FilamentPurchase
from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.product import Product
from app.models.product_component import ProductComponent
from app.models.product_model import ProductModel
from app.models.spool import Spool
from app.models.tenant import Tenant
from app.services.cost_resolution import (
    cost_load_options,
    load_bundle_levels,
    product_cost_breakdown,
)
from app.services.costing import MAX_RECURSION_DEPTH, CostingService, MaxDepthExceededError
from tests.integration.test_product_graph_load_strategy import _make_bundle, _make_leaf

LABOR_RATE = Decimal("25.00")


def _full_eager_options(depth: int) -> list:
    """The option tree the old `cost_load_options()` declared, to `depth` levels.

    Kept here as the reference the walker is checked against: whatever it
    loaded, the walker must load, or a figure would change.
    """

    def chain(prefix: Optional[Any], *path: Any) -> Any:
        loader = prefix
        for relationship in path:
            loader = (
                selectinload(relationship) if loader is None else loader.selectinload(relationship)
            )
        return loader

    def inputs(prefix: Optional[Any]) -> list:
        return [
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
            chain(prefix, Product.packaging_consumable, ConsumableType.purchases),
        ]

    options: list = []
    prefix = None
    for _ in range(depth + 1):
        options.extend(inputs(prefix))
        prefix = chain(prefix, Product.child_products, ProductComponent.child_product)
        options.append(prefix)
    return options


async def _three_levels(db: AsyncSession, tenant: Tenant, spool_id) -> Product:
    leaf_a = await _make_leaf(db, tenant, spool_id, Decimal("100"), Decimal("0.0300"), "LV-A")
    leaf_b = await _make_leaf(db, tenant, spool_id, Decimal("50"), Decimal("0.0200"), "LV-B")
    middle = await _make_bundle(db, tenant, [(leaf_a, 2), (leaf_b, 1)], "LV-MID")
    top = await _make_bundle(db, tenant, [(middle, 3)], "LV-TOP")
    await db.commit()
    return top


async def _load(db: AsyncSession, product_id, options: list) -> Product:
    db.expunge_all()
    return (
        await db.execute(select(Product).where(Product.id == product_id).options(*options))
    ).scalar_one()


class _QueryCounter:
    """Counts the statements a block sends to the database."""

    def __init__(self, db: AsyncSession) -> None:
        self.engine = db.bind.sync_engine  # type: ignore[union-attr]
        self.count = 0

    def _on_execute(self, *args: Any, **kwargs: Any) -> None:
        self.count += 1

    def __enter__(self) -> "_QueryCounter":
        event.listen(self.engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *exc: Any) -> None:
        event.remove(self.engine, "before_cursor_execute", self._on_execute)


class TestNoFigureChanges:
    async def test_a_three_level_bundle_costs_as_the_full_eager_load_did(
        self, db_session: AsyncSession, test_tenant: Tenant, test_spool
    ) -> None:
        top = await _three_levels(db_session, test_tenant, test_spool.id)
        top_id = top.id

        reference = await _load(db_session, top_id, _full_eager_options(3))
        expected = CostingService.calculate_product_cost(reference, labor_rate=LABOR_RATE)

        walked = await _load(db_session, top_id, cost_load_options())
        await load_bundle_levels(db_session, [walked])
        actual = CostingService.calculate_product_cost(walked, labor_rate=LABOR_RATE)

        assert actual.model_dump() == expected.model_dump()
        # leaf A 100 g x 0.03 = 3.00, leaf B 50 g x 0.02 = 1.00;
        # middle 2 x 3.00 + 1.00 = 7.00; top 3 x 7.00 = 21.00.
        assert actual.total_make_cost == Decimal("21.00")

    async def test_the_itemised_breakdown_walks_the_levels_itself(
        self, db_session: AsyncSession, test_tenant: Tenant, test_spool
    ) -> None:
        """`product_cost_breakdown` loads what is below; its caller need not."""
        top = await _three_levels(db_session, test_tenant, test_spool.id)
        loaded = await _load(db_session, top.id, cost_load_options())

        breakdown = await product_cost_breakdown(db_session, test_tenant, loaded)

        assert breakdown.total_make_cost == Decimal("21.00")


class TestOneDepthLimit:
    async def test_a_chain_deeper_than_the_engine_allows_raises_its_error(
        self, db_session: AsyncSession, test_tenant: Tenant, test_spool
    ) -> None:
        """The walker stops where the engine's guard does: the guard still fires.

        Had the walker stopped short, the engine would meet an unloaded
        collection and fail with SQLAlchemy's `MissingGreenlet` instead.
        """
        product = await _make_leaf(
            db_session, test_tenant, test_spool.id, Decimal("10"), Decimal("0.0100"), "DEEP-0"
        )
        for level in range(1, MAX_RECURSION_DEPTH + 3):
            product = await _make_bundle(db_session, test_tenant, [(product, 1)], f"DEEP-{level}")
        await db_session.commit()

        loaded = await _load(db_session, product.id, cost_load_options())
        await load_bundle_levels(db_session, [loaded])

        with pytest.raises(MaxDepthExceededError):
            CostingService.calculate_product_cost(loaded, labor_rate=LABOR_RATE)


class TestItCostsWhatTheCatalogueHas:
    def test_the_options_no_longer_grow_with_the_depth_limit(self) -> None:
        """One level: four input chains and the link to the next level."""
        assert len(cost_load_options()) == 5

    async def test_a_flat_product_walks_no_level(
        self, db_session: AsyncSession, test_tenant: Tenant, test_spool
    ) -> None:
        leaf = await _make_leaf(
            db_session, test_tenant, test_spool.id, Decimal("80"), Decimal("0.0250"), "FLAT"
        )
        await db_session.commit()
        loaded = await _load(db_session, leaf.id, cost_load_options())

        with _QueryCounter(db_session) as counter:
            await load_bundle_levels(db_session, [loaded])

        assert counter.count == 0

    async def test_a_three_level_bundle_walks_one_query_per_level(
        self, db_session: AsyncSession, test_tenant: Tenant, test_spool
    ) -> None:
        top = await _three_levels(db_session, test_tenant, test_spool.id)
        loaded = await _load(db_session, top.id, cost_load_options())

        with _QueryCounter(db_session) as counter:
            await load_bundle_levels(db_session, [loaded])

        # The middle level and the leaves, each with its own selectin loads; never
        # anything for the empty level below the leaves.
        assert counter.count > 0
        with _QueryCounter(db_session) as again:
            await load_bundle_levels(db_session, [])
        assert again.count == 0
