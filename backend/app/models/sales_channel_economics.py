"""A channel's planning economics, one row per effective period (task T136).

Four figures used to sit as plain mutable columns on ``sales_channels``:
``expected_discount_pct``, ``expected_refund_pct``, ``free_shipping_threshold``
and ``rounding_rule``. Every one of them is an operator decision in the sense
of FR-002 -- a reserve they choose to hold, a threshold they set -- and FR-003
requires a decision to be effective-dated: superseded, never updated in place.

## What went wrong while they were columns

An operator who raised their refund reserve from 2% to 5% changed what every
*past* plan said it had reserved. The figures a quote had been built on moved
under it, so the margin a product was shown as having last month became the
margin it would have had under today's reserve -- which is the restatement
FR-038 forbids on a settled line and FR-003 forbids on a planning figure.
Nothing was wrong with the arithmetic; the inputs had no date.

## One row per period, one open row per channel

``effective_to IS NULL`` marks the row in force, and a partial unique index
says so in the schema rather than leaving it to whoever writes the next update
path -- the same device ``tenant_pricing_policy`` uses. A write closes the
current row the day before the new one opens, so the periods do not overlap,
and :func:`app.services.channel_economics.resolve_economics_row` reads the row
that was in force on a given date.

## The legacy columns are a fallback, not a second authority

``sales_channels`` keeps the four columns, because the pure costing functions
take a channel object and no session: a unit test or a scenario sweep can hand
them a plain stand-in. They are read in exactly one place --
:func:`app.services.channel_economics.channel_defaults` -- and only when a
channel has no economics row at all. The migration backfills a row for every
existing channel and the create path writes one, so in a live database the
fallback is unreachable (Constitution III).
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
    from app.models.sales_channel import SalesChannel


#: The figures this table carries. Named once so the resolver, the write path
#: and the response all agree on what "the channel's economics" means.
ECONOMICS_FIELDS: tuple[str, ...] = (
    "expected_discount_pct",
    "expected_refund_pct",
    "free_shipping_threshold",
    "rounding_rule",
)


class SalesChannelEconomics(Base, UUIDMixin, TimestampMixin):
    """What one channel's planning figures were, over one period."""

    __tablename__ = "sales_channel_economics"

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
        comment="The channel these figures belong to",
    )

    expected_discount_pct: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Expected discount share, which reduces planned net revenue (FR-026)",
    )

    expected_refund_pct: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Expected refund share, held as a reserve against planned revenue (FR-026)",
    )

    free_shipping_threshold: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Order value at which shipping is free; the solver may snap to it (FR-033)",
    )

    rounding_rule: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="How a solved price is rounded on this channel, e.g. 'psychological_99' (FR-033)",
    )

    effective_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="First day these figures applied",
    )

    effective_to: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        comment="Last day they applied; NULL means this is the current period",
    )

    set_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Who set these figures, for the provenance a cost screen shows (FR-012)",
    )

    set_by_role: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="The role they held when they set it (FR-007a)",
    )

    sales_channel: Mapped["SalesChannel"] = relationship(
        "SalesChannel",
        back_populates="economics",
        lazy="select",
    )

    __table_args__ = (
        # Exactly one current period per channel.
        Index(
            "uq_channel_economics_current",
            "sales_channel_id",
            unique=True,
            postgresql_where=effective_to.is_(None),
            sqlite_where=effective_to.is_(None),
        ),
        # The read the resolver does: this channel's periods, newest first.
        Index(
            "idx_channel_economics_channel_from",
            "sales_channel_id",
            "effective_from",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_channel_economics_effective_range",
        ),
        CheckConstraint(
            "expected_discount_pct >= 0 AND expected_discount_pct <= 100",
            name="ck_channel_economics_discount_is_a_percentage",
        ),
        CheckConstraint(
            "expected_refund_pct >= 0 AND expected_refund_pct <= 100",
            name="ck_channel_economics_refund_is_a_percentage",
        ),
        CheckConstraint(
            "free_shipping_threshold IS NULL OR free_shipping_threshold >= 0",
            name="ck_channel_economics_threshold_is_not_negative",
        ),
        {
            "comment": (
                "A channel's planning economics, one row per effective period "
                "(FR-003). Superseded, never updated in place"
            )
        },
    )

    @property
    def is_current(self) -> bool:
        return self.effective_to is None

    def __repr__(self) -> str:
        return (
            f"<SalesChannelEconomics(channel={self.sales_channel_id}, "
            f"from={self.effective_from}, to={self.effective_to})>"
        )
