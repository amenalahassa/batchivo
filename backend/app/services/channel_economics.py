"""The one authority for a channel's planning economics (task T136).

Eight figures -- the expected discount share, the refund reserve, the
free-shipping threshold, the rounding rule and, since task T216, the monthly
subscription, the tax remitter, the offsite-ads opt-in and the selling
currency -- are operator decisions about how a channel is planned against. FR-003 requires a decision to be
effective-dated, so they live in ``sales_channel_economics``, one row per
period, and this module is the only thing that reads them.

## What this module exists to prevent

While the four were plain columns, raising a refund reserve changed what every
past plan said it had reserved: the figures a quote had been built on moved
under it. The fix is not arithmetic, it is a date. ``resolve_channel_economics``
takes an ``as_of`` and returns what was in force then, so a quote from last
month still explains itself.

## Why the costing functions take a frozen value

:func:`app.services.costing.CostingService.margin` and
:func:`app.services.pricing_solver.solve` are synchronous and take no session.
They accept a :class:`ChannelEconomics` -- already resolved -- rather than
resolving one themselves, which keeps the engine a pure function of its inputs
and keeps the as-of decision with the caller that knows which date applies: the
sale date for a settled line, today for a quote.

When no value is passed they fall back to :func:`channel_defaults`, which reads
the legacy columns on the channel object. That is the one place those columns
are read, and in a live database it is unreachable: the migration backfilled a
row for every channel and the create path writes one. It exists so a unit test
or a scenario sweep can hand the engine a plain stand-in.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models.sales_channel_economics import ECONOMICS_FIELDS, SalesChannelEconomics

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.sales_channel import SalesChannel
    from app.models.tenant import Tenant
    from app.models.user import User

logger = logging.getLogger(__name__)

ZERO = Decimal("0")


class EconomicsMisconfigured(ValueError):
    """A figure that could not be used once stored."""


@dataclass(frozen=True)
class ChannelEconomics:
    """A channel's planning figures, as they stood on one date.

    Frozen because it is an input the engine was given, not a mutable handle on
    a row: a cost computed from it must stay explainable by it.
    """

    expected_discount_pct: Decimal = ZERO
    expected_refund_pct: Decimal = ZERO
    free_shipping_threshold: Optional[Decimal] = None
    rounding_rule: Optional[str] = None

    #: The subscription or booth fee, absorbed over a period's orders (FR-025).
    monthly_cost: Decimal = ZERO
    #: Who remits the sales tax; a liability only where the operator does
    #: (FR-028b, FR-028d).
    tax_remitter: str = "operator"
    offsite_ads_opt_in: bool = False
    currency_code: str = "GBP"

    #: First day these figures applied, where they came from a dated row.
    effective_from: Optional[date] = None
    #: ``"economics_row"`` or ``"channel_default"`` -- which is the difference
    #: between a figure with a history and one without.
    origin: str = "channel_default"

    @property
    def deduction_pct(self) -> Decimal:
        """Discount and refund together, the share planned revenue loses."""
        return self.expected_discount_pct + self.expected_refund_pct


def _decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    if value is None:
        return default
    return Decimal(str(value))


def economics_from_row(row: SalesChannelEconomics) -> ChannelEconomics:
    """Freeze a stored period into the value the engine takes."""
    return ChannelEconomics(
        expected_discount_pct=_decimal(row.expected_discount_pct),
        expected_refund_pct=_decimal(row.expected_refund_pct),
        free_shipping_threshold=(
            _decimal(row.free_shipping_threshold)
            if row.free_shipping_threshold is not None
            else None
        ),
        rounding_rule=row.rounding_rule,
        monthly_cost=_decimal(row.monthly_cost),
        tax_remitter=row.tax_remitter or "operator",
        offsite_ads_opt_in=bool(row.offsite_ads_opt_in),
        currency_code=row.currency_code or "GBP",
        effective_from=row.effective_from,
        origin="economics_row",
    )


def channel_defaults(channel: Optional["SalesChannel"]) -> ChannelEconomics:
    """The figures on the channel object itself -- the fallback.

    The only place the legacy ``sales_channels`` columns are read. ``getattr``
    rather than attribute access because the costing functions are given
    stand-ins as well as ORM rows, and a stand-in that carries no economics
    should plan with none rather than fail.
    """
    if channel is None:
        return ChannelEconomics()
    threshold = getattr(channel, "free_shipping_threshold", None)
    return ChannelEconomics(
        expected_discount_pct=_decimal(getattr(channel, "expected_discount_pct", None)),
        expected_refund_pct=_decimal(getattr(channel, "expected_refund_pct", None)),
        free_shipping_threshold=_decimal(threshold) if threshold is not None else None,
        rounding_rule=getattr(channel, "rounding_rule", None),
        monthly_cost=_decimal(getattr(channel, "monthly_cost", None)),
        tax_remitter=getattr(channel, "tax_remitter", None) or "operator",
        offsite_ads_opt_in=bool(getattr(channel, "offsite_ads_opt_in", False)),
        currency_code=getattr(channel, "currency_code", None) or "GBP",
        effective_from=None,
        origin="channel_default",
    )


async def resolve_economics_row(
    db: AsyncSession,
    channel_id: Any,
    as_of: Optional[date] = None,
) -> Optional[SalesChannelEconomics]:
    """The period in force on ``as_of``, or ``None`` if there is none.

    Ordered by start date, then by whether the row is still open, then by
    insertion -- newest first. Two rows can legitimately share a start date
    when a figure is changed twice in one day, and the later write is the one
    in force; among those, the open row is by definition the later write and
    the partial unique index guarantees there is only one. It cannot disturb a
    historical read, because the start date is still the primary sort.
    """
    reference = as_of or clock.today()
    statement = (
        select(SalesChannelEconomics)
        .where(
            SalesChannelEconomics.sales_channel_id == channel_id,
            SalesChannelEconomics.effective_from <= reference,
        )
        .where(
            (SalesChannelEconomics.effective_to.is_(None))
            | (SalesChannelEconomics.effective_to >= reference)
        )
        .order_by(
            SalesChannelEconomics.effective_from.desc(),
            SalesChannelEconomics.effective_to.is_(None).desc(),
            SalesChannelEconomics.created_at.desc(),
        )
        .limit(1)
    )
    return (await db.execute(statement)).scalars().first()


async def current_economics_row(
    db: AsyncSession, channel_id: Any
) -> Optional[SalesChannelEconomics]:
    """The open row -- the one with no ``effective_to``."""
    return (
        (
            await db.execute(
                select(SalesChannelEconomics).where(
                    SalesChannelEconomics.sales_channel_id == channel_id,
                    SalesChannelEconomics.effective_to.is_(None),
                )
            )
        )
        .scalars()
        .first()
    )


async def resolve_channel_economics(
    db: AsyncSession,
    channel: "SalesChannel",
    as_of: Optional[date] = None,
) -> ChannelEconomics:
    """What ``channel`` was planned against on ``as_of``.

    Falls back to the channel's own columns where no period is stored, so a
    channel that predates the migration still plans -- with figures that have
    no history, which ``origin`` says plainly rather than implying otherwise.
    """
    row = await resolve_economics_row(db, channel.id, as_of)
    if row is None:
        return channel_defaults(channel)
    return economics_from_row(row)


async def resolve_many(
    db: AsyncSession,
    channels: list["SalesChannel"],
    as_of: Optional[date] = None,
) -> dict[Any, ChannelEconomics]:
    """One resolution per channel, in one query rather than N.

    What the channel list screen needs. The as-of filter and the newest-first
    ordering are the same as the single read's; the first row seen for a
    channel is the one in force, because the ordering puts it there.
    """
    reference = as_of or clock.today()
    if not channels:
        return {}

    ids = [channel.id for channel in channels]
    statement = (
        select(SalesChannelEconomics)
        .where(
            SalesChannelEconomics.sales_channel_id.in_(ids),
            SalesChannelEconomics.effective_from <= reference,
        )
        .where(
            (SalesChannelEconomics.effective_to.is_(None))
            | (SalesChannelEconomics.effective_to >= reference)
        )
        .order_by(
            SalesChannelEconomics.sales_channel_id,
            SalesChannelEconomics.effective_from.desc(),
            SalesChannelEconomics.effective_to.is_(None).desc(),
            SalesChannelEconomics.created_at.desc(),
        )
    )

    resolved: dict[Any, ChannelEconomics] = {}
    for row in (await db.execute(statement)).scalars().all():
        if row.sales_channel_id not in resolved:
            resolved[row.sales_channel_id] = economics_from_row(row)

    for channel in channels:
        resolved.setdefault(channel.id, channel_defaults(channel))
    return resolved


async def economics_over(
    db: AsyncSession,
    channel: "SalesChannel",
    start: date,
    end: date,
) -> list[tuple[ChannelEconomics, date, date]]:
    """Each set of figures in force during ``start``..``end``, with the days it covered.

    What a period-scale read needs: a subscription raised mid-quarter is owed
    at the old figure for the first part and the new one for the rest, and
    resolving once at either end would charge the whole quarter at one of them
    (task T214). Days before the channel's first period, if any, fall back to
    the channel's own figures exactly as a single-date read does. Where two
    rows share a day the later write wins, as in :func:`resolve_economics_row`.
    """
    rows = list(
        (
            await db.execute(
                select(SalesChannelEconomics)
                .where(
                    SalesChannelEconomics.sales_channel_id == channel.id,
                    SalesChannelEconomics.effective_from <= end,
                )
                .where(
                    (SalesChannelEconomics.effective_to.is_(None))
                    | (SalesChannelEconomics.effective_to >= start)
                )
                .order_by(
                    SalesChannelEconomics.effective_from,
                    SalesChannelEconomics.effective_to.is_(None),
                    SalesChannelEconomics.created_at,
                )
            )
        )
        .scalars()
        .all()
    )

    segments: list[tuple[ChannelEconomics, date, date]] = []
    cursor = start
    for index, row in enumerate(rows):
        lo = max(cursor, row.effective_from)
        hi = end if row.effective_to is None else min(end, row.effective_to)
        # A later row starting on the same day supersedes this one from then.
        following = rows[index + 1] if index + 1 < len(rows) else None
        if following is not None and following.effective_from <= hi:
            hi = following.effective_from - timedelta(days=1)
        if lo > hi:
            continue
        if lo > cursor:
            segments.append((channel_defaults(channel), cursor, lo - timedelta(days=1)))
        segments.append((economics_from_row(row), lo, hi))
        cursor = hi + timedelta(days=1)
    if cursor <= end:
        segments.append((channel_defaults(channel), cursor, end))
    return segments


def _validate(values: dict[str, Any]) -> None:
    for field in ("expected_discount_pct", "expected_refund_pct"):
        rate = _decimal(values.get(field))
        if rate < ZERO or rate > Decimal("100"):
            raise EconomicsMisconfigured(f"{field} must be between 0 and 100, got {rate}")

    threshold = values.get("free_shipping_threshold")
    if threshold is not None and _decimal(threshold) < ZERO:
        raise EconomicsMisconfigured(f"free_shipping_threshold cannot be negative, got {threshold}")

    if _decimal(values.get("monthly_cost")) < ZERO:
        raise EconomicsMisconfigured(
            f"monthly_cost cannot be negative, got {values.get('monthly_cost')}"
        )

    remitter = values.get("tax_remitter")
    if remitter not in ("marketplace", "operator"):
        raise EconomicsMisconfigured(
            f"tax_remitter must be 'marketplace' or 'operator', got {remitter!r}"
        )

    currency = values.get("currency_code")
    if not isinstance(currency, str) or len(currency) != 3:
        raise EconomicsMisconfigured(f"currency_code must be a 3-letter code, got {currency!r}")


async def write_economics(
    db: AsyncSession,
    tenant: "Tenant",
    channel: "SalesChannel",
    changes: dict[str, Any],
    *,
    user: Optional["User"] = None,
    role: Optional[str] = None,
    effective_from: Optional[date] = None,
) -> SalesChannelEconomics:
    """Open a new period, copying unchanged figures forward.

    Never updates in place (FR-003). The superseded row is closed the day
    before the new one opens, so the two do not overlap; where a figure is
    changed twice on one day the superseded row is closed on its own start
    date, leaving a period of zero length that the as-of read orders past.

    Unknown keys are refused rather than ignored, because a silently dropped
    figure is a reserve the operator believes they set.
    """
    unknown = sorted(set(changes) - set(ECONOMICS_FIELDS))
    if unknown:
        raise EconomicsMisconfigured(
            f"unknown channel economics: {', '.join(unknown)}. "
            f"Known figures: {', '.join(ECONOMICS_FIELDS)}"
        )

    opens_on = effective_from or clock.today()
    current = await current_economics_row(db, channel.id)

    if current is not None:
        carried = {field: getattr(current, field) for field in ECONOMICS_FIELDS}
    else:
        # No stored period yet: carry the legacy columns forward so the first
        # write preserves what the channel was already planning against rather
        # than silently zeroing a reserve.
        fallback = channel_defaults(channel)
        carried = {field: getattr(fallback, field) for field in ECONOMICS_FIELDS}

    merged = {**carried, **changes}
    _validate(merged)

    if current is not None:
        closes_on = opens_on - timedelta(days=1)
        if closes_on < current.effective_from:
            # Two changes on one day. The row keeps a zero-length period rather
            # than an invalid one, and the as-of read takes the later write.
            closes_on = current.effective_from
        current.effective_to = closes_on
        db.add(current)
        await db.flush()

    row = SalesChannelEconomics(
        tenant_id=tenant.id,
        sales_channel_id=channel.id,
        effective_from=opens_on,
        effective_to=None,
        set_by_user_id=user.id if user is not None else None,
        set_by_role=role,
        **merged,
    )
    db.add(row)
    await db.flush()
    logger.info(
        f"Wrote channel economics for channel {channel.id} effective {opens_on} "
        f"(figures changed: {', '.join(sorted(changes)) or 'none'})"
    )
    return row


async def ensure_economics_row(
    db: AsyncSession,
    tenant: "Tenant",
    channel: "SalesChannel",
    *,
    effective_from: Optional[date] = None,
) -> SalesChannelEconomics:
    """The channel's open period, created from its own figures if absent.

    Called when a channel is created, so that every channel has a dated first
    period and the legacy-column fallback stays unreachable in practice.
    """
    current = await current_economics_row(db, channel.id)
    if current is not None:
        return current
    return await write_economics(db, tenant, channel, {}, effective_from=effective_from)


__all__ = [
    "ChannelEconomics",
    "EconomicsMisconfigured",
    "channel_defaults",
    "current_economics_row",
    "economics_from_row",
    "economics_over",
    "ensure_economics_row",
    "resolve_channel_economics",
    "resolve_economics_row",
    "resolve_many",
    "write_economics",
]
