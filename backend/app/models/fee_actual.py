"""A fee as the statement actually charged it (task T066).

Planned fees are what the rules predict; these are what arrived. FR-041 wants
the difference reportable, which needs both figures kept apart -- overwriting
the plan with the actual would destroy the only evidence that the rules are
wrong.

Two granularities, and exactly one per row (FR-041a, FR-041b):

* a **period total** per fee category per channel, which is the routine path
  while reconciliation is a human reading a monthly statement, and
* an **order-scoped** amount, for when one order looks anomalous.

An order-scoped row may name the **statement period** its charge appeared in.
The spec's edge case is an order placed on the 31st and settled on next
month's statement: that charge belongs to next month's reconciliation, not to
the month the order was placed in (task T235). A row that names no statement
period falls back to the period containing the order's placed date, which is
how every row recorded before the column existed is read.

Where both exist for a category and period, the order-scoped rows take
precedence and reduce the period's unallocated remainder (FR-041c), so no
amount is counted twice. That arithmetic lives in
:mod:`app.services.channel_pnl`; this table only guarantees that a row is one
or the other and never both.

``source`` is always ``entered`` for now, and FR-041e is the reason it is a
column rather than an assumption: the day a statement is ingested
automatically, those rows become ``observed`` and the ones a human typed must
not be relabelled with them.

That column is also why this table is deliberately outside the provenance
registry in :mod:`app.services.provenance`. The registry records where an
*estimate's* inputs came from; a recorded actual is not an estimate, it carries
its own origin here, and registering it would offer ``observed`` as a value for
a figure a human typed.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.sales_channel import SalesChannel
    from app.models.user import User


#: How a recorded actual reached the system. ``entered`` is a human reading a
#: statement; ``ingested`` is reserved for an automated feed (FR-041e).
FEE_ACTUAL_SOURCES: tuple[str, ...] = ("entered", "ingested")


class FeeActual(Base, UUIDMixin, TimestampMixin):
    """One recorded fee amount, scoped to a period or to a single order."""

    __tablename__ = "fee_actuals"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )

    sales_channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sales_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="The channel that charged this fee",
    )

    fee_category: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        comment="Matches a FeeRule.name, so plan and actual are comparable",
    )

    period_start: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        comment="First day of the statement period; NULL on an order-scoped row",
    )

    period_end: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        comment="Last day of the statement period; NULL on an order-scoped row",
    )

    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="The one order this amount belongs to; NULL on a period row",
    )

    statement_period_start: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        comment=(
            "On an order-scoped row: the first day of the statement period the "
            "statement put this charge in, which need not contain the day the "
            "order was placed (FR-041c, task T235). NULL on a period row"
        ),
    )

    statement_period_end: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        comment="On an order-scoped row: the last day of that statement period",
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="The amount charged, as the statement shows it",
    )

    source: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default="entered",
        server_default="entered",
        comment="'entered' by a human or 'ingested' from a feed (FR-041e)",
    )

    recorded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Who recorded it; NULL for an ingested row",
    )

    sales_channel: Mapped["SalesChannel"] = relationship("SalesChannel", lazy="select")
    order: Mapped[Optional["Order"]] = relationship("Order", lazy="select")
    recorded_by: Mapped[Optional["User"]] = relationship("User", lazy="select")

    __table_args__ = (
        Index(
            "ix_fee_actuals_channel_period",
            "sales_channel_id",
            "fee_category",
            "period_start",
        ),
        # Exactly one scope. Written as a pair of mutually exclusive shapes
        # rather than as two separate checks, because a row with a period *and*
        # an order would be double-counted by any reconciliation that read it.
        CheckConstraint(
            "("
            " order_id IS NULL"
            " AND period_start IS NOT NULL"
            " AND period_end IS NOT NULL"
            ") OR ("
            " order_id IS NOT NULL"
            " AND period_start IS NULL"
            " AND period_end IS NULL"
            ")",
            name="check_fee_actual_exactly_one_scope",
        ),
        CheckConstraint(
            "period_end IS NULL OR period_start IS NULL OR period_end >= period_start",
            name="check_fee_actual_period_range",
        ),
        # A statement period belongs only on an order-scoped row, and whole.
        # It says which statement reconciles the order's charge; it is not a
        # second scope, so the row is still counted once.
        CheckConstraint(
            "("
            " statement_period_start IS NULL AND statement_period_end IS NULL"
            ") OR ("
            " order_id IS NOT NULL"
            " AND statement_period_start IS NOT NULL"
            " AND statement_period_end IS NOT NULL"
            " AND statement_period_end >= statement_period_start"
            ")",
            name="check_fee_actual_statement_period",
        ),
        CheckConstraint(
            "source IN ('entered', 'ingested')",
            name="check_fee_actual_source",
        ),
        {"comment": "Fees as a statement charged them, per period or per order (FR-041)"},
    )

    @property
    def is_order_scoped(self) -> bool:
        return self.order_id is not None

    def __repr__(self) -> str:
        scope = f"order={self.order_id}" if self.is_order_scoped else f"period={self.period_start}"
        return f"<FeeActual(category={self.fee_category}, amount={self.amount}, {scope})>"
