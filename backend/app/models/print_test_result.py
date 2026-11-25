"""Results of printed test pieces (spec 009, US4).

A result says how a printed test piece did -- a clearance grid, a critical zone
cut out of a part, or the full part -- with its measurements, failure mode, a
photo and notes. It names the print job, the model file version, or both
(clarification Q3); the version is required for a part test, which the service
enforces. Links are ``SET NULL`` so a deleted print job leaves the result.
"""

import uuid
from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.calibration import ORIENTATIONS

TEST_KINDS = ("clearance_grid", "critical_zone", "full_part")
#: Kinds that test a part, so they must name the model version they tested.
PART_TEST_KINDS = ("critical_zone", "full_part")
TEST_OUTCOMES = ("pass", "fail", "partial")

_JSON = JSON().with_variant(JSONB(), "postgresql")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class PrintTestResult(Base, UUIDMixin, TimestampMixin):
    """How one printed test piece did."""

    __tablename__ = "print_test_results"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str] = mapped_column(String(8), nullable=False)
    model_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("models.id", ondelete="SET NULL"), nullable=True
    )
    model_file_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("model_file_versions.id", ondelete="SET NULL"), nullable=True
    )
    print_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("print_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    printer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("printers.id", ondelete="SET NULL"), nullable=True
    )
    material_type_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("material_types.id", ondelete="SET NULL"), nullable=True
    )
    filament_type_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("filament_types.id", ondelete="SET NULL"), nullable=True
    )
    orientation: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    measurements: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    failure_mode: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    photo_thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    photo_content_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    photo_original_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recorded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(f"kind IN ({_in(TEST_KINDS)})", name="ck_print_test_results_kind"),
        CheckConstraint(f"outcome IN ({_in(TEST_OUTCOMES)})", name="ck_print_test_results_outcome"),
        CheckConstraint(
            f"orientation IS NULL OR orientation IN ({_in(ORIENTATIONS)})",
            name="ck_print_test_results_orientation",
        ),
        Index("ix_print_test_results_model_created", "tenant_id", "model_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<PrintTestResult(kind={self.kind}, outcome={self.outcome})>"
