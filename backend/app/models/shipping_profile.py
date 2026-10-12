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
        {"comment": "Postage paid per zone and weight bracket (FR-024)"},
    )

    def covers(self, grams: Decimal) -> bool:
        """Whether a parcel of ``grams`` falls in this bracket.

        Inclusive below, exclusive above, so adjacent brackets published as
        0-250 and 250-500 do not both claim a 250 g parcel.
        """
        if grams < self.weight_bracket_min_grams:
            return False
        if self.weight_bracket_max_grams is None:
            return True
        return grams < self.weight_bracket_max_grams

    def __repr__(self) -> str:
        return (
            f"<ShippingProfile(name={self.name}, zone={self.destination_zone}, "
            f"postage_cost={self.postage_cost})>"
        )
