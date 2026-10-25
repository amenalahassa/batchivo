"""ModelMaterial model for Bill of Materials (BOM) tracking."""

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.model import Model
    from app.models.spool import Spool


class ModelMaterial(Base, UUIDMixin, TimestampMixin):
    """
    Bill of Materials (BOM) entry linking models to filament spools.

    Tracks which materials (spools) are used in a model and how much.

    ``cost_per_gram`` is an operator override and is normally empty: the line
    then costs at its spool's landed per-gram figure, derived on read
    (task T254, FR-008, FR-049). It used to hold a figure the browser computed
    from nominal weight when the line was added, which left out the remainder,
    the purchase's shipping and its tax, and never followed a later price
    change. Consumed material is frozen on ``ProductionRunMaterial`` and a sale
    on its snapshot, so nothing historical depends on this column.
    """

    __tablename__ = "model_materials"

    # References
    model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Model this material belongs to",
    )

    spool_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spools.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Spool (material type/color/brand combination) used",
    )

    # Usage & Cost
    weight_grams: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Weight of this material used in model (grams)",
    )

    cost_per_gram: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 4),
        nullable=True,
        comment="Operator override of the per-gram cost; NULL derives it from the spool",
    )

    # Relationships
    model: Mapped["Model"] = relationship(
        "Model",
        back_populates="materials",
    )

    spool: Mapped["Spool"] = relationship(
        "Spool",
        lazy="joined",
    )

    def __repr__(self) -> str:
        return f"<ModelMaterial(model_id={self.model_id}, spool_id={self.spool_id}, weight={self.weight_grams}g)>"

    @property
    def resolved_cost_per_gram(self) -> Optional[Decimal]:
        """The per-gram figure this line costs at: the override, else the spool's."""
        from app.services.landed_cost import material_cost_per_gram

        return material_cost_per_gram(self).cost_per_gram

    @property
    def line_cost(self) -> Optional[Decimal]:
        """Weight times the resolved per-gram figure, unrounded, for display."""
        per_gram = self.resolved_cost_per_gram
        if per_gram is None:
            return None
        return Decimal(str(self.weight_grams)) * per_gram
