"""Where an item's dimensions and packaging come from (research D1, D2, D11).

The one place that answers "how big is this, and what is it packed in": a
size variant's own figures when it has them, otherwise its product's. The
advisor, the product screens and postage all read through here, so a variant
never shows one size on one screen and its product's on another.

It is also the only writer of dimensions. An operator's entry is recorded as
``entered``; a measurement reaches an item only when the item has no
dimensions yet, or when the operator adopts it -- never over an entry (FR-003).
"""

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model import Model
from app.models.model_file import ModelFile
from app.models.product import Product
from app.models.product_model import ProductModel
from app.models.product_variant import ProductVariant
from app.schemas.dimensions import DimensionsIn, DimensionsOut
from app.services.dims import Dims

if TYPE_CHECKING:
    from app.models.consumable import ConsumableType
    from app.models.tenant import Tenant
    from app.services.mesh_bounds import Measurement

logger = logging.getLogger(__name__)

DimensionedItem = Union[Model, Product, ProductVariant]


class MeasurementNotFound(LookupError):
    """The file to adopt is not this item's (or not this tenant's): a 404."""


class MeasurementUnavailable(ValueError):
    """The file exists but holds no measurement to adopt: a 422."""


def dimensions_out(item: DimensionedItem, *, inherited: bool = False) -> Optional[DimensionsOut]:
    """The response shape for an item's own dimensions, or ``None`` when it has none."""
    if Dims.from_row(item) is None:
        return None
    return DimensionsOut(
        length_mm=item.length_mm,
        width_mm=item.width_mm,
        height_mm=item.height_mm,
        source=item.dimensions_source,
        source_file_id=item.dimensions_source_file_id,
        set_at=item.dimensions_set_at,
        inherited=inherited,
    )


def effective_dimensions(
    product: Product, variant: Optional[ProductVariant] = None
) -> tuple[Optional[Dims], Optional[DimensionsOut]]:
    """A variant's dimensions, else its product's (marked ``inherited``)."""
    if variant is not None:
        own = Dims.from_row(variant)
        if own is not None:
            return own, dimensions_out(variant)
        return Dims.from_row(product), dimensions_out(product, inherited=True)
    return Dims.from_row(product), dimensions_out(product)


def effective_packaging(
    product: Product, variant: Optional[ProductVariant] = None
) -> tuple[Optional["ConsumableType"], int]:
    """The packaging consumable and quantity in force for one unit.

    Each of the variant's two fields overrides the product's on its own; a
    null inherits.
    """
    consumable = getattr(product, "packaging_consumable", None)
    quantity = getattr(product, "packaging_quantity", None) or 1
    if variant is not None:
        if variant.packaging_consumable_id is not None:
            consumable = variant.packaging_consumable
        if variant.packaging_quantity is not None:
            quantity = variant.packaging_quantity
    return consumable, quantity


def variant_for_order_line(product: Product, sku: Optional[str]) -> Optional[ProductVariant]:
    """The variant an order line names by SKU, else ``None`` (research D11).

    Order items carry no variant id; a line whose ``product_sku`` is a
    variant's SKU is that variant, anything else is the product.
    """
    if not sku:
        return None
    for variant in getattr(product, "variants", None) or []:
        if variant.sku == sku:
            return variant
    return None


def single_model_of(product: Product) -> Optional[Model]:
    """The product's one model, when it is made of exactly one at quantity 1 (FR-009)."""
    links = list(product.product_models or [])
    if len(links) != 1 or links[0].quantity != 1 or product.child_products:
        return None
    return links[0].model


def _write(
    item: DimensionedItem,
    dims: Optional[Dims],
    source: Optional[str],
    file_id: Optional[uuid.UUID],
) -> None:
    if dims is None:
        item.length_mm = item.width_mm = item.height_mm = None
        item.dimensions_source = None
        item.dimensions_source_file_id = None
        item.dimensions_set_at = None
        return
    dims = dims.quantize()
    item.length_mm, item.width_mm, item.height_mm = dims.as_tuple()
    item.dimensions_source = source
    item.dimensions_source_file_id = file_id
    item.dimensions_set_at = datetime.now(UTC)


def _file_dims(model_file: ModelFile) -> Optional[Dims]:
    return Dims.from_row(model_file, prefix="measured_")


async def _adoptable_file(
    db: AsyncSession,
    tenant: "Tenant",
    item: DimensionedItem,
    file_id: uuid.UUID,
    product: Optional[Product],
) -> ModelFile:
    """The file to adopt, if it belongs to this item's model (or product's single model)."""
    if isinstance(item, Model):
        model_id: Optional[uuid.UUID] = item.id
    else:
        owner = item if isinstance(item, Product) else product
        model = single_model_of(owner) if owner is not None else None
        model_id = model.id if model is not None else None
    model_file = (
        await db.execute(
            select(ModelFile).where(ModelFile.id == file_id, ModelFile.tenant_id == tenant.id)
        )
    ).scalar_one_or_none()
    if model_file is None or model_id is None or model_file.model_id != model_id:
        raise MeasurementNotFound(f"model file {file_id} is not one of this item's files")
    return model_file


async def set_dimensions(
    db: AsyncSession,
    tenant: "Tenant",
    item: DimensionedItem,
    dims_in: DimensionsIn,
    *,
    product: Optional[Product] = None,
) -> Optional[DimensionsOut]:
    """Save an operator's dimensions (``entered``), adopt a file's (``measured``), or clear.

    ``product`` is a variant's product, which says which model's files it may
    adopt from. Clearing a variant returns it to its product's dimensions.
    """
    if item.tenant_id != tenant.id:  # defence in depth; routes already scope by tenant
        raise MeasurementNotFound("item belongs to another tenant")
    if dims_in.adopt_file_id is not None:
        model_file = await _adoptable_file(db, tenant, item, dims_in.adopt_file_id, product)
        measured = _file_dims(model_file)
        if measured is None:
            raise MeasurementUnavailable(
                f"{model_file.original_filename} has no measurement to adopt"
            )
        _write(item, measured, "measured", model_file.id)
    elif dims_in.clears:
        _write(item, None, None, None)
    else:
        assert dims_in.length_mm and dims_in.width_mm and dims_in.height_mm
        _write(
            item,
            Dims(dims_in.length_mm, dims_in.width_mm, dims_in.height_mm),
            "entered",
            None,
        )
    await db.flush()
    logger.info(
        f"Set dimensions of {type(item).__name__} {item.id} to "
        f"{item.length_mm} x {item.width_mm} x {item.height_mm} ({item.dimensions_source})"
    )
    return dimensions_out(item)


def record_measurement(model_file: ModelFile, measurement: "Measurement") -> None:
    """Store what a file measured on its row (research D4); the sizes only when known."""
    from app.services.mesh_bounds import objects_json

    overall = measurement.overall
    model_file.measured_length_mm = overall.length if overall else None
    model_file.measured_width_mm = overall.width if overall else None
    model_file.measured_height_mm = overall.height if overall else None
    model_file.measured_objects = objects_json(measurement.objects) or None
    model_file.measurement_note = (measurement.note or None) and measurement.note[:255]
    model_file.measurement_status = measurement.status
    model_file.measured_at = datetime.now(UTC) if overall else None


async def apply_measurement(
    db: AsyncSession,
    tenant: "Tenant",
    model: Model,
    model_file: ModelFile,
) -> list[str]:
    """Give a file's measurement to the records that have no dimensions yet (D2, FR-009).

    The model takes it when it has none; so does each product made of exactly
    this model at quantity 1 that has none. Anything with dimensions -- above
    all an operator's entry -- is left alone, and the measurement stays on the
    file as an offer. Returns which records took it (``"model"``, ``"product"``).
    """
    measured = _file_dims(model_file)
    if measured is None or model_file.model_id != model.id:
        return []

    applied: list[str] = []
    if Dims.from_row(model) is None:
        _write(model, measured, "measured", model_file.id)
        applied.append("model")

    products = (
        (
            await db.execute(
                select(Product)
                .join(ProductModel, ProductModel.product_id == Product.id)
                .where(ProductModel.model_id == model.id, Product.tenant_id == tenant.id)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    for product in products:
        only = single_model_of(product)
        if only is not None and only.id == model.id and Dims.from_row(product) is None:
            _write(product, measured, "measured", model_file.id)
            if "product" not in applied:
                applied.append("product")
    if applied:
        await db.flush()
        logger.info(f"Applied measurement of file {model_file.id} to {', '.join(applied)}")
    return applied


def dims_dict(dims: Optional[Dims]) -> Optional[dict[str, Decimal]]:
    """``{"length_mm": ..., ...}`` for a response, or ``None``."""
    if dims is None:
        return None
    return {"length_mm": dims.length, "width_mm": dims.width, "height_mm": dims.height}


__all__ = [
    "MeasurementNotFound",
    "MeasurementUnavailable",
    "apply_measurement",
    "dimensions_out",
    "dims_dict",
    "effective_dimensions",
    "effective_packaging",
    "set_dimensions",
    "single_model_of",
    "variant_for_order_line",
]
