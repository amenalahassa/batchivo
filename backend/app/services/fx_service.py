"""Exchange rates behind a narrow port (task T098, FR-028f - FR-028j).

Five requirements shape this module, and each one is a rule about what must
happen when the outside world does not cooperate:

- **FR-028f**: fetch once per day per pair and reuse, not once per order. A
  marketplace day with forty sales must not be forty requests to a rate
  service, and forty orders on the same day must not be priced at forty
  slightly different rates.
- **FR-028g**: where the service is unreachable, use the most recent known
  rate and **show the date it came from**. A stale rate used silently is worse
  than a stale rate used visibly, because only the second can be questioned.
- **FR-028h**: an operator may enter a rate by hand, which overrides the
  fetched one and is recorded with its own origin.
- **FR-028i**: a sale is never blocked by rate-service unavailability. This is
  the one that decides the shape of the code: every failure path returns
  something, and the only thing that can make this module raise is a pair it
  has never had a rate for -- which is a question for the operator, not an
  outage.
- **FR-028j**: a rate frozen onto an order is never revised.

**Why a port.** The provider is reached through :class:`RateProvider`, a
protocol with one method. The point is not provider-swapping for its own sake:
it is that the tests exercise the whole of the logic above -- day reuse, stale
fallback, manual override, the never-fetched pair -- without a network, and a
test that needs a network is a test that gets skipped and then deleted.

**What is never implied.** A pair with no rate on record returns ``None`` with
a reason, never ``1.0``. Treating an unknown rate as parity is the defect this
module is most likely to be "simplified" into: it makes a cross-currency sale
look like a same-currency one, and the error is invisible until somebody
reconciles a bank statement.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.config import get_settings
from app.models.fx_rate import FxRate

logger = logging.getLogger(__name__)

ONE = Decimal("1")


class RateUnavailableError(RuntimeError):
    """No rate for this pair has ever been recorded, and none could be fetched.

    Deliberately an error rather than a ``1.0``: a pair nobody has a rate for
    is a question the operator has to answer (FR-028h gives them the means),
    and implying parity would make a cross-currency sale look correct while
    being wrong by whatever the real rate is.

    This is raised by :func:`require_rate`, which the margin path uses.
    :func:`resolve_rate` returns ``None`` instead, which is what the *sale*
    path uses -- because FR-028i says a sale is never blocked.
    """

    def __init__(self, base: str, quote: str):
        self.base = base
        self.quote = quote
        super().__init__(
            f"no exchange rate has ever been recorded for {base}/{quote} and "
            f"none could be fetched. Enter one by hand rather than assuming "
            f"parity -- a rate of 1.0 would price this sale as though the two "
            f"currencies were the same"
        )


@dataclass(frozen=True)
class ResolvedRate:
    """A rate, and everything a reader needs to judge it.

    ``as_of`` and ``is_stale`` exist for FR-028g: an interface showing a rate
    without the day it came from gives a reader no way to tell a live figure
    from one from three weeks ago.
    """

    base_currency: str
    quote_currency: str
    rate: Decimal
    #: The day the rate applies to, which is what makes staleness visible.
    as_of: date
    source: str
    #: True when the rate is older than the date it was asked for, i.e. a
    #: fallback was used because a current rate could not be had.
    is_stale: bool
    #: Why this rate rather than another, in words, for the screen.
    reason: str

    @property
    def is_parity(self) -> bool:
        """Same currency, so no conversion -- not an unknown rate."""
        return self.base_currency == self.quote_currency


class RateProvider(Protocol):
    """One method, so the tests never need a network."""

    async def fetch(self, base: str, quote: str) -> Optional[Decimal]:
        """Today's rate, or ``None`` where it could not be obtained.

        Implementations must not raise for an ordinary outage: a provider that
        throws on a timeout would make every caller handle it, and one of them
        would eventually let it reach a sale (FR-028i).
        """
        ...


class HttpRateProvider:
    """The default provider: one HTTP call, short timeout, no exceptions out.

    The timeout is deliberately short (``fx_timeout_seconds``, default five
    seconds). A sale must not wait on a rate service, and a rate fetched after
    thirty seconds is worth less than the last known one served instantly.
    """

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        self._client = client

    async def fetch(self, base: str, quote: str) -> Optional[Decimal]:
        settings = get_settings()
        if not settings.fx_enabled:
            logger.debug("Exchange-rate fetching is disabled; using recorded rates only")
            return None

        url = f"{settings.fx_api_url.rstrip('/')}/{base.upper()}"
        headers = {"apikey": settings.fx_api_key} if settings.fx_api_key else {}

        try:
            if self._client is not None:
                response = await self._client.get(url, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=settings.fx_timeout_seconds) as client:
                    response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Swallowed on purpose. The caller falls back to the last known
            # rate (FR-028g) and the sale proceeds (FR-028i); an exception here
            # would turn a rate outage into a failed checkout.
            logger.warning(f"Exchange-rate fetch for {base}/{quote} failed: {exc}")
            return None

        rates = payload.get("rates") or payload.get("conversion_rates") or {}
        raw = rates.get(quote.upper())
        if raw is None:
            logger.warning(f"Rate service returned no quote for {quote} against {base}")
            return None

        try:
            # Through `str` so a JSON float never becomes a binary-float rate
            # (Constitution IV). The provider sends a number; we refuse to keep
            # it as one.
            return Decimal(str(raw))
        except (InvalidOperation, TypeError):
            logger.warning(f"Rate service returned an unusable rate for {base}/{quote}: {raw!r}")
            return None


def _normalise(code: str) -> str:
    return (code or "").strip().upper()


async def latest_known_rate(
    db: AsyncSession,
    base: str,
    quote: str,
    *,
    on_or_before: Optional[date] = None,
) -> Optional[FxRate]:
    """The most recent recorded rate for a pair, at or before a date.

    A manual rate wins over a fetched one for the same day (FR-028h), which is
    why ``source`` is part of the ordering rather than left to insertion order.
    """
    conditions = [
        FxRate.base_currency == _normalise(base),
        FxRate.quote_currency == _normalise(quote),
    ]
    if on_or_before is not None:
        conditions.append(FxRate.rate_date <= on_or_before)

    rows = (
        (await db.execute(select(FxRate).where(*conditions).order_by(FxRate.rate_date.desc())))
        .scalars()
        .all()
    )
    if not rows:
        return None

    newest = rows[0].rate_date
    same_day = [row for row in rows if row.rate_date == newest]
    manual = next((row for row in same_day if row.source == "manual"), None)
    return manual or same_day[0]


async def record_rate(
    db: AsyncSession,
    *,
    base: str,
    quote: str,
    rate: Decimal,
    rate_date: Optional[date] = None,
    source: str = "service",
) -> FxRate:
    """Store a rate, or return the one already stored for that day and source.

    Idempotent by the table's uniqueness key, which is what makes day reuse
    safe under concurrency: two sales on the same day racing to record the same
    fetched rate must not become two rows or one failed checkout.
    """
    on = rate_date or clock.today()
    existing = (
        await db.execute(
            select(FxRate).where(
                FxRate.base_currency == _normalise(base),
                FxRate.quote_currency == _normalise(quote),
                FxRate.rate_date == on,
                FxRate.source == source,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    row = FxRate(
        base_currency=_normalise(base),
        quote_currency=_normalise(quote),
        rate_date=on,
        rate=Decimal(str(rate)),
        source=source,
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        # Lost the race. The other writer stored the same figure, so read it
        # back rather than failing the sale.
        await db.rollback()
        again = await latest_known_rate(db, base, quote, on_or_before=on)
        if again is None:
            raise
        return again
    return row


async def set_manual_rate(
    db: AsyncSession,
    *,
    base: str,
    quote: str,
    rate: Decimal,
    rate_date: Optional[date] = None,
) -> FxRate:
    """Record an operator-entered rate, which overrides the fetched one (FR-028h).

    Stored as its own row with ``source = 'manual'`` rather than overwriting
    the fetched figure: the override is a statement about what the rate was,
    and keeping both means a reader can see that a hand-entered rate is in use
    and what it replaced.
    """
    if Decimal(str(rate)) <= 0:
        raise ValueError("an exchange rate must be greater than zero")
    return await record_rate(
        db, base=base, quote=quote, rate=rate, rate_date=rate_date, source="manual"
    )


async def resolve_rate(
    db: AsyncSession,
    base: str,
    quote: str,
    *,
    as_of: Optional[date] = None,
    provider: Optional[RateProvider] = None,
) -> Optional[ResolvedRate]:
    """The rate to use, by the whole of FR-028f - FR-028i.

    In order:

    1. **Same currency** -- parity, with no fetch and no row.
    2. **A rate already recorded for the day asked for** -- reused rather than
       re-requested (FR-028f). A manual row wins over a fetched one.
    3. **A fetch**, but only when the day asked for is today. Backdating a sale
       does not make a provider able to quote a past day, and asking for one
       would store today's figure under yesterday's date.
    4. **The most recent known rate**, flagged stale and carrying the day it
       came from (FR-028g).
    5. **``None``** -- a pair with no rate ever recorded. Never ``1.0``.

    Returns rather than raises at step 5 so a sale is never blocked (FR-028i).
    :func:`require_rate` is the raising variant, for the reporting paths where
    a missing rate should be a question rather than a silent gap.
    """
    base_code = _normalise(base)
    quote_code = _normalise(quote)
    on = as_of or clock.today()

    if not base_code or not quote_code:
        return None

    if base_code == quote_code:
        return ResolvedRate(
            base_currency=base_code,
            quote_currency=quote_code,
            rate=ONE,
            as_of=on,
            source="parity",
            is_stale=False,
            reason="the sale and the books are in the same currency, so no conversion applies",
        )

    recorded = await latest_known_rate(db, base_code, quote_code, on_or_before=on)
    if recorded is not None and recorded.rate_date == on:
        return ResolvedRate(
            base_currency=base_code,
            quote_currency=quote_code,
            rate=Decimal(str(recorded.rate)),
            as_of=recorded.rate_date,
            source=recorded.source,
            is_stale=False,
            reason=(
                f"entered by hand for {recorded.rate_date}"
                if recorded.source == "manual"
                else f"fetched for {recorded.rate_date} and reused for this sale"
            ),
        )

    if on == clock.today():
        fetched = await (provider or HttpRateProvider()).fetch(base_code, quote_code)
        if fetched is not None and fetched > 0:
            stored = await record_rate(
                db, base=base_code, quote=quote_code, rate=fetched, rate_date=on
            )
            return ResolvedRate(
                base_currency=base_code,
                quote_currency=quote_code,
                rate=Decimal(str(stored.rate)),
                as_of=stored.rate_date,
                source=stored.source,
                is_stale=False,
                reason=f"fetched for {stored.rate_date}",
            )

    if recorded is not None:
        return ResolvedRate(
            base_currency=base_code,
            quote_currency=quote_code,
            rate=Decimal(str(recorded.rate)),
            as_of=recorded.rate_date,
            source=recorded.source,
            is_stale=True,
            reason=(
                f"the rate service could not be reached, so the last known rate "
                f"from {recorded.rate_date} was used"
            ),
        )

    logger.warning(
        f"No exchange rate available for {base_code}/{quote_code}; reporting it as "
        f"unknown rather than assuming parity"
    )
    return None


async def require_rate(
    db: AsyncSession,
    base: str,
    quote: str,
    *,
    as_of: Optional[date] = None,
    provider: Optional[RateProvider] = None,
) -> ResolvedRate:
    """:func:`resolve_rate`, raising where no rate exists.

    For reporting paths, where a missing rate is a question the operator should
    answer. The sale path uses :func:`resolve_rate` instead and records the
    gap, because FR-028i does not permit a sale to fail over a rate.
    """
    resolved = await resolve_rate(db, base, quote, as_of=as_of, provider=provider)
    if resolved is None:
        raise RateUnavailableError(_normalise(base), _normalise(quote))
    return resolved
