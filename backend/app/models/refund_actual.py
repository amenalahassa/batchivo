"""A refund as it was actually paid back, against the order it came from (task T189).

Nothing recorded this. `_handle_refund_created` in
:mod:`app.services.square_webhook_service` set ``order.status = REFUNDED`` and
wrote the amount only into a payment log; :mod:`app.models.order` had no refund
column at all; and ``ReturnRequest.refund_amount`` is an RMA record the pricing
engine never opened. So :mod:`app.services.realised_margin`, whose own
docstring names its revenue source as "the order's own recorded amounts", read
the full un-reduced total -- and a fully refunded order still reported the
margin it earned at sale.

That made SC-001 ("within 2 percentage points of the margin computed from what
was actually received") false by the whole refund, for a routine case. Of
FR-040's and FR-041's actuals -- material used, production time, fees charged,
refunds -- this was the one never built, and the spec names it directly: a
refund is "recorded against the settled order as an actual, reducing realised
margin without rewriting the snapshot".

## Why a row of its own, rather than a column on the order

Three reasons, all of them the Constitution's.

**History is immutable (VI).** The snapshot says what the sale was priced on
and must not move. A refund is a later event with its own date, and reducing
`Order.total` in place would restate the sale itself -- the margin would change
*and* the evidence that it changed would be gone.

**An order can be refunded more than once.** A partial refund, then another.
One column holds the latest, or a running sum nobody can decompose; rows hold
each event with what it was for.

**It is an actual, so it carries its own origin.** ``source`` mirrors
``FeeActual``: ``entered`` is a human recording a refund they issued,
``ingested`` is the Square webhook writing what the provider reported. The day
one is automated the other must not be relabelled with it (FR-041e). This table
is deliberately outside the provenance registry for the same reason
``FeeActual`` is: the registry records where an *estimate's* inputs came from,
and a recorded actual is not an estimate.

## What it does not do

It does not reprice anything and it writes nothing derived. The realised margin
reads these rows and subtracts them from revenue on demand (Constitution V);
the planned margin never sees them, because a refund that happened is not a
refund that was expected. ``expected_refund_pct`` in
:mod:`app.services.channel_economics` is the planned side (FR-026) and is a
different figure answering a different question.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.user import User


#: How a recorded refund reached the system, mirroring `FEE_ACTUAL_SOURCES`.
#: ``entered`` is a human recording a refund they issued; ``ingested`` is a
#: provider webhook reporting one (FR-041e).
REFUND_ACTUAL_SOURCES: tuple[str, ...] = ("entered", "ingested")


class RefundActual(Base, UUIDMixin, TimestampMixin):
    """One refund actually paid back on one order."""

    __tablename__ = "refund_actuals"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="The settled order this refund reduces (FR-040)",
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="What was returned to the customer, in the order's currency",
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="GBP",
        server_default="GBP",
        comment="Matches the order's currency; a refund is paid in what was charged",
    )

    refunded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When the money went back, which is not when the sale was made",
    )

    source: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default="entered",
        server_default="entered",
        comment="'entered' by a human or 'ingested' from a provider webhook (FR-041e)",
    )

    provider_refund_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="The provider's own id, so one webhook delivered twice records once",
    )

    reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Why it was refunded, as recorded",
    )

    recorded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Who recorded it; NULL for an ingested row",
    )

    order: Mapped["Order"] = relationship("Order", lazy="select")
    recorded_by: Mapped[Optional["User"]] = relationship("User", lazy="select")

    __table_args__ = (
        Index("ix_refund_actuals_order", "tenant_id", "order_id"),
        # One row per provider refund, so a webhook redelivery -- which Square
        # does on any non-2xx -- cannot double the amount subtracted from
        # revenue. Partial, scoped to the tenant, and only where there is an
        # id: a human-entered refund has none and two of them on one order are
        # legitimate.
        Index(
            "uq_refund_actuals_provider_refund",
            "tenant_id",
            "provider_refund_id",
            unique=True,
            postgresql_where=text("provider_refund_id IS NOT NULL"),
        ),
        CheckConstraint("amount > 0", name="check_refund_actual_amount_positive"),
        CheckConstraint(
            "source IN ('entered', 'ingested')",
            name="check_refund_actual_source",
        ),
        {"comment": "Refunds as they were actually paid back, per order (FR-040, SC-001)"},
    )

    def __repr__(self) -> str:
        return f"<RefundActual(order={self.order_id}, amount={self.amount}, source={self.source})>"
