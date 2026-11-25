"""Fit calibrations per printer, material, orientation and fit type (spec 009, US3).

A calibration is the clearance per side that works for one combination, how it
was obtained (measured, or assumed until measured), from which print and when.
It is never edited: a new value for the same combination supersedes the current
one, which keeps its value and gains a ``superseded_by_id`` link (principle VI).
A database trigger refuses any other UPDATE (research R6), and a partial unique
index keeps at most one current value per combination.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    DDL,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    event,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

#: Preflight's calibrable fit types (`pf.py` ENUMS["fit"] minus screw/insert/none).
FIT_TYPES = ("slide", "press", "snap", "print-in-place")
ORIENTATIONS = ("vertical", "horizontal")
CALIBRATION_PROVENANCES = ("measured", "assumed")
#: Stands for "no filament" in the current-value index, so NULLs compare equal.
NIL_UUID = "00000000-0000-0000-0000-000000000000"


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class Calibration(Base, UUIDMixin, TimestampMixin):
    """One recorded fit value; immutable except for being superseded once."""

    __tablename__ = "calibrations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    printer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("printers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    material_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("material_types.id", ondelete="RESTRICT"), nullable=False
    )
    filament_type_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("filament_types.id", ondelete="CASCADE"), nullable=True
    )
    orientation: Mapped[str] = mapped_column(String(12), nullable=False)
    fit_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value_mm: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    provenance: Mapped[str] = mapped_column(String(10), nullable=False)
    source_print_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("print_jobs.id", ondelete="SET NULL"), nullable=True
    )
    source_test_result_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("print_test_results.id", ondelete="SET NULL"), nullable=True
    )
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recorded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # No ON DELETE action: a whole chain shares its printer (and filament), so a
    # cascade removes it in one statement; SET NULL would be an UPDATE the trigger refuses.
    superseded_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("calibrations.id"), nullable=True
    )
    superseded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            f"orientation IN ({_in(ORIENTATIONS)})", name="ck_calibrations_orientation"
        ),
        CheckConstraint(f"fit_type IN ({_in(FIT_TYPES)})", name="ck_calibrations_fit_type"),
        CheckConstraint(
            f"provenance IN ({_in(CALIBRATION_PROVENANCES)})", name="ck_calibrations_provenance"
        ),
        CheckConstraint("value_mm >= 0 AND value_mm <= 2", name="ck_calibrations_value_range"),
        Index(
            "uq_calibrations_current",
            "tenant_id",
            "printer_id",
            "material_type_id",
            func.coalesce(text("filament_type_id"), text(f"'{NIL_UUID}'")),
            "orientation",
            "fit_type",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
            sqlite_where=text("superseded_at IS NULL"),
        ),
        Index("ix_calibrations_printer_created", "printer_id", "created_at"),
    )

    @property
    def is_current(self) -> bool:
        return self.superseded_by_id is None

    def __repr__(self) -> str:
        return (
            f"<Calibration(printer={self.printer_id}, fit={self.fit_type}, "
            f"orientation={self.orientation}, value_mm={self.value_mm})>"
        )


#: Lets only the supersede link go from NULL to a value; refuses every other change.
CALIBRATION_TRIGGER_SQL = (
    # Allowed: superseding a current value once, and ON DELETE SET NULL clearing a
    # reference (recorder, source print job, source test result) of a deleted row.
    "CREATE OR REPLACE FUNCTION calibrations_immutable() RETURNS trigger AS $$ "
    "DECLARE refs text[] := ARRAY['recorded_by_user_id', 'source_print_job_id', "
    "'source_test_result_id']; "
    "BEGIN "
    "IF (to_jsonb(NEW) - refs) = (to_jsonb(OLD) - refs) "
    "AND (NEW.recorded_by_user_id IS NULL OR NEW.recorded_by_user_id = OLD.recorded_by_user_id) "
    "AND (NEW.source_print_job_id IS NULL OR NEW.source_print_job_id = OLD.source_print_job_id) "
    "AND (NEW.source_test_result_id IS NULL "
    "OR NEW.source_test_result_id = OLD.source_test_result_id) "
    "THEN RETURN NEW; END IF; "
    "IF OLD.superseded_by_id IS NOT NULL "
    "OR (to_jsonb(NEW) - 'superseded_by_id' - 'superseded_at' - 'updated_at') "
    "<> (to_jsonb(OLD) - 'superseded_by_id' - 'superseded_at' - 'updated_at') "
    "THEN RAISE EXCEPTION 'calibrations are immutable: record a new value instead'; "
    "END IF; RETURN NEW; END; $$ LANGUAGE plpgsql",
    "CREATE TRIGGER trg_calibrations_immutable BEFORE UPDATE ON calibrations "
    "FOR EACH ROW EXECUTE FUNCTION calibrations_immutable()",
)

for _statement in CALIBRATION_TRIGGER_SQL:
    event.listen(
        Calibration.__table__,
        "after_create",
        DDL(_statement).execute_if(dialect="postgresql"),
    )
