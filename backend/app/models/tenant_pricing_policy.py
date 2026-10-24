"""The operator's monetary policy, as a typed temporal row (research.md D2).

Every lever here is an *operator decision* in the sense of FR-002: editable,
never overwritten by any automated process, and versioned with effective dates
so a past figure stays readable after the policy changes (FR-003).

That is why this is a table and not a key in ``Tenant.settings``. A JSON blob
cannot express "what was the labor rate on the day this order was placed",
which FR-031d and FR-039 both need, and it cannot give a column a type -- the
legacy ``settings["default_labor_rate"]`` was a `float`, read by nobody, while
every cost on every screen used a hardcoded 10.00.

Changing one lever writes a **new row** copying the rest forward; nothing is
updated in place. One row per tenant has ``effective_to IS NULL`` and is the
current policy, enforced by a partial unique index rather than by convention.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.user import User


#: Which amount a margin percentage is taken over (FR-031). The default
#: reproduces today's definition, so switching the setting is opt-in.
MARGIN_BASES = ("customer_total", "item_price", "net_revenue")

#: How overhead reaches a unit of production (FR-014). Per machine-hour is the
#: method this feature introduces; the percentage method is retained because it
#: is what every existing tenant's costs were built from, and changing it
#: silently would violate FR-050.
OVERHEAD_METHODS = ("per_machine_hour", "percentage")


class TenantPricingPolicy(Base, UUIDMixin, TimestampMixin):
    """One effective period of a tenant's pricing policy."""

    __tablename__ = "tenant_pricing_policy"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )

    # ------------------------------------------------------------------
    # Labor
    # ------------------------------------------------------------------
    print_labor_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        comment="Hourly rate for print handling and per-plate preparation",
    )

    finishing_labor_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        comment="Hourly rate for finishing work, which may differ from handling (FR-012)",
    )

    # ------------------------------------------------------------------
    # Machine and overhead
    # ------------------------------------------------------------------
    default_machine_rate_per_hour: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="Fallback hourly machine rate when an item is planned on no printer (FR-011)",
    )

    overhead_method: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="per_machine_hour",
        server_default="per_machine_hour",
        comment="'per_machine_hour' (FR-014 default) or 'percentage' of material plus labor",
    )

    overhead_monthly_pool: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="Monthly overhead pool absorbed over expected machine-hours",
    )

    expected_monthly_machine_hours: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="Expected monthly machine capacity; the overhead absorption denominator",
    )

    electricity_rate_per_kwh: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="Tenant electricity rate, used by any printer that carries none of its own",
    )

    overhead_percentage: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Overhead percentage of material and labor, for the percentage method (FR-014)",
    )

    # ------------------------------------------------------------------
    # Margin and price presentation
    # ------------------------------------------------------------------
    margin_basis: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="customer_total",
        server_default="customer_total",
        comment="Which amount a margin percentage is taken over (FR-031, FR-031a)",
    )

    default_target_margin_pct: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 4),
        nullable=True,
        comment="Target margin the solver uses when a request names none",
    )

    rounding_rule: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="How a solved price is rounded, e.g. 'psychological_99' (FR-033)",
    )

    # ------------------------------------------------------------------
    # Tax
    # ------------------------------------------------------------------
    sales_tax_recoverable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether input sales tax is recoverable, which decides if it enters cost (FR-008c)",
    )

    # ------------------------------------------------------------------
    # Trust, staleness and learning thresholds
    # ------------------------------------------------------------------
    staleness_threshold_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=180,
        server_default="180",
        comment="Days after which a hand-measured figure is flagged stale (FR-005)",
    )

    margin_alert_threshold_pct: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        nullable=False,
        default=Decimal("5"),
        server_default="5",
        comment="Percentage points of realised-versus-planned divergence that alerts (FR-042)",
    )

    min_outcomes_before_auto_update: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        server_default="5",
        comment="Recorded outcomes required before an estimate updates itself (FR-042a)",
    )

    estimate_divergence_threshold_pct: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        nullable=False,
        default=Decimal("25"),
        server_default="25",
        comment="Divergence beyond which an observation is held for review (FR-042b)",
    )

    # ------------------------------------------------------------------
    # Effective period and authorship
    # ------------------------------------------------------------------
    effective_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="First day this policy applied",
    )

    effective_to: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        comment="Last day this policy applied; NULL means it is the current policy",
    )

    set_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Who wrote this row; NULL for the row seeded by migration",
    )

    set_by_role: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="The role that authorised the change (FR-007a)",
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", lazy="select")
    set_by_user: Mapped[Optional["User"]] = relationship("User", lazy="select")

    __table_args__ = (
        # Exactly one current policy per tenant. A partial unique index says
        # this in the schema rather than leaving it to whoever writes the next
        # update path (research.md D6 uses the same device for prices).
        Index(
            "uq_tenant_pricing_policy_current",
            "tenant_id",
            unique=True,
            postgresql_where=effective_to.is_(None),
            sqlite_where=effective_to.is_(None),
        ),
        CheckConstraint(
            "margin_basis IN ('customer_total', 'item_price', 'net_revenue')",
            name="check_pricing_policy_margin_basis",
        ),
        CheckConstraint(
            "overhead_method IN ('per_machine_hour', 'percentage')",
            name="check_pricing_policy_overhead_method",
        ),
        # Absorbing overhead per machine-hour needs a capacity to divide by.
        # Zero expected hours is the spec's "expected capacity of zero" edge
        # case: refused at save time rather than divided by at read time.
        CheckConstraint(
            "overhead_method <> 'per_machine_hour'"
            " OR (expected_monthly_machine_hours IS NOT NULL"
            " AND expected_monthly_machine_hours > 0)",
            name="check_pricing_policy_capacity_when_absorbing_per_hour",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="check_pricing_policy_effective_range",
        ),
        CheckConstraint(
            "overhead_percentage >= 0",
            name="check_policy_overhead_percentage_non_negative",
        ),
        {"comment": "Operator monetary policy, one row per effective period (research.md D2)"},
    )

    @property
    def is_current(self) -> bool:
        """Whether this row is the policy in effect now."""
        return self.effective_to is None

    def __repr__(self) -> str:
        return (
            f"<TenantPricingPolicy(tenant_id={self.tenant_id}, "
            f"effective_from={self.effective_from}, effective_to={self.effective_to})>"
        )
