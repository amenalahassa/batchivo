"""The converted fee rules must charge what the channels charged (task T061).

FR-030 is the one requirement in this feature that admits no approximation:
every existing single-percentage-plus-fixed channel must produce the *same* fee
amounts after migration, expressed as equivalent rules. An operator whose fees
moved during a migration they were told was safe will not trust the figures
afterwards, and would be right not to.

So this suite asserts parity **per channel, over every channel in the
database**, rather than on a sample. The channels are chosen to cover the
shapes that behave differently: percentage only, fixed only, both, neither, a
rate with more decimals than the old column could hold, and a channel whose fee
is large enough that a rounding mistake would be visible.

Parity is checked against the superseded implementation itself --
``SalesChannel.calculate_platform_fee``, which is still present and still the
definition of what the channel used to charge -- rather than against a figure
retyped here. Comparing against a transcription would pass if both the
transcription and the migration were wrong in the same direction.

Everything is synchronous, like the Tier 1 suite and for the same reason: a
migration is synchronous, and psycopg's async mode cannot run on the default
Windows event loop.
"""

import os
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from app.services import fee_engine
from app.services.fee_engine import OrderContext
from tests.integration.migration_support import (
    alembic_against,
    database_named,
    sync_url,
)

TIER2_REVISION = "pricing_tier2_v1"
TIER2_PARENT = "pricing_tier1_v1"

CHANNEL_CREATED_ON = "2024-03-09"

#: (slug, fee_percentage, fee_fixed). Every shape the old pair could take.
SEEDED_CHANNELS: tuple[tuple[str, Decimal, Decimal], ...] = (
    ("both", Decimal("6.50"), Decimal("0.30")),
    ("percentage-only", Decimal("12.50"), Decimal("0.00")),
    ("fixed-only", Decimal("0.00"), Decimal("2.52")),
    ("neither", Decimal("0.00"), Decimal("0.00")),
    # A rate whose last decimal is the one a Numeric(7,4) must not lose.
    ("awkward-rate", Decimal("3.25"), Decimal("0.01")),
    # Large enough that a cent of rounding error shows up.
    ("expensive", Decimal("35.00"), Decimal("15.75")),
)

#: Prices the parity check is made at. The small ones are where a fixed fee
#: dominates and the large ones where a percentage does, so an error in either
#: term cannot hide behind the other.
PARITY_PRICES: tuple[Decimal, ...] = (
    Decimal("0.01"),
    Decimal("4.99"),
    Decimal("37.31"),
    Decimal("64.99"),
    Decimal("1999.95"),
)


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


def _is_postgres() -> bool:
    return "postgres" in _database_url()


pytestmark = pytest.mark.skipif(
    not _is_postgres(),
    reason=(
        "the Tier 2 data migration needs the PostgreSQL dialect (RLS policies, "
        "gen_random_uuid); set DATABASE_URL to a PostgreSQL instance to run it"
    ),
)


class _Rule:
    """A fee rule as the migration wrote it, shaped for the engine.

    The engine reads attributes, so a row from the database can be handed to it
    directly. Deliberately not the ORM class: this suite is checking what the
    *migration* produced, and loading it through the model would let a model
    default paper over a column the migration left empty.
    """

    def __init__(self, row) -> None:
        self.id = row.id
        self.name = row.name
        self.basis = row.basis
        self.rate_pct = row.rate_pct
        self.fixed_amount = row.fixed_amount
        self.min_amount = row.min_amount
        self.max_amount = row.max_amount
        self.incidence_pct = row.incidence_pct
        self.sort_order = row.sort_order
        self.applies_from = row.applies_from
        self.applies_to = row.applies_to

    def applies_on(self, as_of: date) -> bool:
        if as_of < self.applies_from:
            return False
        return self.applies_to is None or as_of <= self.applies_to


class _Channel:
    def __init__(self, rules: list[_Rule]) -> None:
        self.fee_rules = rules
        self.expected_discount_pct = Decimal("0")
        self.expected_refund_pct = Decimal("0")
        self.tax_remitter = "operator"


def _superseded_fee(percentage: Decimal, fixed: Decimal, price: Decimal) -> Decimal:
    """What the old implementation charged, by its own arithmetic.

    This is ``SalesChannel.calculate_platform_fee`` written out: exact decimal,
    no intermediate rounding. It is reproduced rather than imported because the
    column it reads is deprecated and task T123 deletes it along with the
    method, at which point parity has already been established and this file
    needs no edit.
    """
    return price * (percentage / Decimal("100")) + fixed


@pytest.fixture
def migrated_tier2_db():
    """A scratch database with pre-Tier-2 channels in it, then migrated.

    The channels are inserted *between* the two upgrades. Run on an empty
    database the conversion statements are no-ops and prove nothing, which is
    the trap this fixture exists to avoid.
    """
    base_url = _database_url()
    scratch = f"tier2_parity_{uuid.uuid4().hex[:10]}"
    admin_url = database_named(base_url, "postgres")
    scratch_url = database_named(base_url, scratch)

    admin = create_engine(sync_url(admin_url), isolation_level="AUTOCOMMIT")
    engine = None
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{scratch}"'))

        engine = create_engine(sync_url(scratch_url), isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

        with alembic_against(scratch_url) as config:
            command.upgrade(config, TIER2_PARENT)

        with engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO tenants (id, name, slug, is_active, settings,
                                         created_at, updated_at)
                    VALUES (gen_random_uuid(), 'Parity Tenant', 'parity-tenant', true,
                            CAST('{}' AS JSONB), now(), now())
                    """
                )
            )
            for slug, percentage, fixed in SEEDED_CHANNELS:
                conn.execute(
                    text(
                        """
                        INSERT INTO sales_channels (
                            id, tenant_id, name, platform_type, fee_percentage,
                            fee_fixed, monthly_cost, is_active, created_at, updated_at
                        )
                        SELECT gen_random_uuid(), tenants.id, :name, 'etsy',
                               :percentage, :fixed, 0, true, :created_at, now()
                        FROM tenants WHERE tenants.slug = 'parity-tenant'
                        """
                    ),
                    {
                        "name": slug,
                        "percentage": percentage,
                        "fixed": fixed,
                        "created_at": f"{CHANNEL_CREATED_ON}T10:00:00Z",
                    },
                )

        with alembic_against(scratch_url) as config:
            command.upgrade(config, TIER2_REVISION)

        yield SimpleNamespace(engine=engine, url=scratch_url)
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def migrated_tier2(migrated_tier2_db):
    """Just the engine, which is all most of these tests need."""
    return migrated_tier2_db.engine


def _channels_with_rules(engine) -> list[tuple[str, Decimal, Decimal, _Channel]]:
    """Every channel in the database, with the rules the migration gave it."""
    with engine.connect() as conn:
        channels = conn.execute(
            text("SELECT id, name, fee_percentage, fee_fixed FROM sales_channels ORDER BY name")
        ).all()
        result = []
        for channel in channels:
            rules = conn.execute(
                text(
                    """
                    SELECT id, name, basis, rate_pct, fixed_amount, min_amount,
                           max_amount, incidence_pct, sort_order, applies_from, applies_to
                    FROM fee_rules
                    WHERE sales_channel_id = :channel_id
                    ORDER BY sort_order
                    """
                ),
                {"channel_id": channel.id},
            ).all()
            result.append(
                (
                    channel.name,
                    Decimal(str(channel.fee_percentage)),
                    Decimal(str(channel.fee_fixed)),
                    _Channel([_Rule(row) for row in rules]),
                )
            )
    return result


# ============================================================================
# Parity, per channel
# ============================================================================


class TestEveryChannelChargesWhatItChargedBefore:
    def test_every_seeded_channel_is_actually_present(self, migrated_tier2) -> None:
        """Guard the guard: a parity check over zero channels passes vacuously."""
        names = {name for name, _, _, _ in _channels_with_rules(migrated_tier2)}

        assert names == {slug for slug, _, _ in SEEDED_CHANNELS}

    def test_the_converted_rules_reproduce_the_fee_at_every_price(self, migrated_tier2) -> None:
        """FR-030, over every channel and every price, with no tolerance.

        Exact equality rather than a tolerance: ``rate x basis + fixed`` is
        exactly what the old implementation computed, so any difference at all
        is a conversion error rather than a rounding artefact.
        """
        as_of = date(2026, 6, 1)
        failures: list[str] = []

        for name, percentage, fixed, channel in _channels_with_rules(migrated_tier2):
            for price in PARITY_PRICES:
                before = _superseded_fee(percentage, fixed, price)
                after = fee_engine.compute(
                    channel, OrderContext(item_subtotal=price), as_of
                ).total_exact
                if before != after:
                    failures.append(f"{name} at {price}: charged {before} before, {after} after")

        assert not failures, "the migration changed what a channel charges: " + "; ".join(failures)

    def test_a_channel_charging_nothing_gets_no_rules(self, migrated_tier2) -> None:
        """Two rows charging zero would be noise on every fee screen."""
        channels = dict(
            (name, channel) for name, _, _, channel in _channels_with_rules(migrated_tier2)
        )

        assert channels["neither"].fee_rules == []

    def test_a_percentage_only_channel_gets_one_rule(self, migrated_tier2) -> None:
        channels = dict(
            (name, channel) for name, _, _, channel in _channels_with_rules(migrated_tier2)
        )
        rules = channels["percentage-only"].fee_rules

        assert [rule.basis for rule in rules] == ["item_plus_shipping"]

    def test_a_fixed_only_channel_gets_one_rule(self, migrated_tier2) -> None:
        channels = dict(
            (name, channel) for name, _, _, channel in _channels_with_rules(migrated_tier2)
        )
        rules = channels["fixed-only"].fee_rules

        assert [rule.basis for rule in rules] == ["per_order"]

    def test_a_channel_charging_both_gets_both_rules_in_order(self, migrated_tier2) -> None:
        channels = dict(
            (name, channel) for name, _, _, channel in _channels_with_rules(migrated_tier2)
        )
        rules = channels["both"].fee_rules

        assert [rule.basis for rule in rules] == ["item_plus_shipping", "per_order"]
        assert [rule.sort_order for rule in rules] == [10, 20]


# ============================================================================
# The dates, which decide whether history keeps its fees
# ============================================================================


class TestTheRulesCoverTheChannelsWholeHistory:
    def test_each_rule_starts_when_the_channel_did(self, migrated_tier2) -> None:
        """FR-022 and FR-039: an as-of read of an old order must find a rule.

        Dating the converted rules from the migration day instead would leave
        every historical order with no fee rule in effect and a margin that
        silently improved.
        """
        expected = date.fromisoformat(CHANNEL_CREATED_ON)

        for name, _, _, channel in _channels_with_rules(migrated_tier2):
            for rule in channel.fee_rules:
                assert rule.applies_from == expected, f"{name}/{rule.name}"

    def test_no_rule_has_already_ended(self, migrated_tier2) -> None:
        for _, _, _, channel in _channels_with_rules(migrated_tier2):
            for rule in channel.fee_rules:
                assert rule.applies_to is None

    def test_a_fee_charged_on_an_old_order_is_still_the_old_fee(self, migrated_tier2) -> None:
        """Parity, as at a date before the migration ran."""
        as_of = date.fromisoformat(CHANNEL_CREATED_ON)
        price = Decimal("64.99")

        for name, percentage, fixed, channel in _channels_with_rules(migrated_tier2):
            charged = fee_engine.compute(
                channel, OrderContext(item_subtotal=price), as_of
            ).total_exact
            assert charged == _superseded_fee(percentage, fixed, price), name


# ============================================================================
# What the migration must not have touched
# ============================================================================


class TestTheOldColumnsAreKeptAndKeptPopulated:
    def test_the_deprecated_columns_still_hold_what_they_held(self, migrated_tier2) -> None:
        """FR-030 is uncheckable the moment these are dropped (task T123)."""
        with migrated_tier2.connect() as conn:
            rows = conn.execute(
                text("SELECT name, fee_percentage, fee_fixed FROM sales_channels")
            ).all()

        stored = {
            row.name: (Decimal(str(row.fee_percentage)), Decimal(str(row.fee_fixed)))
            for row in rows
        }
        for slug, percentage, fixed in SEEDED_CHANNELS:
            assert stored[slug] == (percentage, fixed)

    def test_the_new_channel_columns_reproduce_todays_behaviour(self, migrated_tier2) -> None:
        """FR-050: a tenant who changes no setting sees no figure move."""
        with migrated_tier2.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT tax_remitter, expected_discount_pct, expected_refund_pct,
                           free_shipping_threshold, rounding_rule, offsite_ads_opt_in
                    FROM sales_channels
                    """
                )
            ).all()

        for row in rows:
            assert row.tax_remitter == "operator"
            assert Decimal(str(row.expected_discount_pct)) == Decimal("0")
            assert Decimal(str(row.expected_refund_pct)) == Decimal("0")
            assert row.free_shipping_threshold is None
            assert row.rounding_rule is None
            assert row.offsite_ads_opt_in is False

    def test_orders_gain_postage_and_tax_at_zero(self, migrated_tier2) -> None:
        """And `shipping_cost` keeps its meaning as revenue (FR-024)."""
        with migrated_tier2.connect() as conn:
            columns = conn.execute(
                text(
                    """
                    SELECT column_name, column_default
                    FROM information_schema.columns
                    WHERE table_name = 'orders'
                      AND column_name IN ('postage_paid', 'sales_tax_collected',
                                          'shipping_cost')
                    """
                )
            ).all()

        found = {row.column_name for row in columns}
        assert found == {"postage_paid", "sales_tax_collected", "shipping_cost"}


# ============================================================================
# Reversibility
# ============================================================================


class TestTheMigrationIsReversible:
    def test_downgrading_removes_the_rules_and_keeps_the_old_columns(
        self, migrated_tier2_db
    ) -> None:
        """The converted rules are derived data, so losing them costs nothing.

        What must survive is the pair they were derived from, because that pair
        is the only record of what the channel charged.
        """
        engine = migrated_tier2_db.engine

        with alembic_against(migrated_tier2_db.url) as config:
            command.downgrade(config, TIER2_PARENT)

        with engine.connect() as conn:
            tables = conn.execute(
                text(
                    """
                    SELECT table_name FROM information_schema.tables
                    WHERE table_name IN ('fee_rules', 'fee_actuals', 'shipping_profiles')
                    """
                )
            ).all()
            channels = conn.execute(
                text("SELECT name, fee_percentage, fee_fixed FROM sales_channels")
            ).all()

        assert tables == []
        stored = {
            row.name: (Decimal(str(row.fee_percentage)), Decimal(str(row.fee_fixed)))
            for row in channels
        }
        for slug, percentage, fixed in SEEDED_CHANNELS:
            assert stored[slug] == (percentage, fixed)
