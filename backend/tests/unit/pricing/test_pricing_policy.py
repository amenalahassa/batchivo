"""Policy is read as at a date, and a change writes a row instead of overwriting.

FR-003 is the whole point of this table: a past figure must stay readable after
the policy changes, because FR-031d and FR-039 report a settled order on the
policy that was in effect when it was placed. An update in place destroys that,
silently, and only shows up as a report that cannot be reproduced.

So two properties are tested, and the second is tested by counting rows as well
as by reading them back: a write that updated in place and then inserted a
copy would satisfy a read-back assertion alone.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.models.tenant_pricing_policy import TenantPricingPolicy
from app.services.pricing_policy import (
    PolicyMisconfigured,
    current_policy_row,
    ensure_policy_row,
    legacy_cost_policy,
    resolve_cost_policy,
    resolve_policy_row,
    write_policy,
)

TODAY = date(2026, 10, 11)
LAST_YEAR = date(2025, 10, 11)


async def _row_count(db: AsyncSession, tenant: Tenant) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(TenantPricingPolicy)
            .where(TenantPricingPolicy.tenant_id == tenant.id)
        )
    ) or 0


@pytest.fixture
async def seeded(db_session: AsyncSession, test_tenant: Tenant) -> TenantPricingPolicy:
    """A policy in force since last year, as the Tier 1 migration seeds one."""
    row = TenantPricingPolicy(
        tenant_id=test_tenant.id,
        print_labor_rate=Decimal("20.0000"),
        finishing_labor_rate=Decimal("20.0000"),
        overhead_method="percentage",
        margin_basis="customer_total",
        sales_tax_recoverable=False,
        staleness_threshold_days=180,
        margin_alert_threshold_pct=Decimal("5"),
        min_outcomes_before_auto_update=5,
        estimate_divergence_threshold_pct=Decimal("25"),
        effective_from=LAST_YEAR,
        effective_to=None,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


class TestAnAsOfReadReturnsTheRowInEffect:
    async def test_todays_read_returns_the_open_row(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        resolved = await resolve_policy_row(db_session, test_tenant, TODAY)
        assert resolved is not None
        assert resolved.id == seeded.id

    async def test_a_date_before_the_first_row_resolves_to_nothing(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        """A cost dated before any policy existed must not borrow a later one."""
        assert (
            await resolve_policy_row(db_session, test_tenant, LAST_YEAR - timedelta(days=1)) is None
        )

    async def test_a_superseded_row_is_still_readable_at_its_own_date(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        await write_policy(
            db_session,
            test_tenant,
            {"print_labor_rate": Decimal("25.0000")},
            effective_from=TODAY,
        )
        await db_session.commit()

        then = await resolve_policy_row(db_session, test_tenant, LAST_YEAR)
        now = await resolve_policy_row(db_session, test_tenant, TODAY)
        assert then is not None and now is not None
        assert then.print_labor_rate == Decimal("20.0000")
        assert now.print_labor_rate == Decimal("25.0000")

    async def test_the_boundary_day_belongs_to_the_new_row(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        """A policy effective from a date applies on that date, not the next."""
        await write_policy(
            db_session,
            test_tenant,
            {"print_labor_rate": Decimal("25.0000")},
            effective_from=TODAY,
        )
        await db_session.commit()
        resolved = await resolve_policy_row(db_session, test_tenant, TODAY)
        assert resolved is not None
        assert resolved.print_labor_rate == Decimal("25.0000")

    async def test_the_day_before_the_change_belongs_to_the_old_row(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        await write_policy(
            db_session,
            test_tenant,
            {"print_labor_rate": Decimal("25.0000")},
            effective_from=TODAY,
        )
        await db_session.commit()
        resolved = await resolve_policy_row(db_session, test_tenant, TODAY - timedelta(days=1))
        assert resolved is not None
        assert resolved.print_labor_rate == Decimal("20.0000")


class TestAWriteNeverUpdatesInPlace:
    """FR-003, checked by counting rows as well as by reading them back."""

    async def test_a_change_adds_a_row(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        before = await _row_count(db_session, test_tenant)
        await write_policy(
            db_session,
            test_tenant,
            {"print_labor_rate": Decimal("25.0000")},
            effective_from=TODAY,
        )
        await db_session.commit()
        assert await _row_count(db_session, test_tenant) == before + 1

    async def test_the_superseded_row_keeps_its_figure(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        await write_policy(
            db_session,
            test_tenant,
            {"print_labor_rate": Decimal("25.0000")},
            effective_from=TODAY,
        )
        await db_session.commit()
        await db_session.refresh(seeded)
        assert seeded.print_labor_rate == Decimal("20.0000"), (
            "the old row's figure was overwritten, so no report before today can "
            "be reproduced (FR-003)"
        )

    async def test_the_superseded_row_is_closed_the_day_before(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        await write_policy(
            db_session,
            test_tenant,
            {"print_labor_rate": Decimal("25.0000")},
            effective_from=TODAY,
        )
        await db_session.commit()
        await db_session.refresh(seeded)
        assert seeded.effective_to == TODAY - timedelta(days=1)

    async def test_exactly_one_row_stays_open(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        for day, rate in ((TODAY, "25"), (TODAY + timedelta(days=30), "27")):
            await write_policy(
                db_session,
                test_tenant,
                {"print_labor_rate": Decimal(rate)},
                effective_from=day,
            )
            await db_session.commit()

        open_rows = (
            await db_session.execute(
                select(func.count())
                .select_from(TenantPricingPolicy)
                .where(
                    TenantPricingPolicy.tenant_id == test_tenant.id,
                    TenantPricingPolicy.effective_to.is_(None),
                )
            )
        ).scalar()
        assert open_rows == 1

    async def test_unchanged_levers_are_copied_forward(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        """A change to one lever must not reset the others to their defaults."""
        await write_policy(
            db_session,
            test_tenant,
            {"staleness_threshold_days": 90},
            effective_from=TODAY,
        )
        await db_session.commit()
        current = await current_policy_row(db_session, test_tenant)
        assert current is not None
        assert current.staleness_threshold_days == 90
        assert current.print_labor_rate == Decimal("20.0000")
        assert current.margin_basis == "customer_total"

    async def test_two_changes_in_one_day_leave_the_later_one_in_force(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        for rate in ("25", "30"):
            await write_policy(
                db_session,
                test_tenant,
                {"print_labor_rate": Decimal(rate)},
                effective_from=TODAY,
            )
            await db_session.commit()
        resolved = await resolve_policy_row(db_session, test_tenant, TODAY)
        assert resolved is not None
        assert resolved.print_labor_rate == Decimal("30")

    async def test_the_author_and_role_are_recorded(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy, test_user
    ) -> None:
        """FR-007a: a policy change carries the role that authorised it."""
        row = await write_policy(
            db_session,
            test_tenant,
            {"print_labor_rate": Decimal("25")},
            user=test_user,
            role="admin",
            effective_from=TODAY,
        )
        await db_session.commit()
        assert row.set_by_user_id == test_user.id
        assert row.set_by_role == "admin"


class TestAMisconfiguredPolicyIsRefused:
    async def test_an_unknown_lever_is_refused_rather_than_ignored(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        """A silently dropped lever is a policy the operator believes they set."""
        with pytest.raises(PolicyMisconfigured) as excinfo:
            await write_policy(db_session, test_tenant, {"labour_rate": Decimal("25")})
        assert "labour_rate" in str(excinfo.value)

    async def test_absorbing_per_machine_hour_without_a_capacity_is_refused(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        """Spec edge case: expected capacity of zero is reported, not divided by."""
        with pytest.raises(PolicyMisconfigured):
            await write_policy(
                db_session,
                test_tenant,
                {"overhead_method": "per_machine_hour", "overhead_monthly_pool": Decimal("180")},
            )

    async def test_a_zero_capacity_is_refused(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        with pytest.raises(PolicyMisconfigured):
            await write_policy(
                db_session,
                test_tenant,
                {
                    "overhead_method": "per_machine_hour",
                    "overhead_monthly_pool": Decimal("180"),
                    "expected_monthly_machine_hours": Decimal("0"),
                },
            )

    async def test_an_unknown_margin_basis_is_refused(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        with pytest.raises(PolicyMisconfigured):
            await write_policy(db_session, test_tenant, {"margin_basis": "on_vibes"})

    async def test_a_negative_labor_rate_is_refused(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        with pytest.raises(PolicyMisconfigured):
            await write_policy(db_session, test_tenant, {"print_labor_rate": Decimal("-5")})

    async def test_a_valid_per_machine_hour_policy_is_accepted(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        row = await write_policy(
            db_session,
            test_tenant,
            {
                "overhead_method": "per_machine_hour",
                "overhead_monthly_pool": Decimal("180"),
                "expected_monthly_machine_hours": Decimal("600"),
            },
            effective_from=TODAY,
        )
        await db_session.commit()
        assert row.overhead_method == "per_machine_hour"


class TestTheResolvedSnapshotTheEngineTakes:
    async def test_it_carries_the_rows_figures(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        policy = await resolve_cost_policy(db_session, test_tenant, TODAY)
        assert policy.print_labor_rate == Decimal("20.0000")
        assert policy.origin == "policy_row"

    async def test_overhead_per_machine_hour_is_derived_not_stored(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        """Constitution V: the absorption rate is computed from pool and capacity."""
        await write_policy(
            db_session,
            test_tenant,
            {
                "overhead_method": "per_machine_hour",
                "overhead_monthly_pool": Decimal("180"),
                "expected_monthly_machine_hours": Decimal("600"),
            },
            effective_from=TODAY,
        )
        await db_session.commit()
        policy = await resolve_cost_policy(db_session, test_tenant, TODAY)
        assert policy.overhead_rate_per_machine_hour == Decimal("0.3")

    async def test_the_percentage_method_absorbs_no_hourly_overhead(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        policy = await resolve_cost_policy(db_session, test_tenant, TODAY)
        assert policy.overhead_method == "percentage"
        assert policy.overhead_rate_per_machine_hour is None

    async def test_a_tenant_with_no_policy_row_falls_back_to_its_settings(
        self, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        """No row yet is not a reason to cost at a rate nobody configured."""
        test_tenant.settings = {**(test_tenant.settings or {}), "default_labor_rate": "33.00"}
        db_session.add(test_tenant)
        await db_session.commit()

        policy = await resolve_cost_policy(db_session, test_tenant, TODAY)
        assert policy.print_labor_rate == Decimal("33.00")
        assert policy.origin == "legacy_settings"
        assert policy.default_machine_rate_per_hour is None

    async def test_the_fallback_names_itself_as_a_fallback(self, test_tenant: Tenant) -> None:
        """So a breakdown can say the figure is a legacy default, not a decision."""
        assert legacy_cost_policy(test_tenant).origin == "legacy_settings"


class TestSeedingARowForATenantThatHasNone:
    async def test_a_row_is_created_from_the_legacy_settings(
        self, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        test_tenant.settings = {**(test_tenant.settings or {}), "default_labor_rate": "21.50"}
        db_session.add(test_tenant)
        await db_session.commit()

        row = await ensure_policy_row(db_session, test_tenant, effective_from=TODAY)
        await db_session.commit()
        assert row.print_labor_rate == Decimal("21.50")
        assert row.finishing_labor_rate == Decimal("21.50")
        assert row.effective_from == TODAY

    async def test_an_existing_row_is_returned_unchanged(
        self, db_session: AsyncSession, test_tenant: Tenant, seeded: TenantPricingPolicy
    ) -> None:
        before = await _row_count(db_session, test_tenant)
        row = await ensure_policy_row(db_session, test_tenant)
        assert row.id == seeded.id
        assert await _row_count(db_session, test_tenant) == before
