"""Converting a minor-unit amount into an exact major-unit `Decimal`.

Square, the storefront's cart and every discount rule in this system carry
money as an integer of the currency's minor unit -- pence for GBP, cents for
USD -- because an integer cannot drift. The database stores the major unit in
`Numeric` columns, so somewhere between the two the amount has to be divided
by a hundred, and that division is where the exactness was being lost.

In Python `int / int` is binary floating point: `7999 / 100` is
`79.989999999999994884`, not `79.99`. That value was written straight into
`Order.subtotal`, `Order.total` and `OrderItem.unit_price` -- the `Numeric`
columns `realised_margin.py` and `channel_pnl.py` read exactly and that
`sale_snapshot.write_sale_snapshot` freezes onto a settled order. A margin
computed from an approximation of what the customer paid is not the margin,
and Constitution IV rules out binary floating point for money end to end.

`Decimal(100)` as the divisor rather than `/ 100` keeps the result exact, and
`Decimal(str(...))` guards the input: a caller handing in a `float` would
otherwise widen the binary approximation it already carries rather than being
caught by it.
"""

from decimal import ROUND_HALF_UP, Decimal

#: How many minor units make one major unit. The same for every currency this
#: system handles; a zero-decimal currency such as JPY would need its own
#: factor, and none is supported today.
MINOR_UNITS_PER_MAJOR = Decimal(100)


def pence_to_pounds(pence: int | Decimal | str | None) -> Decimal:
    """Return ``pence`` as an exact major-unit amount.

    ``None`` becomes zero, because the callers are order fields that are
    absent rather than negative. Nothing is rounded: `1` pence is
    `Decimal("0.01")` and a third of a penny stays a third of a penny, to be
    rounded once at the edge by whoever presents it.
    """
    if pence is None:
        return Decimal("0")
    if isinstance(pence, Decimal):
        exact = pence
    else:
        # `str` first: an incoming float carries its own approximation, and
        # `Decimal(0.1)` would preserve it to 50 digits rather than reject it.
        exact = Decimal(str(pence))
    return exact / MINOR_UNITS_PER_MAJOR


def pounds_to_pence(pounds: int | Decimal | str | None) -> int:
    """Return ``pounds`` as a whole number of minor units.

    The other direction, and lossy in the same way when done with a float:
    `int(79.99 * 100)` is **7998**, because `79.99 * 100` is
    `7998.999999999999090505`. That decided a refund amount in
    `orders.py:refund_order` and the price offered to a customer in
    `etsy_sync.py`, each a penny short of what was intended.

    Rounded half-up to the nearest minor unit rather than truncated, so a
    price carrying a third decimal -- a per-unit figure the engine solved --
    becomes the nearest penny rather than always the lower one. This is the
    single rounding at the edge Constitution IV permits, and the only one on
    the way out.
    """
    if pounds is None:
        return 0
    exact = pounds if isinstance(pounds, Decimal) else Decimal(str(pounds))
    return int((exact * MINOR_UNITS_PER_MAJOR).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
