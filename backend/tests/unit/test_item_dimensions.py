"""Effective dimensions and packaging, and who may write dimensions (research D2, D11)."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.model import Model
from app.models.model_file import ModelFile
from app.models.product import Product
from app.models.product_model import ProductModel
from app.models.product_variant import ProductVariant
from app.schemas.dimensions import DimensionsIn
from app.services.dims import Dims
from app.services.item_dimensions import (
    MeasurementNotFound,
    MeasurementUnavailable,
    apply_measurement,
    effective_dimensions,
    effective_packaging,
    set_dimensions,
    single_model_of,
    variant_for_order_line,
)
from tests.utils.packaging import set_dims
from tests.utils.model_files import active_version_id


def _product(**kw):
    base = dict(
        length_mm=None,
        width_mm=None,
        height_mm=None,
        dimensions_source=None,
        dimensions_source_file_id=None,
        dimensions_set_at=None,
        packaging_consumable=None,
        packaging_quantity=1,
        variants=[],
        product_models=[],
        child_products=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _variant(**kw):
    base = dict(
        length_mm=None,
        width_mm=None,
        height_mm=None,
        dimensions_source=None,
        dimensions_source_file_id=None,
        dimensions_set_at=None,
        packaging_consumable_id=None,
        packaging_consumable=None,
        packaging_quantity=None,
        sku="P-L",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestEffectiveDimensions:
    def test_product_own(self) -> None:
        product = set_dims(_product(), 120, 80, 45)
        dims, out = effective_dimensions(product)
        assert dims == Dims(Decimal(120), Decimal(80), Decimal(45))
        assert out is not None and out.source == "entered" and not out.inherited

    def test_variant_without_dims_inherits(self) -> None:
        product = set_dims(_product(), 120, 80, 45)
        dims, out = effective_dimensions(product, _variant())
        assert dims == Dims(Decimal(120), Decimal(80), Decimal(45))
        assert out is not None and out.inherited

    def test_variant_with_dims_overrides(self) -> None:
        product = set_dims(_product(), 120, 80, 45)
        variant = set_dims(_variant(), 180, 120, 60)
        dims, out = effective_dimensions(product, variant)
        assert dims == Dims(Decimal(180), Decimal(120), Decimal(60))
        assert out is not None and not out.inherited

    def test_nothing_recorded(self) -> None:
        assert effective_dimensions(_product()) == (None, None)


class TestEffectivePackaging:
    def test_product_packaging(self) -> None:
        box = SimpleNamespace(id=uuid4())
        assert effective_packaging(_product(packaging_consumable=box, packaging_quantity=2)) == (
            box,
            2,
        )

    def test_variant_overrides_each_field(self) -> None:
        box, big = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        product = _product(packaging_consumable=box, packaging_quantity=2)
        variant = _variant(packaging_consumable_id=big.id, packaging_consumable=big)
        assert effective_packaging(product, variant) == (big, 2)
        assert effective_packaging(product, _variant(packaging_quantity=3)) == (box, 3)


class TestVariantForOrderLine:
    def test_matches_by_sku(self) -> None:
        large = _variant(sku="DRG-L")
        product = _product(variants=[_variant(sku="DRG-S"), large])
        assert variant_for_order_line(product, "DRG-L") is large

    def test_product_sku_is_the_product(self) -> None:
        assert variant_for_order_line(_product(variants=[_variant()]), "DRG") is None
        assert variant_for_order_line(_product(), None) is None


class TestSingleModel:
    def test_one_model_at_quantity_one(self) -> None:
        model = SimpleNamespace(id=uuid4())
        link = SimpleNamespace(quantity=1, model=model)
        assert single_model_of(_product(product_models=[link])) is model

    def test_quantity_two_or_two_models_is_none(self) -> None:
        m = SimpleNamespace(id=uuid4())
        assert (
            single_model_of(_product(product_models=[SimpleNamespace(quantity=2, model=m)])) is None
        )
        two = [SimpleNamespace(quantity=1, model=m), SimpleNamespace(quantity=1, model=m)]
        assert single_model_of(_product(product_models=two)) is None


# ============================================
# Writers (database)
# ============================================


async def _model(db, tenant, sku="M-1") -> Model:
    model = Model(id=uuid4(), tenant_id=tenant.id, sku=sku, name=sku)
    db.add(model)
    await db.commit()
    return model


async def _file(db, tenant, model, dims=(40, 30, 20)) -> ModelFile:
    f = ModelFile(
        id=uuid4(),
        tenant_id=tenant.id,
        model_id=model.id,
        version_id=await active_version_id(db, tenant.id, model.id),
        file_type="source_stl",
        original_filename="block.stl",
    )
    if dims is not None:
        f.measured_length_mm, f.measured_width_mm, f.measured_height_mm = (
            Decimal(str(v)) for v in dims
        )
        f.measurement_status = "done"
    db.add(f)
    await db.commit()
    return f


class TestSetDimensions:
    async def test_entered(self, db_session, test_tenant) -> None:
        model = await _model(db_session, test_tenant)
        out = await set_dimensions(
            db_session,
            test_tenant,
            model,
            DimensionsIn(length_mm=Decimal("120"), width_mm=Decimal("80"), height_mm=Decimal("45")),
        )
        assert out is not None and out.source == "entered" and out.set_at is not None
        assert model.length_mm == Decimal("120.0")

    async def test_clear(self, db_session, test_tenant) -> None:
        model = set_dims(await _model(db_session, test_tenant), 1, 2, 3)
        assert await set_dimensions(db_session, test_tenant, model, DimensionsIn()) is None
        assert model.dimensions_source is None and model.dimensions_set_at is None

    async def test_adopt_measurement(self, db_session, test_tenant) -> None:
        model = await _model(db_session, test_tenant)
        f = await _file(db_session, test_tenant, model)
        out = await set_dimensions(db_session, test_tenant, model, DimensionsIn(adopt_file_id=f.id))
        assert out is not None and out.source == "measured" and out.source_file_id == f.id
        assert (out.length_mm, out.width_mm, out.height_mm) == (
            Decimal("40.0"),
            Decimal("30.0"),
            Decimal("20.0"),
        )

    async def test_adopt_someone_elses_file_is_not_found(self, db_session, test_tenant) -> None:
        model = await _model(db_session, test_tenant)
        other = await _model(db_session, test_tenant, sku="M-2")
        f = await _file(db_session, test_tenant, other)
        with pytest.raises(MeasurementNotFound):
            await set_dimensions(db_session, test_tenant, model, DimensionsIn(adopt_file_id=f.id))

    async def test_adopt_unmeasured_file(self, db_session, test_tenant) -> None:
        model = await _model(db_session, test_tenant)
        f = await _file(db_session, test_tenant, model, dims=None)
        with pytest.raises(MeasurementUnavailable):
            await set_dimensions(db_session, test_tenant, model, DimensionsIn(adopt_file_id=f.id))


class TestApplyMeasurement:
    async def _product_of(self, db, tenant, model, quantity=1, sku="P-1") -> Product:
        product = Product(id=uuid4(), tenant_id=tenant.id, sku=sku, name=sku)
        db.add(product)
        await db.flush()
        db.add(ProductModel(product_id=product.id, model_id=model.id, quantity=quantity))
        await db.commit()
        await db.refresh(product)
        return product

    async def test_fills_empty_model_and_single_model_product(
        self, db_session, test_tenant
    ) -> None:
        model = await _model(db_session, test_tenant)
        product = await self._product_of(db_session, test_tenant, model)
        f = await _file(db_session, test_tenant, model)
        applied = await apply_measurement(db_session, test_tenant, model, f)
        assert applied == ["model", "product"]
        assert model.dimensions_source == "measured" and model.dimensions_source_file_id == f.id
        assert product.length_mm == Decimal("40.0")

    async def test_never_overwrites_an_entry(self, db_session, test_tenant) -> None:
        model = set_dims(await _model(db_session, test_tenant), 99, 99, 99)
        await db_session.commit()
        f = await _file(db_session, test_tenant, model)
        assert await apply_measurement(db_session, test_tenant, model, f) == []
        assert model.length_mm == Decimal("99") and model.dimensions_source == "entered"

    async def test_product_at_quantity_two_is_untouched(self, db_session, test_tenant) -> None:
        model = await _model(db_session, test_tenant)
        product = await self._product_of(db_session, test_tenant, model, quantity=2)
        f = await _file(db_session, test_tenant, model)
        assert await apply_measurement(db_session, test_tenant, model, f) == ["model"]
        assert product.length_mm is None


async def test_variant_constraint_rejects_partial_dims(db_session, test_tenant) -> None:
    from sqlalchemy.exc import IntegrityError

    product = Product(id=uuid4(), tenant_id=test_tenant.id, sku="P-X", name="X")
    db_session.add(product)
    await db_session.flush()
    db_session.add(
        ProductVariant(
            tenant_id=test_tenant.id,
            product_id=product.id,
            size="L",
            sku="P-X-L",
            length_mm=Decimal("10"),
            dimensions_source="entered",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
