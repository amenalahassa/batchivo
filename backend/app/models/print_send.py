"""PrintSend: one prepared send of a sliced file to a Bambu printer (spec 011).

A send is prepared (summary shown, confirmation token issued), then confirmed
at most once (file transferred, print started, print job created). It keeps
what was confirmed — file, plate, slot mapping, warnings acknowledged, who and
when (FR-018) — and, once the print ends, the spool deduction proposal the
operator accepts or dismisses (FR-020).

The summary is a snapshot written once (Constitution VI): it records what the
operator saw, it is not recomputed.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.print_job import PrintJob
    from app.models.printer import Printer
    from app.models.user import User


def _json() -> JSON:
    """``JSONB`` on PostgreSQL, portable ``JSON`` on SQLite (the test suite)."""
    return JSON().with_variant(JSONB(), "postgresql")


class PrintSendStatus(str, Enum):
    """Lifecycle of a send (data-model.md, send states)."""

    PREPARED = "prepared"
    CONFIRMING = "confirming"
    STARTED = "started"
    TRANSFER_FAILED = "transfer_failed"
    START_FAILED = "start_failed"


class ConsumptionStatus(str, Enum):
    """State of the spool deduction proposal of a finished print."""

    NONE = "none"
    PENDING = "pending"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


class PrintSend(Base, UUIDMixin, TimestampMixin):
    """A prepared (and possibly confirmed) print send to a Bambu LAN printer."""

    __tablename__ = "print_sends"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )
    printer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("printers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prepared_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    model_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("models.id", ondelete="SET NULL"), nullable=True
    )
    model_file_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("model_files.id", ondelete="SET NULL"), nullable=True
    )
    upload_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Storage URL of an uploaded file not attached to a model; cleared once deleted",
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_md5: Mapped[str] = mapped_column(String(32), nullable=False)
    remote_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    plate_index: Mapped[int] = mapped_column(Integer, nullable=False)
    ams_mapping: Mapped[list[dict[str, Any]]] = mapped_column(_json(), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(
        _json(), nullable=False, comment="Snapshot of the summary shown at prepare"
    )
    warning_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, comment="SHA-256 of the confirmation token"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PrintSendStatus.PREPARED.value, index=True
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    confirmed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    warnings_acknowledged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    print_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("print_jobs.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    printer_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment="First printer report showing this send's file running",
    )
    consumption_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ConsumptionStatus.NONE.value,
        server_default=ConsumptionStatus.NONE.value,
    )
    consumption_lines: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        _json(), nullable=True
    )
    consumption_decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    consumption_decided_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    printer: Mapped["Printer"] = relationship("Printer", lazy="selectin")
    print_job: Mapped[Optional["PrintJob"]] = relationship(
        "PrintJob", lazy="selectin", foreign_keys=[print_job_id]
    )
    confirmed_by: Mapped[Optional["User"]] = relationship(
        "User", lazy="selectin", foreign_keys=[confirmed_by_user_id], viewonly=True
    )

    __table_args__ = (
        CheckConstraint("plate_index >= 1", name="ck_print_sends_plate_index"),
        CheckConstraint(
            "status IN ('prepared','confirming','started','transfer_failed','start_failed')",
            name="ck_print_sends_status",
        ),
        CheckConstraint(
            "consumption_status IN ('none','pending','accepted','dismissed')",
            name="ck_print_sends_consumption_status",
        ),
        Index("ix_print_sends_tenant_printer_created", "tenant_id", "printer_id", "created_at"),
        Index("ix_print_sends_printer_status", "printer_id", "status"),
        {"comment": "Print sends to Bambu printers: prepare, confirmation, outcome (spec 011)"},
    )

    def is_expired(self, now: datetime) -> bool:
        """Whether the confirmation window has passed at ``now``."""
        expires = self.expires_at
        if expires.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        return now >= expires

    def __repr__(self) -> str:
        return f"<PrintSend(id={self.id}, printer_id={self.printer_id}, status={self.status})>"
