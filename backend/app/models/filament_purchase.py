"""A buying event covering one or more spools (FR-008a).

Landed cost cannot be derived from a spool alone: inbound shipping arrives once
for the whole purchase and has to be allocated across it, by weight, because
weight is what drove the postage (FR-008b). Recording only the spool leaves the
operator typing a per-gram figure they worked out by hand, which is exactly the
kind of number nobody can explain six months later (FR-008f).

A spool with no parent purchase stays valid and costs from its own price with
no allocated shipping (FR-008e), so this table is additive: nothing that works
today stops working because this exists.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.spool import Spool
    from app.models.tenant import Tenant


class FilamentPurchase(Base, UUIDMixin, TimestampMixin):
    """One filament purchase, from which its spools' landed costs are derived."""

    __tablename__ = "filament_purchases"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )

    supplier: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Supplier or vendor name",
    )

    purchase_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="When the purchase was made; the as-of date of its landed costs",
    )

    inbound_shipping_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
        server_default="0",
        comment="Total inbound shipping for the purchase, allocated across its spools by weight",
    )

    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
        server_default="0",
        comment="Sales tax on the purchase; enters cost only when it is not recoverable",
    )

    tax_recoverable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment=(
            "Whether this tax is recoverable. Recoverable tax is excluded from "
            "landed cost, non-recoverable tax is included (FR-008c)"
        ),
    )

    order_reference: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Supplier order number, for reconciling against the invoice",
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", lazy="select")

    spools: Mapped[list["Spool"]] = relationship(
        "Spool",
        back_populates="filament_purchase",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "inbound_shipping_cost >= 0",
            name="check_filament_purchase_shipping_non_negative",
        ),
        CheckConstraint("tax_amount >= 0", name="check_filament_purchase_tax_non_negative"),
        {"comment": "Filament purchases, from which per-spool landed costs are derived (FR-008a)"},
    )

    def __repr__(self) -> str:
        return (
            f"<FilamentPurchase(supplier={self.supplier}, "
            f"purchase_date={self.purchase_date}, shipping={self.inbound_shipping_cost})>"
        )
