"""Resolve the operator's pricing policy as at a date, and version a change.

Two things the old ``Tenant.settings`` blob could not do, and that FR-002,
FR-003, FR-031d and FR-039 all need:

* **Read as at a date.** "What was the labor rate when this order was placed"
  must be answerable from the data, not reconstructed from a changelog.
* **Write without overwriting.** Changing one lever writes a new effective row
  copying the rest forward; the superseded row stays readable (research.md D2).

The engine in :mod:`app.services.costing` is synchronous and takes no database
session, so policy is resolved here and handed over as a :class:`CostPolicy` --
an immutable snapshot of the figures a cost needs. That is also what keeps the
engine free to run inside a recursive bill-of-materials walk without issuing a
query per node.

Until the Tier 1 migration seeds a policy row per tenant, and for a tenant
created before it, :func:`resolve_cost_policy` falls back to the legacy
settings reader so no cost is ever computed from a figure nobody configured.
"""

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_pricing_policy import (
    MARGIN_BASES,
    OVERHEAD_METHODS,
    TenantPricingPolicy,
)
from app.services.tenant_cost_settings import (
    tenant_labor_rate,
    tenant_overhead_percentage,
)

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.tenant import Tenant

logger = logging.getLogger(__name__)


#: The levers a `PUT /settings/pricing-policy` may carry. Anything else in the
#: body is a typo, and a typo that silently did nothing would be worse than a
#: refusal.
POLICY_FIELDS: tuple[str, ...] = (
    "print_labor_rate",
    "finishing_labor_rate",
    "default_machine_rate_per_hour",
    "overhead_method",
    "overhead_monthly_pool",
    "expected_monthly_machine_hours",
    "electricity_rate_per_kwh",
    "margin_basis",
    "default_target_margin_pct",
    "rounding_rule",
    "sales_tax_recoverable",
    "staleness_threshold_days",
    "margin_alert_threshold_pct",
    "min_outcomes_before_auto_update",
    "estimate_divergence_threshold_pct",
)


class PolicyMisconfigured(ValueError):
    """Raised when a policy change would store a figure that cannot be used."""


@dataclass(frozen=True)
class CostPolicy:
    """The policy figures one cost calculation needs, frozen at a date.

    Immutable on purpose: a product cost built from two different labor rates
    is one figure with two policies in it, which is the defect User Story 1
    removed. Passing a frozen snapshot down the recursion makes that
    impossible rather than merely discouraged.
    """

    print_labor_rate: Decimal
    finishing_labor_rate: Decimal
    overhead_method: str = "percentage"
    overhead_monthly_pool: Optional[Decimal] = None
    expected_monthly_machine_hours: Optional[Decimal] = None
    default_machine_rate_per_hour: Optional[Decimal] = None
    electricity_rate_per_kwh: Optional[Decimal] = None
    #: Overhead percentage for the percentage method. It is not a column on
    #: `tenant_pricing_policy`: the percentage method is the legacy path, and
    #: its figure still lives where the settings UI writes it.
    overhead_percentage: Decimal = Decimal("0")
    margin_basis: str = "customer_total"
    default_target_margin_pct: Optional[Decimal] = None
    rounding_rule: Optional[str] = None
    sales_tax_recoverable: bool = False
    staleness_threshold_days: int = 180
    margin_alert_threshold_pct: Decimal = Decimal("5")
    min_outcomes_before_auto_update: int = 5
    estimate_divergence_threshold_pct: Decimal = Decimal("25")
    effective_from: Optional[date] = None
    #: Where these figures came from: a policy row, or the legacy settings blob
    #: for a tenant the migration has not reached. Surfaced so a breakdown can
    #: say which, rather than presenting a fallback as a decision.
    origin: str = "policy_row"

    @property
    def overhead_rate_per_machine_hour(self) -> Optional[Decimal]:
        """Overhead absorbed per machine-hour, or ``None`` if not absorbable.

        ``None`` means the operator has not declared a pool and a capacity, so
        the overhead line is reported as incompletely costed rather than as
        zero (FR-019). Zero capacity cannot reach here -- the table's CHECK
        refuses it -- but it is guarded anyway, because a division by zero in a
        cost is the kind of failure that surfaces as a 500 on a pricing screen.
        """
        if self.overhead_method != "per_machine_hour":
            return None
        pool = self.overhead_monthly_pool
        hours = self.expected_monthly_machine_hours
        if pool is None or hours is None or hours <= 0:
            return None
        return Decimal(str(pool)) / Decimal(str(hours))

    def with_overhead_percentage(self, percentage: Decimal) -> "CostPolicy":
        """Return a copy carrying the tenant's legacy overhead percentage."""
        return replace(self, overhead_percentage=percentage)


def _today() -> date:
    return datetime.now(timezone.utc).date()


async def resolve_policy_row(
    db: AsyncSession,
    tenant: "Tenant",
    as_of: Optional[date] = None,
) -> Optional[TenantPricingPolicy]:
    """The policy row in effect on ``as_of``, or ``None`` if there is none.

    Ordered by ``effective_from`` then insertion, newest first: two rows can
    legitimately share a start date when a lever is changed twice in one day,
    and the later write is the one in force.
    """
    reference = as_of or _today()
    statement = (
        select(TenantPricingPolicy)
        .where(
            TenantPricingPolicy.tenant_id == tenant.id,
            TenantPricingPolicy.effective_from <= reference,
        )
        .where(
            (TenantPricingPolicy.effective_to.is_(None))
            | (TenantPricingPolicy.effective_to >= reference)
        )
        .order_by(
            TenantPricingPolicy.effective_from.desc(),
            TenantPricingPolicy.created_at.desc(),
        )
        .limit(1)
    )
    result = await db.execute(statement)
    return result.scalars().first()


async def current_policy_row(db: AsyncSession, tenant: "Tenant") -> Optional[TenantPricingPolicy]:
    """The open row -- the one with no ``effective_to``."""
    result = await db.execute(
        select(TenantPricingPolicy).where(
            TenantPricingPolicy.tenant_id == tenant.id,
            TenantPricingPolicy.effective_to.is_(None),
        )
    )
    return result.scalars().first()


def cost_policy_from_row(
    row: TenantPricingPolicy,
    *,
    overhead_percentage: Decimal = Decimal("0"),
) -> CostPolicy:
    """Freeze a policy row into the snapshot the engine takes."""
    return CostPolicy(
        print_labor_rate=Decimal(str(row.print_labor_rate)),
        finishing_labor_rate=Decimal(str(row.finishing_labor_rate)),
        overhead_method=row.overhead_method,
        overhead_monthly_pool=(
            Decimal(str(row.overhead_monthly_pool))
            if row.overhead_monthly_pool is not None
            else None
        ),
        expected_monthly_machine_hours=(
            Decimal(str(row.expected_monthly_machine_hours))
            if row.expected_monthly_machine_hours is not None
            else None
        ),
        default_machine_rate_per_hour=(
            Decimal(str(row.default_machine_rate_per_hour))
            if row.default_machine_rate_per_hour is not None
            else None
        ),
        electricity_rate_per_kwh=(
            Decimal(str(row.electricity_rate_per_kwh))
            if row.electricity_rate_per_kwh is not None
            else None
        ),
        overhead_percentage=overhead_percentage,
        margin_basis=row.margin_basis,
        default_target_margin_pct=(
            Decimal(str(row.default_target_margin_pct))
            if row.default_target_margin_pct is not None
            else None
        ),
        rounding_rule=row.rounding_rule,
        sales_tax_recoverable=bool(row.sales_tax_recoverable),
        staleness_threshold_days=row.staleness_threshold_days,
        margin_alert_threshold_pct=Decimal(str(row.margin_alert_threshold_pct)),
        min_outcomes_before_auto_update=row.min_outcomes_before_auto_update,
        estimate_divergence_threshold_pct=Decimal(str(row.estimate_divergence_threshold_pct)),
        effective_from=row.effective_from,
        origin="policy_row",
    )


def legacy_cost_policy(tenant: "Tenant") -> CostPolicy:
    """The policy a tenant with no policy row still has.

    Built from the figures the settings UI writes, so a tenant the Tier 1
    migration has not reached keeps costing at the rate they configured rather
    than at one invented here (Constitution IV). It carries no machine rate and
    no overhead pool, which is why such a tenant's machine line is reported
    missing rather than guessed.
    """
    rate = tenant_labor_rate(tenant)
    return CostPolicy(
        print_labor_rate=rate,
        finishing_labor_rate=rate,
        overhead_method="percentage",
        overhead_percentage=tenant_overhead_percentage(tenant),
        origin="legacy_settings",
    )


async def resolve_cost_policy(
    db: AsyncSession,
    tenant: "Tenant",
    as_of: Optional[date] = None,
) -> CostPolicy:
    """The policy snapshot the cost engine should use for this tenant.

    The legacy overhead percentage is carried across from the settings blob
    either way: the percentage absorption method is retained as an option
    (FR-014) and its figure has not moved into the policy table.
    """
    row = await resolve_policy_row(db, tenant, as_of)
    if row is None:
        return legacy_cost_policy(tenant)
    return cost_policy_from_row(row, overhead_percentage=tenant_overhead_percentage(tenant))


def _validate(values: dict[str, Any]) -> None:
    """Refuse a policy that could not be used once stored."""
    basis = values.get("margin_basis")
    if basis is not None and basis not in MARGIN_BASES:
        raise PolicyMisconfigured(f"margin_basis must be one of {MARGIN_BASES}, not {basis!r}")

    method = values.get("overhead_method")
    if method is not None and method not in OVERHEAD_METHODS:
        raise PolicyMisconfigured(
            f"overhead_method must be one of {OVERHEAD_METHODS}, not {method!r}"
        )

    if method == "per_machine_hour":
        hours = values.get("expected_monthly_machine_hours")
        if hours is None or Decimal(str(hours)) <= 0:
            raise PolicyMisconfigured(
                "absorbing overhead per machine-hour needs expected_monthly_machine_hours "
                "above zero; a capacity of zero is a misconfiguration, not a divisor"
            )

    for field in ("print_labor_rate", "finishing_labor_rate"):
        value = values.get(field)
        if value is not None and Decimal(str(value)) < 0:
            raise PolicyMisconfigured(f"{field} cannot be negative")


async def write_policy(
    db: AsyncSession,
    tenant: "Tenant",
    changes: dict[str, Any],
    *,
    user: Optional["User"] = None,
    role: Optional[str] = None,
    effective_from: Optional[date] = None,
) -> TenantPricingPolicy:
    """Write a new effective policy row, copying unchanged levers forward.

    Never updates in place (FR-003). The superseded row is closed the day
    before the new one opens, so the two do not overlap; where a lever is
    changed twice on one day the superseded row is closed on its own start
    date, leaving a period of zero length that the as-of read orders past.

    Unknown keys are refused rather than ignored, because a silently dropped
    lever is a policy the operator believes they set.
    """
    unknown = sorted(set(changes) - set(POLICY_FIELDS))
    if unknown:
        raise PolicyMisconfigured(
            f"unknown policy levers: {', '.join(unknown)}. Known levers: {', '.join(POLICY_FIELDS)}"
        )

    opens_on = effective_from or _today()
    current = await current_policy_row(db, tenant)

    if current is not None:
        carried = {field: getattr(current, field) for field in POLICY_FIELDS}
    else:
        legacy = legacy_cost_policy(tenant)
        carried = {
            "print_labor_rate": legacy.print_labor_rate,
            "finishing_labor_rate": legacy.finishing_labor_rate,
            "default_machine_rate_per_hour": None,
            "overhead_method": "percentage",
            "overhead_monthly_pool": None,
            "expected_monthly_machine_hours": None,
            "electricity_rate_per_kwh": None,
            "margin_basis": "customer_total",
            "default_target_margin_pct": None,
            "rounding_rule": None,
            "sales_tax_recoverable": False,
            "staleness_threshold_days": 180,
            "margin_alert_threshold_pct": Decimal("5"),
            "min_outcomes_before_auto_update": 5,
            "estimate_divergence_threshold_pct": Decimal("25"),
        }

    merged = {**carried, **changes}
    _validate(merged)

    if current is not None:
        closes_on = opens_on - timedelta(days=1)
        if closes_on < current.effective_from:
            # Two changes on one day. The row keeps a zero-length period rather
            # than an invalid one, and the as-of read takes the later write.
            closes_on = current.effective_from
        current.effective_to = closes_on
        db.add(current)
        await db.flush()

    row = TenantPricingPolicy(
        tenant_id=tenant.id,
        effective_from=opens_on,
        effective_to=None,
        set_by_user_id=user.id if user is not None else None,
        set_by_role=role,
        **merged,
    )
    db.add(row)
    await db.flush()
    logger.info(
        f"Wrote pricing policy for tenant {tenant.id} effective {opens_on} "
        f"(levers changed: {', '.join(sorted(changes)) or 'none'})"
    )
    return row


async def ensure_policy_row(
    db: AsyncSession,
    tenant: "Tenant",
    *,
    effective_from: Optional[date] = None,
) -> TenantPricingPolicy:
    """The tenant's current policy row, seeding one from legacy settings if absent.

    Used by the policy endpoints so a tenant created before Tier 1 gets a row
    the first time anybody writes one, rather than a 404 on their own settings.
    """
    current = await current_policy_row(db, tenant)
    if current is not None:
        return current
    return await write_policy(
        db,
        tenant,
        {},
        effective_from=effective_from or _today(),
    )
