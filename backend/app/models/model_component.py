"""ModelComponent model for non-material costs (magnets, inserts, etc.)."""

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.consumable import ConsumableType
    from app.models.model import Model


class ModelComponent(Base, UUIDMixin, TimestampMixin):
    """
    Non-material component costs for models.

    Tracks additional components used in models like magnets, heat inserts,
    screws, glue, paint, etc. Each component has a quantity and unit cost.

    Can optionally link to a ConsumableType for automatic cost tracking
    and inventory management.
    """

    __tablename__ = "model_components"

    # Reference
    model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Model this component belongs to",
    )

    # Optional link to consumable inventory
    consumable_type_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("consumable_types.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Link to consumable type for automatic cost/inventory tracking",
    )

    # Component Info
    component_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Component name (e.g., 'M3 x 10mm magnet', 'M3 heat insert')",
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Quantity of this component used in model",
    )

    #: The column is ``Numeric``, so SQLAlchemy hands back a ``Decimal``; the
    #: annotation said ``float``, which made every reader's type checking
    #: agree with a conversion that never happens and would be wrong if it
    #: did (Constitution IV).
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Cost per unit in local currency",
    )

    supplier: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Supplier/vendor name",
    )

    # Relationships
    model: Mapped["Model"] = relationship(
        "Model",
        back_populates="components",
    )

    consumable_type: Mapped[Optional["ConsumableType"]] = relationship(
        "ConsumableType",
        back_populates="model_components",
    )

    def __repr__(self) -> str:
        return f"<ModelComponent(name={self.component_name}, qty={self.quantity}, unit_cost={self.unit_cost})>"

    # `total_cost` and `effective_unit_cost` stood here, and both were float
    # arithmetic on a monetary column with no reader anywhere in `app/`
    # (Constitution IV).
    #
    # `total_cost` was `quantity * unit_cost`, which
    # `app/services/costing.py` already computes in `Decimal` as the
    # "components" line -- a second implementation of one figure
    # (Constitution III).
    #
    # `effective_unit_cost` was worse than duplicate: it preferred a linked
    # consumable's `current_cost_per_unit` over the typed `unit_cost`, which
    # is *not* what the engine does for a model component. Two answers to one
    # question, differing on exactly the rows where a consumable is linked.
    # Whichever is right, it is the engine's to decide, in one place, with the
    # provenance the engine records beside it.
