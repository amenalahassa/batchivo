"""Exchange rates the operator enters by hand (task T223, FR-028h).

`fx_service.set_manual_rate` existed with no caller, so an order whose sale
froze no rate -- "no exchange rate was available" -- had no remedy, though the
edge case says the operator is asked for one. Two routes give it one:

* ``GET /fx-rates/waiting`` lists this tenant's settled lines that froze no
  rate, with the currency pair each is waiting on. Every role may read it.
* ``POST /fx-rates/manual`` records a rate with ``source = 'manual'`` and then
  fills the waiting lines it covers. Admin or owner only: a rate moves every
  margin built on it.

A rate entered later fills only a line that froze none. A frozen rate is never
revised (FR-028j) -- `sale_snapshot.freeze_rate` refuses a line that has one.

Rates themselves are not tenant-scoped (see ``app/models/fx_rate.py``): a rate
is a statement about what the rate *was*. The lines it fills are, and are read
and written only within the caller's tenant.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireAdmin, TenantDB
from app.core import clock
from app.models.order import Order, OrderItem
from app.services import fx_service
from app.services.currency_edge import books_currency
from app.services.sale_snapshot import NO_RATE_PREFIX, freeze_rate

logger = logging.getLogger(__name__)

router = APIRouter()


class ManualRateRequest(BaseModel):
    """A rate typed by the operator: one ``base`` is ``rate`` of ``quote``."""

    base_currency: str = Field(..., min_length=3, max_length=3)
    quote_currency: str = Field(..., min_length=3, max_length=3)
    rate: Decimal = Field(..., gt=0, description="A decimal string; never a float")
    rate_date: Optional[date] = Field(None, description="The day it applies to; today if absent")

    model_config = ConfigDict(extra="forbid")

    @field_validator("base_currency", "quote_currency")
    @classmethod
    def _upper(cls, value: str) -> str:
        if not value.isalpha():
            raise ValueError("a currency is a three-letter ISO 4217 code")
        return value.upper()


class ManualRateResponse(BaseModel):
    base_currency: str
    quote_currency: str
    rate: Decimal
    rate_date: date
    source: str
    lines_filled: int = Field(..., description="Settled lines that had frozen no rate, now filled")


class WaitingLine(BaseModel):
    order_id: UUID
    order_number: str
    order_item_id: UUID
    product_name: str
    sold_on: Optional[date]
    base_currency: str
    quote_currency: str


class WaitingLinesResponse(BaseModel):
    lines: list[WaitingLine]
    total: int


async def _waiting_items(db, tenant) -> list[tuple[OrderItem, Order]]:
    """Settled lines in this tenant that froze no exchange rate."""
    rows = (
        (
            await db.execute(
                select(OrderItem)
                .where(
                    OrderItem.tenant_id == tenant.id,
                    OrderItem.pricing_rev.isnot(None),
                    OrderItem.fx_rate.is_(None),
                )
                .options(selectinload(OrderItem.order))
            )
        )
        .scalars()
        .all()
    )
    return [(item, item.order) for item in rows if item.order is not None]


def _pair_of(item: OrderItem, order: Order, books: str) -> tuple[str, str]:
    base = (order.currency or books).strip().upper()
    quote = (item.fx_quote_currency or books).strip().upper()
    return base, quote


@router.get("/waiting", response_model=WaitingLinesResponse)
async def list_lines_waiting_on_a_rate(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> WaitingLinesResponse:
    """The settled lines that froze no rate, and the pair each is waiting on."""
    books = books_currency(tenant)
    lines = []
    for item, order in await _waiting_items(db, tenant):
        base, quote = _pair_of(item, order, books)
        lines.append(
            WaitingLine(
                order_id=order.id,
                order_number=order.order_number,
                order_item_id=item.id,
                product_name=item.product_name,
                sold_on=order.created_at.date() if order.created_at else None,
                base_currency=base,
                quote_currency=quote,
            )
        )
    return WaitingLinesResponse(lines=lines, total=len(lines))


@router.post("/manual", response_model=ManualRateResponse, status_code=status.HTTP_201_CREATED)
async def record_manual_rate(
    body: ManualRateRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> ManualRateResponse:
    """Record a hand-entered rate and fill the lines waiting on that pair.

    A second, different rate for the same pair and day is a ``409``: a rate row
    is never updated (``app/models/fx_rate.py``), and silently keeping the
    first while reporting success would leave the operator believing the
    second was in force.
    """
    if body.base_currency == body.quote_currency:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="a currency converts to itself at parity; no rate is needed",
        )

    on = body.rate_date or clock.today()
    stored = await fx_service.set_manual_rate(
        db,
        base=body.base_currency,
        quote=body.quote_currency,
        rate=body.rate,
        rate_date=on,
    )
    if Decimal(str(stored.rate)) != body.rate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"a manual rate of {stored.rate} is already recorded for "
                f"{body.base_currency}/{body.quote_currency} on {on}; rates are never "
                f"rewritten, so enter the correction against another day"
            ),
        )

    books = books_currency(tenant)
    filled = 0
    for item, order in await _waiting_items(db, tenant):
        if _pair_of(item, order, books) != (body.base_currency, body.quote_currency):
            continue
        sold_on = order.created_at.date() if order.created_at else on
        resolved = await fx_service.resolve_rate(
            db, body.base_currency, body.quote_currency, as_of=sold_on
        )
        if resolved is None:
            # Entered for a day after this sale: the rate did not exist when it
            # was made, and the sale waits on one for its own day.
            continue
        freeze_rate(item, resolved, body.quote_currency)
        item.snapshot_incomplete = [
            reason
            for reason in (item.snapshot_incomplete or [])
            if not reason.startswith(NO_RATE_PREFIX)
        ] or None
        if resolved.is_stale:
            item.snapshot_incomplete = [
                *(item.snapshot_incomplete or []),
                f"the exchange rate filled in later is from {resolved.as_of}, "
                f"before this sale: {resolved.reason}",
            ]
        db.add(item)
        filled += 1

    await db.commit()
    logger.info(
        f"Recorded a manual {body.base_currency}/{body.quote_currency} rate of {body.rate} "
        f"for {on} and filled {filled} line(s) in tenant {tenant.id}"
    )
    return ManualRateResponse(
        base_currency=stored.base_currency,
        quote_currency=stored.quote_currency,
        rate=Decimal(str(stored.rate)),
        rate_date=stored.rate_date,
        source=stored.source,
        lines_filled=filled,
    )
