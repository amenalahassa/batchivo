"""Exchange rates — the one table in this feature that is **not** tenant-scoped.

## The deliberate RLS exception

Constitution principle I requires every table to carry `tenant_id` under a
row-level security policy, and this table does not. That is a decision, not an
oversight, and it is recorded here so a future reader does not "fix" it.

A published exchange rate is not tenant data. CAD/GBP on 12 October 2026 is the
same number for every operator in the system; it was not derived from anyone's
business, it reveals nothing about anyone's business, and nobody owns it. Giving
it a `tenant_id` would mean:

- the same rate stored once per tenant, so two tenants pricing the same day
  could disagree about what the day's rate was;
- a rate service called once per tenant rather than once per day, which FR-028f
  explicitly forbids ("reused for further sales on the same day rather than
  re-requested per order");
- no way to express "the most recent known rate" (FR-028g) across the system,
  only per tenant, so a tenant who joined yesterday would have no fallback.

So the table is shared and read-only to tenants in practice. What *is* tenant
data is the rate frozen onto an order line (`order_items.fx_rate`), which lives
on a tenant-scoped table under RLS like everything else.

The one case that looks like tenant data is a manually entered rate (FR-028h).
It is recorded with `source = 'manual'` and it is still not scoped: an operator
entering a rate by hand is asserting what the rate *was*, which is either right
or wrong for everybody. The `source` column keeps the two apart so a fetched
rate is never silently replaced by a hand-entered one, and the uniqueness key
includes `source` so both can be held for the same day and the resolution order
is explicit rather than a race.

## Immutability

A rate row is never updated. A corrected rate for a past day is a new row, and
a rate already frozen onto an order is not revised by either (FR-028j) — the
difference is reported as a variance, not corrected, exactly as FR-037 treats
every other recorded figure.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

#: Where a rate came from. A hand-entered rate overrides a fetched one for the
#: same day (FR-028h), which is why the two are distinguishable rather than
#: merged into one column.
FX_RATE_SOURCES = ("service", "manual")


class FxRate(Base, UUIDMixin, TimestampMixin):
    """One currency pair's rate on one day, from one source."""

    __tablename__ = "fx_rates"

    base_currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        comment="ISO 4217 code the rate is quoted FROM",
    )

    quote_currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        comment="ISO 4217 code the rate is quoted TO",
    )

    rate_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="The day this rate applies to, in the rate service's own terms",
    )

    rate: Mapped[Decimal] = mapped_column(
        Numeric(14, 8),
        nullable=False,
        comment=(
            "Units of quote_currency per one unit of base_currency. Eight "
            "decimal places because a thinly traded pair's rate is small and "
            "rounding it at four would move a price (Constitution IV)"
        ),
    )

    source: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="service",
        comment="'service' for a fetched rate, 'manual' for one entered by hand (FR-028h)",
    )

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment=(
            "When this rate was obtained. Distinct from rate_date: a stale "
            "rate is one whose rate_date is old, and FR-028g requires the "
            "figure on screen to show which day it came from"
        ),
    )

    __table_args__ = (
        # `source` is part of the key so a fetched rate and a hand-entered one
        # can coexist for the same day. Resolution prefers the manual row
        # (FR-028h); holding only one would make the override destructive.
        UniqueConstraint(
            "base_currency",
            "quote_currency",
            "rate_date",
            "source",
            name="uq_fx_rate_pair_date_source",
        ),
        # The lookup every read does: the most recent known rate for a pair at
        # or before a date (FR-028g).
        Index("ix_fx_rates_pair_date", "base_currency", "quote_currency", "rate_date"),
        CheckConstraint("rate > 0", name="ck_fx_rate_positive"),
        CheckConstraint(
            "source IN ('service', 'manual')",
            name="ck_fx_rate_source",
        ),
        CheckConstraint(
            "base_currency <> quote_currency",
            name="ck_fx_rate_pair_distinct",
        ),
        {
            "comment": (
                "Published exchange rates. Deliberately NOT tenant-scoped: a "
                "published rate is not tenant data. See the module docstring"
            )
        },
    )

    def __repr__(self) -> str:
        return (
            f"<FxRate({self.base_currency}/{self.quote_currency} "
            f"{self.rate_date} {self.rate} {self.source})>"
        )
