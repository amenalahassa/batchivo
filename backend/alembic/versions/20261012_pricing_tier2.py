"""Tier 2 of the pricing rebuild: the real fee stack, shipping and tax.

Revision ID: pricing_tier2_v1
Revises: pricing_tier1_v1

What this migration is careful about, and why (task T075):

* **Every existing channel keeps charging exactly what it charged.** FR-030 is
  the hard constraint here, and it is not satisfied by approximation. Each
  channel's ``fee_percentage`` and ``fee_fixed`` are converted into two dated
  ``fee_rules`` rows -- a percentage rule on ``item_plus_shipping`` and a flat
  rule ``per_order`` -- which reproduce the single blended figure exactly,
  because ``rate x basis + fixed`` is what the old
  ``calculate_platform_fee`` computed and the basis is the only revenue figure
  it had. ``tests/integration/test_fee_migration_parity.py`` asserts this per
  channel, not on a sample.

* **The old columns are kept and kept populated.** Dropping them here would
  make FR-030 uncheckable the moment this migration ran, and would break every
  read path in one step. They are marked deprecated in the model and dropped by
  task T123 once nothing reads them.

* **A channel with no fees gets no rules.** A zero percentage and a zero fixed
  amount is a channel that charges nothing, and two rows charging zero would be
  noise on every screen that lists fees. The parity test covers this case by
  asserting the converted total, which is zero either way.

* **The converted rules start when the channel did.** ``applies_from`` is the
  channel's ``created_at`` date, so an as-of read of any past order finds a
  rule in effect (FR-022, FR-039). Dating them from today would leave every
  historical order with no fee rule and a margin that silently improved.

* **Nothing existing is retyped or made non-nullable.** The new channel and
  order columns all carry server defaults reproducing today's behaviour:
  ``tax_remitter`` defaults to ``operator``, the reserves to zero,
  ``postage_paid`` and ``sales_tax_collected`` to zero. A tenant who changes no
  setting sees no figure move (FR-050).

* **``orders.shipping_cost`` is left alone.** It holds shipping *revenue*
  charged to the customer. Reusing it for postage paid is the confusion FR-024
  exists to end, so ``postage_paid`` is a new column and the old one keeps its
  meaning.

The downgrade is complete: it drops what it added, including the converted
rules, and leaves the original ``fee_percentage`` and ``fee_fixed`` untouched
where they have been all along.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "pricing_tier2_v1"
down_revision = "pricing_tier1_v1"
branch_labels = None
depends_on = None


#: Names given to the two rules converted from each channel's single pair.
#: They were shared with a fixture that reproduced the superseded figure
#: through the same two rules; FR-052 retired that comparison once the
#: migration was done, and task T124 deleted it.
PERCENTAGE_RULE_NAME = "platform_percentage"
FIXED_RULE_NAME = "platform_fixed"


def _enable_rls(table: str) -> None:
    """Tenant isolation at the database layer, as Constitution I requires.

    Guarded so the statement is a no-op outside PostgreSQL: the test suite runs
    on SQLite, where RLS does not exist, and a hard failure there would make
    the migration untestable rather than safe.
    """
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def _disable_rls(table: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def _uuid_default() -> sa.sql.elements.TextClause | None:
    """``gen_random_uuid()`` on PostgreSQL, nothing on SQLite."""
    if op.get_bind().dialect.name == "postgresql":
        return sa.text("gen_random_uuid()")
    return None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.Uuid()
    now = sa.func.now()

    # ------------------------------------------------------------------
    # fee_rules
    # ------------------------------------------------------------------
    op.create_table(
        "fee_rules",
        sa.Column("id", uuid_type, primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "tenant_id",
            uuid_type,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sales_channel_id",
            uuid_type,
            sa.ForeignKey("sales_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("basis", sa.String(20), nullable=False),
        sa.Column("rate_pct", sa.Numeric(7, 4), nullable=False, server_default="0"),
        sa.Column("fixed_amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("min_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("max_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("incidence_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("applies_from", sa.Date, nullable=False),
        sa.Column("applies_to", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint(
            "basis IN ('item_subtotal', 'item_plus_shipping', 'order_total', "
            "'per_listing', 'per_order', 'per_unit_sold', 'per_month')",
            name="check_fee_rule_basis",
        ),
        sa.CheckConstraint(
            "min_amount IS NULL OR max_amount IS NULL OR min_amount <= max_amount",
            name="check_fee_rule_clamp_order",
        ),
        sa.CheckConstraint(
            "applies_to IS NULL OR applies_to >= applies_from",
            name="check_fee_rule_effective_range",
        ),
        sa.CheckConstraint("rate_pct >= 0", name="check_fee_rule_rate_not_negative"),
        sa.CheckConstraint(
            "incidence_pct IS NULL OR (incidence_pct >= 0 AND incidence_pct <= 100)",
            name="check_fee_rule_incidence_is_a_share",
        ),
        comment="Ordered, dated marketplace fee rules per channel (FR-020, FR-021)",
    )
    op.create_index("ix_fee_rules_tenant_id", "fee_rules", ["tenant_id"])
    op.create_index("ix_fee_rules_sales_channel_id", "fee_rules", ["sales_channel_id"])
    op.create_index("ix_fee_rules_channel_order", "fee_rules", ["sales_channel_id", "sort_order"])
    _enable_rls("fee_rules")

    # ------------------------------------------------------------------
    # fee_actuals
    # ------------------------------------------------------------------
    op.create_table(
        "fee_actuals",
        sa.Column("id", uuid_type, primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "tenant_id",
            uuid_type,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sales_channel_id",
            uuid_type,
            sa.ForeignKey("sales_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fee_category", sa.String(80), nullable=False),
        sa.Column("period_start", sa.Date, nullable=True),
        sa.Column("period_end", sa.Date, nullable=True),
        sa.Column(
            "order_id",
            uuid_type,
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("source", sa.String(12), nullable=False, server_default="entered"),
        sa.Column(
            "recorded_by_user_id",
            uuid_type,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint(
            "("
            " order_id IS NULL"
            " AND period_start IS NOT NULL"
            " AND period_end IS NOT NULL"
            ") OR ("
            " order_id IS NOT NULL"
            " AND period_start IS NULL"
            " AND period_end IS NULL"
            ")",
            name="check_fee_actual_exactly_one_scope",
        ),
        sa.CheckConstraint(
            "period_end IS NULL OR period_start IS NULL OR period_end >= period_start",
            name="check_fee_actual_period_range",
        ),
        sa.CheckConstraint(
            "source IN ('entered', 'ingested')",
            name="check_fee_actual_source",
        ),
        comment="Fees as a statement charged them, per period or per order (FR-041)",
    )
    op.create_index("ix_fee_actuals_tenant_id", "fee_actuals", ["tenant_id"])
    op.create_index("ix_fee_actuals_sales_channel_id", "fee_actuals", ["sales_channel_id"])
    op.create_index("ix_fee_actuals_order_id", "fee_actuals", ["order_id"])
    op.create_index(
        "ix_fee_actuals_channel_period",
        "fee_actuals",
        ["sales_channel_id", "fee_category", "period_start"],
    )
    _enable_rls("fee_actuals")

    # ------------------------------------------------------------------
    # shipping_profiles
    # ------------------------------------------------------------------
    op.create_table(
        "shipping_profiles",
        sa.Column("id", uuid_type, primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "tenant_id",
            uuid_type,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("destination_zone", sa.String(50), nullable=False),
        sa.Column(
            "weight_bracket_min_grams", sa.Numeric(10, 2), nullable=False, server_default="0"
        ),
        sa.Column("weight_bracket_max_grams", sa.Numeric(10, 2), nullable=True),
        sa.Column("postage_cost", sa.Numeric(10, 2), nullable=False),
        sa.Column("carrier", sa.String(50), nullable=True),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint(
            "weight_bracket_max_grams IS NULL"
            " OR weight_bracket_max_grams > weight_bracket_min_grams",
            name="check_shipping_profile_bracket_order",
        ),
        sa.CheckConstraint(
            "weight_bracket_min_grams >= 0",
            name="check_shipping_profile_bracket_not_negative",
        ),
        sa.CheckConstraint("postage_cost >= 0", name="check_shipping_profile_postage_not_negative"),
        comment="Postage paid per zone and weight bracket (FR-024)",
    )
    op.create_index("ix_shipping_profiles_tenant_id", "shipping_profiles", ["tenant_id"])
    op.create_index(
        "ix_shipping_profiles_zone_bracket",
        "shipping_profiles",
        ["tenant_id", "destination_zone", "weight_bracket_min_grams"],
    )
    _enable_rls("shipping_profiles")

    # ------------------------------------------------------------------
    # sales_channels: channel economics
    # ------------------------------------------------------------------
    op.add_column(
        "sales_channels",
        sa.Column("tax_remitter", sa.String(12), nullable=False, server_default="operator"),
    )
    op.add_column(
        "sales_channels",
        sa.Column("expected_discount_pct", sa.Numeric(7, 4), nullable=False, server_default="0"),
    )
    op.add_column(
        "sales_channels",
        sa.Column("expected_refund_pct", sa.Numeric(7, 4), nullable=False, server_default="0"),
    )
    op.add_column(
        "sales_channels",
        sa.Column("free_shipping_threshold", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column("sales_channels", sa.Column("rounding_rule", sa.String(20), nullable=True))
    op.add_column(
        "sales_channels",
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="GBP"),
    )
    op.add_column(
        "sales_channels",
        sa.Column("offsite_ads_opt_in", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_check_constraint(
        "check_sales_channel_tax_remitter",
        "sales_channels",
        "tax_remitter IN ('marketplace', 'operator')",
    )

    # ------------------------------------------------------------------
    # orders: postage paid and tax collected
    # ------------------------------------------------------------------
    op.add_column(
        "orders",
        sa.Column("postage_paid", sa.Numeric(10, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "orders",
        sa.Column("sales_tax_collected", sa.Numeric(10, 2), nullable=False, server_default="0"),
    )

    # ------------------------------------------------------------------
    # pricing_input_provenance: the new entity types
    #
    # The CHECK is recreated rather than altered because a CHECK cannot be
    # extended in place. `fee_actuals` is deliberately absent: a recorded
    # actual carries its origin in its own `source` column (FR-041e).
    # ------------------------------------------------------------------
    if is_postgres:
        op.drop_constraint(
            "check_pricing_input_provenance_entity_type",
            "pricing_input_provenance",
            type_="check",
        )
        op.create_check_constraint(
            "check_pricing_input_provenance_entity_type",
            "pricing_input_provenance",
            "entity_type IN ("
            "'model', 'model_material', 'model_component', 'model_printer_config', "
            "'product', 'printer', 'spool', 'filament_purchase', "
            "'tenant_pricing_policy', 'sales_channel', "
            "'fee_rule', 'shipping_profile'"
            ")",
        )

    # ------------------------------------------------------------------
    # The data migration: one channel's pair becomes two dated rules (FR-030)
    # ------------------------------------------------------------------
    _convert_channel_fees(uuid_type)


def _convert_channel_fees(uuid_type) -> None:
    """Turn each channel's single percentage and fixed amount into rules.

    Written as two INSERT ... SELECT statements rather than a Python loop so
    the conversion is one statement per rule kind over every channel, inside
    the migration's own transaction. A loop issuing a statement per channel
    would be slower and, more importantly, would make a partial conversion
    possible if it failed halfway.

    ``applies_from`` is the channel's own creation date so that an as-of read
    of any historical order finds a rule in effect (FR-022, FR-039).

    Only channels that actually charge something get a rule: a zero percentage
    and a zero fixed amount is a channel that charges nothing, and two rows
    charging zero would be noise on every screen listing fees.
    """
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    new_id = "gen_random_uuid()" if is_postgres else "lower(hex(randomblob(16)))"
    # SQLite stores DATE as text; both dialects accept a cast from the
    # timestamp the channel was created at.
    created_date = "CAST(created_at AS DATE)" if is_postgres else "date(created_at)"

    op.execute(
        f"""
        INSERT INTO fee_rules (
            id, tenant_id, sales_channel_id, name, basis, rate_pct, fixed_amount,
            sort_order, applies_from, created_at, updated_at
        )
        SELECT
            {new_id},
            tenant_id,
            id,
            '{PERCENTAGE_RULE_NAME}',
            'item_plus_shipping',
            fee_percentage,
            0,
            10,
            {created_date},
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM sales_channels
        WHERE fee_percentage IS NOT NULL AND fee_percentage > 0
        """
    )

    op.execute(
        f"""
        INSERT INTO fee_rules (
            id, tenant_id, sales_channel_id, name, basis, rate_pct, fixed_amount,
            sort_order, applies_from, created_at, updated_at
        )
        SELECT
            {new_id},
            tenant_id,
            id,
            '{FIXED_RULE_NAME}',
            'per_order',
            0,
            fee_fixed,
            20,
            {created_date},
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM sales_channels
        WHERE fee_fixed IS NOT NULL AND fee_fixed > 0
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # The converted rules go with the table, and `fee_percentage` and
    # `fee_fixed` were never touched, so nothing is lost by dropping them.
    if is_postgres:
        op.drop_constraint(
            "check_pricing_input_provenance_entity_type",
            "pricing_input_provenance",
            type_="check",
        )
        op.create_check_constraint(
            "check_pricing_input_provenance_entity_type",
            "pricing_input_provenance",
            "entity_type IN ("
            "'model', 'model_material', 'model_component', 'model_printer_config', "
            "'product', 'printer', 'spool', 'filament_purchase', "
            "'tenant_pricing_policy', 'sales_channel'"
            ")",
        )

    for column in ("sales_tax_collected", "postage_paid"):
        op.drop_column("orders", column)

    op.drop_constraint("check_sales_channel_tax_remitter", "sales_channels", type_="check")
    for column in (
        "offsite_ads_opt_in",
        "currency_code",
        "rounding_rule",
        "free_shipping_threshold",
        "expected_refund_pct",
        "expected_discount_pct",
        "tax_remitter",
    ):
        op.drop_column("sales_channels", column)

    _disable_rls("shipping_profiles")
    op.drop_index("ix_shipping_profiles_zone_bracket", table_name="shipping_profiles")
    op.drop_index("ix_shipping_profiles_tenant_id", table_name="shipping_profiles")
    op.drop_table("shipping_profiles")

    _disable_rls("fee_actuals")
    op.drop_index("ix_fee_actuals_channel_period", table_name="fee_actuals")
    op.drop_index("ix_fee_actuals_order_id", table_name="fee_actuals")
    op.drop_index("ix_fee_actuals_sales_channel_id", table_name="fee_actuals")
    op.drop_index("ix_fee_actuals_tenant_id", table_name="fee_actuals")
    op.drop_table("fee_actuals")

    _disable_rls("fee_rules")
    op.drop_index("ix_fee_rules_channel_order", table_name="fee_rules")
    op.drop_index("ix_fee_rules_sales_channel_id", table_name="fee_rules")
    op.drop_index("ix_fee_rules_tenant_id", table_name="fee_rules")
    op.drop_table("fee_rules")
