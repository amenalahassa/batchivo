"""Printer model for 3D printers available for production runs."""

import uuid
from typing import TYPE_CHECKING, Any, Optional

from decimal import Decimal
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.ams_slot_mapping import AMSSlotMapping
    from app.models.model_printer_config import ModelPrinterConfig
    from app.models.print_job import PrintJob
    from app.models.printer_connection import PrinterConnection
    from app.models.production_run import ProductionRun
    from app.models.production_run_plate import ProductionRunPlate
    from app.models.tenant import Tenant


class Printer(Base, UUIDMixin, TimestampMixin):
    """
    Printer represents a 3D printer available for production runs.

    Each printer can have different capabilities (bed size, materials, AMS)
    and different configurations for each model (prints per plate, times).

    Multi-tenant: Each printer belongs to a single tenant.
    """

    __tablename__ = "printers"

    # Tenant isolation
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )

    # Printer Identification
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Printer name (e.g., 'Bambu A1 Mini')",
    )

    manufacturer: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Manufacturer name",
    )

    model: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Model name",
    )

    # Bed Size
    bed_size_x_mm: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Bed size X in millimeters",
    )

    bed_size_y_mm: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Bed size Y in millimeters",
    )

    bed_size_z_mm: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Bed size Z in millimeters",
    )

    # Printer Settings
    nozzle_diameter_mm: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(3, 2),
        nullable=True,
        default=Decimal("0.4"),
        server_default="0.4",
        comment="Nozzle diameter in millimeters",
    )

    default_bed_temp: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Default bed temperature",
    )

    default_nozzle_temp: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Default nozzle temperature",
    )

    # Capabilities (JSON for flexibility)
    capabilities: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
        server_default="{}",
        comment="Printer capabilities (AMS, materials, etc.)",
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="Whether printer is active",
    )

    # Queue management status
    current_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="offline",
        server_default="offline",
        comment="Current operational status for queue management (idle, printing, error, offline)",
    )

    current_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey(
            "print_jobs.id", ondelete="SET NULL", use_alter=True, name="fk_printers_current_job_id"
        ),
        nullable=True,
        comment="Currently printing job (if any)",
    )

    # Current job relationship (for queue management)
    current_job: Mapped[Optional["PrintJob"]] = relationship(
        "PrintJob",
        foreign_keys=[current_job_id],
        lazy="selectin",
        post_update=True,  # Avoid circular dependency issues
    )

    # ------------------------------------------------------------------
    # Machine cost policy (Tier 1, FR-010, FR-011)
    #
    # Every column is nullable, and that is the point: a printer whose policy
    # the operator has not entered yields *no* machine rate and marks the item
    # incompletely costed (FR-019). A zero rate would read like a real figure
    # and make a 40-hour print look free.
    # ------------------------------------------------------------------
    purchase_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="All-in acquisition cost, the numerator of depreciation",
    )

    expected_lifetime_hours: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Expected printing hours over the machine's life; the depreciation denominator",
    )

    maintenance_reserve_total: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Nozzles, belts, plates and AMS parts expected over the whole life",
    )

    measured_watts: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(8, 2),
        nullable=True,
        comment="Measured draw at the wall while printing, not the nameplate rating",
    )

    electricity_rate_per_kwh: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="Per-printer electricity rate; falls back to the tenant pricing policy",
    )

    # Notes
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="printers",
        lazy="select",
    )

    model_printer_configs: Mapped[list["ModelPrinterConfig"]] = relationship(
        "ModelPrinterConfig",
        back_populates="printer",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    production_runs: Mapped[list["ProductionRun"]] = relationship(
        "ProductionRun",
        back_populates="printer",
        lazy="select",
    )

    production_run_plates: Mapped[list["ProductionRunPlate"]] = relationship(
        "ProductionRunPlate",
        back_populates="printer",
        lazy="select",
    )

    # Bambu integration relationships
    connection: Mapped[Optional["PrinterConnection"]] = relationship(
        "PrinterConnection",
        back_populates="printer",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="joined",
    )

    ams_slot_mappings: Mapped[list["AMSSlotMapping"]] = relationship(
        "AMSSlotMapping",
        back_populates="printer",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # Print queue jobs assigned to this printer
    print_jobs: Mapped[list["PrintJob"]] = relationship(
        "PrintJob",
        back_populates="assigned_printer",
        foreign_keys="[PrintJob.assigned_printer_id]",
        lazy="select",
    )

    # Constraints
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_printer_tenant_name"),
        # A purchase price with no life to spread it over is a division by zero
        # waiting to happen, so it is refused at save time (contracts: 422).
        CheckConstraint(
            "purchase_price IS NULL"
            " OR (expected_lifetime_hours IS NOT NULL AND expected_lifetime_hours > 0)",
            name="check_printer_lifetime_hours_positive_when_priced",
        ),
        {"comment": "3D printers available for production runs"},
    )

    @property
    def bed_size_str(self) -> Optional[str]:
        """Return bed size as formatted string (e.g., '180x180x180')."""
        if self.bed_size_x_mm and self.bed_size_y_mm and self.bed_size_z_mm:
            return f"{self.bed_size_x_mm}x{self.bed_size_y_mm}x{self.bed_size_z_mm}"
        return None

    # ------------------------------------------------------------------
    # Derived machine rate (Constitution V: derived, never stored)
    # ------------------------------------------------------------------

    def machine_rate_components(
        self,
        electricity_rate_per_kwh: Optional[Decimal] = None,
    ) -> dict[str, Any]:
        """Break the hourly occupancy rate into the parts it is made of.

        FR-010 defines the rate as depreciation over expected life, plus a
        maintenance reserve over the same life, plus measured power draw at the
        operator's electricity rate. Each part is reported separately because
        FR-018 requires a figure to be explainable without recomputing it.

        ``electricity_rate_per_kwh`` is the tenant policy fallback used when
        the printer carries no rate of its own (FR-011). Any part whose inputs
        are missing is omitted and named in ``missing``; the total is ``None``
        only when *nothing* could be derived, since a printer with a known
        purchase price but unmeasured power still has a real depreciation cost.
        """
        components: dict[str, Decimal] = {}
        missing: list[str] = []

        lifetime = self.expected_lifetime_hours
        if lifetime and lifetime > 0:
            if self.purchase_price is not None:
                components["depreciation_per_hour"] = Decimal(str(self.purchase_price)) / Decimal(
                    lifetime
                )
            else:
                missing.append("purchase_price")
            if self.maintenance_reserve_total is not None:
                components["maintenance_per_hour"] = Decimal(
                    str(self.maintenance_reserve_total)
                ) / Decimal(lifetime)
            else:
                missing.append("maintenance_reserve_total")
        else:
            missing.append("expected_lifetime_hours")
            if self.purchase_price is None:
                missing.append("purchase_price")

        rate = self.electricity_rate_per_kwh
        if rate is None:
            rate = electricity_rate_per_kwh
        if self.measured_watts is not None and rate is not None:
            components["power_per_hour"] = (
                Decimal(str(self.measured_watts)) / Decimal("1000")
            ) * Decimal(str(rate))
        else:
            if self.measured_watts is None:
                missing.append("measured_watts")
            if rate is None:
                missing.append("electricity_rate_per_kwh")

        total = sum(components.values(), Decimal("0")) if components else None
        return {"components": components, "total": total, "missing": missing}

    @property
    def machine_rate_per_hour(self) -> Optional[Decimal]:
        """Hourly cost of occupying this machine, or ``None`` if unknowable.

        Uses only this printer's own electricity rate; the caller that holds
        the tenant policy passes its fallback to
        :meth:`machine_rate_components` instead.
        """
        derived: Optional[Decimal] = self.machine_rate_components()["total"]
        return derived

    def __repr__(self) -> str:
        return f"<Printer(name={self.name}, manufacturer={self.manufacturer})>"
