"""Catalogue-wide shocks: "if filament rose 25%, what stops paying?"

## The one hard requirement

A scenario must not write a cost, a price or a provenance figure (FR-044d).
That is harder than it sounds, because the only honest way to shock a material
price is to change the figure the engine reads -- and the engine reads ORM
objects attached to a live session.

So the sweep runs inside a **savepoint that is always rolled back**. The
shocked figures are written to the objects, the engine reads them exactly as
it reads real ones, and the savepoint is discarded before the run's own state
is committed. The alternative -- a parallel "shocked" cost path that applies
percentages to a finished breakdown -- would be a second implementation of the
cost calculation, which the Constitution forbids outright and which would
quietly diverge: a material shock has to flow through the at-risk subtotal and
the failure premium to mean anything.

The policy side needs no savepoint: ``CostPolicy`` is a frozen dataclass, so a
shocked labor or electricity rate is a replacement value handed to the engine,
which is the same override mechanism the legacy comparison profile uses.

## What a result says

The shock, the inputs it ran against, how many products were evaluated, which
fell below the floor, and which could not be costed and why. A result read a
fortnight later is interpretable on its own (FR-044c) -- without that, an
operator cannot tell an old hypothetical from a current report.
"""

import logging
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import clock
from app.models.fee_rule import FeeRule
from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.product import Product
from app.models.product_pricing import ProductPricing
from app.models.sales_channel import SalesChannel
from app.models.scenario_run import ScenarioRun
from app.services import fee_engine
from app.services.cost_resolution import cost_load_options, product_cost_breakdown
from app.services.costing import (
    CircularReferenceError,
    CostingService,
    MaxDepthExceededError,
    resolve_margin_basis,
)
from app.services.pricing_policy import resolve_cost_policy

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.services.pricing_policy import CostPolicy

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")


class ShockIsEmpty(ValueError):
    """Raised for a scenario that changes nothing.

    A shock of zero is the margin report, which one request already answers.
    Queueing a catalogue sweep to recompute it would be a second way to ask an
    answered question (Constitution III), and the result would look like a
    forecast while being a restatement.
    """


@dataclass(frozen=True)
class Shock:
    """The overrides a scenario applies, each a relative percentage change.

    Relative rather than absolute on purpose: "filament up 25%" is a question
    an operator can ask about a catalogue of two hundred products, where "set
    every cost per gram to 0.04" is not a question about anything.

    Each lever is floored at -100%, which is where a cost reaches zero.
    Below that a cost goes negative and the whole sweep becomes nonsense
    dressed as analysis.
    """

    material_cost_pct: Decimal = ZERO
    labor_rate_pct: Decimal = ZERO
    fee_rate_pct: Decimal = ZERO
    electricity_rate_pct: Decimal = ZERO

    #: The levers, in the order a result lists them. ``ClassVar`` so the
    #: dataclass does not take it as a fifth field.
    FIELDS: ClassVar[tuple[str, ...]] = (
        "material_cost_pct",
        "labor_rate_pct",
        "fee_rate_pct",
        "electricity_rate_pct",
    )

    def __post_init__(self) -> None:
        for name in self.FIELDS:
            value = getattr(self, name)
            if value is None:
                object.__setattr__(self, name, ZERO)
                continue
            amount = Decimal(str(value))
            if amount < Decimal("-100"):
                raise ValueError(
                    f"{name} of {amount}% would make the figure negative; "
                    f"-100% is where it reaches zero"
                )
            object.__setattr__(self, name, amount)

    @property
    def is_empty(self) -> bool:
        return all(getattr(self, name) == ZERO for name in self.FIELDS)

    def factor(self, name: str) -> Decimal:
        """The multiplier for one lever: 25% becomes 1.25."""
        return Decimal("1") + getattr(self, name) / HUNDRED

    def as_json(self) -> dict[str, str]:
        """Decimal strings, never JSON numbers (Constitution IV)."""
        return {name: str(getattr(self, name)) for name in self.FIELDS}

    @classmethod
    def from_json(cls, data: Optional[dict[str, Any]]) -> "Shock":
        if not data:
            return cls()
        return cls(
            **{name: Decimal(str(data[name])) for name in cls.FIELDS if data.get(name) is not None}
        )


# ---------------------------------------------------------------------------
# Requesting one
# ---------------------------------------------------------------------------


async def request_run(
    db: AsyncSession,
    tenant: "Tenant",
    *,
    shock: Shock,
    margin_floor_pct: Decimal,
    sales_channel_id: Optional[UUID] = None,
    user: Optional["User"] = None,
) -> ScenarioRun:
    """Record the request. No calculation happens here.

    This is the whole of what ``POST /scenarios`` does before it answers
    (FR-044a): persist the question, so the handle it returns refers to
    something that survives the request, the worker and a pod restart.
    """
    if shock.is_empty:
        raise ShockIsEmpty("a scenario must change at least one figure")

    run = ScenarioRun(
        tenant_id=tenant.id,
        requested_by_user_id=getattr(user, "id", None),
        shock_json=shock.as_json(),
        margin_floor_pct=Decimal(str(margin_floor_pct)),
        inputs_json={"sales_channel_id": str(sales_channel_id) if sales_channel_id else None},
        state="queued",
    )
    db.add(run)
    await db.flush()
    return run


async def load_run(db: AsyncSession, tenant: "Tenant", run_id: UUID) -> Optional[ScenarioRun]:
    """One run, this tenant's only.

    Tenant-scoped in the query as well as by RLS, because ``rls_enabled`` is
    off in development and a scenario naming another tenant's products would
    be the worst possible leak: their whole catalogue, with margins.
    """
    return (
        await db.execute(
            select(ScenarioRun).where(
                ScenarioRun.id == run_id,
                ScenarioRun.tenant_id == tenant.id,
            )
        )
    ).scalar_one_or_none()


async def list_runs(
    db: AsyncSession, tenant: "Tenant", *, limit: int = 50, offset: int = 0
) -> tuple[list[ScenarioRun], int]:
    """This tenant's runs, newest first, with the total."""
    base = select(ScenarioRun).where(ScenarioRun.tenant_id == tenant.id)
    total = len((await db.execute(base)).scalars().all())
    rows = (
        (
            await db.execute(
                base.order_by(ScenarioRun.created_at.desc(), ScenarioRun.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return (list(rows), total)


# ---------------------------------------------------------------------------
# Running one
# ---------------------------------------------------------------------------


def _shocked_policy(policy: "CostPolicy", shock: Shock) -> "CostPolicy":
    """The operator's policy with the labor and power levers applied.

    A replacement rather than a mutation: ``CostPolicy`` is frozen precisely
    so a shocked figure cannot leak into the policy every other calculation in
    the process is reading.
    """
    labor = shock.factor("labor_rate_pct")
    power = shock.factor("electricity_rate_pct")
    return replace(
        policy,
        print_labor_rate=policy.print_labor_rate * labor,
        finishing_labor_rate=policy.finishing_labor_rate * labor,
        electricity_rate_per_kwh=(
            policy.electricity_rate_per_kwh * power
            if policy.electricity_rate_per_kwh is not None
            else None
        ),
        origin=f"scenario:{policy.origin}",
    )


async def _apply_material_shock(db: AsyncSession, tenant: "Tenant", shock: Shock) -> int:
    """Move every material's cost per gram, inside the caller's savepoint.

    Written to the rows the engine reads, so a shocked cost flows through the
    at-risk subtotal and the failure premium exactly as a real price rise
    would. The caller discards the savepoint, so none of it is ever committed.
    """
    factor = shock.factor("material_cost_pct")
    if factor == Decimal("1"):
        return 0

    rows = (
        (
            await db.execute(
                select(ModelMaterial)
                .join(Model, ModelMaterial.model_id == Model.id)
                .where(
                    # Tenant-scoped through the model, because `model_materials`
                    # carries no tenant_id of its own and RLS is off in
                    # development: an unscoped shock would read -- and under a
                    # lesser guarantee than a savepoint, write -- another
                    # tenant's costs.
                    Model.tenant_id == tenant.id,
                    ModelMaterial.cost_per_gram.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.cost_per_gram = Decimal(str(row.cost_per_gram)) * factor
    return len(rows)


async def _apply_fee_shock(db: AsyncSession, tenant: "Tenant", shock: Shock) -> int:
    """Move every fee rate, inside the caller's savepoint."""
    factor = shock.factor("fee_rate_pct")
    if factor == Decimal("1"):
        return 0

    rows = (await db.execute(select(FeeRule).where(FeeRule.tenant_id == tenant.id))).scalars().all()
    for row in rows:
        if row.rate_pct is not None:
            row.rate_pct = Decimal(str(row.rate_pct)) * factor
    return len(rows)


async def _priced_products(
    db: AsyncSession,
    tenant: "Tenant",
    *,
    reference: date,
    sales_channel_id: Optional[UUID],
) -> list[tuple[Product, SalesChannel, ProductPricing]]:
    """Every product with a price in effect, paired with its channel.

    A product nobody has listed is not swept. It is not a failure and not a
    skip: a shock answers "which of the things I sell stop paying", and an
    unlisted product is not one of them.
    """
    query = (
        select(ProductPricing)
        .join(ProductPricing.product)
        .where(
            Product.tenant_id == tenant.id,
            Product.is_active.is_(True),
            ProductPricing.valid_from <= reference,
        )
        .options(
            # The same cost-bearing tree the product endpoints load. A
            # relationship nobody loaded raises here -- or, worse, reads as
            # absent and reports a product cheaper than it is.
            selectinload(ProductPricing.product).options(*cost_load_options()),
            selectinload(ProductPricing.sales_channel).selectinload(SalesChannel.fee_rules),
        )
    )
    if sales_channel_id is not None:
        query = query.where(ProductPricing.sales_channel_id == sales_channel_id)

    pairs: list[tuple[Product, SalesChannel, ProductPricing]] = []
    for pricing in (await db.execute(query)).scalars().all():
        if pricing.valid_to is not None and pricing.valid_to < reference:
            continue
        if (pricing.min_quantity or 1) > 1:
            # A tier price is not this product's headline price, and sweeping
            # every tier would report the same product several times with
            # different answers.
            continue
        product = pricing.product
        channel = pricing.sales_channel
        if product is None or channel is None:  # pragma: no cover - FK-guarded
            continue
        pairs.append((product, channel, pricing))
    return pairs


async def _sweep(
    db: AsyncSession,
    tenant: "Tenant",
    run: ScenarioRun,
    *,
    shock: Shock,
    policy: "CostPolicy",
    reference: date,
) -> dict[str, Any]:
    """Cost and margin every listed product under the shock."""
    floor = Decimal(str(run.margin_floor_pct))
    channel_filter = None
    if run.inputs_json and run.inputs_json.get("sales_channel_id"):
        channel_filter = UUID(str(run.inputs_json["sales_channel_id"]))

    materials_shocked = await _apply_material_shock(db, tenant, shock)
    rules_shocked = await _apply_fee_shock(db, tenant, shock)

    pairs = await _priced_products(db, tenant, reference=reference, sales_channel_id=channel_filter)

    below_floor: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    margins: dict[str, Optional[str]] = {}
    evaluated = 0

    for product, channel, pricing in pairs:
        try:
            breakdown = await product_cost_breakdown(db, tenant, product, policy=policy)
        except (CircularReferenceError, MaxDepthExceededError) as exc:
            # The operator's own data is theirs to fix. Named rather than
            # swallowed: a sweep that silently omits a product reports a
            # catalogue that is cheaper than it is.
            skipped.append(
                {
                    "product_id": str(product.id),
                    "sku": product.sku,
                    "sales_channel_id": str(channel.id),
                    "reason": str(exc),
                }
            )
            continue

        context, treatment = fee_engine.exclusive_context(
            item_subtotal=Decimal(str(pricing.list_price)),
            quantity=1,
        )
        stack = fee_engine.compute(channel, context, reference, rules=list(channel.fee_rules or []))
        margin = CostingService.margin(
            context=context,
            make_cost=breakdown.total_make_cost,
            channel=channel,
            fees=stack,
            policy=policy,
            tax=treatment,
            machine_hours=breakdown.machine_hours,
            observed_share=breakdown.observed_share,
            assumed_share=breakdown.assumed_share,
        )
        evaluated += 1
        key = f"{product.id}:{channel.id}"
        margins[key] = str(margin.margin_pct) if margin.margin_pct is not None else None

        # A margin that is undefined -- fees consuming the whole basis -- is
        # below any floor. Treating it as "not below" would hide the worst case
        # the shock found.
        if margin.margin_pct is None or margin.margin_pct < floor:
            below_floor.append(
                {
                    "product_id": str(product.id),
                    "sku": product.sku,
                    "name": product.name,
                    "sales_channel_id": str(channel.id),
                    "channel_name": channel.name,
                    "list_price": str(margin.list_price),
                    "make_cost": str(margin.make_cost),
                    "margin_pct": (
                        str(margin.margin_pct) if margin.margin_pct is not None else None
                    ),
                    "profit": str(margin.profit),
                    "profit_per_machine_hour": (
                        str(margin.profit_per_machine_hour)
                        if margin.profit_per_machine_hour is not None
                        else None
                    ),
                    "shortfall_pct": (
                        str((floor - margin.margin_pct).quantize(Decimal("0.0001")))
                        if margin.margin_pct is not None
                        else None
                    ),
                }
            )

    return {
        "shock": shock.as_json(),
        "inputs": {
            "as_of": reference.isoformat(),
            "margin_basis": resolve_margin_basis(policy),
            "margin_floor_pct": str(run.margin_floor_pct),
            "labor_rate": str(policy.print_labor_rate),
            "electricity_rate_per_kwh": (
                str(policy.electricity_rate_per_kwh)
                if policy.electricity_rate_per_kwh is not None
                else None
            ),
            "overhead_method": policy.overhead_method,
            "policy_origin": policy.origin,
            "sales_channel_id": str(channel_filter) if channel_filter else None,
            "materials_shocked": materials_shocked,
            "fee_rules_shocked": rules_shocked,
        },
        "evaluated": evaluated,
        "below_floor": below_floor,
        "skipped": skipped,
        "margins": margins,
    }


async def execute_run(db: AsyncSession, tenant: "Tenant", run_id: UUID) -> ScenarioRun:
    """Run one scenario to completion and record what it found.

    Idempotent for a finished run: a worker retry returns the stored result
    rather than recomputing it, because a result an operator has read must not
    change underneath them.

    The state transitions are committed outside the savepoint, so a run that
    dies mid-sweep is left ``running`` with a start time rather than vanishing
    -- and the sweep's figures are discarded either way.
    """
    run = await load_run(db, tenant, run_id)
    if run is None:
        raise LookupError(f"scenario run {run_id} does not belong to this tenant")
    if run.is_terminal:
        return run

    run.state = "running"
    run.started_at = clock.now()
    db.add(run)
    await db.commit()

    shock = Shock.from_json(run.shock_json)
    reference = clock.today()

    result: Optional[dict[str, Any]] = None
    failure: Optional[str] = None

    savepoint = await db.begin_nested()
    try:
        policy = _shocked_policy(await resolve_cost_policy(db, tenant), shock)
        result = await _sweep(db, tenant, run, shock=shock, policy=policy, reference=reference)
    except Exception as exc:  # noqa: BLE001 - recorded on the run, never swallowed
        logger.error(f"Scenario run {run_id} failed: {exc}")
        failure = str(exc)
    finally:
        # Always. This is what makes FR-044d true rather than intended: every
        # shocked figure the sweep wrote is discarded here, on the success
        # path and the failure path alike.
        await savepoint.rollback()

    if failure is not None:
        run.state = "failed"
        run.error_text = failure
    else:
        assert result is not None
        run.result_json = result
        run.inputs_json = result["inputs"]
        run.state = "partial" if result["skipped"] else "succeeded"

    run.finished_at = clock.now()
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


__all__ = [
    "Shock",
    "ShockIsEmpty",
    "execute_run",
    "list_runs",
    "load_run",
    "request_run",
]
