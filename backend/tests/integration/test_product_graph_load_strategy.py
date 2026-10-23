"""The product graph must not eager-load itself in a cycle.

`ProductComponent.child_product` used to be `lazy="joined"`, commented "eager
load for cost calculation". Both `Product.child_products` and
`Product.parent_products` are `selectin` to `ProductComponent`, so that joined
load re-entered a `Product` row carrying a dozen further `selectin`
relationships -- `pricing` and `current_pricing` among them -- and did it again
at every level of a bundle. Two stack dumps died inside that shape during
SQLAlchemy's eager-join compilation.

The engine never needed it. `CostingService` walks bundles itself with its own
`_visited` cycle detection and `MAX_RECURSION_DEPTH` (FR-017/FR-049), and the
levels it costs are loaded explicitly by `cost_load_options()`. These tests pin
both halves of that claim: the link is lazy, and a bundle costed through the
declared options still costs correctly -- while a circular one is still an
error rather than a hang or a wrong number.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.product import Product
from app.models.product_component import ProductComponent
from app.models.product_model import ProductModel
from app.models.tenant import Tenant
from app.services.cost_resolution import cost_load_options
from app.services.costing import CircularReferenceError, CostingService

LABOR_RATE = Decimal("25.00")


# ---------------------------------------------------------------------------
# The load strategy itself
# ---------------------------------------------------------------------------


class TestTheChildLinkIsLazy:
    def test_child_product_is_not_eager_loaded(self) -> None:
        """A joined or selectin load here re-enters Product and recurses."""
        strategy = inspect(ProductComponent).relationships["child_product"].lazy
        assert strategy not in ("joined", "selectin", "subquery"), (
            "ProductComponent.child_product must stay lazy: Product.child_products and "
            "Product.parent_products are both selectin to ProductComponent, so eager-loading "
            "back to Product makes the graph re-enter itself at every bundle level"
        )

    def test_the_engine_declares_the_levels_it_needs(self) -> None:
        """The traversal's eager loads are declared in one place, not on the model."""
        assert cost_load_options(), (
            "cost_load_options() is what replaces the eager link; if it is empty the "
            "traversal has nothing loaded to walk"
        )


# ---------------------------------------------------------------------------
# Helpers -- a real ORM graph, loaded only through the declared options
# ---------------------------------------------------------------------------


async def _make_leaf(
    db: AsyncSession,
    tenant: Tenant,
    spool_id,
    grams: Decimal,
    cost_per_gram: Decimal,
    tag: str,
) -> Product:
    """A product holding one model, which holds one BOM line."""
    model = Model(
        id=uuid4(),
        tenant_id=tenant.id,
        sku=f"LAZY-M-{tag}",
        name=f"Lazy model {tag}",
        is_active=True,
    )
    db.add(model)
    await db.flush()

    db.add(
        ModelMaterial(
            id=uuid4(),
            model_id=model.id,
            spool_id=spool_id,
            weight_grams=grams,
            cost_per_gram=cost_per_gram,
        )
    )

    product = Product(
        id=uuid4(),
        tenant_id=tenant.id,
        sku=f"LAZY-P-{tag}",
        name=f"Lazy product {tag}",
        is_active=True,
    )
    db.add(product)
    await db.flush()

    db.add(ProductModel(id=uuid4(), product_id=product.id, model_id=model.id, quantity=1))
    await db.flush()
    return product


async def _make_bundle(
    db: AsyncSession,
    tenant: Tenant,
    children: list[tuple[Product, int]],
    tag: str,
) -> Product:
    bundle = Product(
        id=uuid4(),
        tenant_id=tenant.id,
        sku=f"LAZY-B-{tag}",
        name=f"Lazy bundle {tag}",
        is_active=True,
    )
    db.add(bundle)
    await db.flush()
    for child, quantity in children:
        db.add(
            ProductComponent(
                id=uuid4(),
                parent_product_id=bundle.id,
                child_product_id=child.id,
                quantity=quantity,
            )
        )
    await db.flush()
    return bundle


async def _load(db: AsyncSession, product_id) -> Product:
    """Load a product exactly as a costing caller does, and from cold.

    `expunge_all` matters: reading through objects the session already holds
    would exercise the identity map rather than the declared load options, so a
    missing option would pass here and raise in a request.
    """
    db.expunge_all()
    return (
        await db.execute(
            select(Product).where(Product.id == product_id).options(*cost_load_options())
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# A nested bundle still costs correctly
# ---------------------------------------------------------------------------


class TestNestedBundleStillCosts:
    async def test_a_three_level_bundle_costs_from_its_leaves(
        self, db_session: AsyncSession, test_tenant: Tenant, test_spool
    ) -> None:
        """The figure is derived from the inputs here, not copied from a previous run."""
        leaf_a = await _make_leaf(
            db_session, test_tenant, test_spool.id, Decimal("100"), Decimal("0.0300"), "A"
        )
        leaf_b = await _make_leaf(
            db_session, test_tenant, test_spool.id, Decimal("50"), Decimal("0.0200"), "B"
        )
        middle = await _make_bundle(db_session, test_tenant, [(leaf_a, 2), (leaf_b, 1)], "MID")
        top = await _make_bundle(db_session, test_tenant, [(middle, 3)], "TOP")
        await db_session.commit()

        leaf_a_id, leaf_b_id, middle_id, top_id = leaf_a.id, leaf_b.id, middle.id, top.id

        cost_a = CostingService.calculate_product_cost(
            await _load(db_session, leaf_a_id), labor_rate=LABOR_RATE
        ).total_make_cost
        cost_b = CostingService.calculate_product_cost(
            await _load(db_session, leaf_b_id), labor_rate=LABOR_RATE
        ).total_make_cost
        cost_middle = CostingService.calculate_product_cost(
            await _load(db_session, middle_id), labor_rate=LABOR_RATE
        ).total_make_cost
        cost_top = CostingService.calculate_product_cost(
            await _load(db_session, top_id), labor_rate=LABOR_RATE
        ).total_make_cost

        # Each leaf carries a material line, so neither may cost nothing --
        # a lazy relationship read as absent would show up exactly here.
        assert cost_a > Decimal("0")
        assert cost_b > Decimal("0")

        assert cost_middle == (cost_a * 2 + cost_b).quantize(Decimal("0.01"))
        assert cost_top == (cost_middle * 3).quantize(Decimal("0.01"))

    async def test_the_bundle_lines_are_reachable_after_a_cold_load(
        self, db_session: AsyncSession, test_tenant: Tenant, test_spool
    ) -> None:
        """The traversal reads `pc.child_product` synchronously; it must be loaded."""
        leaf = await _make_leaf(
            db_session, test_tenant, test_spool.id, Decimal("120"), Decimal("0.0250"), "C"
        )
        bundle = await _make_bundle(db_session, test_tenant, [(leaf, 4)], "REACH")
        await db_session.commit()
        bundle_id = bundle.id

        loaded = await _load(db_session, bundle_id)
        components = list(loaded.child_products)
        assert len(components) == 1
        # No await here on purpose: if this needed a lazy load it would raise
        # MissingGreenlet, which is what the engine would hit in a request.
        assert components[0].child_product.sku == "LAZY-P-C"
        assert components[0].quantity == 4


# ---------------------------------------------------------------------------
# A circular bundle is still an error
# ---------------------------------------------------------------------------


class TestCircularBundleIsStillReported:
    async def test_a_two_product_cycle_raises_rather_than_recursing(
        self, db_session: AsyncSession, test_tenant: Tenant, test_spool
    ) -> None:
        """A contains B and B contains A: the engine's own `_visited` must catch it.

        The database's `check_no_self_reference` constraint stops a product
        containing itself directly, so a cycle has to be built with two rows --
        which is the case the eager link could never have survived at all.
        """
        product_a = await _make_leaf(
            db_session, test_tenant, test_spool.id, Decimal("90"), Decimal("0.0210"), "CYC-A"
        )
        product_b = await _make_leaf(
            db_session, test_tenant, test_spool.id, Decimal("70"), Decimal("0.0190"), "CYC-B"
        )
        db_session.add(
            ProductComponent(
                id=uuid4(),
                parent_product_id=product_a.id,
                child_product_id=product_b.id,
                quantity=1,
            )
        )
        db_session.add(
            ProductComponent(
                id=uuid4(),
                parent_product_id=product_b.id,
                child_product_id=product_a.id,
                quantity=1,
            )
        )
        await db_session.commit()
        product_a_id = product_a.id

        loaded = await _load(db_session, product_a_id)
        with pytest.raises(CircularReferenceError):
            CostingService.calculate_product_cost(loaded, labor_rate=LABOR_RATE)
