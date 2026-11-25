"""The parcels an order was actually sent in (packaging advisor, research D10).

Recorded when the operator confirms dispatch: which containers, how many,
the packed weight and outer size postage was priced from. A deliberate,
immutable record -- like a ``PriceSnapshot`` -- of what was done, so a later
change to a box's weight or a profile's price does not move a settled order's
postage (FR-031). Never recomputed; a mistake is corrected by the operator
entering postage, not by editing these rows.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.consumable import ConsumableType


class OrderParcel(Base, UUIDMixin, TimestampMixin):
    """One parcel of a dispatched order: its packed weight and outer size."""

    __tablename__ = "order_parcels"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="1, 2, … within the order"
    )
    outer_length_mm: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 1), nullable=True)
    outer_width_mm: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 1), nullable=True)
    outer_height_mm: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 1), nullable=True)
    packed_weight_grams: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 1), nullable=True, comment="NULL when a weight it needed was unknown"
    )
    confirmed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    items: Mapped[list["OrderParcelItem"]] = relationship(
        "OrderParcelItem",
        back_populates="parcel",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="OrderParcelItem.created_at",
    )

    __table_args__ = (
        UniqueConstraint("order_id", "sequence", name="uq_order_parcels_order_sequence"),
        CheckConstraint("sequence > 0", name="ck_order_parcels_sequence_positive"),
        {"comment": "Parcels confirmed at dispatch (packaging advisor, FR-028)"},
    )


class OrderParcelItem(Base, UUIDMixin, TimestampMixin):
    """A packing consumable in a parcel: the box, mailer, fill or wrap and how many."""

    __tablename__ = "order_parcel_items"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_parcel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("order_parcels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    consumable_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("consumable_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    parcel: Mapped[OrderParcel] = relationship("OrderParcel", back_populates="items")
    consumable_type: Mapped["ConsumableType"] = relationship("ConsumableType", lazy="selectin")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_parcel_items_quantity_positive"),
    )
