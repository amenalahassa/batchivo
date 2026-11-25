"""Model file for 3D model file tracking (STL, 3MF, gcode, etc.)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.model import Model
    from app.models.model_file_version import ModelFileVersion
    from app.models.user import User


class ModelFileType(str, Enum):
    """Types of 3D model files."""

    SOURCE_STL = "source_stl"  # Original STL file from designer
    SOURCE_3MF = "source_3mf"  # Original 3MF file from designer
    SLICER_PROJECT = "slicer_project"  # Slicer project file with settings
    GCODE = "gcode"  # Pre-sliced gcode ready to print
    PLATE_LAYOUT = "plate_layout"  # Plate arrangement file


class FileLocation(str, Enum):
    """Where the file is stored."""

    UPLOADED = "uploaded"  # File was uploaded and stored in storage backend
    LOCAL_REFERENCE = "local_reference"  # Path reference to local filesystem


class ModelFile(Base, UUIDMixin, TimestampMixin):
    """
    ModelFile tracks 3D model files associated with a Model.

    Supports multiple files per model (multi-part models), versioning,
    and different file types (source files, slicer projects, gcode).
    """

    __tablename__ = "model_files"

    # Tenant isolation
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant this file belongs to",
    )

    # Model reference
    model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="3D model this file is associated with",
    )

    # The version this file belongs to. Grouping follows this column; the
    # free-text `version` below is kept for older clients and is informational.
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_file_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Version this file belongs to",
    )

    # Whether the file is a sliced plate (G-code, or a 3MF carrying plate
    # G-code). Set once at upload: a file's bytes never change, so it cannot go
    # stale (research D3).
    is_sliced: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="True for a sliced plate (.gcode, or a 3MF with plate G-code)",
    )

    # File type categorization
    file_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
        comment="File type: source_stl, source_3mf, slicer_project, gcode, plate_layout",
    )

    # File storage location
    file_location: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="uploaded",
        comment="Where file is stored: 'uploaded' (in storage) or 'local_reference' (filesystem path)",
    )

    file_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="URL or path to the stored file (for uploaded files)",
    )

    local_path: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
        comment="Local filesystem path (for local_reference files)",
    )

    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Original filename as uploaded or referenced",
    )

    file_size: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        comment="File size in bytes (may be null for local references)",
    )

    content_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="MIME content type (e.g., model/stl, model/3mf)",
    )

    # Multi-part model support
    part_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Part name for multi-part models (e.g., 'body', 'wings', 'base')",
    )

    # Versioning
    version: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Version identifier (e.g., 'v2.1', '2024-01-15')",
    )

    # Primary file flag
    is_primary: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Whether this is the primary/default file for the model",
    )

    # Notes
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="User notes about the file (e.g., slicer settings, print tips)",
    )

    # Audit trail
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="When the file was uploaded",
    )

    uploaded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="User who uploaded the file",
    )

    # Bounding box measured from the file's geometry (packaging advisor, research
    # D4). Stored rather than recomputed: a file's bytes never change after
    # upload (a new version is a new row), so the figure cannot go stale; it goes
    # when the row does. A suggestion only -- it reaches a model's dimensions
    # through `item_dimensions.apply_measurement`, which never overwrites an
    # operator's entry (FR-003).
    measured_length_mm: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 1), nullable=True, comment="Measured build length in mm"
    )
    measured_width_mm: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 1), nullable=True, comment="Measured build width in mm"
    )
    measured_height_mm: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 1), nullable=True, comment="Measured build height in mm"
    )
    measured_objects: Mapped[Optional[list]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
        comment="Per-object sizes: [{name, length_mm, width_mm, height_mm}] as decimal strings",
    )
    measured_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When the file was measured"
    )
    measurement_note: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Why the file was not measured, or the multi-object warning",
    )
    measurement_status: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="done | pending (queued, file > 25 MB) | skipped | failed",
    )
    measurement_reason: Mapped[Optional[str]] = mapped_column(
        String(40),
        nullable=True,
        comment="Machine-readable reason a file was not measured, e.g. no_geometry",
    )

    # Relationships
    model: Mapped["Model"] = relationship(
        "Model",
        back_populates="files",
        foreign_keys=[model_id],
        lazy="select",
    )

    uploaded_by: Mapped[Optional["User"]] = relationship(
        "User",
        lazy="select",
    )

    file_version: Mapped["ModelFileVersion"] = relationship(
        "ModelFileVersion",
        back_populates="files",
        foreign_keys=[version_id],
        lazy="select",
    )

    #: Which records took this file's measurement on upload; set by the
    #: service for the response only, never stored.
    measurement_applied_to: list[str] = []
    #: Whether the upload made a new version for this file; response only.
    version_created: bool = False

    @property
    def measurement(self) -> Optional[dict]:
        """The measurement as the API reports it, or None for a file never measured."""
        if self.measurement_status is None:
            return None
        return {
            "length_mm": self.measured_length_mm,
            "width_mm": self.measured_width_mm,
            "height_mm": self.measured_height_mm,
            "objects": self.measured_objects or [],
            "note": self.measurement_note,
            "status": self.measurement_status,
            "reason": self.measurement_reason,
            "applied_to": list(self.measurement_applied_to),
        }

    __table_args__ = (
        CheckConstraint(
            "measurement_status IS NULL OR "
            "measurement_status IN ('done', 'pending', 'skipped', 'failed')",
            name="ck_model_files_measurement_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<ModelFile(id={self.id}, model_id={self.model_id}, type={self.file_type}, filename={self.original_filename})>"
