"""The single authoritative implementation of model and product cost.

Constitution III: a domain calculation exists once. `Product.calculate_make_cost`
and `Product._calculate_model_cost` were a second, float-based implementation
with their own labor rate; they were deleted rather than kept in sync.

Tier 1 adds the lines the old model omitted -- machine occupancy, purge and
spool remainder, the plate/item and handling/finishing labor split, overhead
absorbed per machine-hour, and a failure premium applied only to the work
actually at risk. Those lines are computed **once**, in :func:`_item_lines`,
and read two ways:

* :meth:`CostingService.item_breakdown` returns the structured
  :class:`~app.schemas.model.CostBreakdown` -- every line with its amount, risk
  class, origin and date, the at-risk split, the premium and what was missing.
  This is what the API serves (FR-018, FR-019, FR-046).
* :meth:`CostingService.calculate_model_cost` returns the flat four-field shape
  the existing endpoints still publish. It is a projection of the same lines,
  not a second calculation.

**Rounding.** Figures are computed in one unrounded chain and rounded once, at
the end, for presentation (FR-047). The structured breakdown rounds each line
to the cent, which is the unit money is actually paid in, and totals the
rounded lines -- so the breakdown an operator reads adds up to the total they
are quoted. The flat projection keeps the three-decimal presentation its
callers already publish. Both read the same unrounded chain; where they differ
it is by less than a cent, and only in presentation.

Constitution IV: exact decimal arithmetic end to end. No binary float appears
in this module, and ``tests/unit/pricing/test_no_float_in_money_paths.py``
fails the build if one ever does.
"""

import dataclasses
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, AbstractSet, Any, Mapping, Optional, Sequence
from uuid import UUID

if TYPE_CHECKING:
    from app.models.model import Model
    from app.models.model_printer_config import ModelPrinterConfig
    from app.models.printer import Printer
    from app.models.product import Product
    from app.models.sales_channel import SalesChannel
    from app.services.provenance import FieldOrigin

from app.observability.tracing import traced
from app.schemas.model import CostBreakdown, CostLine, ModelCostBreakdown
from app.schemas.product import ProductCostBreakdown
from app.services.channel_economics import ChannelEconomics, channel_defaults
from app.services.fee_engine import (
    FeeCharge,
    FeeStack,
    OrderContext,
    TaxTreatment,
)
from app.services.landed_cost import (
    MaterialPerGram,
    _relationship_loaded,
    material_cost_per_gram,
)
from app.services.pricing_policy import CostPolicy

logger = logging.getLogger(__name__)


class CircularReferenceError(Exception):
    """Raised when a circular reference is detected in product components."""

    def __init__(self, product_id: UUID, visited: set):
        self.product_id = product_id
        self.visited = visited
        super().__init__(
            f"Circular reference detected: Product {product_id} already visited. "
            f"Chain: {' -> '.join(str(v) for v in visited)}"
        )


class MaxDepthExceededError(Exception):
    """Raised when product hierarchy exceeds maximum allowed depth."""

    def __init__(self, depth: int, max_depth: int):
        self.depth = depth
        self.max_depth = max_depth
        super().__init__(
            f"Product hierarchy too deep: depth {depth} exceeds maximum {max_depth}. "
            f"Consider flattening the product structure."
        )


# There is deliberately no default labor rate.
#
# A default here is what caused the defect this feature removes: every screen
# costed labor at 10.00/hour while the operator's configured rate sat unread in
# `Tenant.settings`. Constitution IV calls a hardcoded default that shadows a
# tenant setting a defect, not a fallback -- so `labor_rate` is required, and a
# caller that forgets it gets a TypeError rather than a plausible wrong number.
#
# The tenant's figures are resolved by `app/services/pricing_policy.py`, which
# reads the typed temporal policy table and falls back to the legacy settings
# reader for a tenant the Tier 1 migration has not reached.

# Maximum recursion depth for product cost calculation
MAX_RECURSION_DEPTH = 20

#: Which revision of this engine produced a figure, recorded on every sale
#: snapshot (``order_items.pricing_rev``).
#:
#: It exists so a historical margin can be attributed to the arithmetic that
#: made it. FR-037 forbids recomputing a settled figure, which means a snapshot
#: written by an older engine stays as it is -- and a reader comparing two
#: quarters' margins needs to know whether a step change was the business or
#: the engine.
#:
#: Bump this when a change alters what the engine would compute for unchanged
#: inputs. Revision 1 is the Tier 1-3 engine: the structured breakdown, the
#: at-risk split and failure premium, overhead per machine-hour, the fee rules
#: engine and the tax-exclusive margin.
PRICING_ENGINE_REV = 1

ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")
MILLE = Decimal("0.001")

#: How much weight a reader should give an origin, lowest first. A line is only
#: as trustworthy as its weakest input, so a line's reported origin is the
#: minimum over the inputs that built it (FR-001, FR-018).
_SOURCE_RANK: dict[str, int] = {"assumed": 0, "policy": 1, "measured": 2, "observed": 3}

#: Which lines the failure premium reaches (FR-015). Packaging materials and
#: packing labor are spent on a part already known good, so they never carry
#: it. Finishing does, which research.md D3 flags as a modelling choice rather
#: than a physical truth: strictly, a part that failed was never finished, and
#: keeping finishing at risk models the rework.
AT_RISK_KEYS: frozenset[str] = frozenset(
    {
        "material",
        "waste",
        "machine",
        "overhead",
        "labor_handling",
        "labor_finishing",
        "components",
    }
)

_LINE_LABELS: dict[str, str] = {
    "material": "Filament in the part",
    "waste": "Purge and priming",
    "machine": "Machine occupancy",
    "overhead": "Overhead",
    "labor_handling": "Handling labor",
    "labor_finishing": "Finishing labor",
    "labor_packing": "Packing labor",
    "packaging": "Packaging materials",
    "components": "Components",
    "child_products": "Child products",
    "assembly": "Assembly labor",
}

#: Presentation order for lines, so two breakdowns of the same product always
#: read the same way.
_LINE_ORDER: tuple[str, ...] = (
    "material",
    "waste",
    "machine",
    "overhead",
    "labor_handling",
    "labor_finishing",
    "components",
    "child_products",
    "labor_packing",
    "packaging",
    "assembly",
)


@dataclass(frozen=True)
class _Origin:
    """An origin reduced to the three things a line needs from it.

    ``pending`` is FR-042e: an observation has arrived that disputes this
    figure and is waiting for an operator to accept or reject it. The figure
    on the line is still the one in force -- telemetry proposes and does not
    reprice (Constitution VII) -- but a screen showing it must say that it is
    under review, or the operator reads a number the evidence already
    contradicts and has no way to know.
    """

    source: str
    as_of: Optional[date]
    pending: bool = False
    #: How far to believe an observed figure, in (0, 1], from the outcomes
    #: behind it (T259). ``None`` where confidence means nothing -- a policy
    #: decision, a hand measurement, an assumption.
    confidence: Optional[Decimal] = None


_DEFAULT_ORIGIN = _Origin(source="assumed", as_of=None)


def _policy_origin(policy: CostPolicy, *levers: str) -> _Origin:
    """The origin of a figure taken from the tenant's pricing policy.

    Per lever (T260): ``policy`` with the day an operator chose it, ``assumed``
    for a lever nobody has -- even on a row somebody wrote, which carries the
    levers it did not name forward. A figure built from several levers is as
    weak as the weakest of them. Hardcoding ``policy`` here presented a
    default rate nobody chose as a decision (task T219).
    """
    if not levers:
        return _Origin(source=policy.source, as_of=policy.effective_from)
    return _weakest(
        [
            _Origin(source=policy.lever_source(lever), as_of=policy.lever_as_of(lever))
            for lever in levers
        ]
    )


@dataclass
class _RawLine:
    """One cost line before presentation rounding."""

    key: str
    amount: Decimal
    source: str = "assumed"
    as_of: Optional[date] = None
    pending: bool = False
    confidence: Optional[Decimal] = None

    @property
    def risk_class(self) -> str:
        return "at_risk" if self.key in AT_RISK_KEYS else "not_at_risk"


@dataclass
class _ItemLines:
    """Every unrounded figure one printed item's cost is built from."""

    lines: list[_RawLine] = field(default_factory=list)
    prints_per_plate: Decimal = ONE
    print_hours_per_item: Optional[Decimal] = None
    machine_rate_per_hour: Optional[Decimal] = None
    expected_yield: Decimal = ONE
    failure_mode: str = "per_part"
    incomplete_reasons: list[str] = field(default_factory=list)

    def amount(self, key: str) -> Decimal:
        return sum((line.amount for line in self.lines if line.key == key), ZERO)

    @property
    def at_risk_total(self) -> Decimal:
        return sum((line.amount for line in self.lines if line.risk_class == "at_risk"), ZERO)

    @property
    def not_at_risk_total(self) -> Decimal:
        return sum((line.amount for line in self.lines if line.risk_class == "not_at_risk"), ZERO)

    @property
    def failure_divisor(self) -> Decimal:
        """What the at-risk portion is divided by (research.md D3).

        The stored yield is always a **per-part** success probability. The mode
        decides how one part's failure propagates: under ``per_part`` only that
        part is lost, so the divisor is ``y``; under ``per_plate`` one failure
        condemns the plate, so plate survival is ``y**N`` and the divisor is
        that. The two agree exactly at one print per plate, which is the
        boundary case the spec asserts.
        """
        if self.expected_yield >= ONE:
            return ONE
        if self.failure_mode != "per_plate":
            return self.expected_yield
        exponent = int(self.prints_per_plate) if self.prints_per_plate > ZERO else 1
        return self.expected_yield**exponent

    @property
    def failure_premium(self) -> Decimal:
        """What the yield figure adds to the at-risk portion, unrounded."""
        divisor = self.failure_divisor
        if divisor >= ONE or divisor <= ZERO:
            return ZERO
        return self.at_risk_total / divisor - self.at_risk_total

    @property
    def total(self) -> Decimal:
        return self.at_risk_total + self.failure_premium + self.not_at_risk_total


def _as_decimal(value: Any, default: Optional[Decimal] = None) -> Optional[Decimal]:
    """Exact conversion through ``str``.

    A value that arrived as a JSON number would otherwise carry binary floating
    point error into exact arithmetic, which defeats the point.
    """
    if value is None:
        return default
    return Decimal(str(value))


def _positive(value: Optional[Decimal]) -> Optional[Decimal]:
    return value if value is not None and value > ZERO else None


def _origin_of(
    origins: Optional[Mapping[tuple[str, uuid.UUID, str], "FieldOrigin"]],
    pending: Optional[AbstractSet[tuple[str, uuid.UUID, str]]],
    entity_type: str,
    entity_id: Optional[uuid.UUID],
    field_name: str,
) -> _Origin:
    """The recorded origin of one input, or its registry default.

    The engine never queries: origins are resolved once by the caller and
    handed in. With no map at all every input falls back to the registry's
    default, which is honest -- an unrecorded figure *is* an assumption, and a
    policy lever is a decision whether or not anyone wrote a row for it.
    """
    from app.services.provenance import REGISTRY

    entry = REGISTRY.get((entity_type, field_name))
    default_source = entry.default_source if entry is not None else "assumed"

    if origins is None or entity_id is None:
        return _Origin(source=default_source, as_of=None)

    # A proposal is held against a field whether or not anyone ever recorded
    # an origin for it, so this is read before the early return below.
    is_pending = pending is not None and (entity_type, entity_id, field_name) in pending

    recorded = origins.get((entity_type, entity_id, field_name))
    if recorded is None:
        return _Origin(source=default_source, as_of=None, pending=is_pending)
    return _Origin(
        source=recorded.source,
        as_of=recorded.as_of,
        pending=is_pending,
        confidence=recorded.confidence,
    )


def _weakest(origins: Sequence[_Origin]) -> _Origin:
    """Reduce several inputs' origins to the one a line can claim.

    A line is only as trustworthy as its weakest input: a labor figure built
    from a policy rate and an assumed number of minutes is an assumption. The
    date is the oldest of them, and unknown if any is unknown -- a line cannot
    honestly claim a date for a figure nobody recorded.
    """
    if not origins:
        return _DEFAULT_ORIGIN
    weakest = min(origins, key=lambda origin: _SOURCE_RANK.get(origin.source, 0))
    dates = [origin.as_of for origin in origins]
    oldest = None if any(value is None for value in dates) else min(d for d in dates if d)
    # Any disputed input makes the line disputed. The symmetry with `source` is
    # deliberate: a line is as weak as its weakest input and as under-review as
    # its most disputed one.
    # A line is as believable as its least believable observed input; the
    # others say nothing about confidence either way (T259).
    confidences = [origin.confidence for origin in origins if origin.confidence is not None]
    return _Origin(
        source=weakest.source,
        as_of=oldest,
        pending=any(origin.pending for origin in origins),
        confidence=min(confidences) if confidences else None,
    )


def _printer_config_for(
    model: "Model", printer: Optional["Printer"]
) -> Optional["ModelPrinterConfig"]:
    """The per-printer configuration for this model, if one exists.

    FR-011 costs an item at the rate of the machine it is planned on, and the
    per-printer row is where that machine's real print time and per-item weight
    live -- measured on that printer rather than estimated for the model in
    general. It therefore wins over the model-level figure whenever it exists
    (task T044).

    Returns ``None`` rather than raising when the relationship was not
    eager-loaded: the engine is synchronous, and a lazy load here would turn a
    pricing screen into a 500.
    """
    if printer is None:
        return None
    configs = getattr(model, "printer_configs", None)
    if not configs:
        return None
    for config in configs:
        if getattr(config, "printer_id", None) == printer.id:
            found: "ModelPrinterConfig" = config
            return found
    return None


def _material_origins(
    material: Any,
    resolved: MaterialPerGram,
    origins: Optional[Mapping[tuple[str, uuid.UUID, str], "FieldOrigin"]],
    pending: Optional[AbstractSet[tuple[str, uuid.UUID, str]]],
) -> list[_Origin]:
    """The inputs one bill-of-materials line's per-gram figure stands on.

    An override is one figure the operator typed. A derived figure is the
    spool's landed cost, so it is as trustworthy as the spool's price, weight
    and remainder and, where it has one, its purchase's shipping and tax.
    """
    if resolved.overridden:
        return [
            _origin_of(
                origins, pending, "model_material", getattr(material, "id", None), "cost_per_gram"
            )
        ]
    spool = resolved.spool
    if spool is None:
        return []
    spool_id = getattr(spool, "id", None)
    found = [
        _origin_of(origins, pending, "spool", spool_id, field_name)
        for field_name in ("purchase_price", "initial_weight", "unusable_remainder_grams")
    ]
    purchase_id = getattr(spool, "filament_purchase_id", None)
    if purchase_id is not None:
        found.extend(
            _origin_of(origins, pending, "filament_purchase", purchase_id, field_name)
            for field_name in ("inbound_shipping_cost", "tax_amount")
        )
    return found


def _average_cost_per_gram(model: "Model") -> Optional[Decimal]:
    """Weighted average landed cost per gram across the bill of materials.

    Used for purge, which is filament consumed off the part: it has no bill-of
    materials row of its own, and charging it at the average of what the part
    is actually printed in is the closest honest figure. A line whose cost
    cannot be derived is left out; the material line reports it.
    """
    materials = getattr(model, "materials", None) or []
    total_weight = ZERO
    total_cost = ZERO
    for material in materials:
        per_gram = material_cost_per_gram(material).cost_per_gram
        if per_gram is None:
            continue
        weight = _as_decimal(getattr(material, "weight_grams", None), ZERO) or ZERO
        total_weight += weight
        total_cost += weight * per_gram
    if total_weight <= ZERO:
        return None
    return total_cost / total_weight


def _labor_hours(model: "Model", prints_per_plate: Decimal) -> dict[str, Decimal]:
    """The four labor components, per sellable item.

    Per-plate preparation is divided across the plate's output and per-item
    work is not (FR-013), which is the whole reason the two are separate
    columns.

    ``labor_hours`` is the deprecated single figure. It is read only when the
    per-item column is absent or zero -- which is true for a record created
    before the Tier 1 migration copied one into the other, and for the
    in-memory fakes the unit tests build. Once the deprecated column is
    dropped this fallback goes with it.
    """
    per_plate = _as_decimal(getattr(model, "labor_hours_per_plate", None), ZERO) or ZERO
    per_item = _as_decimal(getattr(model, "labor_hours_per_item", None), ZERO) or ZERO
    finishing = _as_decimal(getattr(model, "finishing_hours_per_item", None), ZERO) or ZERO
    packing = _as_decimal(getattr(model, "packing_hours_per_item", None), ZERO) or ZERO

    if per_item == ZERO and per_plate == ZERO:
        deprecated = _as_decimal(getattr(model, "labor_hours", None), ZERO) or ZERO
        per_item = deprecated

    handling = per_item
    if per_plate > ZERO and prints_per_plate > ZERO:
        handling += per_plate / prints_per_plate

    return {"handling": handling, "finishing": finishing, "packing": packing}


def _planned_printer(model: "Model") -> Optional["Printer"]:
    """The machine the item is planned on, if one is set and loaded.

    Read from the instance state rather than the attribute, so an item built in
    memory or loaded without the relationship never triggers a query from
    inside the engine, which issues none.
    """
    state = getattr(model, "__dict__", {})
    return state.get("planned_printer")


def _item_lines(
    model: "Model",
    policy: CostPolicy,
    *,
    printer: Optional["Printer"] = None,
    origins: Optional[Mapping[tuple[str, uuid.UUID, str], "FieldOrigin"]] = None,
    pending: Optional[AbstractSet[tuple[str, uuid.UUID, str]]] = None,
) -> _ItemLines:
    """Every line of one printed item's cost, unrounded.

    This is the single place a printed item's cost is computed. Both the
    structured breakdown and the flat legacy shape read it, which is what keeps
    Constitution III true while two response shapes exist.
    """
    result = _ItemLines()
    model_id = getattr(model, "id", None)
    # A machine named by the caller (a queue job's assigned printer, the
    # `printer_id` a screen asks about) wins; otherwise the item's planned
    # machine; otherwise the policy's default rate (FR-011, T243).
    printer = printer or _planned_printer(model)
    config = _printer_config_for(model, printer)

    # ---------------------------------------------------------------- plate
    config_per_plate = _positive(_as_decimal(getattr(config, "prints_per_plate", None)))
    model_per_plate = _positive(_as_decimal(getattr(model, "prints_per_plate", None)))
    prints_per_plate = config_per_plate or model_per_plate or ONE
    result.prints_per_plate = prints_per_plate

    plate_origin = (
        _origin_of(
            origins,
            pending,
            "model_printer_config",
            getattr(config, "id", None),
            "prints_per_plate",
        )
        if config_per_plate is not None
        else _origin_of(origins, pending, "model", model_id, "prints_per_plate")
    )

    # ------------------------------------------------------------- material
    average_per_gram = _average_cost_per_gram(model)
    config_weight = _as_decimal(getattr(config, "material_weight_grams", None))

    material_origins: list[_Origin] = [plate_origin]
    if config_weight is not None and average_per_gram is not None:
        # The per-printer row records the weight for ONE item, measured on that
        # machine, so it is not divided by the plate count.
        material_cost = config_weight * average_per_gram
        for material in getattr(model, "materials", None) or []:
            resolved = material_cost_per_gram(material)
            result.incomplete_reasons.extend(
                f"material: {reason}" for reason in resolved.incomplete_reasons
            )
            material_origins.extend(_material_origins(material, resolved, origins, pending))
        material_origins.append(
            _origin_of(
                origins,
                pending,
                "model_printer_config",
                getattr(config, "id", None),
                "material_weight_grams",
            )
        )
    else:
        material_cost = ZERO
        for material in getattr(model, "materials", None) or []:
            resolved = material_cost_per_gram(material)
            for reason in resolved.incomplete_reasons:
                result.incomplete_reasons.append(f"material: {reason}")
            if resolved.cost_per_gram is None:
                # Not costed as zero (FR-019): the reason above makes the total
                # a floor, and the line carries what could be derived.
                continue
            weight = _as_decimal(getattr(material, "weight_grams", None), ZERO) or ZERO
            material_cost += weight * resolved.cost_per_gram
            material_id = getattr(material, "id", None)
            material_origins.append(
                _origin_of(origins, pending, "model_material", material_id, "weight_grams")
            )
            material_origins.extend(_material_origins(material, resolved, origins, pending))
        material_cost = material_cost / prints_per_plate

    if material_cost != ZERO:
        material_at = _weakest(material_origins)
        result.lines.append(
            _RawLine(
                "material",
                material_cost,
                material_at.source,
                material_at.as_of,
                material_at.pending,
                material_at.confidence,
            )
        )

    # ---------------------------------------------------------------- waste
    waste_grams = _as_decimal(getattr(model, "waste_grams", None), ZERO) or ZERO
    if waste_grams > ZERO:
        if average_per_gram is None:
            result.incomplete_reasons.append(
                "purge and priming waste is recorded but the bill of materials "
                "carries no per-gram cost to charge it at"
            )
        else:
            # Purge is consumed once per plate, so it divides across the plate's
            # output exactly as the part weight does.
            waste_cost = waste_grams * average_per_gram / prints_per_plate
            waste_at = _weakest(
                [_origin_of(origins, pending, "model", model_id, "waste_grams"), plate_origin]
            )
            result.lines.append(
                _RawLine(
                    "waste",
                    waste_cost,
                    waste_at.source,
                    waste_at.as_of,
                    waste_at.pending,
                    waste_at.confidence,
                )
            )

    # -------------------------------------------------------------- machine
    config_minutes = _positive(_as_decimal(getattr(config, "print_time_minutes", None)))
    model_minutes = _positive(_as_decimal(getattr(model, "print_time_minutes", None)))
    plate_minutes = config_minutes or model_minutes

    if plate_minutes is None:
        result.incomplete_reasons.append(
            "no print time is recorded, so this item carries no machine or "
            "per-hour overhead charge (FR-019)"
        )
    else:
        result.print_hours_per_item = plate_minutes / Decimal("60") / prints_per_plate

    time_origin = (
        _origin_of(
            origins,
            pending,
            "model_printer_config",
            getattr(config, "id", None),
            "print_time_minutes",
        )
        if config_minutes is not None
        else _origin_of(origins, pending, "model", model_id, "print_time_minutes")
    )

    machine_rate: Optional[Decimal] = None
    machine_origins: list[_Origin] = [time_origin, plate_origin]
    if printer is not None:
        derived = printer.machine_rate_components(policy.electricity_rate_per_kwh)
        machine_rate = derived["total"]
        if machine_rate is None:
            result.incomplete_reasons.append(
                f"printer {printer.name} has no machine cost policy "
                f"(missing: {', '.join(derived['missing'])}), so no machine rate "
                f"could be derived"
            )
        elif derived["missing"]:
            result.incomplete_reasons.append(
                f"printer {printer.name} has a partial machine cost policy "
                f"(missing: {', '.join(derived['missing'])}); the machine line "
                f"covers only what is recorded"
            )
        for field_name in (
            "purchase_price",
            "expected_lifetime_hours",
            "maintenance_reserve_total",
            "measured_watts",
            "electricity_rate_per_kwh",
        ):
            machine_origins.append(_origin_of(origins, pending, "printer", printer.id, field_name))

    if machine_rate is None:
        machine_rate = policy.default_machine_rate_per_hour
        if machine_rate is not None and printer is None:
            # FR-011: an item planned on no printer falls back to the policy rate.
            machine_origins.append(_policy_origin(policy, "default_machine_rate_per_hour"))

    if machine_rate is None and result.print_hours_per_item is not None:
        result.incomplete_reasons.append(
            "no machine rate is available for this item -- neither the printer "
            "it is planned on nor the pricing policy carries one -- so machine "
            "occupancy is not costed (FR-011, FR-019)"
        )

    result.machine_rate_per_hour = machine_rate

    if result.print_hours_per_item is not None and machine_rate is not None:
        machine_at = _weakest(machine_origins)
        result.lines.append(
            _RawLine(
                "machine",
                result.print_hours_per_item * machine_rate,
                machine_at.source,
                machine_at.as_of,
                machine_at.pending,
                machine_at.confidence,
            )
        )

    # ---------------------------------------------------------------- labor
    hours = _labor_hours(model, prints_per_plate)
    override = _as_decimal(getattr(model, "labor_rate_override", None))
    handling_rate = override if override is not None else policy.print_labor_rate
    finishing_rate = override if override is not None else policy.finishing_labor_rate

    def rate_origin_for(lever: str) -> _Origin:
        # Each line carries its own rate's origin (T260): the finishing rate
        # being a default nobody chose says nothing about the handling rate.
        if override is not None:
            return _origin_of(origins, pending, "model", model_id, "labor_rate_override")
        return _policy_origin(policy, lever)

    for key, hours_key, rate, field_name, lever in (
        ("labor_handling", "handling", handling_rate, "labor_hours_per_item", "print_labor_rate"),
        (
            "labor_finishing",
            "finishing",
            finishing_rate,
            "finishing_hours_per_item",
            "finishing_labor_rate",
        ),
        # Packing is handling work, charged at the handling rate; what matters
        # for FR-016 is that it is distinguishable from finishing, and for
        # FR-015 that the premium never reaches it.
        ("labor_packing", "packing", handling_rate, "packing_hours_per_item", "print_labor_rate"),
    ):
        component_hours = hours[hours_key]
        if component_hours <= ZERO:
            continue
        line_at = _weakest(
            [
                rate_origin_for(lever),
                _origin_of(origins, pending, "model", model_id, field_name),
                plate_origin,
            ]
        )
        result.lines.append(
            _RawLine(
                key,
                component_hours * rate,
                line_at.source,
                line_at.as_of,
                line_at.pending,
                line_at.confidence,
            )
        )

    # ----------------------------------------------------------- components
    component_cost = ZERO
    component_origins: list[_Origin] = []
    for component in getattr(model, "components", None) or []:
        quantity = _as_decimal(getattr(component, "quantity", None), ZERO) or ZERO
        unit_cost = _as_decimal(getattr(component, "unit_cost", None), ZERO) or ZERO
        component_cost += quantity * unit_cost
        component_id = getattr(component, "id", None)
        component_origins.append(
            _origin_of(origins, pending, "model_component", component_id, "quantity")
        )
        component_origins.append(
            _origin_of(origins, pending, "model_component", component_id, "unit_cost")
        )
    if component_cost != ZERO:
        component_at = _weakest(component_origins) if component_origins else _DEFAULT_ORIGIN
        result.lines.append(
            _RawLine(
                "components",
                component_cost,
                component_at.source,
                component_at.as_of,
                component_at.pending,
                component_at.confidence,
            )
        )

    # ------------------------------------------------------------- overhead
    model_pct = _positive(_as_decimal(getattr(model, "overhead_percentage", None)))
    overhead_rate = policy.overhead_rate_per_machine_hour

    if policy.overhead_method == "per_machine_hour" and model_pct is None:
        if overhead_rate is None:
            result.incomplete_reasons.append(
                "overhead is set to absorb per machine-hour but the pricing "
                "policy carries no pool and capacity, so no overhead is charged "
                "(FR-014, FR-019)"
            )
        elif result.print_hours_per_item is not None:
            overhead_at = _weakest(
                [
                    _policy_origin(
                        policy,
                        "overhead_method",
                        "overhead_monthly_pool",
                        "expected_monthly_machine_hours",
                    ),
                    time_origin,
                    plate_origin,
                ]
            )
            result.lines.append(
                _RawLine(
                    "overhead",
                    result.print_hours_per_item * overhead_rate,
                    overhead_at.source,
                    overhead_at.as_of,
                    overhead_at.pending,
                    overhead_at.confidence,
                )
            )
    else:
        # The percentage method, retained as an option (FR-014). Its base is
        # material plus labor, which is what every existing tenant's costs were
        # built from; changing the base silently would breach FR-050.
        percentage = model_pct if model_pct is not None else policy.overhead_percentage
        if percentage and percentage > ZERO:
            base = (
                result.amount("material")
                + result.amount("waste")
                + result.amount("labor_handling")
                + result.amount("labor_finishing")
                + result.amount("labor_packing")
            )
            overhead_at = (
                _origin_of(origins, pending, "model", model_id, "overhead_percentage")
                if model_pct is not None
                else _policy_origin(policy, "overhead_percentage")
            )
            result.lines.append(
                _RawLine(
                    "overhead",
                    base * percentage / Decimal("100"),
                    overhead_at.source,
                    overhead_at.as_of,
                    overhead_at.pending,
                    overhead_at.confidence,
                )
            )

    # ----------------------------------------------------------- yield mode
    # Not `or ONE`: a stored zero is falsy, and swallowing it here would hide
    # the misconfiguration this branch exists to report.
    expected_yield = _as_decimal(getattr(model, "expected_yield", None), ONE)
    if expected_yield is None:
        expected_yield = ONE
    if expected_yield <= ZERO:
        # The database CHECK refuses this; an in-memory object can still carry
        # it, and an infinite cost is worse than a reported misconfiguration.
        result.incomplete_reasons.append(
            "the expected yield is zero or negative, which is a configuration "
            "error rather than a cost; no failure premium was applied"
        )
        expected_yield = ONE
    elif expected_yield > ONE:
        result.incomplete_reasons.append(
            "the expected yield is above 100%, which cannot happen; no failure premium was applied"
        )
        expected_yield = ONE
    result.expected_yield = expected_yield

    mode = getattr(model, "failure_mode", None) or "per_part"
    result.failure_mode = mode if mode in ("per_part", "per_plate") else "per_part"

    return result


def _rounded_lines(raw: Sequence[_RawLine]) -> list[CostLine]:
    """Aggregate the raw lines by key, round to the cent, and order them.

    Aggregation is why a bundle's breakdown reads in the same terms as a single
    item's: three models' material becomes one material line rather than three
    anonymous ones. A merged line claims the weakest origin of its parts, since
    a total is no better evidenced than its worst input.
    """
    merged: dict[str, Decimal] = {}
    origins: dict[str, list[_Origin]] = {}
    for line in raw:
        merged[line.key] = merged.get(line.key, ZERO) + line.amount
        origins.setdefault(line.key, []).append(
            _Origin(line.source, line.as_of, line.pending, line.confidence)
        )

    order = {key: index for index, key in enumerate(_LINE_ORDER)}
    keys = sorted(merged, key=lambda key: (order.get(key, len(order)), key))

    lines: list[CostLine] = []
    for key in keys:
        amount = merged[key]
        if amount == ZERO:
            continue
        origin = _weakest(origins[key])
        lines.append(
            CostLine(
                key=key,
                label=_LINE_LABELS.get(key, key.replace("_", " ").capitalize()),
                amount=amount.quantize(CENT),
                risk_class=("at_risk" if key in AT_RISK_KEYS else "not_at_risk"),
                source=origin.source,  # type: ignore[arg-type]
                as_of=origin.as_of,
                has_pending_revision=origin.pending,
                confidence=origin.confidence,
            )
        )
    return lines


def _assemble(
    raw: Sequence[_RawLine],
    *,
    expected_yield: Decimal,
    failure_mode: str,
    failure_divisor: Decimal,
    incomplete_reasons: Sequence[str],
    machine_hours: Optional[Decimal] = None,
) -> CostBreakdown:
    """Build the served breakdown from raw lines, rounding once.

    Subtotals and the total are taken over the **rounded** lines, so the
    breakdown an operator reads adds up to the total they are quoted. The
    premium is derived from the rounded at-risk subtotal for the same reason.
    """
    from app.services.provenance import observed_share

    lines = _rounded_lines(raw)
    at_risk = sum((line.amount for line in lines if line.risk_class == "at_risk"), ZERO)
    not_at_risk = sum((line.amount for line in lines if line.risk_class == "not_at_risk"), ZERO)

    if failure_divisor >= ONE or failure_divisor <= ZERO:
        premium = ZERO
    else:
        premium = (at_risk / failure_divisor - at_risk).quantize(CENT)

    observed, assumed = observed_share(lines)

    return CostBreakdown(
        lines=lines,
        at_risk_subtotal=at_risk,
        not_at_risk_subtotal=not_at_risk,
        yield_applied=expected_yield,
        failure_mode=failure_mode,  # type: ignore[arg-type]
        failure_premium=premium,
        total_make_cost=at_risk + premium + not_at_risk,
        machine_hours=machine_hours,
        observed_share=observed.quantize(Decimal("0.0001")),
        assumed_share=assumed.quantize(Decimal("0.0001")),
        incomplete_reasons=list(dict.fromkeys(incomplete_reasons)),
    )


def _policy_from(
    policy: Optional[CostPolicy],
    labor_rate: Optional[Decimal],
    overhead_percentage: Optional[Decimal],
) -> CostPolicy:
    """Accept either a resolved policy or the two legacy figures.

    The flat endpoints still pass a labor rate and an overhead percentage. They
    are turned into a policy here rather than branching through the engine, so
    there is one shape of input to reason about.
    """
    if policy is not None:
        if overhead_percentage is not None:
            return policy.with_overhead_percentage(Decimal(str(overhead_percentage)))
        return policy
    if labor_rate is None:
        raise TypeError(
            "calculate_model_cost() requires either a resolved policy or a "
            "labor_rate; there is no default rate to fall back to "
            "(Constitution IV)"
        )
    rate = Decimal(str(labor_rate))
    return CostPolicy(
        print_labor_rate=rate,
        finishing_labor_rate=rate,
        overhead_method="percentage",
        overhead_percentage=(
            ZERO if overhead_percentage is None else Decimal(str(overhead_percentage))
        ),
        origin="caller_supplied",
    )


# ---------------------------------------------------------------------------
# Margin (tasks T071, T072)
# ---------------------------------------------------------------------------

#: What a margin percentage is taken over (FR-031), and how to say so beside
#: the figure (FR-031b). Two percentages must never be compared without
#: knowing they share a basis, which is only possible if every figure carries
#: its basis as data rather than as a convention.
MARGIN_BASIS_LABELS: dict[str, str] = {
    "customer_total": "of the total the customer paid",
    "item_price": "of the item price",
    "net_revenue": "of net revenue after fees",
}

#: The basis that reproduces the definition in use before this feature, so a
#: tenant who changes nothing sees no percentage move (FR-031a).
DEFAULT_MARGIN_BASIS = "customer_total"


@dataclass(frozen=True)
class RevenueDeduction:
    """One amount taken off revenue that is not a fee and not a cost.

    Expected discounts and an expected refund rate reduce *planned* net revenue
    (FR-026). They are reserves against revenue the operator has not lost yet,
    which is why they are neither a fee -- nobody charged them -- nor a cost:
    nothing was consumed. Keeping them as their own kind of line is what lets
    the reconciliation view compare planned fees against a statement without
    the reserves polluting the comparison.
    """

    key: str
    label: str
    amount: Decimal
    amount_exact: Decimal
    rate_pct: Decimal
    basis_amount: Decimal


@dataclass(frozen=True)
class MarginResult:
    """What one unit earns on one channel at one price, and on what basis.

    **Where the rounding happens.** Unlike :class:`CostBreakdown`, which sums
    rounded lines so an operator can add them up, this is one arithmetic chain
    whose end is a profit figure: the fees and reserves enter unrounded and the
    profit is rounded once. The two conventions differ by half a cent on the
    acceptance case, and which one each uses is pinned by its own test --
    rounding the fee stack early moves the acceptance margin off the figure the
    spec names, and summing the cost lines unrounded moves the make-cost off
    the figure the spec names. Both are deliberate.
    """

    # What was charged and what was earned
    list_price: Decimal
    shipping_revenue: Decimal
    make_cost: Decimal
    postage_paid: Decimal

    fees: list["FeeCharge"]
    fee_total: Decimal
    deductions: list[RevenueDeduction]
    deduction_total: Decimal

    #: Shipping revenue less postage paid, positive or negative. FR-024 makes
    #: this its own line because on a channel advertising free shipping it is
    #: usually the largest negative one, and netting it into either revenue or
    #: cost is how it went unnoticed.
    shipping_net: Decimal

    net_revenue: Decimal
    profit: Decimal

    #: ``None`` when the basis is zero or negative -- net revenue after fees
    #: with fees consuming the whole amount. Reported as undefined rather than
    #: divided by zero (spec, Edge Cases).
    margin_pct: Optional[Decimal]
    margin_basis: str
    margin_basis_label: str
    margin_basis_amount: Decimal

    # Tax: tracked, never revenue (FR-028c)
    sales_tax_collected: Decimal
    sales_tax_liability: Decimal
    tax_remitter: str
    #: True when the amounts handed in were tax-inclusive and the exclusive
    #: figures below were derived here (FR-028e).
    tax_exclusive_derived: bool
    revenue_tax_exclusive: Decimal

    #: Profit divided by the machine hours the unit occupies (FR-043).
    #:
    #: A first-class figure rather than something a screen derives, because in
    #: a print shop the binding constraint is the machine and not the money:
    #: ranked by percentage, a 2% margin on a forty-hour print outranks a
    #: healthy one on a two-hour print, and a shop run that way fills its
    #: printers with work that pays nothing.
    #:
    #: ``None`` where there are no machine hours -- a hand-assembled kit, or an
    #: item whose print time nobody recorded. Undefined is the honest answer:
    #: zero would read as "this earns nothing an hour" and sort it to the
    #: bottom of a ranking it does not belong in at all. Negative is kept as
    #: negative, since a product losing money per machine-hour is precisely
    #: what a capacity ranking exists to surface.
    profit_per_machine_hour: Optional[Decimal] = None
    #: The hours the figure above was divided by, so a reader can check it.
    machine_hours: Optional[Decimal] = None

    observed_share: Optional[Decimal] = None
    assumed_share: Optional[Decimal] = None
    incomplete_reasons: list[str] = field(default_factory=list)

    @property
    def margin_pct_display(self) -> Optional[Decimal]:
        """The percentage as a screen shows it: one decimal place."""
        if self.margin_pct is None:
            return None
        return self.margin_pct.quantize(Decimal("0.1"))


def resolve_margin_basis(
    policy: Optional[CostPolicy] = None,
    *,
    override: Optional[str] = None,
) -> str:
    """Which basis a percentage should be taken over (T072).

    ``override`` wins, and exists for exactly one caller: a settled order
    reports the basis that was in effect when it sold, not the one in effect
    now (FR-031d). Everything else reads the operator's policy, and a policy
    naming an unknown basis falls back to the default with a warning rather
    than raising -- a pricing screen that 500s because a string is misspelt is
    worse than one that says which basis it used.
    """
    candidate = override or (policy.margin_basis if policy is not None else None)
    if candidate in MARGIN_BASIS_LABELS:
        return candidate
    if candidate is not None:
        logger.warning(
            f"Unknown margin basis {candidate!r}; reporting on {DEFAULT_MARGIN_BASIS} instead"
        )
    return DEFAULT_MARGIN_BASIS


def basis_amount_for(
    basis: str,
    *,
    item_price: Decimal,
    customer_total: Decimal,
    fee_total_exact: Decimal,
) -> Decimal:
    """The denominator each basis puts under the profit (FR-031).

    Public because `margin_alert` recomputes a settled line's *planned* margin
    from its snapshot and has to put the same denominator under it. A second
    copy of this three-way choice is exactly the divergence Constitution III
    forbids -- two screens disagreeing about one percentage.
    """
    if basis == "item_price":
        return item_price
    if basis == "net_revenue":
        return customer_total - fee_total_exact
    return customer_total


@dataclass(frozen=True)
class MarginFigures:
    """A profit and the percentage it is over its basis, unrounded."""

    profit: Decimal
    basis_amount: Decimal
    #: Undefined, not zero, where the basis amount is nothing: zero reads as
    #: break-even and a division would read as a crash.
    margin_pct: Optional[Decimal]


def margin_of(
    *,
    item_price: Decimal,
    shipping_revenue: Decimal,
    fees: Decimal,
    make_cost: Decimal,
    postage_paid: Decimal,
    basis: str,
    refund: Decimal = ZERO,
    other_costs: Decimal = ZERO,
) -> MarginFigures:
    """The one derivation of a profit and a margin percentage (task T221).

    Every margin in the system comes through here: a quote
    (:meth:`CostingService.margin`), a settled line's planned margin
    (``margin_alert.planned_margin_pct``), its realised margin
    (``realised_margin``) and a channel period (``channel_pnl.period_margin``).
    Four copies of ``revenue - fees - cost - postage`` and two of the basis
    choice were four chances for two screens to disagree about one figure.

    ``refund`` is money given back. It comes off revenue on every basis --
    the item-price basis included -- so a refunded line never reports a
    healthy percentage of money it no longer has. ``other_costs`` reduce the
    profit and never the basis: the reserves a quote holds back (FR-026), or
    the absorbed periodic costs a period carries (FR-025).

    Nothing is rounded; the caller rounds once, at its edge.
    """
    customer_total = item_price + shipping_revenue - refund
    profit = customer_total - fees - make_cost - postage_paid - other_costs
    basis_amount = basis_amount_for(
        basis,
        item_price=item_price - refund,
        customer_total=customer_total,
        fee_total_exact=fees,
    )
    margin_pct = (
        (profit / basis_amount * Decimal("100")).quantize(Decimal("0.0001"))
        if basis_amount > ZERO
        else None
    )
    return MarginFigures(profit=profit, basis_amount=basis_amount, margin_pct=margin_pct)


class CostingService:
    """The single authoritative implementation of model and product cost."""

    # ------------------------------------------------------------------
    # The structured breakdown (Tier 1)
    # ------------------------------------------------------------------

    @staticmethod
    @traced("cost.item_breakdown")
    def item_breakdown(
        model: "Model",
        *,
        policy: Optional[CostPolicy] = None,
        labor_rate: Optional[Decimal] = None,
        overhead_percentage: Optional[Decimal] = None,
        printer: Optional["Printer"] = None,
        origins: Optional[Mapping[tuple[str, uuid.UUID, str], "FieldOrigin"]] = None,
        pending: Optional[AbstractSet[tuple[str, uuid.UUID, str]]] = None,
    ) -> CostBreakdown:
        """The full cost of one printed item, itemised (FR-018).

        Every line carries its amount, its risk class, where its inputs came
        from and when they were set (FR-001). What was missing is reported in
        ``incomplete_reasons`` rather than costed at zero (FR-019).
        """
        resolved = _policy_from(policy, labor_rate, overhead_percentage)
        raw = _item_lines(model, resolved, printer=printer, origins=origins, pending=pending)
        return _assemble(
            raw.lines,
            expected_yield=raw.expected_yield,
            failure_mode=raw.failure_mode,
            failure_divisor=raw.failure_divisor,
            incomplete_reasons=raw.incomplete_reasons,
            machine_hours=raw.print_hours_per_item,
        )

    @staticmethod
    @traced("cost.product_breakdown")
    def product_breakdown(
        product: "Product",
        *,
        policy: Optional[CostPolicy] = None,
        labor_rate: Optional[Decimal] = None,
        overhead_percentage: Optional[Decimal] = None,
        printer_for_model: Optional[Mapping[uuid.UUID, "Printer"]] = None,
        origins: Optional[Mapping[tuple[str, uuid.UUID, str], "FieldOrigin"]] = None,
        pending: Optional[AbstractSet[tuple[str, uuid.UUID, str]]] = None,
        _visited: Optional[set] = None,
        _depth: int = 0,
    ) -> CostBreakdown:
        """The full cost of one sellable unit, itemised and recursive.

        Bundles still cost recursively, with the cycle detection and depth
        limit preserved (FR-017). A child's lines are aggregated into the
        parent's by key, so a bundle's breakdown reads in the same terms as a
        single item's, and a child's own failure premium is carried across
        rather than recomputed -- applying a parent yield on top of it would
        charge for the same failures twice.
        """
        resolved = _policy_from(policy, labor_rate, overhead_percentage)

        if _depth > MAX_RECURSION_DEPTH:
            raise MaxDepthExceededError(_depth, MAX_RECURSION_DEPTH)

        if _visited is None:
            _visited = set()
        if product.id in _visited:
            raise CircularReferenceError(product.id, _visited)
        _visited = _visited.copy()
        _visited.add(product.id)

        raw: list[_RawLine] = []
        inherited_premium = ZERO
        inherited_at_risk = ZERO
        # Machine occupancy totals across the bundle so the one engine that
        # knows each item's print time is also the one that reports the
        # bundle's. `None` until some child reports hours, so a product nobody
        # has timed stays unknown rather than becoming a zero that reads as an
        # item occupying no machine (FR-019).
        inherited_machine_hours: Optional[Decimal] = None
        reasons: list[str] = []
        modes: set[str] = set()
        yields: set[Decimal] = set()

        def absorb(breakdown: CostBreakdown, quantity: Decimal) -> None:
            nonlocal inherited_premium, inherited_at_risk, inherited_machine_hours
            if breakdown.machine_hours is not None:
                inherited_machine_hours = (
                    inherited_machine_hours or ZERO
                ) + breakdown.machine_hours * quantity
            for line in breakdown.lines:
                raw.append(
                    _RawLine(
                        key=line.key,
                        amount=line.amount * quantity,
                        source=line.source,
                        as_of=line.as_of,
                        pending=line.has_pending_revision,
                        confidence=line.confidence,
                    )
                )
            inherited_premium += breakdown.failure_premium * quantity
            inherited_at_risk += breakdown.at_risk_subtotal * quantity
            reasons.extend(breakdown.incomplete_reasons)
            modes.add(breakdown.failure_mode)
            yields.add(breakdown.yield_applied)

        for pm in getattr(product, "product_models", None) or []:
            model = getattr(pm, "model", None)
            if model is None:
                continue
            quantity = _as_decimal(getattr(pm, "quantity", None), ONE) or ONE
            model_id = getattr(model, "id", None)
            printer = (printer_for_model or {}).get(model_id) if model_id is not None else None
            absorb(
                CostingService.item_breakdown(
                    model,
                    policy=resolved,
                    printer=printer,
                    origins=origins,
                    pending=pending,
                ),
                quantity,
            )

        for pc in getattr(product, "child_products", None) or []:
            child = getattr(pc, "child_product", None)
            if child is None:
                continue
            quantity = _as_decimal(getattr(pc, "quantity", None), ONE) or ONE
            absorb(
                CostingService.product_breakdown(
                    child,
                    policy=resolved,
                    printer_for_model=printer_for_model,
                    origins=origins,
                    pending=pending,
                    _visited=_visited,
                    _depth=_depth + 1,
                ),
                quantity,
            )

        # Packaging: materials consumed after the part is good, so never at risk
        # (FR-015, FR-016). The existing packaging path is reused as-is.
        packaging_cost, packaging_origin = _packaging_cost(product, origins, pending)
        if packaging_cost != ZERO:
            raw.append(
                _RawLine(
                    "packaging",
                    packaging_cost,
                    packaging_origin.source,
                    packaging_origin.as_of,
                    packaging_origin.pending,
                    packaging_origin.confidence,
                )
            )

        assembly_minutes = _as_decimal(getattr(product, "assembly_minutes", None), ZERO) or ZERO
        if assembly_minutes > ZERO:
            assembly_origin = _origin_of(
                origins, pending, "product", getattr(product, "id", None), "assembly_minutes"
            )
            raw.append(
                _RawLine(
                    "assembly",
                    assembly_minutes / Decimal("60") * resolved.print_labor_rate,
                    assembly_origin.source,
                    assembly_origin.as_of,
                    assembly_origin.pending,
                    assembly_origin.confidence,
                )
            )

        # The parent applies no yield of its own: its children's premiums are
        # already in `inherited_premium`. The yield reported is the one those
        # premiums imply, so the figure stays explainable and the invariant
        # total = at_risk + premium + not_at_risk still holds.
        breakdown = _assemble(
            raw,
            expected_yield=ONE,
            failure_mode=(modes.pop() if len(modes) == 1 else "per_part"),
            failure_divisor=ONE,
            incomplete_reasons=reasons,
            machine_hours=inherited_machine_hours,
        )

        if inherited_premium <= ZERO:
            return breakdown

        at_risk = breakdown.at_risk_subtotal
        if len(yields) == 1:
            # Every child shares one yield figure, which is the usual case and
            # the only one where a single figure is the literal truth.
            reported_yield = yields.pop()
        else:
            # Several yields blended: report the figure the premium implies, so
            # the number on screen still explains the premium beside it.
            reported_yield = (
                (at_risk / (at_risk + inherited_premium)).quantize(Decimal("0.0001"))
                if at_risk > ZERO
                else ONE
            )
        return breakdown.model_copy(
            update={
                "yield_applied": reported_yield if reported_yield > ZERO else ONE,
                "failure_premium": inherited_premium,
                "total_make_cost": at_risk + inherited_premium + breakdown.not_at_risk_subtotal,
            }
        )

    # ------------------------------------------------------------------
    # The flat shapes the existing endpoints publish
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_model_cost(
        model: "Model",
        labor_rate: Optional[Decimal] = None,
        overhead_percentage: Optional[Decimal] = None,
        *,
        policy: Optional[CostPolicy] = None,
        printer: Optional["Printer"] = None,
    ) -> ModelCostBreakdown:
        """Model cost in the flat four-field shape the endpoints still publish.

        A projection of :func:`_item_lines`, not a second calculation: material
        and purge are reported together, the three labor components are
        reported together, and the total carries every Tier 1 line including
        machine occupancy and the failure premium.

        Args:
            model: Model instance with materials and components loaded
            labor_rate: The tenant's configured hourly labor rate. Required
                unless ``policy`` is given -- see the note above on why there is
                no default.
            overhead_percentage: The tenant's default overhead percentage
                (0-100), used only for a model that sets none of its own.
            policy: A resolved policy snapshot, which carries the machine rate,
                the overhead method and the two labor rates.
            printer: The machine this item is planned on, whose cost policy
                gives the machine rate (FR-011).
        """
        resolved = _policy_from(policy, labor_rate, overhead_percentage)
        raw = _item_lines(model, resolved, printer=printer)

        material_cost = raw.amount("material") + raw.amount("waste")
        component_cost = raw.amount("components")
        labor_cost = (
            raw.amount("labor_handling")
            + raw.amount("labor_finishing")
            + raw.amount("labor_packing")
        )
        overhead_cost = raw.amount("overhead")

        return ModelCostBreakdown(
            material_cost=material_cost.quantize(MILLE),
            component_cost=component_cost.quantize(MILLE),
            labor_cost=labor_cost.quantize(MILLE),
            overhead_cost=overhead_cost.quantize(MILLE),
            total_cost=raw.total.quantize(MILLE),
            incomplete_reasons=list(dict.fromkeys(raw.incomplete_reasons)),
        )

    @staticmethod
    def calculate_product_cost(
        product: "Product",
        labor_rate: Optional[Decimal] = None,
        overhead_percentage: Optional[Decimal] = None,
        _visited: Optional[set] = None,
        _depth: int = 0,
        *,
        policy: Optional[CostPolicy] = None,
        printer_for_model: Optional[Mapping[uuid.UUID, "Printer"]] = None,
        realised_unit_costs: Optional[Mapping[uuid.UUID, Decimal]] = None,
    ) -> ProductCostBreakdown:
        """
        Calculate total product (sellable item) cost with breakdown.

        Supports nested products (bundles containing other products) with
        recursive cost calculation and circular reference detection.

        Args:
            product: Product instance with product_models and child_products loaded
            labor_rate: The tenant's configured hourly labor rate. Required
                unless ``policy`` is given. It is forwarded to every nested
                model and child product, so one product cost is never built
                from two different labor rates.
            overhead_percentage: The tenant's default overhead percentage (0-100),
                forwarded to nested models that set none of their own.
            _visited: Internal set for cycle detection (do not pass manually)
            _depth: Internal recursion depth counter (do not pass manually)
            policy: A resolved policy snapshot, forwarded unchanged.
            printer_for_model: Which machine each model is planned on (FR-011).
            realised_unit_costs: Each model's realised unit cost, averaged over
                its completed runs and derived on read by
                ``production_run.realised_unit_costs`` (T255). The engine does
                not query, so a caller that shows actual costs resolves these
                first; without them no actual cost is reported.

        Returns:
            ProductCostBreakdown with models cost, child products cost, packaging,
            assembly, and total make cost

        Raises:
            CircularReferenceError: If a circular reference is detected in product hierarchy
            MaxDepthExceededError: If product hierarchy exceeds MAX_RECURSION_DEPTH
        """
        resolved = _policy_from(policy, labor_rate, overhead_percentage)

        # The total is the structured breakdown's, never a second sum: this
        # shape used to add per-model totals already rounded to 0.001 and
        # rounded again, so the list and the detail disagreed with `/cost`,
        # the margin and the snapshot by a cent (T239, FR-047, FR-048). The
        # breakdown also does the cycle and depth checks.
        breakdown = CostingService.product_breakdown(
            product,
            policy=resolved,
            printer_for_model=printer_for_model,
            _visited=_visited,
            _depth=_depth,
        )
        total_make_cost = breakdown.total_make_cost
        incomplete_reasons: list[str] = list(breakdown.incomplete_reasons)

        # The flat fields split that same total by where each line came from.
        # Each part is the engine's own unrounded figure, so the parts still
        # add up to the total exactly.
        models_cost = ZERO
        models_actual_cost = ZERO
        models_with_actual_cost = 0
        models_total = 0
        seen_model_ids: set = set()
        for pm in getattr(product, "product_models", None) or []:
            model = getattr(pm, "model", None)
            if model is None:
                continue
            quantity = _as_decimal(getattr(pm, "quantity", None), ONE) or ONE
            item = CostingService.item_breakdown(
                model,
                policy=resolved,
                printer=(printer_for_model or {}).get(model.id),
            )
            models_cost += quantity * item.total_make_cost

            # Phase 3: actual production cost, where the model records one
            actual = (realised_unit_costs or {}).get(model.id)
            if model.id not in seen_model_ids:
                seen_model_ids.add(model.id)
                models_total += 1
                if actual is not None:
                    models_with_actual_cost += 1
            if actual is not None:
                models_actual_cost += quantity * actual

        child_products_cost = ZERO
        for pc in getattr(product, "child_products", None) or []:
            child = getattr(pc, "child_product", None)
            if child is None:
                continue
            quantity = _as_decimal(getattr(pc, "quantity", None), ONE) or ONE
            child_products_cost += (
                quantity
                * CostingService.product_breakdown(
                    child, policy=resolved, printer_for_model=printer_for_model
                ).total_make_cost
            )

        # The breakdown's "packaging" and "assembly" lines include the
        # children's, so this product's own are taken from the one packaging
        # helper and the remainder -- which is what assembly is.
        packaging_cost, _packaging_origin = _packaging_cost(product, None)
        assembly_cost = total_make_cost - models_cost - child_products_cost - packaging_cost

        # 6. Phase 3: Calculate actual total cost and variance if we have actual data
        total_actual_cost = None
        cost_variance_percentage = None

        if models_with_actual_cost > 0 and models_total > 0:
            # Only calculate total actual cost if ALL models have actual data
            if models_with_actual_cost == models_total:
                total_actual_cost = (
                    models_actual_cost + child_products_cost + packaging_cost + assembly_cost
                )
                # Calculate variance: (actual - theoretical) / theoretical * 100
                if total_make_cost > 0:
                    cost_variance_percentage = (
                        (total_actual_cost - total_make_cost) / total_make_cost * Decimal("100")
                    )

        return ProductCostBreakdown(
            models_cost=models_cost.quantize(Decimal("0.01")),
            child_products_cost=child_products_cost.quantize(Decimal("0.01")),
            packaging_cost=packaging_cost.quantize(Decimal("0.01")),
            assembly_cost=assembly_cost.quantize(Decimal("0.01")),
            total_make_cost=total_make_cost.quantize(Decimal("0.01")),
            # Phase 3 fields
            models_actual_cost=models_actual_cost.quantize(Decimal("0.01"))
            if models_with_actual_cost > 0
            else None,
            total_actual_cost=total_actual_cost.quantize(Decimal("0.01"))
            if total_actual_cost is not None
            else None,
            cost_variance_percentage=cost_variance_percentage.quantize(Decimal("0.01"))
            if cost_variance_percentage is not None
            else None,
            models_with_actual_cost=models_with_actual_cost,
            models_total=models_total,
            incomplete_reasons=list(dict.fromkeys(incomplete_reasons)),
        )

    # ------------------------------------------------------------------
    # Margin (tasks T071, T072)
    # ------------------------------------------------------------------

    @staticmethod
    @traced("cost.margin")
    def margin(
        *,
        context: OrderContext,
        make_cost: Decimal,
        channel: "SalesChannel",
        fees: FeeStack,
        policy: Optional[CostPolicy] = None,
        economics: Optional[ChannelEconomics] = None,
        tax: Optional[TaxTreatment] = None,
        postage_paid: Decimal = ZERO,
        margin_basis: Optional[str] = None,
        machine_hours: Optional[Decimal] = None,
        observed_share: Optional[Decimal] = None,
        assumed_share: Optional[Decimal] = None,
        incomplete_reasons: Sequence[str] = (),
    ) -> MarginResult:
        """What one unit earns on ``channel`` at the price ``context`` carries.

        ``context`` is the **tax-exclusive** order built by
        :func:`app.services.fee_engine.exclusive_context`, and it is the same
        object the fee stack was computed from. That is deliberate and it is
        the one invariant this signature exists to enforce: a price cannot be
        charged fees on one amount and divided by another. Margin is computed
        on tax-exclusive amounts under every basis and on every channel
        (FR-028a), so the tax comes out once, upstream, and ``tax`` carries
        what was removed so the result can report it (FR-028e).

        The rest of the chain, in the order the arithmetic runs:

        1. **The fees, unrounded.** Shipping revenue is never netted before
           them (FR-023).
        2. **The reserves.** An expected discount and an expected refund rate
           reduce planned net revenue (FR-026).
        3. **What the sale cost**: the make-cost, and the postage the operator
           paid -- a cost, not a reduction of revenue, whose difference from
           shipping revenue is reported as its own line (FR-024).
        4. **The basis the operator chose**, named beside the figure (FR-031b).

        Nothing here is stored. A margin is recomputed on demand
        (Constitution V); the one figure ever frozen is the snapshot written on
        a settled order line at the moment of sale, and that path passes
        ``margin_basis`` so the order keeps the basis it sold on (FR-031d).
        """
        treatment = tax if tax is not None else TaxTreatment()
        item_price = Decimal(str(context.item_subtotal))
        shipping = Decimal(str(context.shipping_revenue))
        postage = Decimal(str(postage_paid))
        cost = Decimal(str(make_cost))
        collected = Decimal(str(treatment.collected))

        customer_total = item_price + shipping
        exclusive_total = customer_total
        tax_exclusive_derived = treatment.derived_from_inclusive

        # --- 1. Fees, unrounded (research.md D9) ---------------------------
        fee_total_exact = fees.total_exact

        # --- 2. Reserves against revenue (FR-026) --------------------------
        # The reserves are effective-dated (FR-003, task T136), so they are an
        # input resolved by the caller that knows which date applies -- the
        # sale date for a settled line, today for a quote. Falling back to the
        # channel's own columns keeps a stand-in without a session working.
        rates = economics if economics is not None else channel_defaults(channel)
        deductions: list[RevenueDeduction] = []
        for key, label, rate in (
            (
                "expected_discount",
                "Expected discounts",
                rates.expected_discount_pct,
            ),
            (
                "expected_refund",
                "Refund reserve",
                rates.expected_refund_pct,
            ),
        ):
            if rate == ZERO:
                continue
            amount = customer_total * rate / Decimal("100")
            deductions.append(
                RevenueDeduction(
                    key=key,
                    label=label,
                    amount=amount.quantize(CENT),
                    amount_exact=amount,
                    rate_pct=rate,
                    basis_amount=customer_total,
                )
            )
        deduction_total_exact = sum((d.amount_exact for d in deductions), ZERO)

        # --- 3 and 4. What the sale cost, and the percentage over the basis -
        # The reserves reduce profit, not the basis the percentage is over.
        net_revenue_exact = customer_total - fee_total_exact - deduction_total_exact
        basis = resolve_margin_basis(policy, override=margin_basis)
        figures = margin_of(
            item_price=item_price,
            shipping_revenue=shipping,
            fees=fee_total_exact,
            make_cost=cost,
            postage_paid=postage,
            basis=basis,
            other_costs=deduction_total_exact,
        )
        profit_exact = figures.profit
        basis_amount = figures.basis_amount
        margin_pct = figures.margin_pct

        # --- 5. What the machine time earned (FR-043) ----------------------
        # Divided out of the unrounded profit and rounded once, like every
        # other figure in this chain. Rounding the profit first and dividing
        # that would put the error in the denominator, where a long print
        # magnifies it.
        hours = Decimal(str(machine_hours)) if machine_hours is not None else None
        if hours is not None and hours > ZERO:
            per_machine_hour: Optional[Decimal] = (profit_exact / hours).quantize(CENT)
        else:
            per_machine_hour = None

        # Who owes the tax. It is never revenue under either answer (FR-028c),
        # and it is a liability only where the operator remits it (FR-028d).
        # Effective-dated with the rest of the channel's levers (task T216),
        # so a settled line reports who remitted the tax when it sold.
        remitter = rates.tax_remitter
        liability = collected if remitter == "operator" else ZERO

        return MarginResult(
            list_price=item_price.quantize(CENT),
            shipping_revenue=shipping.quantize(CENT),
            make_cost=cost.quantize(CENT),
            postage_paid=postage.quantize(CENT),
            fees=list(fees.charges),
            fee_total=fee_total_exact.quantize(CENT),
            deductions=deductions,
            deduction_total=deduction_total_exact.quantize(CENT),
            shipping_net=(shipping - postage).quantize(CENT),
            net_revenue=net_revenue_exact.quantize(CENT),
            profit=profit_exact.quantize(CENT),
            margin_pct=margin_pct,
            margin_basis=basis,
            margin_basis_label=MARGIN_BASIS_LABELS[basis],
            margin_basis_amount=basis_amount.quantize(CENT),
            profit_per_machine_hour=per_machine_hour,
            machine_hours=hours,
            sales_tax_collected=collected.quantize(CENT),
            sales_tax_liability=liability.quantize(CENT),
            tax_remitter=remitter,
            tax_exclusive_derived=tax_exclusive_derived,
            revenue_tax_exclusive=exclusive_total.quantize(CENT),
            observed_share=observed_share,
            assumed_share=assumed_share,
            incomplete_reasons=list(dict.fromkeys([*incomplete_reasons, *fees.incomplete_reasons])),
        )

    @staticmethod
    def calculate_cost_per_gram_from_spool(
        purchase_price: Optional[Decimal],
        initial_weight: Decimal,
    ) -> Decimal:
        """
        Calculate cost per gram from spool purchase information.

        Args:
            purchase_price: Purchase price of spool
            initial_weight: Initial weight of spool in grams

        Returns:
            Cost per gram
        """
        if purchase_price is None or purchase_price <= 0:
            return Decimal("0")

        if initial_weight <= 0:
            return Decimal("0")

        return (Decimal(str(purchase_price)) / Decimal(str(initial_weight))).quantize(
            Decimal("0.0001")
        )


def pricing_purchase(consumable: Any) -> Optional[Any]:
    """The purchase that prices a consumable's unit, or ``None`` (task T273).

    The latest purchase still on record with a quantity and a total; two on the
    same day go to the one recorded last. A consumable whose purchases were not
    loaded has none here rather than lazily loading under asyncio; every cost
    read loads them (`cost_resolution.cost_load_options`).
    """
    purchases = (
        list(getattr(consumable, "purchases", None) or [])
        if _relationship_loaded(consumable, "purchases")
        else []
    )
    priced = [
        purchase
        for purchase in purchases
        if (_as_decimal(getattr(purchase, "quantity_purchased", None), ZERO) or ZERO) > ZERO
        and getattr(purchase, "total_cost", None) is not None
    ]
    if not priced:
        return None
    return max(
        priced,
        key=lambda purchase: (
            getattr(purchase, "purchase_date", None) or date.min,
            str(getattr(purchase, "created_at", None) or ""),
        ),
    )


def consumable_unit_cost(consumable: Any) -> Decimal:
    """What one unit of a consumable costs, derived on read (task T273).

    From the purchase that prices it (`pricing_purchase`), as an exact
    ``total_cost / quantity_purchased``: seven for 1.00 is 1/7 each, not a
    four-place 0.1429 multiplied back up. The quotient used to be stored on the
    consumable, and it stayed after the purchase behind it was deleted
    (Constitution IV and V). With no purchase on record, the unit cost is the
    figure the operator typed.
    """
    purchase = pricing_purchase(consumable)
    if purchase is not None:
        total = _as_decimal(purchase.total_cost, ZERO) or ZERO
        quantity = _as_decimal(purchase.quantity_purchased, ONE) or ONE
        return total / quantity
    return _as_decimal(getattr(consumable, "current_cost_per_unit", None), ZERO) or ZERO


def _packaging_cost(
    product: "Product",
    origins: Optional[Mapping[tuple[str, uuid.UUID, str], "FieldOrigin"]],
    pending: Optional[AbstractSet[tuple[str, uuid.UUID, str]]] = None,
) -> tuple[Decimal, _Origin]:
    """Packaging materials for one sellable unit, and where the figure came from.

    The existing packaging path is reused unchanged (a linked consumable wins
    over the typed figure); Tier 1 only reclassifies it as not-at-risk.
    """
    product_id = getattr(product, "id", None)
    consumable = getattr(product, "packaging_consumable", None)
    if consumable is not None:
        unit_cost = consumable_unit_cost(consumable)
        quantity = _as_decimal(getattr(product, "packaging_quantity", None), ONE) or ONE
        # The unit cost sets the amount, so its origin is the line's: a
        # quantity of one measured box tells nothing about what a box costs
        # (FR-001, T249).
        origin = _origin_of(
            origins,
            pending,
            "consumable_type",
            getattr(consumable, "id", None),
            "current_cost_per_unit",
        )
        # Dated by the purchase that prices it, so a deleted purchase's date
        # does not outlive it on the line (task T277).
        purchase = pricing_purchase(consumable)
        if purchase is not None and getattr(purchase, "purchase_date", None) is not None:
            origin = dataclasses.replace(origin, as_of=purchase.purchase_date)
        return (unit_cost * quantity, origin)

    cost = _as_decimal(getattr(product, "packaging_cost", None), ZERO) or ZERO
    return (cost, _origin_of(origins, pending, "product", product_id, "packaging_cost"))
