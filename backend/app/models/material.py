"""Material type reference data models."""

from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class MaterialType(Base, UUIDMixin, TimestampMixin):
    """
    Material type reference data (PLA, PETG, ASA, TPU, etc.).

    This is shared across all tenants as reference data.
    Tenants reference these when creating spools.
    """

    __tablename__ = "material_types"

    # Material information
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
        comment="Material name (e.g., PLA, PETG, ASA)",
    )

    code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        unique=True,
        index=True,
        comment="Short code for material (e.g., PLA, PETG)",
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Description of material properties and uses",
    )

    # Typical properties (defaults that users can override per spool)
    typical_density: Mapped[float | None] = mapped_column(
        nullable=True,
        comment="Typical density in g/cm³ (e.g., 1.24 for PLA)",
    )

    # Money, so `Numeric` and `Decimal` rather than the binary float this was
    # (task T154, FR-047). T024's sweep converted every money column in this
    # package that was already `Numeric`; this one was declared without a type
    # at all, so SQLAlchemy inferred `Float` from the `float` annotation and
    # the sweep passed it over.
    #
    # Exposure is narrow -- it prefills a spool's purchase price rather than
    # entering the engine -- but the figure it prefills is the one
    # `costing.py:cost_per_gram` divides by a weight, so the inexactness was
    # one keystroke from the cost of every print. `typical_density` beside it
    # stays a float: a density is a measurement, not an amount of money.
    typical_cost_per_kg: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Typical cost per kilogram (for defaults)",
    )

    # Printing characteristics
    min_temp: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="Minimum printing temperature (°C)",
    )

    max_temp: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="Maximum printing temperature (°C)",
    )

    bed_temp: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="Typical bed temperature (°C)",
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        comment="Whether this material type is active",
    )

    def __repr__(self) -> str:
        return f"<MaterialType(code='{self.code}', name='{self.name}')>"
