"""Freezing what a sale earned, at the moment it is made (task T096).

FR-036 and FR-037 are one rule in two halves: record the cost breakdown, the
price, the fees and the exchange rate as they stood, and then never recompute
them. FR-038 is what the rule is *for* — changing a spool price, a labor rate,
an overhead setting or a fee rule must not alter any settled order's reported
margin.

Without this module the system would recompute a historical margin from today's
inputs, which silently restates last quarter's profit every time a figure
moves. That is not a reporting quirk; it is the reason an operator cannot
answer "did that product line make money last year".

## Written once

:func:`write_sale_snapshot` skips any line that already carries one. It is
therefore safe to call more than once — on order creation and again on
fulfilment, which is deliberate, because the three sale paths (the manual
order, the storefront checkout and the Shopify import) do not share a single
moment of sale. What they share is that the first call wins.

Nothing here ever *updates* a snapshot. A corrected cost is a variance to
report, not a figure to restate (FR-037, FR-028j).

## Allocating order-level fees across lines

A per-order fee is charged once on the order, but a snapshot lives on a line.
Recording the whole charge on every line would overstate the fees on a
three-line order threefold, and recording it on none would understate them. So
the fee stack is computed **once for the order** and each charge is allocated
across lines in proportion to line subtotal, with the rounding remainder given
to the largest line so the allocated shares sum to the charge exactly.

That is the same allocation a reconciliation would do, which is the point: the
lines' snapshotted fees add up to the fees the order was actually charged.

## A missing figure is missing, not zero

A line whose product has been deleted, or whose channel carries no fee rules,
or whose currency pair has no rate, records what it could and leaves the rest
null with a reason in the breakdown's ``incomplete_reasons``. A zero make-cost
on a settled order is indistinguishable from a real one, and would read as a
sale with no cost of goods at all.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models.fee_rule import FeeRule
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.sales_channel import SalesChannel
from app.models.tenant import Tenant
from app.services import fee_engine, fx_service
from app.services.cost_resolution import product_cost_breakdown
from app.services.costing import (
    PRICING_ENGINE_REV,
    CircularReferenceError,
    MaxDepthExceededError,
    resolve_margin_basis,
)
from app.services.pricing_policy import resolve_cost_policy
from app.services.temporal_pricing import price_as_of

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
CENT = Decimal("0.01")


@dataclass
class SnapshotResult:
    """What was frozen, and what could not be."""

    lines_written: int = 0
    lines_skipped: int = 0
    #: Lines that got a partial snapshot, with why. Reported rather than
    #: silently zeroed (FR-019).
    incomplete: list[str] = field(default_factory=list)

    @property
    def wrote_anything(self) -> bool:
        return self.lines_written > 0


def allocate_across_lines(
    amount: Decimal,
    weights: Sequence[Decimal],
) -> list[Decimal]:
    """Split ``amount`` over ``weights`` so the parts sum to it exactly.

    Pro-rata to the cent, with the rounding remainder given to the heaviest
    weight. The exactness is the requirement, not a nicety: a per-order fee
    whose allocated shares do not add up to the charge makes every
    reconciliation off by a cent for a reason nobody can find.

    All-zero weights split evenly — an order of free lines still carried its
    order-level fee, and refusing to allocate it would lose it.
    """
    count = len(weights)
    if count == 0:
        return []

    total_weight = sum(weights, ZERO)
    if total_weight <= ZERO:
        even = (amount / Decimal(count)).quantize(CENT)
        shares = [even] * count
    else:
        shares = [(amount * weight / total_weight).quantize(CENT) for weight in weights]

    remainder = amount.quantize(CENT) - sum(shares, ZERO)
    if remainder != ZERO:
        heaviest = max(range(count), key=lambda index: weights[index])
        shares[heaviest] += remainder
    return shares


def _charge_as_json(charge: "fee_engine.FeeCharge", amount: Decimal) -> dict:
    """One fee as it is stored on a line.

    Amounts are **strings**. A JSONB number is a float the moment anything
    reads it back, and this is a monetary figure that must survive the trip
    unchanged (Constitution IV) — a snapshot that drifts on deserialisation is
    not a snapshot.
    """
    return {
        "name": charge.name,
        "basis": charge.basis,
        "amount": str(amount),
        "rate_pct": str(charge.rate_pct),
        "fixed_amount": str(charge.fixed_amount),
        "basis_amount": str(charge.basis_amount),
        "clamp_applied": charge.clamp_applied,
        "is_expected": charge.is_expected,
        "order_amount": str(charge.amount_exact),
        "allocated": True,
    }


async def write_sale_snapshot(
    db: AsyncSession,
    tenant: Tenant,
    order: Order,
    *,
    as_of: Optional[date] = None,
    commit: bool = False,
) -> SnapshotResult:
    """Freeze each of ``order``'s lines, skipping any already frozen.

    ``order`` must have ``items`` loaded; this runs on a request thread where a
    lazy load raises. Nothing is committed unless ``commit`` is set, so the
    snapshot joins the same transaction as the sale that produced it — a sale
    that rolled back must not leave a snapshot of an order that never existed.
    """
    result = SnapshotResult()
    items: list[OrderItem] = list(getattr(order, "items", None) or [])
    if not items:
        return result

    pending = [item for item in items if not item.has_snapshot]
    result.lines_skipped = len(items) - len(pending)
    if not pending:
        return result

    reference = as_of or (
        order.created_at.date() if getattr(order, "created_at", None) else clock.today()
    )

    policy = await resolve_cost_policy(db, tenant, reference)
    basis = resolve_margin_basis(policy)

    channel: Optional[SalesChannel] = None
    if order.sales_channel_id is not None:
        channel = (
            await db.execute(
                select(SalesChannel).where(
                    SalesChannel.id == order.sales_channel_id,
                    SalesChannel.tenant_id == tenant.id,
                )
            )
        ).scalar_one_or_none()

    rules: list[FeeRule] = []
    if channel is not None:
        rules = list(
            (
                await db.execute(
                    select(FeeRule).where(
                        FeeRule.sales_channel_id == channel.id,
                        FeeRule.tenant_id == tenant.id,
                    )
                )
            )
            .scalars()
            .all()
        )

    # --- the exchange rate, frozen (FR-028f, FR-028j) ----------------------
    #
    # `resolve_rate` rather than `require_rate`: a sale is never blocked by
    # rate availability (FR-028i), so an unknown rate is recorded as unknown
    # and reported, not raised.
    frozen_rate: Optional[Decimal] = None
    books_currency = getattr(channel, "currency_code", None) or order.currency
    if order.currency and books_currency:
        resolved = await fx_service.resolve_rate(
            db, order.currency, books_currency, as_of=reference
        )
        if resolved is not None:
            frozen_rate = resolved.rate
            if resolved.is_stale:
                result.incomplete.append(
                    f"the exchange rate frozen onto this order is the last known one, "
                    f"from {resolved.as_of}: {resolved.reason}"
                )
        else:
            result.incomplete.append(
                f"no exchange rate was available for {order.currency}/{books_currency}, "
                f"so none was frozen onto this order -- it is recorded as unknown "
                f"rather than as parity"
            )

    # --- the order's fee stack, computed once ------------------------------
    allocations: dict[int, list[dict]] = {index: [] for index in range(len(items))}
    if channel is not None and rules:
        order_subtotal = sum((Decimal(str(item.total_price or ZERO)) for item in items), ZERO)
        context, _treatment = fee_engine.exclusive_context(
            item_subtotal=order_subtotal,
            shipping_revenue=Decimal(str(order.shipping_cost or ZERO)),
            quantity=sum(int(item.quantity or 0) for item in items) or 1,
            sales_tax_collected=Decimal(str(order.sales_tax_collected or ZERO)),
        )
        stack = fee_engine.compute(channel, context, reference, rules=rules)

        weights = [Decimal(str(item.total_price or ZERO)) for item in items]
        for charge in stack.charges:
            shares = allocate_across_lines(charge.amount_exact, weights)
            for index, share in enumerate(shares):
                allocations[index].append(_charge_as_json(charge, share))

    # --- per-line cost and price ------------------------------------------
    for index, item in enumerate(items):
        if item.has_snapshot:
            continue

        breakdown_json: Optional[dict] = None
        make_cost: Optional[Decimal] = None

        if item.product_id is not None:
            product = (
                await db.execute(
                    select(Product).where(
                        Product.id == item.product_id,
                        Product.tenant_id == tenant.id,
                    )
                )
            ).scalar_one_or_none()
            if product is not None:
                try:
                    breakdown = await product_cost_breakdown(db, tenant, product, policy=policy)
                except (CircularReferenceError, MaxDepthExceededError) as exc:
                    # A cycle in the operator's own bundle must not stop a sale
                    # being recorded. The gap is reported instead.
                    result.incomplete.append(
                        f"line {item.product_sku} could not be costed at sale: {exc}"
                    )
                else:
                    breakdown_json = breakdown.model_dump(mode="json")
                    make_cost = breakdown.total_make_cost
                    if breakdown.incomplete_reasons:
                        result.incomplete.extend(breakdown.incomplete_reasons)
            else:
                result.incomplete.append(
                    f"line {item.product_sku} refers to a product that is no longer "
                    f"readable, so no cost breakdown was frozen onto it"
                )
        else:
            result.incomplete.append(
                f"line {item.product_sku} has no product on record, so no cost "
                f"breakdown was frozen onto it"
            )

        # The channel list price in effect at sale, read temporally (FR-039).
        # Distinct from `unit_price`, which is what was actually charged: the
        # two differing is a discount, which is information rather than error.
        list_price: Optional[Decimal] = None
        if item.product_id is not None and order.sales_channel_id is not None:
            row = await price_as_of(
                db,
                item.product_id,
                order.sales_channel_id,
                as_of=reference,
                quantity=int(item.quantity or 1),
            )
            if row is not None and row.list_price is not None:
                list_price = Decimal(str(row.list_price))

        item.cost_breakdown_json = breakdown_json
        item.make_cost_at_sale = make_cost
        item.list_price_at_sale = list_price
        item.fees_json = allocations[index] or None
        item.fx_rate = frozen_rate
        item.margin_basis_at_sale = basis
        item.pricing_rev = PRICING_ENGINE_REV
        db.add(item)
        result.lines_written += 1

    if result.incomplete:
        # Deduplicated: a three-line order of the same product would otherwise
        # repeat one gap three times.
        result.incomplete = list(dict.fromkeys(result.incomplete))

    await db.flush()
    if commit:
        await db.commit()

    logger.info(
        f"Froze the sale snapshot on order {order.order_number}: "
        f"{result.lines_written} line(s) written, {result.lines_skipped} already frozen"
    )
    return result
