"""Factories for the packaging advisor's tests (task T002)."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consumable import ConsumableType
from app.models.tenant import Tenant


def _dec(value: Any) -> Optional[Decimal]:
    return None if value is None else Decimal(str(value))


async def make_box(
    db: AsyncSession,
    tenant: Tenant,
    name: str,
    inner: Optional[tuple[Any, Any, Any]] = None,
    weight: Any = None,
    on_hand: int = 10,
    cost: Any = None,
    kind: str = "box",
    wall: Any = None,
) -> ConsumableType:
    """A container (box or mailer) with inner size in mm and empty weight in g."""
    length, width, height = inner if inner is not None else (None, None, None)
    box = ConsumableType(
        id=uuid4(),
        tenant_id=tenant.id,
        sku=f"PKG-{uuid4().hex[:8].upper()}",
        name=name,
        category="packaging",
        packaging_kind=kind,
        inner_length_mm=_dec(length),
        inner_width_mm=_dec(width),
        inner_height_mm=_dec(height),
        wall_mm=_dec(wall),
        empty_weight_grams=_dec(weight),
        quantity_on_hand=on_hand,
        current_cost_per_unit=_dec(cost),
        is_active=True,
    )
    db.add(box)
    await db.commit()
    await db.refresh(box)
    return box


async def make_void_fill(
    db: AsyncSession,
    tenant: Tenant,
    fill_volume_ml: Any,
    on_hand: int = 10,
    name: str = "Paper fill",
    weight: Any = None,
) -> ConsumableType:
    """Void fill that fills ``fill_volume_ml`` per unit."""
    fill = ConsumableType(
        id=uuid4(),
        tenant_id=tenant.id,
        sku=f"FILL-{uuid4().hex[:8].upper()}",
        name=name,
        category="packaging",
        packaging_kind="void_fill",
        fill_volume_ml=_dec(fill_volume_ml),
        empty_weight_grams=_dec(weight),
        quantity_on_hand=on_hand,
        is_active=True,
    )
    db.add(fill)
    await db.commit()
    await db.refresh(fill)
    return fill


async def make_wrap(
    db: AsyncSession, tenant: Tenant, on_hand: int = 10, name: str = "Bubble wrap"
) -> ConsumableType:
    """Protective wrap."""
    wrap = ConsumableType(
        id=uuid4(),
        tenant_id=tenant.id,
        sku=f"WRAP-{uuid4().hex[:8].upper()}",
        name=name,
        category="packaging",
        packaging_kind="wrap",
        quantity_on_hand=on_hand,
        is_active=True,
    )
    db.add(wrap)
    await db.commit()
    await db.refresh(wrap)
    return wrap


def set_dims(item: Any, length: Any, width: Any, height: Any, source: str = "entered") -> Any:
    """Give a model, product or variant dimensions in place (commit separately)."""
    item.length_mm = _dec(length)
    item.width_mm = _dec(width)
    item.height_mm = _dec(height)
    item.dimensions_source = source
    item.dimensions_set_at = datetime.now(UTC)
    return item
