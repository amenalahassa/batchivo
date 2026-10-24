"""Resolving a price as at a date, and keeping the history coherent (T097).

Two jobs, and they are two jobs because the database can only do one of them.

**Reading.** FR-039: a product's price on a channel must be readable as at a
date, so an order reports the price effective when it was placed. That is
:func:`resolve_price` and :func:`price_at`, and the subtlety is the quantity
tier: several rows can cover one date, and the one that applies is the highest
tier the quantity reaches. Resolution is deliberately *pure* — it takes rows
and returns one — so the rule lives in one place whether the caller already has
the collection loaded (the storefront, which loads `current_pricing` eagerly)
or needs a query (an order reporting a historical price).

**Writing.** The partial unique index on the table guarantees one *current* row
per product, channel and tier. It cannot guarantee that historical periods do
not overlap, because expressing that needs a range exclusion constraint and the
`btree_gist` extension this cluster has not declared (research D6). So the
overlap guard is here, in :func:`assert_no_overlap`, with its own test — an
invariant the database cannot express is still an invariant somebody has to
keep, and "somebody" is this module.

:func:`set_price` is the only correct way to change a price. It closes the
current period and opens a new one; it never updates a row in place, because a
settled order reading its price as at its own date would otherwise find the
figure it sold at silently replaced.
"""

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models.product_pricing import ProductPricing

if TYPE_CHECKING:
    from app.models.product import Product

logger = logging.getLogger(__name__)

ONE_DAY = timedelta(days=1)


class PriceOverlapError(ValueError):
    """Two prices would apply to the same product, channel, tier and day.

    Raised at save time rather than discovered at read time. A read that found
    two applicable prices would have to pick one, and whichever it picked would
    be arbitrary — so the write is refused instead, naming the row it collided
    with so the operator can see what they are about to contradict.
    """

    def __init__(self, existing: ProductPricing, *, valid_from: date, valid_to: Optional[date]):
        self.existing = existing
        self.valid_from = valid_from
        self.valid_to = valid_to
        period = f"{valid_from} to {valid_to or 'open-ended'}"
        clash = f"{existing.valid_from} to {existing.valid_to or 'open-ended'}"
        super().__init__(
            f"a price of {existing.list_price} already applies from {clash} at "
            f"quantities of {existing.min_quantity} or more, which overlaps the "
            f"period {period} being saved -- close the existing period first, or "
            f"save a different one"
        )


class TierOverlapError(ValueError):
    """Two quantity tiers would start at the same quantity on the same day.

    Distinct from :class:`PriceOverlapError` so an interface can say which
    mistake was made: an operator adding a second "10 or more" tier has made a
    different error from one whose dates collide, and telling them "dates
    overlap" would send them to the wrong field.
    """

    def __init__(self, existing: ProductPricing):
        self.existing = existing
        super().__init__(
            f"a tier already starts at {existing.min_quantity} units for this "
            f"product and channel, priced at {existing.list_price} -- change "
            f"that tier rather than adding a second one at the same quantity"
        )


# ---------------------------------------------------------------------------
# Reading (FR-039)
# ---------------------------------------------------------------------------


def resolve_price(
    rows: Iterable[ProductPricing],
    *,
    as_of: date,
    quantity: int = 1,
    sales_channel_id: Optional[uuid.UUID] = None,
) -> Optional[ProductPricing]:
    """The one row that priced ``quantity`` units on ``as_of``.

    Pure: no query, no session. Hand it a loaded collection -- ``product.
    pricing`` for a historical read, ``product.current_pricing`` for today's --
    and it applies the one resolution rule the whole system shares.

    **The tier rule.** Several rows can cover one date at different quantity
    breaks. The row that applies is the one with the **highest**
    ``min_quantity`` the quantity reaches, which makes the price at exactly a
    break quantity unambiguous: at 10 units, a tier starting at 10 wins over
    one starting at 1. Expressing tiers as a lower bound and resolving by
    maximum is what removes the ambiguity, rather than a convention each caller
    would have to remember.

    Returns ``None`` where the product was not priced on that channel on that
    date. That is not a price of zero, and callers must not treat it as one: a
    product nobody had listed yet was not being sold for nothing.
    """
    candidates = [
        row
        for row in rows
        if (sales_channel_id is None or row.sales_channel_id == sales_channel_id)
        and row.covers(as_of, quantity=quantity)
    ]
    if not candidates:
        return None

    # Highest tier reached, then the latest period -- the second only matters
    # if the overlap guard was bypassed (a direct SQL edit, or a migration),
    # and preferring the newest row is the least surprising answer there.
    return max(candidates, key=lambda row: (row.min_quantity, row.valid_from))


def price_at(
    rows: Iterable[ProductPricing],
    *,
    as_of: date,
    quantity: int = 1,
    sales_channel_id: Optional[uuid.UUID] = None,
) -> Optional[Decimal]:
    """Just the amount from :func:`resolve_price`, or ``None``."""
    row = resolve_price(rows, as_of=as_of, quantity=quantity, sales_channel_id=sales_channel_id)
    if row is None or row.list_price is None:
        return None
    return Decimal(str(row.list_price))


def current_rows(product: "Product") -> list["ProductPricing"]:
    """This product's price rows that are in effect now.

    Prefers ``current_pricing``, the relationship primary-joined on
    ``valid_to IS NULL``, and falls back to filtering the history where that
    relationship is absent or was not loaded.

    The fallback is not defensive clutter. Three things can hand over a product
    without the view: a caller constructing one by hand, a test double, and a
    future change to the loading strategy. Reading
    ``product.current_pricing`` directly turns each of those into an
    ``AttributeError`` on a live marketplace sync or a shop page, and a lazy
    load would raise on the request thread. Filtering the history gives the
    same answer.

    One function rather than the same two lines in five places
    (Constitution III): the temporal filter is the thing that must not be
    forgotten, and this is where it lives.
    """
    rows = getattr(product, "current_pricing", None)
    if rows is None:
        # Reads the column, not `ProductPricing.is_current`. The fallback
        # exists for objects that are not fully-formed models, and those are
        # exactly the ones that will not have the property either. An absent
        # `valid_to` reads as current, which is what it means.
        return [
            row
            for row in (getattr(product, "pricing", None) or [])
            if getattr(row, "valid_to", None) is None
        ]
    return list(rows)


def current_price(
    product: "Product",
    sales_channel_id: uuid.UUID,
    *,
    quantity: int = 1,
) -> Optional[Decimal]:
    """The price in effect now, from the eagerly loaded current rows.

    Reads ``current_pricing`` rather than ``pricing``: the first is
    primary-joined on ``valid_to IS NULL``, so a superseded row cannot be
    served by accident. This is the function every current-price read path
    should call, including the storefront.
    """
    candidates = [
        row
        for row in current_rows(product)
        if row.sales_channel_id == sales_channel_id and quantity >= row.min_quantity
    ]
    if not candidates:
        return None
    row = max(candidates, key=lambda r: r.min_quantity)
    return None if row.list_price is None else Decimal(str(row.list_price))


def storefront_price(
    product: "Product",
    *,
    sales_channel_id: Optional[uuid.UUID],
    quantity: int = 1,
) -> Optional[Decimal]:
    """The shop channel's own current price for this product, or ``None``.

    Every shop read site goes through here, so the temporal filter is applied
    once and no shop page can serve last quarter's price by forgetting it.

    ``None`` means unpriced on the shop: the product carries no current price
    on the shop channel, or there is no shop channel at all. The shop must then
    treat it as not for sale -- the previous code substituted zero, which put a
    free product on a public page. There is no fall-back to another channel's
    listing (task T228, removed in T253): falling back charged a marketplace's
    price on the shop.
    """
    if sales_channel_id is None:
        return None
    on_channel = [
        row
        for row in current_rows(product)
        if row.is_active
        and quantity >= row.min_quantity
        and row.sales_channel_id == sales_channel_id
    ]
    if not on_channel:
        return None
    row = max(on_channel, key=lambda r: r.min_quantity)
    return None if row.list_price is None else Decimal(str(row.list_price))


async def price_as_of(
    db: AsyncSession,
    product_id: uuid.UUID,
    sales_channel_id: uuid.UUID,
    *,
    as_of: date,
    quantity: int = 1,
) -> Optional[ProductPricing]:
    """:func:`resolve_price` against the database, for a historical read.

    ``ProductPricing`` carries no ``tenant_id`` of its own -- it is scoped
    through the product and the channel -- so the caller must have already
    checked both against the tenant. Every caller in ``api/v1`` does.
    """
    rows = (
        (
            await db.execute(
                select(ProductPricing).where(
                    ProductPricing.product_id == product_id,
                    ProductPricing.sales_channel_id == sales_channel_id,
                    ProductPricing.valid_from <= as_of,
                )
            )
        )
        .scalars()
        .all()
    )
    return resolve_price(rows, as_of=as_of, quantity=quantity)


# ---------------------------------------------------------------------------
# Writing (research D6)
# ---------------------------------------------------------------------------


def assert_no_overlap(
    existing: Sequence[ProductPricing],
    *,
    valid_from: date,
    valid_to: Optional[date],
    min_quantity: int,
    exclude_id: Optional[uuid.UUID] = None,
) -> None:
    """Refuse a period that would collide with one already recorded.

    This is the invariant the partial unique index cannot express: the index
    guarantees one row per tier with ``valid_to IS NULL``, which stops two
    *current* prices, but nothing stops two historical periods overlapping, and
    a read that found both would have to pick one arbitrarily.

    Two periods overlap when each starts on or before the other ends. An
    open-ended period ends at infinity, which is why ``None`` is compared as
    "no upper bound" rather than coerced to a date.
    """
    for row in existing:
        if exclude_id is not None and row.id == exclude_id:
            continue
        if row.min_quantity != min_quantity:
            continue

        starts_before_other_ends = valid_to is None or row.valid_from <= valid_to
        other_starts_before_this_ends = row.valid_to is None or valid_from <= row.valid_to
        if starts_before_other_ends and other_starts_before_this_ends:
            raise PriceOverlapError(row, valid_from=valid_from, valid_to=valid_to)


async def set_price(
    db: AsyncSession,
    *,
    product_id: uuid.UUID,
    sales_channel_id: uuid.UUID,
    list_price: Decimal,
    valid_from: Optional[date] = None,
    min_quantity: int = 1,
    is_active: bool = True,
) -> ProductPricing:
    """Change a price by closing the current period and opening a new one.

    Never an update in place (FR-039, Constitution VI). The current row's
    ``valid_to`` is set to the day before the new period starts, so the two
    periods abut without overlapping and every past day still resolves to the
    figure that was actually charged then.

    Three cases worth naming:

    - **No current price**: a first listing. One row is opened and nothing is
      closed.
    - **A new price from today**: the usual case. Today's orders get the new
      figure, yesterday's keep the old one.
    - **A new price from the same day the current one started**: there is no
      day left for the old row to own, so it is removed rather than closed to a
      period that ends before it begins. An operator correcting a price they
      set an hour ago means to replace it, not to record an hour of history.

    Backdating further than the current period's start is refused by
    :func:`assert_no_overlap`: it would mean two prices applied on the days in
    between, and the operator has to say which.
    """
    effective = valid_from or clock.today()

    rows = list(
        (
            await db.execute(
                select(ProductPricing).where(
                    ProductPricing.product_id == product_id,
                    ProductPricing.sales_channel_id == sales_channel_id,
                )
            )
        )
        .scalars()
        .all()
    )

    current = next(
        (row for row in rows if row.valid_to is None and row.min_quantity == min_quantity),
        None,
    )

    if current is not None:
        if current.valid_from > effective:
            raise PriceOverlapError(current, valid_from=effective, valid_to=None)
        if current.valid_from == effective:
            # Nothing for the old row to own. Replacing it is what the operator
            # means; closing it to [from, from - 1 day] would be incoherent.
            await db.delete(current)
            await db.flush()
            rows = [row for row in rows if row.id != current.id]
        else:
            current.valid_to = effective - ONE_DAY
            db.add(current)
            rows = [row for row in rows if row.id != current.id] + [current]

    assert_no_overlap(
        rows,
        valid_from=effective,
        valid_to=None,
        min_quantity=min_quantity,
    )

    opened = ProductPricing(
        product_id=product_id,
        sales_channel_id=sales_channel_id,
        list_price=Decimal(str(list_price)),
        valid_from=effective,
        valid_to=None,
        min_quantity=min_quantity,
        is_active=is_active,
    )
    db.add(opened)
    await db.flush()
    logger.info(
        f"Priced product {product_id} on channel {sales_channel_id} at "
        f"{list_price} from {effective} for quantities of {min_quantity} or more"
    )
    return opened


async def add_quantity_tier(
    db: AsyncSession,
    *,
    product_id: uuid.UUID,
    sales_channel_id: uuid.UUID,
    list_price: Decimal,
    min_quantity: int,
    valid_from: Optional[date] = None,
) -> ProductPricing:
    """Open a new quantity tier, refusing one that already exists.

    A second tier starting at the same quantity is a :class:`TierOverlapError`
    rather than a silent replacement: the operator either meant to change the
    existing tier or mistyped the break, and guessing which would quietly
    reprice a product.
    """
    if min_quantity < 1:
        raise ValueError("a quantity tier starts at one unit or more")

    rows = list(
        (
            await db.execute(
                select(ProductPricing).where(
                    ProductPricing.product_id == product_id,
                    ProductPricing.sales_channel_id == sales_channel_id,
                    ProductPricing.valid_to.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    clash = next((row for row in rows if row.min_quantity == min_quantity), None)
    if clash is not None:
        raise TierOverlapError(clash)

    return await set_price(
        db,
        product_id=product_id,
        sales_channel_id=sales_channel_id,
        list_price=list_price,
        valid_from=valid_from,
        min_quantity=min_quantity,
    )
