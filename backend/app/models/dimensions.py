"""Outer dimensions of a model, product or size variant (packaging advisor, FR-001).

Three tables carry the same six columns, so they are declared once here. The
dimensions are not a cost input: their source (``entered`` by the operator or
``measured`` from a model file) is their own vocabulary, separate from the
pricing provenance of cost inputs (research D1).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

DIMENSION_SOURCES = ("entered", "measured")


class DimensionsMixin:
    """Length, width and height in mm, with where they came from and when."""

    length_mm: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 1), nullable=True, comment="Outer length in mm"
    )
    width_mm: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 1), nullable=True, comment="Outer width in mm"
    )
    height_mm: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 1), nullable=True, comment="Outer height in mm"
    )
    dimensions_source: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="Where the dimensions came from: 'entered' or 'measured'",
    )
    dimensions_set_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When the dimensions were set"
    )

    @declared_attr
    def dimensions_source_file_id(cls) -> Mapped[Optional[uuid.UUID]]:
        # use_alter: model_files already references models, so this closes a cycle.
        return mapped_column(
            ForeignKey(
                "model_files.id",
                ondelete="SET NULL",
                use_alter=True,
                name=f"fk_{cls.__tablename__}_dims_source_file",
            ),
            nullable=True,
            comment="Model file the dimensions were measured from",
        )


def dimension_constraints(table: str) -> tuple[CheckConstraint, CheckConstraint]:
    """All three dimensions or none, each positive, and a source exactly when set."""
    return (
        CheckConstraint(
            "(length_mm IS NULL AND width_mm IS NULL AND height_mm IS NULL) OR "
            "(length_mm IS NOT NULL AND width_mm IS NOT NULL AND height_mm IS NOT NULL "
            "AND length_mm > 0 AND width_mm > 0 AND height_mm > 0)",
            name=f"ck_{table}_dims_all_or_none",
        ),
        CheckConstraint(
            "(length_mm IS NULL AND dimensions_source IS NULL) OR "
            "(length_mm IS NOT NULL AND dimensions_source IN ('entered', 'measured'))",
            name=f"ck_{table}_dims_source",
        ),
    )
