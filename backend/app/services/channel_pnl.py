"""Channel profitability, and planned fees against the statement (task T073).

Two jobs, both of which the system could not do before:

**Absorb the costs that are not charged per sale.** A monthly subscription and
a per-listing fee are real costs that no single order carries. FR-025 says they
must be absorbed over a period's *actual* order volume, which makes a slow
month visibly expensive instead of invisibly so. Where a period has no orders
there is nothing to divide by, so the cost is reported as **unabsorbed** rather
than divided by zero -- a channel that sold nothing has not become free.

**Reconcile plan against statement.** FR-041d wants the planned fee total, the
recorded actual total, the unallocated remainder and the difference against
plan, per channel and period. Order-scoped actuals take precedence over the
period total and reduce its remainder (FR-041c), so nothing is counted twice,
and an order-scoped amount exceeding the period total is reported rather than
absorbed silently -- the period figure is then the one that needs fixing.

Nothing here is stored. Everything is derived on demand from the orders, the
rules and the recorded actuals (Constitution V).
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Iterable, Optional, Sequence

from app.services.fee_engine import FeeStack

if TYPE_CHECKING:
    from app.models.fee_actual import FeeActual

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
CENT = Decimal("0.01")


class ReconciliationConflict(ValueError):
    """Raised when order-scoped actuals exceed the period total they sit in.

    FR-041c's edge case. Reported rather than absorbed, because the two figures
    contradict each other and only the operator knows which is wrong; the
    endpoint turns it into a ``409``.
    """

    def __init__(self, category: str, period_total: Decimal, order_total: Decimal) -> None:
        self.category = category
        self.period_total = period_total
        self.order_total = order_total
        super().__init__(
            f"order-scoped actuals for {category!r} total {order_total}, which exceeds the "
            f"period total of {period_total}; the period figure needs correcting rather "
            f"than the order amounts being discarded"
        )


@dataclass(frozen=True)
class CategoryReconciliation:
    """Plan against statement for one fee category in one period."""

    category: str
    planned: Decimal
    #: The period total a human read off the statement, if one was recorded.
    actual_period: Optional[Decimal]
    #: Amounts attributed to individual orders inside this period.
    actual_order_scoped: Decimal
    #: The part of the period total not yet attributed to any order (FR-041c).
    unallocated_remainder: Optional[Decimal]
    #: Recorded actual, however it was scoped, or ``None`` if nothing was.
    actual_total: Optional[Decimal]

    @property
    def difference(self) -> Optional[Decimal]:
        """Recorded less planned, or ``None`` while nothing is recorded.

        Zero and "nothing recorded" are different answers, and conflating them
        would report a channel nobody has reconciled as reconciling perfectly.
        """
        if self.actual_total is None:
            return None
        return self.actual_total - self.planned

    @property
    def difference_pct_of_fee(self) -> Optional[Decimal]:
        """The difference as a share of the planned fee (SC-009)."""
        if self.actual_total is None or self.planned == ZERO:
            return None
        return (self.difference / self.planned * Decimal("100")).quantize(Decimal("0.0001"))


@dataclass(frozen=True)
class AbsorbedCost:
    """A periodic or per-listing cost spread over the period's order volume."""

    key: str
    label: str
    total: Decimal
    order_count: int
    #: ``None`` when there were no orders to divide by (FR-025's edge case).
    per_order: Optional[Decimal]

    @property
    def is_unabsorbed(self) -> bool:
        return self.per_order is None


@dataclass(frozen=True)
class ChannelPnL:
    """One channel over one period."""

    channel_id: object
    period_start: date
    period_end: date
    order_count: int

    #: Revenue tax-exclusive, because tax is never revenue (FR-028c).
    revenue_tax_exclusive: Decimal
    #: Collected and owed, shown as a liability and never as revenue (FR-028d).
    sales_tax_collected: Decimal
    sales_tax_liability: Decimal

    postage_paid: Decimal
    shipping_revenue: Decimal

    planned_fee_total: Decimal
    actual_fee_total: Optional[Decimal]
    unallocated_remainder: Decimal
    reconciliation: list[CategoryReconciliation] = field(default_factory=list)

    absorbed_costs: list[AbsorbedCost] = field(default_factory=list)
    unabsorbed_total: Decimal = ZERO

    make_cost_total: Decimal = ZERO
    profit: Decimal = ZERO
    margin_pct: Optional[Decimal] = None
    margin_basis: str = "customer_total"
    margin_basis_label: str = ""

    @property
    def fee_difference(self) -> Optional[Decimal]:
        """Recorded actual fees less planned, over the whole channel."""
        if self.actual_fee_total is None:
            return None
        return self.actual_fee_total - self.planned_fee_total

    @property
    def shipping_net(self) -> Decimal:
        """FR-024, at period scale."""
        return self.shipping_revenue - self.postage_paid


def absorb(
    *,
    key: str,
    label: str,
    total: Decimal,
    order_count: int,
) -> AbsorbedCost:
    """Spread ``total`` over ``order_count`` orders, or report it unabsorbed.

    The zero-order branch is the whole reason this is a function rather than a
    division: a channel that sold nothing still owed its subscription, and the
    honest report is "CA$X unabsorbed over 0 orders", not a crash and not a
    zero.
    """
    amount = Decimal(str(total))
    if order_count <= 0:
        if amount > ZERO:
            logger.info(f"{label} of {amount} could not be absorbed: the period has no orders")
        return AbsorbedCost(key=key, label=label, total=amount, order_count=0, per_order=None)
    return AbsorbedCost(
        key=key,
        label=label,
        total=amount,
        order_count=order_count,
        per_order=(amount / Decimal(order_count)).quantize(Decimal("0.0001")),
    )


def reconcile_category(
    category: str,
    *,
    planned: Decimal,
    actuals: Sequence["FeeActual"],
    strict: bool = False,
) -> CategoryReconciliation:
    """Plan against statement for one category (FR-041c, FR-041d).

    Order-scoped amounts take precedence: they are counted in full, and the
    period total's remainder is what is left after them. With ``strict``, an
    order-scoped total exceeding the period total raises rather than reporting
    a negative remainder -- which is what the write endpoint needs, so the
    contradiction is refused at the moment it would be created.
    """
    period_rows = [row for row in actuals if row.order_id is None]
    order_rows = [row for row in actuals if row.order_id is not None]

    period_total: Optional[Decimal] = None
    if period_rows:
        period_total = sum((Decimal(str(row.amount)) for row in period_rows), ZERO)

    order_total = sum((Decimal(str(row.amount)) for row in order_rows), ZERO)

    if period_total is None:
        remainder: Optional[Decimal] = None
        actual_total: Optional[Decimal] = order_total if order_rows else None
    else:
        remainder = period_total - order_total
        if remainder < ZERO:
            if strict:
                raise ReconciliationConflict(category, period_total, order_total)
            logger.warning(
                f"Order-scoped actuals for {category!r} exceed the period total by "
                f"{-remainder}; reporting the overrun rather than absorbing it"
            )
        # The period total is the authority on what the channel charged; the
        # order rows only say where inside it the money went. Counting both
        # would double the category.
        actual_total = period_total

    return CategoryReconciliation(
        category=category,
        planned=Decimal(str(planned)).quantize(CENT),
        actual_period=period_total.quantize(CENT) if period_total is not None else None,
        actual_order_scoped=order_total.quantize(CENT),
        unallocated_remainder=remainder.quantize(CENT) if remainder is not None else None,
        actual_total=actual_total.quantize(CENT) if actual_total is not None else None,
    )


def reconcile(
    planned_by_category: dict[str, Decimal],
    actuals: Iterable["FeeActual"],
    *,
    strict: bool = False,
) -> list[CategoryReconciliation]:
    """Reconcile every category that appears in either the plan or the record.

    A category recorded but never planned is as interesting as the reverse: it
    is a fee the operator is paying and has not modelled, which is exactly the
    gap this feature exists to close. Both directions therefore appear.
    """
    rows = list(actuals)
    categories = sorted(set(planned_by_category) | {row.fee_category for row in rows})
    return [
        reconcile_category(
            category,
            planned=planned_by_category.get(category, ZERO),
            actuals=[row for row in rows if row.fee_category == category],
            strict=strict,
        )
        for category in categories
    ]


def planned_total(stacks: Iterable[FeeStack]) -> dict[str, Decimal]:
    """Planned fees per category across a period's orders.

    Summed from the exact amounts and rounded once per category, for the same
    reason the margin chain does: a hundred orders' worth of rounding error is
    a figure that cannot be reconciled against anything.
    """
    totals: dict[str, Decimal] = {}
    for stack in stacks:
        for charge in stack.charges:
            totals[charge.name] = totals.get(charge.name, ZERO) + charge.amount_exact
    return {name: amount.quantize(CENT) for name, amount in totals.items()}
