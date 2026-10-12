"""Where each numeric input to a cost came from (research.md D1).

One side table keyed on ``(tenant_id, entity_type, entity_id, field_name)``,
rather than an origin/date/confidence triple beside every numeric column. The
inputs are spread across seven tables and number around twenty-five; column
triples would have added roughly seventy-five columns and made each new input a
migration.

The accepted cost of that choice is stated plainly in research.md D1 and worth
repeating where someone will read it: **PostgreSQL cannot enforce a foreign key
on a field name.** The registry in ``app/services/provenance.py`` and its
coverage test are the enforcement. That is a test, not a constraint, so nobody
should later assume the database is guarding it.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


#: The four origins a figure can have (FR-001). They are ordered by how much
#: weight a reader should give them, which is also the order the UI shows.
#:
#: * ``policy``   -- an operator decision; never overwritten automatically
#: * ``observed`` -- a fact read from its source; read-only to the operator
#: * ``measured`` -- measured once by hand; editable, and goes stale
#: * ``assumed``  -- nobody has supplied it; the system's own guess
PROVENANCE_SOURCES = ("policy", "observed", "measured", "assumed")

#: Entity types the registry knows. Kept here as well as in the registry so the
#: database CHECK and the Python registry cannot drift apart silently; the
#: registry's coverage test asserts they agree.
PROVENANCE_ENTITY_TYPES = (
    "model",
    "model_material",
    "model_component",
    "model_printer_config",
    "product",
    "printer",
    "spool",
    "filament_purchase",
    "tenant_pricing_policy",
    "sales_channel",
)


class PricingInputProvenance(Base, UUIDMixin, TimestampMixin):
    """The recorded origin of one numeric field on one entity."""

    __tablename__ = "pricing_input_provenance"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )

    entity_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Which kind of record the field belongs to; see PROVENANCE_ENTITY_TYPES",
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
        comment=(
            "The record the field belongs to. Deliberately not a foreign key: "
            "one column cannot reference nine tables"
        ),
    )

    field_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="The numeric field, validated against the registry in services/provenance.py",
    )

    source: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="policy | observed | measured | assumed (FR-001)",
    )

    as_of: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="When the figure was set or last observed (FR-001)",
    )

    confidence: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 4),
        nullable=True,
        comment="Confidence in (0, 1] where confidence is meaningful; NULL where it is not",
    )

    measured_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Who measured or decided the figure, so a margin shift stays traceable",
    )

    authorised_by_role: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="The role that authorised a policy change (FR-007a)",
    )

    measured_by_user: Mapped[Optional["User"]] = relationship("User", lazy="select")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "entity_type",
            "entity_id",
            "field_name",
            name="uq_pricing_input_provenance_field",
        ),
        # "What is still assumed" is a question the operator asks often enough
        # to index for (research.md D1).
        Index("ix_pricing_input_provenance_source", "tenant_id", "source"),
        CheckConstraint(
            "source IN ('policy', 'observed', 'measured', 'assumed')",
            name="check_pricing_input_provenance_source",
        ),
        CheckConstraint(
            "entity_type IN ("
            "'model', 'model_material', 'model_component', 'model_printer_config', "
            "'product', 'printer', 'spool', 'filament_purchase', "
            "'tenant_pricing_policy', 'sales_channel'"
            ")",
            name="check_pricing_input_provenance_entity_type",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence > 0 AND confidence <= 1)",
            name="check_pricing_input_provenance_confidence",
        ),
        {"comment": "Origin, date and confidence of every numeric input to a cost (FR-001)"},
    )

    def __repr__(self) -> str:
        return (
            f"<PricingInputProvenance({self.entity_type}.{self.field_name}"
            f"={self.source} as of {self.as_of})>"
        )
