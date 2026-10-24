"""Costs and prices in one currency before one is subtracted from the other.

Task T231. Every cost input -- a spool's price, a labour rate, a postage
profile -- is entered in the currency the operator keeps their books in
(``Tenant.currency_code``). A channel may sell in another
(``SalesChannel.currency_code``). The engine itself is currency-blind: it
subtracts whatever it is handed. So the conversion happens here, once, at the
engine's edge -- on the way in, before a cost meets a price -- and nowhere
else.

Two directions, one rule each:

* **A quote** (a margin, a solved price, a ladder, a queue ranking, a
  scenario) converts the book-currency costs into the channel's currency at
  the rate resolved for the day asked about.
* **A settled sale** converts with the rate frozen onto its line at the moment
  of sale (FR-028j): order currency to books. The frozen rate is never
  re-resolved.

A pair with no rate is never treated as parity. A quote reports it as
incomplete and its caller refuses to present a figure; a settled line reports
its make-cost as unconvertible.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import fx_service

if TYPE_CHECKING:
    from app.models.order import OrderItem
    from app.models.sales_channel import SalesChannel
    from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

ONE = Decimal("1")


class NoExchangeRate(LookupError):
    """A cost cannot be put beside a price: no rate between their currencies."""


@dataclass(frozen=True)
class CostConversion:
    """How a book-currency cost becomes a figure in the currency of a sale."""

    books_currency: str
    sale_currency: str
    #: One unit of the books currency, in the sale currency. ``None`` where no
    #: rate exists -- never ``1``.
    rate: Optional[Decimal]
    as_of: Optional[date] = None
    source: Optional[str] = None
    #: Why the figure is less than certain: a stale rate, or none at all.
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def known(self) -> bool:
        return self.rate is not None

    def apply(self, amount: Decimal) -> Decimal:
        """``amount`` in the sale currency. Raises if no rate is known."""
        if self.rate is None:
            raise NoExchangeRate(self.reasons[0] if self.reasons else "no exchange rate")
        return Decimal(str(amount)) * self.rate


def _code(value: Optional[str]) -> str:
    return (value or "").strip().upper()


def books_currency(tenant: "Tenant") -> str:
    """The currency the tenant's cost inputs are entered in."""
    return _code(getattr(tenant, "currency_code", None)) or "GBP"


async def books_to_sale(
    db: AsyncSession,
    tenant: "Tenant",
    sale_currency: Optional[str],
    as_of: date,
) -> CostConversion:
    """The conversion a quote in ``sale_currency`` on ``as_of`` applies to costs."""
    books = books_currency(tenant)
    sale = _code(sale_currency) or books
    if sale == books:
        return CostConversion(books, sale, ONE, as_of, "parity")

    resolved = await fx_service.resolve_rate(db, books, sale, as_of=as_of)
    if resolved is None:
        return CostConversion(
            books,
            sale,
            None,
            reasons=(
                f"no exchange rate from {books} to {sale} is recorded, so costs kept "
                f"in {books} cannot be set against a price in {sale}; enter one by "
                f"hand under exchange rates",
            ),
        )
    reasons: tuple[str, ...] = ()
    if resolved.is_stale:
        reasons = (
            f"costs are converted from {books} to {sale} at the last known rate, "
            f"from {resolved.as_of}: {resolved.reason}",
        )
    return CostConversion(books, sale, resolved.rate, resolved.as_of, resolved.source, reasons)


async def books_to_channel(
    db: AsyncSession, tenant: "Tenant", channel: "SalesChannel", as_of: date
) -> CostConversion:
    """The conversion a quote on ``channel`` applies to costs."""
    return await books_to_sale(db, tenant, getattr(channel, "currency_code", None), as_of)


def cost_in_sale_currency(item: "OrderItem", amount_in_books: Decimal) -> Optional[Decimal]:
    """A settled line's book-currency cost, in the currency it was sold in.

    Through the rate frozen onto the line, which runs from the order's currency
    to the books (one unit of the order currency is ``fx_rate`` in the books),
    so a cost is divided by it. ``None`` where the sale froze no rate: the cost
    is then unconvertible, which is not the same as equal.
    """
    rate = getattr(item, "fx_rate", None)
    if rate is None:
        return None
    rate = Decimal(str(rate))
    if rate <= 0:  # pragma: no cover - the column's own CHECK refuses it
        return None
    return Decimal(str(amount_in_books)) / rate


__all__ = [
    "CostConversion",
    "NoExchangeRate",
    "books_currency",
    "books_to_channel",
    "books_to_sale",
    "cost_in_sale_currency",
]
