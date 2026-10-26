"""Postage the operator pays, by zone and weight bracket (task T067).

The distinction this table exists to keep is FR-024's: **postage paid is not
shipping revenue collected**. ``orders.shipping_cost`` is what the customer was
charged, and the system had nowhere to record what the label actually cost, so
free shipping looked free. Their difference is a margin line of its own, which
is often the largest negative line on a channel that advertises free shipping.

Packaging is deliberately absent. Boxes and mailers are consumed per sellable
unit and belong to the product (FR-016); putting them here would make a
product's cost depend on where it was shipped, and would double-count the day
an operator recorded both.

Brackets are half-open on the upper bound -- a bracket of 0-250 g and one of
250-500 g do not both claim a 250 g parcel -- which is enforced by the lookup
in :mod:`app.services.fee_engine` rather than by a constraint, because the
brackets a carrier publishes are the operator's to mirror, including gaps.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.services.dims import Dims, Parcel


class ShippingProfile(Base, UUIDMixin, TimestampMixin):
    """What one parcel in one weight bracket to one zone costs to post."""

    __tablename__ = "shipping_profiles"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Operator's name for the service, e.g. 'Canada Post Expedited'",
    )

    destination_zone: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Carrier zone the postage applies to, e.g. 'domestic', 'us', 'international'",
    )

    weight_bracket_min_grams: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Lowest parcel weight in this bracket, inclusive",
    )

    weight_bracket_max_grams: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Highest parcel weight, exclusive; NULL means the bracket is open-ended",
    )

    postage_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="What the operator pays to post one parcel in this bracket (FR-024)",
    )

    carrier: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Carrier name, for reconciliation against their invoice",
    )

    effective_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="First day this postage applied; carriers reprice annually",
    )

    effective_to: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        comment=(
            "Last day this postage applied; NULL while it still does. A repricing "
            "closes the row and opens a new one rather than editing it (FR-003, T233)"
        ),
    )

    # A size class (packaging advisor, research D9): a parcel whose sorted
    # outer dimensions exceed these is not covered. All three or none.
    max_length_mm: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 1), nullable=True, comment="Largest parcel length this service takes"
    )
    max_width_mm: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 1), nullable=True, comment="Largest parcel width this service takes"
    )
    max_height_mm: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 1), nullable=True, comment="Largest parcel height this service takes"
    )
    volumetric_divisor: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(8, 1),
        nullable=True,
        comment="Carrier's volumetric divisor (cm³ per kg, e.g. 5000); NULL charges actual weight",
    )

    __table_args__ = (
        Index(
            "ix_shipping_profiles_zone_bracket",
            "tenant_id",
            "destination_zone",
            "weight_bracket_min_grams",
        ),
        CheckConstraint(
            "weight_bracket_max_grams IS NULL"
            " OR weight_bracket_max_grams > weight_bracket_min_grams",
            name="check_shipping_profile_bracket_order",
        ),
        CheckConstraint(
            "weight_bracket_min_grams >= 0",
            name="check_shipping_profile_bracket_not_negative",
        ),
        CheckConstraint("postage_cost >= 0", name="check_shipping_profile_postage_not_negative"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="check_shipping_profile_effective_range",
        ),
        CheckConstraint(
            "(max_length_mm IS NULL AND max_width_mm IS NULL AND max_height_mm IS NULL)"
            " OR (max_length_mm IS NOT NULL AND max_width_mm IS NOT NULL"
            " AND max_height_mm IS NOT NULL"
            " AND max_length_mm > 0 AND max_width_mm > 0 AND max_height_mm > 0)",
            name="ck_shipping_profiles_size_limits",
        ),
        CheckConstraint(
            "volumetric_divisor IS NULL OR volumetric_divisor > 0",
            name="ck_shipping_profiles_volumetric_divisor",
        ),
        {"comment": "Postage paid per zone and weight bracket (FR-024)"},
    )

    def applies_on(self, on: date) -> bool:
        """Whether this postage was in force on ``on``."""
        if on < self.effective_from:
            return False
        return self.effective_to is None or on <= self.effective_to

    @property
    def size_limits(self) -> Optional[Dims]:
        """The largest parcel this service takes, or None for a weight-only profile."""
        return Dims.from_row(self, prefix="max_")

    def chargeable_grams(self, parcel: Parcel) -> Optional[Decimal]:
        """The weight the carrier charges: actual, or volumetric when that is more.

        Volumetric weight is L·W·H in cm³ divided by the divisor, in kg; it
        needs the outer size, so without one the actual weight stands.
        """
        if parcel.grams is None:
            return None
        if self.volumetric_divisor is None or parcel.outer is None:
            return parcel.grams
        cm3 = parcel.outer.volume_ml  # mm³ / 1000 = cm³
        volumetric = cm3 / Decimal(str(self.volumetric_divisor)) * Decimal("1000")
        return max(parcel.grams, volumetric)

    def covers(self, parcel: Parcel) -> bool:
        """Whether this service takes ``parcel``: its size class, then its weight bracket.

        A size-limited profile needs the parcel's outer size, compared axis by
        axis after sorting both, so a parcel's orientation does not matter. The
        bracket is inclusive below and exclusive above, so adjacent brackets
        published as 0-250 and 250-500 do not both claim a 250 g parcel.
        """
        limits = self.size_limits
        if limits is not None:
            if parcel.outer is None:
                return False
            if any(
                side > limit
                for side, limit in zip(
                    parcel.outer.sorted_desc().as_tuple(), limits.sorted_desc().as_tuple()
                )
            ):
                return False
        grams = self.chargeable_grams(parcel)
        if grams is None or grams < self.weight_bracket_min_grams:
            return False
        if self.weight_bracket_max_grams is None:
            return True
        return grams < self.weight_bracket_max_grams

    def __repr__(self) -> str:
        return (
            f"<ShippingProfile(name={self.name}, zone={self.destination_zone}, "
            f"postage_cost={self.postage_cost})>"
        )
