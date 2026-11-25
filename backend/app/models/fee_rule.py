"""One marketplace fee, as an ordered, dated rule (task T065).

A channel's economics are not one percentage plus one fixed amount. A real
marketplace charges a transaction fee on the item plus the shipping it
collected, a payment processor charges its own percentage plus a fixed amount
on the whole order, a regulatory operating fee lands on the item alone, a
listing fee is charged per listing whether or not anything sold, and some of
those are capped. ``SalesChannel.fee_percentage`` and ``fee_fixed`` could
express one of those five, which is why every margin this system reported was
wrong by the other four.

Three things this table deliberately refuses to express:

* **A fee on a fee.** Every basis is derived from amounts on the order, never
  from another rule's output (research.md D9). Fee-on-fee is the most common
  way a marketplace fee model is got wrong, and making it inexpressible is
  cheaper than catching it in review.
* **An open-ended rule.** ``applies_from`` is not null, so every rule states
  when it started. A statement reconciled against a rule that has no date is
  reconciled against an assumption.
* **A clamp that cannot bind.** ``min_amount > max_amount`` is refused by a
  CHECK (FR-021d) rather than silently producing whichever the code happened
  to apply last.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.sales_channel import SalesChannel


#: What a rule is charged on (FR-021). Each is an amount taken from the order,
#: or a count of something on it -- never another fee.
#:
#: ``item_subtotal``     the item lines alone
#: ``item_plus_shipping``the item lines plus shipping revenue collected (FR-023)
#: ``order_total``       what the customer paid, item plus shipping plus extras
#: ``per_listing``       charged per listing, independent of what sold
#: ``per_order``         charged once per order
#: ``per_unit_sold``     charged per unit on the line (FR-021a)
#: ``per_month``         a periodic charge, absorbed by `channel_pnl` (FR-025)
FEE_BASES: tuple[str, ...] = (
    "item_subtotal",
    "item_plus_shipping",
    "order_total",
    "per_listing",
    "per_order",
    "per_unit_sold",
    "per_month",
)

#: Bases that are a count rather than an amount, so a percentage of them is
#: meaningless: a rule on one of these carries its charge in ``fixed_amount``.
COUNT_BASES: frozenset[str] = frozenset({"per_listing", "per_order", "per_unit_sold", "per_month"})

#: Bases absorbed over a period rather than charged on a sale (FR-025). They
#: never appear in a single order's fee stack.
PERIODIC_BASES: frozenset[str] = frozenset({"per_listing", "per_month"})


class FeeRule(Base, UUIDMixin, TimestampMixin):
    """One fee a channel charges, effective over a date range."""

    __tablename__ = "fee_rules"

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
        comment="The channel that charges this fee",
    )

    name: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        comment="Fee category, matched by a recorded actual (FR-041a)",
    )

    basis: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="What the fee is charged on; one of FEE_BASES (FR-021)",
    )

    rate_pct: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Percentage of the basis, as a percentage (6.5 means 6.5%)",
    )

    fixed_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Amount added once the rate has been applied",
    )

    min_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Floor on the computed amount: a 'percentage but at least X' fee (FR-021b)",
    )

    max_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Cap on the computed amount: a capped final-value fee (FR-021b)",
    )

    incidence_pct: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 4),
        nullable=True,
        comment=(
            "Share of orders this fee actually lands on, as a percentage. "
            "Scales a planning figure only, never a recorded actual (FR-029)"
        ),
    )

    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Evaluation and presentation order (research.md D9)",
    )

    applies_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="First day this rule was charged (FR-022)",
    )

    applies_to: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        comment="Last day this rule was charged; NULL means it still is",
    )

    sales_channel: Mapped["SalesChannel"] = relationship(
        "SalesChannel",
        back_populates="fee_rules",
        lazy="select",
    )

    __table_args__ = (
        Index("ix_fee_rules_channel_order", "sales_channel_id", "sort_order"),
        CheckConstraint(
            "basis IN ('item_subtotal', 'item_plus_shipping', 'order_total', "
            "'per_listing', 'per_order', 'per_unit_sold', 'per_month')",
            name="check_fee_rule_basis",
        ),
        # FR-021d. Both nullable, so the constraint only speaks when both are
        # present; a floor above a cap is a rule that can never be satisfied.
        CheckConstraint(
            "min_amount IS NULL OR max_amount IS NULL OR min_amount <= max_amount",
            name="check_fee_rule_clamp_order",
        ),
        CheckConstraint(
            "applies_to IS NULL OR applies_to >= applies_from",
            name="check_fee_rule_effective_range",
        ),
        CheckConstraint("rate_pct >= 0", name="check_fee_rule_rate_not_negative"),
        CheckConstraint(
            "incidence_pct IS NULL OR (incidence_pct >= 0 AND incidence_pct <= 100)",
            name="check_fee_rule_incidence_is_a_share",
        ),
        {"comment": "Ordered, dated marketplace fee rules per channel (FR-020, FR-021)"},
    )

    @property
    def is_periodic(self) -> bool:
        """Whether this rule is absorbed over a period rather than per sale."""
        return self.basis in PERIODIC_BASES

    def applies_on(self, as_of: date) -> bool:
        """Whether this rule was in force on ``as_of``."""
        if as_of < self.applies_from:
            return False
        return self.applies_to is None or as_of <= self.applies_to

    def __repr__(self) -> str:
        return f"<FeeRule(name={self.name}, basis={self.basis}, rate_pct={self.rate_pct})>"
