"""Spool model for filament inventory tracking."""

import uuid
from decimal import Decimal
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.filament_purchase import FilamentPurchase


class Spool(Base, UUIDMixin, TimestampMixin):
    """
    Filament spool inventory item.

    Tracks individual physical spools of 3D printing filament with purchase info,
    weight tracking, and a reference to the FilamentType that defines the filament
    specifications.
    """

    __tablename__ = "spools"

    # Tenant isolation
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )

    # FilamentType reference (two-tier model: type definition + per-unit spool)
    filament_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("filament_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="FilamentType this spool belongs to",
    )

    # Basic Info
    spool_id: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="User-friendly spool ID (e.g., FIL-001, PLA-RED-001)",
    )

    # Weight Tracking (in grams)
    initial_weight: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Initial filament weight in grams (e.g., 1000.00 for 1kg)",
    )

    current_weight: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Current filament weight in grams",
    )

    empty_spool_weight: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Weight of empty spool in grams (for gross weight calculations)",
    )

    # Purchase Information
    purchase_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Date spool was purchased",
    )

    purchase_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Purchase price in local currency",
    )

    supplier: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Supplier/vendor name",
    )

    # Landed cost (Tier 1)
    filament_purchase_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("filament_purchases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment=(
            "Purchase this spool came in on, which carries the inbound shipping "
            "and tax to allocate. NULL keeps the spool costing from its own "
            "price with no allocated shipping (FR-008e)"
        ),
    )

    unusable_remainder_grams: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(8, 2),
        nullable=True,
        comment=(
            "Filament left on the core that cannot be printed. The per-gram cost "
            "divides by nominal weight less this, never by nominal weight (FR-008d)"
        ),
    )

    # Storage & Organization
    storage_location: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Physical storage location (e.g., Shelf A, Box 3)",
    )

    # QR Code Integration
    qr_code_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
        index=True,
        comment="QR code identifier for quick scanning",
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        comment="Whether spool is active (not empty/discarded)",
    )

    is_labeled: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        comment="Whether a physical label has been printed for this spool",
    )

    # Relationships
    filament_type: Mapped["FilamentType"] = relationship(
        "FilamentType",
        lazy="joined",
    )

    production_run_materials: Mapped[list["ProductionRunMaterial"]] = relationship(
        "ProductionRunMaterial",
        back_populates="spool",
        lazy="select",
    )

    filament_purchase: Mapped[Optional["FilamentPurchase"]] = relationship(
        "FilamentPurchase",
        back_populates="spools",
        lazy="select",
    )

    __table_args__ = (
        CheckConstraint(
            "unusable_remainder_grams IS NULL OR unusable_remainder_grams >= 0",
            name="check_spool_unusable_remainder_non_negative",
        ),
    )

    def __repr__(self) -> str:
        return f"<Spool(id={self.spool_id}, filament_type_id={self.filament_type_id})>"

    @property
    def remaining_weight(self) -> float:
        """Calculate remaining filament weight."""
        return float(self.current_weight)

    @property
    def remaining_percentage(self) -> float:
        """Calculate remaining filament as percentage."""
        if self.initial_weight <= 0:
            return 0.0
        return (float(self.current_weight) / float(self.initial_weight)) * 100

    @property
    def usable_weight_grams(self) -> Decimal:
        """Nominal weight less the measured unusable remainder (FR-008d)."""
        nominal = Decimal(str(self.initial_weight))
        remainder = (
            Decimal(str(self.unusable_remainder_grams))
            if self.unusable_remainder_grams is not None
            else Decimal("0")
        )
        usable = nominal - remainder
        return usable if usable > 0 else Decimal("0")

    @property
    def cost_per_gram(self) -> Optional[Decimal]:
        """Landed cost per usable gram, or ``None`` when it cannot be derived.

        Exact, because this figure seeds `ModelMaterial.cost_per_gram` and so
        reaches every make-cost in the system (Constitution IV). It used to
        divide two floats, which `app/services/production_run.py` then had to
        wrap in `Decimal(str(...))` to put back into a Decimal column.

        Tier 1 makes this the **landed** figure: it divides by usable weight
        rather than nominal weight, and includes the shipping and the
        non-recoverable tax allocated from the parent purchase. There is one
        implementation of that derivation, in
        :mod:`app.services.landed_cost`, and this property calls it rather
        than restating it (Constitution III).

        A spool with no parent purchase and no recorded remainder lands on
        exactly the figure it reported before Tier 1 -- purchase price over
        initial weight -- which is what FR-008e requires.
        """
        from app.services.landed_cost import spool_landed_cost

        return spool_landed_cost(self).cost_per_gram

    @property
    def is_low_stock(self, threshold: float = 20.0) -> bool:
        """Check if spool is below threshold percentage."""
        return self.remaining_percentage < threshold
