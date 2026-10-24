"""Model for 3D printed items (individual printed parts)."""

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.model_component import ModelComponent
    from app.models.model_file import ModelFile
    from app.models.model_material import ModelMaterial
    from app.models.model_printer_config import ModelPrinterConfig
    from app.models.print_job import PrintJob
    from app.models.printer import Printer
    from app.models.production_run_plate import ProductionRunPlate


class Model(Base, UUIDMixin, TimestampMixin):
    """
    Model represents a 3D printed item (individual printed part).

    This is what was previously called "Product" - the actual printed item
    with materials (BOM), components, labor, and cost tracking.

    Multiple Models can be combined into a sellable Product.
    """

    __tablename__ = "models"

    # Tenant isolation
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )

    # Model Identification
    sku: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Stock Keeping Unit (unique per tenant)",
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Model name",
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Model description/notes",
    )

    category: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Model category (e.g., 'Miniatures', 'Functional Parts')",
    )

    # Media
    image_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Model image URL",
    )

    # Labor Costing
    #
    # DEPRECATED by the Tier 1 labor split below. The migration copies this
    # figure into `labor_hours_per_item`; the engine reads it only when the new
    # column is absent or zero, which is what keeps a record created before the
    # migration costing the same as it did. The column is dropped once no read
    # path remains.
    labor_hours: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
        server_default="0",
        comment=(
            "DEPRECATED (Tier 1): superseded by labor_hours_per_item. "
            "Labor hours required (post-processing, assembly, etc.)"
        ),
    )

    # ------------------------------------------------------------------
    # Item cost profile (Tier 1)
    #
    # Labor is split four ways because the four behave differently: per-plate
    # work is divided across the plate's output (FR-013), per-item work is not,
    # finishing may carry its own rate (FR-012), and packing happens on a part
    # already known good so the failure premium must never reach it (FR-015).
    # ------------------------------------------------------------------
    waste_grams: Mapped[Decimal] = mapped_column(
        Numeric(8, 2),
        nullable=False,
        default=0,
        server_default="0",
        comment=(
            "Purge, priming and colour-change filament for one plate — consumed, "
            "never sold, and costed as its own line (FR-009)"
        ),
    )

    expected_yield: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("1.0"),
        server_default="1.0",
        comment="Per-part success probability in (0, 1]; 1.0 means no failure premium",
    )

    failure_mode: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="per_part",
        server_default="per_part",
        comment=(
            "How the yield figure is read: 'per_part' (parts fail independently) "
            "or 'per_plate' (one failure condemns the plate)"
        ),
    )

    labor_hours_per_plate: Mapped[Decimal] = mapped_column(
        Numeric(8, 3),
        nullable=False,
        default=0,
        server_default="0",
        comment="Preparation a plate needs once, divided across its output (FR-013)",
    )

    labor_hours_per_item: Mapped[Decimal] = mapped_column(
        Numeric(8, 3),
        nullable=False,
        default=0,
        server_default="0",
        comment="Handling per item, never divided across a plate (FR-013)",
    )

    finishing_hours_per_item: Mapped[Decimal] = mapped_column(
        Numeric(8, 3),
        nullable=False,
        default=0,
        server_default="0",
        comment="Finishing per item, charged at the finishing rate (FR-012)",
    )

    packing_hours_per_item: Mapped[Decimal] = mapped_column(
        Numeric(8, 3),
        nullable=False,
        default=0,
        server_default="0",
        comment="Packing per item — NOT at risk of print failure (FR-015, FR-016)",
    )

    labor_rate_override: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Override labor rate for this model (£/hour). If null, use tenant default.",
    )

    # Overhead
    overhead_percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=0,
        server_default="0",
        comment="Overhead percentage to apply (0-100). If 0, use tenant default.",
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        comment="Whether model is active",
    )

    # Model Metadata
    designer: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Model designer name (e.g., 'CinderWings')",
    )

    source: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Model source platform (e.g., 'Thangs', 'Patreon')",
    )

    print_time_minutes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Print time in minutes (for full plate if prints_per_plate > 1)",
    )

    # The machine this item is planned on, whose cost policy gives its machine
    # rate (FR-011, T243). NULL costs it at the policy's default rate.
    planned_printer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("printers.id", ondelete="SET NULL"),
        nullable=True,
        comment="The machine this item is planned on; its rate costs the item (FR-011)",
    )

    prints_per_plate: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Number of items printed per plate (for batch printing). Material weights and print time are divided by this.",
    )

    machine: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Printer/machine used (e.g., 'Bambulabs A1 Mini')",
    )

    last_printed_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last time this model was printed",
    )

    units_in_stock: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        default=0,
        server_default="0",
        comment="Number of printed units in inventory",
    )

    # Production Cost Tracking (Phase 2: Rolling average from actual runs)
    actual_production_cost: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 4),
        nullable=True,
        comment="Rolling average actual production cost per unit from completed runs",
    )

    production_cost_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Number of completed production runs included in rolling average",
    )

    production_cost_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last time actual_production_cost was updated",
    )

    # Relationships
    materials: Mapped[list["ModelMaterial"]] = relationship(
        "ModelMaterial",
        back_populates="model",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    components: Mapped[list["ModelComponent"]] = relationship(
        "ModelComponent",
        back_populates="model",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    production_run_items: Mapped[list["ProductionRunItem"]] = relationship(
        "ProductionRunItem",
        back_populates="model",
        lazy="select",
    )

    product_models: Mapped[list["ProductModel"]] = relationship(
        "ProductModel",
        back_populates="model",
        lazy="select",
    )

    # Eager, because the engine issues no queries: a planned machine nobody
    # loaded would read as absent and cost the item at the default rate on one
    # screen and at its own on another (Constitution III).
    planned_printer: Mapped[Optional["Printer"]] = relationship(
        "Printer",
        foreign_keys=[planned_printer_id],
        lazy="selectin",
    )

    # Printer-specific configurations
    printer_configs: Mapped[list["ModelPrinterConfig"]] = relationship(
        "ModelPrinterConfig",
        back_populates="model",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Multi-plate run plates
    production_run_plates: Mapped[list["ProductionRunPlate"]] = relationship(
        "ProductionRunPlate",
        back_populates="model",
        lazy="select",
    )

    # Print queue jobs
    print_jobs: Mapped[list["PrintJob"]] = relationship(
        "PrintJob",
        back_populates="model",
        lazy="select",
    )

    # 3D model files (STL, 3MF, gcode, etc.)
    files: Mapped[list["ModelFile"]] = relationship(
        "ModelFile",
        back_populates="model",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Constraints
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_model_tenant_sku"),
        # A yield of zero would divide the at-risk cost by nothing and report an
        # infinite cost; it is a configuration error, not a number (spec edge
        # case "Yield of zero or 100%").
        CheckConstraint(
            "expected_yield > 0 AND expected_yield <= 1",
            name="check_model_expected_yield_in_unit_interval",
        ),
        CheckConstraint(
            "failure_mode IN ('per_part', 'per_plate')",
            name="check_model_failure_mode",
        ),
        {"comment": "3D printed model/part with Bill of Materials and cost tracking"},
    )

    def __repr__(self) -> str:
        return f"<Model(sku={self.sku}, name={self.name})>"
