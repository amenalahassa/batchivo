"""What a production run's filament cost (T183, T254, T255, T265).

The run's money in one module, so it is held to the money paths' stricter
type-check (research D8) without the rest of the run workflow:

* the per-gram figure a run material is frozen at, from the spool's landed
  cost when the operator gives none;
* the realised unit cost each finished unit is recorded at, and the average
  over completed runs a model's cost screen shows, derived on read;
* the expected-against-actual summary analytics reads.

Exact throughout, rounded once at the stored column's scale.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production_run import ProductionRun, ProductionRunItem
from app.models.production_run_plate import ProductionRunPlate
from app.models.spool import Spool
from app.services.landed_cost import spool_landed_cost

#: The scale of the columns the realised figures are stored in, so the one
#: rounding in `record_actual_unit_costs` happens at the width the database
#: would round to anyway rather than at an arbitrary one.
PER_GRAM = Decimal("0.000001")
PER_UNIT = Decimal("0.0001")

#: The status a run reaches when its actuals are recordable. A plain string on
#: the column rather than an enum, so it is named once here.
COMPLETED = "completed"


@dataclass(frozen=True)
class MaterialCostSummary:
    """A run's filament cost, expected against actual (task T183).

    Three exact figures, unrounded. `actual` and `variance_percent` are `None`
    for a run with nothing recorded yet, which is a different fact from zero.
    """

    estimated: Decimal
    actual: Optional[Decimal]
    variance_percent: Optional[Decimal]


class MaterialCostUnderivable(ValueError):
    """A run material names no cost, and its spool cannot supply one (FR-019).

    Consumed material is history (Constitution VI): a zero written here would
    be a settled run costed as free filament forever. Refusing lets the
    operator fix the spool's price or weight, or type the figure.
    """


def run_material_cost_per_gram(spool: Spool, given: Optional[Decimal]) -> Decimal:
    """The per-gram figure a run material is frozen at.

    ``given`` is what the operator typed and wins. Otherwise it is the spool's
    landed cost per usable gram, with the purchase's shipping and tax, which
    the spool loads with it (T254).
    """
    if given is not None:
        return given
    landed = spool_landed_cost(spool)
    if landed.cost_per_gram is None or landed.cost_per_gram <= Decimal("0"):
        reasons = "; ".join(landed.incomplete_reasons) or "it derives to zero"
        raise MaterialCostUnderivable(
            f"no cost per gram was given for spool {spool.spool_id}, and none can be "
            f"derived from it: {reasons}"
        )
    return landed.cost_per_gram


@dataclass(frozen=True)
class RealisedUnitCost:
    """What one unit of a model actually cost, averaged over completed runs (T255).

    Derived on read from each run's immutable ``actual_cost_per_unit`` and the
    units that succeeded, in one unrounded chain (Constitution IV). Nothing is
    stored, so a run recorded late is weighted by its units like any other and
    no rounded average is ever fed back into the next one (Constitution V).
    """

    average: Decimal
    units: int
    last_completed_at: Optional[datetime]


def average_unit_cost(outcomes: list[tuple[Decimal, int]]) -> Optional[Decimal]:
    """Units-weighted mean of per-run unit costs, unrounded; ``None`` if none."""
    units = sum(quantity for _, quantity in outcomes if quantity > 0)
    if units <= 0:
        return None
    total = sum(
        (Decimal(str(cost)) * Decimal(quantity) for cost, quantity in outcomes if quantity > 0),
        Decimal("0"),
    )
    return total / Decimal(units)


async def realised_unit_costs(
    db: AsyncSession, tenant_id: UUID, model_ids: list[UUID]
) -> dict[UUID, RealisedUnitCost]:
    """The realised unit cost of each model, from its completed runs.

    A single-plate run records its unit cost per item, a multi-plate run per
    plate; each run is read from the one it used, so no unit counts twice.
    """
    if not model_ids:
        return {}

    item_rows = await db.execute(
        select(
            ProductionRunItem.model_id,
            ProductionRunItem.actual_cost_per_unit,
            ProductionRunItem.successful_quantity,
            ProductionRun.completed_at,
        )
        .join(ProductionRun, ProductionRunItem.production_run_id == ProductionRun.id)
        .where(
            ProductionRun.tenant_id == tenant_id,
            ProductionRun.status == COMPLETED,
            ProductionRun.total_plates == 0,
            ProductionRunItem.model_id.in_(model_ids),
            ProductionRunItem.actual_cost_per_unit.is_not(None),
            ProductionRunItem.successful_quantity > 0,
        )
    )
    plate_rows = await db.execute(
        select(
            ProductionRunPlate.model_id,
            ProductionRunPlate.actual_cost_per_unit,
            ProductionRunPlate.successful_prints,
            ProductionRun.completed_at,
        )
        .join(ProductionRun, ProductionRunPlate.production_run_id == ProductionRun.id)
        .where(
            ProductionRun.tenant_id == tenant_id,
            ProductionRun.status == COMPLETED,
            ProductionRun.total_plates > 0,
            ProductionRunPlate.model_id.in_(model_ids),
            ProductionRunPlate.actual_cost_per_unit.is_not(None),
            ProductionRunPlate.successful_prints > 0,
        )
    )

    rows: list[tuple[UUID, Decimal, int, Optional[datetime]]] = [
        (row[0], row[1], row[2], row[3]) for row in [*item_rows.all(), *plate_rows.all()]
    ]
    outcomes: dict[UUID, list[tuple[Decimal, int]]] = {}
    latest: dict[UUID, Optional[datetime]] = {}
    for model_id, cost, quantity, completed_at in rows:
        outcomes.setdefault(model_id, []).append((Decimal(str(cost)), int(quantity)))
        seen = latest.get(model_id)
        if completed_at is not None and (seen is None or completed_at > seen):
            latest[model_id] = completed_at

    result: dict[UUID, RealisedUnitCost] = {}
    for model_id, runs in outcomes.items():
        average = average_unit_cost(runs)
        if average is not None:
            result[model_id] = RealisedUnitCost(
                average=average,
                units=sum(quantity for _, quantity in runs),
                last_completed_at=latest.get(model_id),
            )
    return result


def record_actual_unit_costs(
    production_run: ProductionRun,
    *,
    total_material_cost: Decimal,
    successful_weight: Decimal,
) -> None:
    """Write what each finished unit actually cost in filament (FR-040).

    A recorded actual is one of the two deliberate exceptions to "nothing
    derived is stored": it is what a run consumed, not a figure the engine
    can re-derive once a spool price moves (Constitution III, task T164).

    The waste is distributed across the successful units rather than the
    attempted ones: a plate that failed half its parts put its filament into
    the parts that survived. The quotient is carried unrounded into each
    unit's multiplication and only the stored figures are quantized, to the
    scale of their columns (Constitution IV). Nothing is committed.
    """
    if successful_weight <= Decimal("0"):
        # No successful output, so nothing to attribute the filament to;
        # reported by its absence rather than as a free run (FR-019).
        return

    cost_per_gram = total_material_cost / successful_weight
    production_run.cost_per_gram_actual = cost_per_gram.quantize(PER_GRAM)
    production_run.successful_weight_grams = successful_weight

    units: list[ProductionRunItem] | list[ProductionRunPlate]
    if production_run.is_multi_plate and production_run.plates:
        units = list(production_run.plates)
    elif production_run.items:
        units = list(production_run.items)
    else:
        return

    for unit in units:
        if unit.model_weight_grams:
            unit.actual_cost_per_unit = (unit.model_weight_grams * cost_per_gram).quantize(PER_UNIT)


def material_cost_summary(production_run: ProductionRun) -> MaterialCostSummary:
    """What a run's filament was expected to cost and what it did (task T183).

    Exact and rounded nowhere; a caller that displays these rounds at its own
    edge. The actual is ``None`` for a run that has not completed, and the
    variance is ``None`` when either side is unknown or the estimate is zero
    (FR-019).
    """
    estimated = sum(
        (material.estimated_total_cost for material in production_run.materials),
        Decimal("0"),
    )

    actual: Optional[Decimal] = None
    variance_percent: Optional[Decimal] = None
    if production_run.status == COMPLETED:
        actual = sum(
            (material.total_cost for material in production_run.materials),
            Decimal("0"),
        )
        if estimated > Decimal("0"):
            variance_percent = ((actual - estimated) / estimated) * Decimal("100")

    return MaterialCostSummary(
        estimated=estimated,
        actual=actual,
        variance_percent=variance_percent,
    )
