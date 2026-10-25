"""The registry of numeric cost inputs, and where each one came from.

Three jobs live here, and they are together because they share one map:

1. **The registry.** Every ``(entity_type, field_name)`` pair the cost engine
   can reach, with the origin a figure has before anyone records one. The
   database cannot enforce a foreign key on a field name (research.md D1), so
   this module plus its coverage test is the enforcement. That is a test, not a
   constraint.
2. **Reading and writing rows.** Reads are batched on
   ``(entity_type, entity_id) IN (...)`` so a breakdown costs one extra query
   rather than one per field.
3. **The observed share.** Computed from a breakdown's own lines (FR-046), not
   from a database aggregate, because the share that matters is the share *of
   this cost* -- a tenant-wide count of assumed fields answers a different
   question.

FR-004 and FR-002 are enforced at the write: an ``observed`` figure is
read-only to the operator, and a ``policy`` figure is never moved by an
automated process.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Iterable, Mapping, Optional, Protocol, Sequence, runtime_checkable

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models.pricing_input_provenance import (
    PROVENANCE_ENTITY_TYPES,
    PROVENANCE_SOURCES,
    PricingInputProvenance,
)

if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.schemas.model import CostBreakdown

logger = logging.getLogger(__name__)


class UnknownProvenanceField(ValueError):
    """Raised for an ``(entity_type, field_name)`` pair the registry lacks.

    A typo in a field name would otherwise write a row nothing ever reads,
    leaving the figure looking unrecorded while the table says otherwise.
    """

    def __init__(self, entity_type: str, field_name: str):
        self.entity_type = entity_type
        self.field_name = field_name
        super().__init__(
            f"{entity_type}.{field_name} is not a registered pricing input. "
            f"Add it to REGISTRY in app/services/provenance.py (research.md D1) "
            f"or correct the name."
        )


class ProvenanceNotEditable(PermissionError):
    """Raised when an operator edit would overwrite a non-editable origin."""


@dataclass(frozen=True)
class RegisteredInput:
    """One numeric input the cost engine can reach."""

    entity_type: str
    field_name: str
    #: What this figure's origin is before anybody records one. A policy lever
    #: is an operator decision by construction; everything else starts as an
    #: assumption, which is the honest answer and the one FR-001 wants shown.
    default_source: str
    #: Whether an automated process may ever move this figure. False for every
    #: operator decision (FR-002, FR-042g).
    learnable: bool
    description: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.entity_type, self.field_name)


def _entry(
    entity_type: str,
    field_name: str,
    description: str,
    *,
    default_source: str = "assumed",
    learnable: bool = True,
) -> RegisteredInput:
    return RegisteredInput(
        entity_type=entity_type,
        field_name=field_name,
        default_source=default_source,
        learnable=learnable,
        description=description,
    )


#: Every numeric input the cost engine reaches. The coverage test in
#: ``tests/unit/pricing/test_provenance_registry.py`` walks the ORM models and
#: fails on a cost-bearing column that is missing here.
REGISTERED_INPUTS: tuple[RegisteredInput, ...] = (
    # ---------------------------------------------------------------- model
    _entry("model", "print_time_minutes", "Machine occupancy for a plate"),
    _entry("model", "prints_per_plate", "How many parts share one plate"),
    _entry("model", "waste_grams", "Purge and priming filament per plate"),
    _entry("model", "expected_yield", "Share of starts that reach a sellable part"),
    _entry("model", "labor_hours_per_plate", "Preparation a plate needs once"),
    _entry("model", "labor_hours_per_item", "Handling per item"),
    _entry("model", "finishing_hours_per_item", "Finishing per item"),
    _entry("model", "packing_hours_per_item", "Packing per item"),
    _entry(
        "model",
        "labor_rate_override",
        "Labor rate for this item, overriding policy",
        default_source="policy",
        learnable=False,
    ),
    _entry(
        "model",
        "overhead_percentage",
        "Overhead percentage for this item, overriding policy",
        default_source="policy",
        learnable=False,
    ),
    _entry(
        "model",
        "labor_hours",
        "DEPRECATED: superseded by labor_hours_per_item",
    ),
    # ------------------------------------------------------- model_material
    _entry("model_material", "weight_grams", "Filament that ends up in the part"),
    _entry("model_material", "cost_per_gram", "Landed cost per usable gram, at time of adding"),
    # ------------------------------------------------------ model_component
    _entry("model_component", "quantity", "How many of this component one item uses"),
    _entry("model_component", "unit_cost", "What one of this component costs"),
    # -------------------------------------------------- model_printer_config
    _entry("model_printer_config", "prints_per_plate", "Parts per plate on this printer"),
    _entry("model_printer_config", "print_time_minutes", "Plate print time on this printer"),
    _entry("model_printer_config", "material_weight_grams", "Per-item weight on this printer"),
    # -------------------------------------------------------------- product
    _entry("product", "packaging_cost", "Packaging materials per order"),
    _entry("product", "packaging_quantity", "Units of the packaging consumable per order"),
    _entry("product", "assembly_minutes", "Assembly labor for the sellable unit"),
    # -------------------------------------------------------------- printer
    _entry(
        "printer",
        "purchase_price",
        "All-in acquisition cost",
        default_source="policy",
        learnable=False,
    ),
    _entry(
        "printer",
        "expected_lifetime_hours",
        "Expected printing hours over the machine's life",
        default_source="policy",
        learnable=False,
    ),
    _entry(
        "printer",
        "maintenance_reserve_total",
        "Maintenance reserve over the whole life",
        default_source="policy",
        learnable=False,
    ),
    _entry("printer", "measured_watts", "Measured draw at the wall while printing"),
    _entry(
        "printer",
        "electricity_rate_per_kwh",
        "Electricity rate for this machine",
        default_source="policy",
        learnable=False,
    ),
    # ---------------------------------------------------------------- spool
    _entry("spool", "purchase_price", "What the spool itself cost"),
    _entry("spool", "initial_weight", "Nominal filament weight"),
    _entry("spool", "unusable_remainder_grams", "Filament left on the core"),
    # ----------------------------------------------------- filament_purchase
    _entry("filament_purchase", "inbound_shipping_cost", "Inbound shipping for the purchase"),
    _entry("filament_purchase", "tax_amount", "Sales tax on the purchase"),
    # ------------------------------------------------- tenant_pricing_policy
    *(
        _entry(
            "tenant_pricing_policy",
            field,
            description,
            default_source="policy",
            learnable=False,
        )
        for field, description in (
            ("print_labor_rate", "Hourly rate for print handling"),
            ("finishing_labor_rate", "Hourly rate for finishing"),
            ("default_machine_rate_per_hour", "Machine rate when no printer is assigned"),
            ("overhead_percentage", "Overhead percentage for the percentage method"),
            ("overhead_monthly_pool", "Monthly overhead pool"),
            ("expected_monthly_machine_hours", "Expected monthly machine capacity"),
            ("electricity_rate_per_kwh", "Tenant electricity rate"),
            ("default_target_margin_pct", "Default target margin"),
            ("margin_alert_threshold_pct", "Realised-versus-planned alert threshold"),
            ("estimate_divergence_threshold_pct", "Divergence that holds an observation"),
            ("staleness_threshold_days", "Days before a measured figure is stale"),
            ("min_outcomes_before_auto_update", "Outcomes required before an estimate moves"),
        )
    ),
    # -------------------------------------------------------- sales_channel
    *(
        _entry("sales_channel", field, description, default_source="policy", learnable=False)
        for field, description in (
            ("monthly_cost", "Periodic channel cost, absorbed over order volume"),
            # Channel economics (Tier 2). Every one of these is an operator
            # decision in the sense of FR-002 -- a reserve the operator chooses
            # to hold, a threshold they set -- so each is `policy` and none is
            # learnable: no observation may move a decision (FR-042g).
            ("expected_discount_pct", "Expected discount share, reducing planned net revenue"),
            ("expected_refund_pct", "Refund reserve held against planned revenue"),
            ("free_shipping_threshold", "Order value at which the operator ships free"),
        )
    ),
    # Fee rules (Tier 2). A rule's figures are entered from a published fee
    # schedule, which is a decision about what the channel charges rather than
    # an estimate to be refined: `policy`, and never learnable. What a
    # statement actually charged is a separate record (`fee_actuals`), and
    # FR-041e keeps that labelled as entered rather than observed.
    *(
        _entry("fee_rule", field, description, default_source="policy", learnable=False)
        for field, description in (
            ("rate_pct", "Percentage of the basis this rule charges"),
            ("fixed_amount", "Amount this rule adds once the rate is applied"),
            ("min_amount", "Floor on the amount this rule charges"),
            ("max_amount", "Cap on the amount this rule charges"),
            ("incidence_pct", "Share of orders this fee lands on, for planning only"),
        )
    ),
    # The packaging consumable (T249). A product's packaging line is its unit
    # cost times the product's quantity; the unit cost is typed in or derived
    # from a purchase the operator recorded, so it is theirs, never observed.
    _entry(
        "consumable_type",
        "current_cost_per_unit",
        "Unit cost of a consumable, such as the packaging a product ships in",
    ),
    # Shipping profiles (Tier 2). Postage is a published carrier price the
    # operator transcribes, so it is `policy`; it is learnable because a
    # recorded label cost is a direct observation of the same figure.
    *(
        _entry("shipping_profile", field, description, default_source="policy")
        for field, description in (
            ("postage_cost", "What the operator pays to post one parcel in this bracket"),
            ("weight_bracket_min_grams", "Lowest parcel weight in this bracket"),
            ("weight_bracket_max_grams", "Highest parcel weight in this bracket"),
        )
    ),
)

#: The registry, keyed for lookup.
REGISTRY: Mapping[tuple[str, str], RegisteredInput] = {
    entry.key: entry for entry in REGISTERED_INPUTS
}


def registry_entry(entity_type: str, field_name: str) -> RegisteredInput:
    """Look one input up, or refuse a name the registry does not know."""
    try:
        return REGISTRY[(entity_type, field_name)]
    except KeyError:
        raise UnknownProvenanceField(entity_type, field_name) from None


def known_entity_types() -> frozenset[str]:
    """Entity types the registry carries at least one field for."""
    return frozenset(entry.entity_type for entry in REGISTERED_INPUTS)


def registered_fields(entity_type: str) -> frozenset[str]:
    """Field names registered for one entity type."""
    return frozenset(
        entry.field_name for entry in REGISTERED_INPUTS if entry.entity_type == entity_type
    )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldOrigin:
    """The origin of one field, recorded or defaulted."""

    source: str
    as_of: Optional[date]
    confidence: Optional[Decimal] = None
    #: True when nothing was recorded and the registry's default was used, so a
    #: caller can tell "assumed, and we know it" from "assumed by omission".
    is_default: bool = False

    @property
    def is_evidenced(self) -> bool:
        """Whether this figure rests on evidence rather than on a guess.

        A policy figure is a decision, not evidence: FR-046 contrasts observed
        against assumed, and an operator decision belongs with neither -- it is
        counted as evidenced here because the operator stated it deliberately,
        which is the distinction SC-010 measures.
        """
        return self.source in ("observed", "measured", "policy")

    def is_stale(self, *, threshold_days: int, today: Optional[date] = None) -> bool:
        """Whether a hand-measured figure is past its staleness threshold.

        Only ``measured`` figures go stale (FR-005). A policy decision does not
        expire, and an observed figure is refreshed from its source.
        """
        if self.source != "measured" or self.as_of is None:
            return False
        reference = today or clock.today()
        return (reference - self.as_of).days > threshold_days


def default_origin(entity_type: str, field_name: str) -> FieldOrigin:
    """The origin a field has when nothing has been recorded for it."""
    entry = registry_entry(entity_type, field_name)
    return FieldOrigin(source=entry.default_source, as_of=None, is_default=True)


async def origins_for(
    db: AsyncSession,
    tenant: "Tenant",
    entities: Iterable[tuple[str, uuid.UUID]],
) -> dict[tuple[str, uuid.UUID, str], FieldOrigin]:
    """Every recorded origin for the given entities, in one query.

    ``entities`` is an iterable of ``(entity_type, entity_id)``. The result is
    keyed ``(entity_type, entity_id, field_name)``; a field with no recorded
    row is simply absent, and the caller falls back to
    :func:`default_origin` rather than being handed a fabricated row.
    """
    pairs = sorted({(entity_type, entity_id) for entity_type, entity_id in entities})
    if not pairs:
        return {}

    statement = select(PricingInputProvenance).where(
        PricingInputProvenance.tenant_id == tenant.id,
        tuple_(
            PricingInputProvenance.entity_type,
            PricingInputProvenance.entity_id,
        ).in_(pairs),
    )
    result = await db.execute(statement)

    origins: dict[tuple[str, uuid.UUID, str], FieldOrigin] = {}
    for row in result.scalars().all():
        origins[(row.entity_type, row.entity_id, row.field_name)] = FieldOrigin(
            source=row.source,
            as_of=row.as_of,
            confidence=row.confidence,
        )
    return origins


async def origins_for_entity(
    db: AsyncSession,
    tenant: "Tenant",
    entity_type: str,
    entity_id: uuid.UUID,
) -> dict[str, FieldOrigin]:
    """Every field origin for one entity, defaults included.

    This is what ``GET /provenance`` serves: the registry's view of what the
    entity *has*, not only what somebody got round to recording.
    """
    recorded = await origins_for(db, tenant, [(entity_type, entity_id)])
    return {
        field_name: recorded.get(
            (entity_type, entity_id, field_name),
            default_origin(entity_type, field_name),
        )
        for field_name in sorted(registered_fields(entity_type))
    }


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


async def revert_to_assumed(
    db: AsyncSession,
    tenant: "Tenant",
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    field_name: str,
    as_of: date,
) -> None:
    """Withdraw a figure's claim to be evidence, whatever its origin was.

    For one case only: an item's failure mode changed, so a yield observed
    under the old mode is no longer an observation of anything (FR-015d). The
    figure stays in use -- pricing cannot stop -- but is labelled assumed until
    runs under the new mode accumulate. This is not an operator typing over an
    observed figure (FR-004 still refuses that); it is the system saying the
    evidence no longer applies.
    """
    registry_entry(entity_type, field_name)
    existing = (
        await db.execute(
            select(PricingInputProvenance).where(
                PricingInputProvenance.tenant_id == tenant.id,
                PricingInputProvenance.entity_type == entity_type,
                PricingInputProvenance.entity_id == entity_id,
                PricingInputProvenance.field_name == field_name,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        return
    existing.source = "assumed"
    existing.as_of = as_of
    existing.confidence = None
    await db.flush()


async def record_origin(
    db: AsyncSession,
    tenant: "Tenant",
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    field_name: str,
    source: str,
    as_of: Optional[date] = None,
    confidence: Optional[Decimal] = None,
    measured_by_user_id: Optional[uuid.UUID] = None,
    authorised_by_role: Optional[str] = None,
    automated: bool = False,
) -> PricingInputProvenance:
    """Record or update where one figure came from.

    ``automated`` marks a write made by a process rather than by a person. Such
    a write is refused for a field the registry marks un-learnable (FR-002,
    FR-042g) and for a field whose current origin is ``policy``: an operator
    decision is never moved by machinery, whatever the divergence.

    A manual write over an ``observed`` figure is refused too (FR-004): an
    observed figure is read-only and refreshed only from its source.
    """
    entry = registry_entry(entity_type, field_name)
    if source not in PROVENANCE_SOURCES:
        raise ValueError(
            f"{source!r} is not a provenance source; expected one of {PROVENANCE_SOURCES}"
        )
    if entity_type not in PROVENANCE_ENTITY_TYPES:
        raise ValueError(f"{entity_type!r} is not a provenance entity type")

    existing = (
        await db.execute(
            select(PricingInputProvenance).where(
                PricingInputProvenance.tenant_id == tenant.id,
                PricingInputProvenance.entity_type == entity_type,
                PricingInputProvenance.entity_id == entity_id,
                PricingInputProvenance.field_name == field_name,
            )
        )
    ).scalar_one_or_none()

    current_source = existing.source if existing is not None else entry.default_source

    if automated and not entry.learnable:
        raise ProvenanceNotEditable(
            f"{entity_type}.{field_name} is an operator decision and is never "
            f"updated automatically (FR-002, FR-042g)"
        )
    if automated and current_source == "policy":
        raise ProvenanceNotEditable(
            f"{entity_type}.{field_name} is currently an operator decision; an "
            f"automated process may not overwrite it (FR-002)"
        )
    if not automated and current_source == "observed" and source != "observed":
        raise ProvenanceNotEditable(
            f"{entity_type}.{field_name} is observed from its source and is "
            f"read-only; it is refreshed only from that source (FR-004)"
        )

    effective_as_of = as_of or clock.today()

    if existing is not None:
        existing.source = source
        existing.as_of = effective_as_of
        existing.confidence = confidence
        existing.measured_by_user_id = measured_by_user_id
        existing.authorised_by_role = authorised_by_role
        db.add(existing)
        return existing

    row = PricingInputProvenance(
        tenant_id=tenant.id,
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        source=source,
        as_of=effective_as_of,
        confidence=confidence,
        measured_by_user_id=measured_by_user_id,
        authorised_by_role=authorised_by_role,
    )
    db.add(row)
    return row


def changed_fields(
    entity_type: str,
    entity: object,
    changes: Mapping[str, object],
) -> list[str]:
    """The registered inputs ``changes`` would actually move on ``entity``.

    A body that resends a figure unchanged is not a new measurement of it, so
    it must not restamp the figure's date or its author. Compared as
    :class:`~decimal.Decimal` where both sides are numbers, so ``"12.50"`` and
    ``Decimal("12.5")`` are the same figure. Pass ``entity=None`` for a record
    being created: every registered input the body names is then a change.
    """
    fields = registered_fields(entity_type)
    moved: list[str] = []
    for field_name, new_value in changes.items():
        if field_name not in fields:
            continue
        if entity is None:
            if new_value is not None:
                moved.append(field_name)
            continue
        old_value = getattr(entity, field_name, None)
        if _same_figure(old_value, new_value):
            continue
        moved.append(field_name)
    return sorted(moved)


def _same_figure(old: object, new: object) -> bool:
    if old is None or new is None:
        return old is new
    try:
        return Decimal(str(old)) == Decimal(str(new))
    except (ArithmeticError, ValueError):
        return old == new


async def refuse_overwriting_observed(
    db: AsyncSession,
    tenant: "Tenant",
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    fields: Iterable[str],
) -> None:
    """Raise before anything is written if a person would type over an observed figure.

    FR-004: an observed figure is read-only to the operator and refreshed only
    from its source. Checked for every field first, so a body naming one
    observed figure among several changes none of them rather than half.
    """
    names = sorted(set(fields))
    if not names:
        return
    recorded = await origins_for(db, tenant, [(entity_type, entity_id)])
    observed = [
        name
        for name in names
        if (origin := recorded.get((entity_type, entity_id, name))) is not None
        and origin.source == "observed"
    ]
    if observed:
        raise ProvenanceNotEditable(
            f"{entity_type} {', '.join(observed)} "
            f"{'is' if len(observed) == 1 else 'are'} observed from its source and "
            f"read-only; it is refreshed only from that source (FR-004)"
        )


async def record_operator_write(
    db: AsyncSession,
    tenant: "Tenant",
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    fields: Iterable[str],
    user_id: Optional[uuid.UUID],
    role: Optional[str] = None,
    as_of: Optional[date] = None,
) -> list[str]:
    """Record where each figure a person just wrote came from (task T229).

    The one path every console writer of a cost input goes through, so that a
    figure an operator measured stops reading as ``assumed`` from the
    migration date forever, and one telemetry observed is never silently
    relabelled by a person typing over it -- which would make the observed
    share (FR-046, SC-010) wrong in both directions.

    A registered operator decision -- a field whose default origin is
    ``policy`` and that no observation may move -- is recorded as ``policy``
    with the authorising role; every other figure as ``measured`` against the
    user. Both are dated ``as_of``, today by default. Raises
    :class:`ProvenanceNotEditable` before writing anything if any field is
    currently observed.

    Call it with the fields that actually moved (:func:`changed_fields`), in
    the same transaction as the write itself.
    """
    names = sorted(set(fields))
    await refuse_overwriting_observed(
        db, tenant, entity_type=entity_type, entity_id=entity_id, fields=names
    )
    for name in names:
        entry = registry_entry(entity_type, name)
        is_decision = entry.default_source == "policy" and not entry.learnable
        await record_origin(
            db,
            tenant,
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=name,
            source="policy" if is_decision else "measured",
            as_of=as_of,
            measured_by_user_id=user_id,
            authorised_by_role=role,
        )
    return names


async def seed_assumed_origins(
    db: AsyncSession,
    tenant: "Tenant",
    entity_type: str,
    entity_id: uuid.UUID,
    *,
    as_of: Optional[date] = None,
) -> int:
    """Record every unrecorded field of one entity as ``assumed``.

    Used when a record is created: a figure nobody has justified is an
    assumption, and saying so is the point of FR-001. Fields already recorded
    are left alone, so this never demotes a measured figure.
    """
    recorded = await origins_for(db, tenant, [(entity_type, entity_id)])
    written = 0
    for field_name in sorted(registered_fields(entity_type)):
        if (entity_type, entity_id, field_name) in recorded:
            continue
        entry = registry_entry(entity_type, field_name)
        await record_origin(
            db,
            tenant,
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
            source=entry.default_source,
            as_of=as_of,
        )
        written += 1
    return written


# ---------------------------------------------------------------------------
# The observed share of a breakdown (FR-046)
# ---------------------------------------------------------------------------


def observed_share(lines: Sequence["CostLineLike"]) -> tuple[Decimal, Decimal]:
    """Split a breakdown's total into evidenced and assumed shares.

    Computed from the lines themselves, weighted by amount, because what the
    operator is deciding is whether to bet a price on *this* figure. A count of
    lines would make a 0.10 packaging line weigh as much as a 6.25 labor one.

    Returns ``(observed_share, assumed_share)``, each a fraction in [0, 1] that
    together sum to 1 -- or ``(0, 1)`` for a zero-cost breakdown, where nothing
    is evidenced because there is nothing there.
    """
    total = sum((line.amount for line in lines), Decimal("0"))
    if total <= 0:
        return (Decimal("0"), Decimal("1"))

    evidenced = sum(
        (line.amount for line in lines if line.source in ("observed", "measured", "policy")),
        Decimal("0"),
    )
    share = evidenced / total
    # Clamp rather than trust arithmetic on figures assembled elsewhere: the
    # schema bounds these fields at [0, 1] and a breakdown that fails
    # validation tells the operator nothing useful about its own trust level.
    if share < 0:
        share = Decimal("0")
    elif share > 1:
        share = Decimal("1")
    return (share, Decimal("1") - share)


@runtime_checkable
class CostLineLike(Protocol):
    """Structural type for :func:`observed_share` -- anything with the two fields.

    It is a `Protocol` so that it is actually structural. As a plain class it
    read as structural and behaved nominally: `CostLine` does not inherit it,
    so passing a real breakdown's lines was a type error that went unreported
    until this module came under the money paths' stricter settings (T137).
    `Protocol` is stdlib, so this still drags no schema import into the models
    layer -- which was the reason given for avoiding it.

    Both members are read-only properties rather than attributes. A mutable
    protocol attribute is invariant, which would reject `CostLine.source` for
    being the narrower `Literal["policy", "observed", "measured", "assumed"]`
    instead of exactly `str`. `observed_share` only ever reads them, so
    read-only is both the accurate shape and the one that accepts a real line.
    """

    @property
    def amount(self) -> Decimal: ...

    @property
    def source(self) -> str: ...


def breakdown_observed_share(breakdown: "CostBreakdown") -> tuple[Decimal, Decimal]:
    """The observed and assumed shares of a finished breakdown."""
    return observed_share(breakdown.lines)
