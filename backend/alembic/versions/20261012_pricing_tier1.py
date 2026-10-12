"""Tier 1 of the pricing rebuild: machine cost, yield, policy and provenance.

Revision ID: pricing_tier1_v1
Revises: commerce_handover_v1

What this migration is careful about, and why (task T045):

* **Nothing existing is dropped or retyped.** Every column added is nullable or
  carries a server default that reproduces today's behaviour: `waste_grams`
  defaults to 0, `expected_yield` to 1.0, `failure_mode` to 'per_part'. A
  tenant who changes no setting sees no figure move (FR-050).
* **`labor_hours` is copied, not moved.** The deprecated single figure is
  copied into `labor_hours_per_item` and left in place, so a rollback does not
  lose it and the engine's fallback keeps working either way.
* **One policy row per tenant, seeded from what they already configured.**
  `Tenant.settings['default_labor_rate']` was a float that nothing read while
  every screen costed labor at a hardcoded 10.00. Seeding it as the policy's
  labor rate is what makes User Story 1's correction durable; `effective_from`
  is the tenant's own creation date, so an as-of read of any past order finds a
  policy in effect.
* **Provenance is seeded as 'assumed', dated to the row's own creation.** The
  task text says 'assumed' for every existing numeric input, and that is what
  is done here for every *estimate* — the figures an operator typed or a
  default supplied. The seeded policy row's own levers are recorded as
  'policy' instead: they are decisions, and labelling a decision an assumption
  would understate the trust in exactly the figures FR-002 makes the
  operator's. Fields whose columns this migration creates empty get no row at
  all; an unrecorded field already reads as its registry default, and a row
  claiming a date for a NULL would be a fabrication.

The downgrade is complete and reversible: it drops what it added, and the
copied labor figure is left where it came from.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "pricing_tier1_v1"
down_revision = "commerce_handover_v1"
branch_labels = None
depends_on = None


#: Each entry is (entity_type, table, field, join to reach tenant_id).
#: Only fields that can already hold a figure appear: seeding a provenance row
#: for a column this migration just created empty would date a NULL.
_ASSUMED_INPUTS: tuple[tuple[str, str, str, str], ...] = (
    ("model", "models", "labor_hours", "models.tenant_id"),
    ("model", "models", "labor_hours_per_item", "models.tenant_id"),
    ("model", "models", "print_time_minutes", "models.tenant_id"),
    ("model", "models", "prints_per_plate", "models.tenant_id"),
    ("product", "products", "assembly_minutes", "products.tenant_id"),
    ("product", "products", "packaging_cost", "products.tenant_id"),
    ("product", "products", "packaging_quantity", "products.tenant_id"),
    ("spool", "spools", "initial_weight", "spools.tenant_id"),
    ("spool", "spools", "purchase_price", "spools.tenant_id"),
)

#: The same, for tables that carry no tenant_id of their own and reach it
#: through their parent model.
_ASSUMED_INPUTS_VIA_MODEL: tuple[tuple[str, str, str], ...] = (
    ("model_material", "model_materials", "weight_grams"),
    ("model_material", "model_materials", "cost_per_gram"),
    ("model_component", "model_components", "quantity"),
    ("model_component", "model_components", "unit_cost"),
    ("model_printer_config", "model_printer_configs", "print_time_minutes"),
    ("model_printer_config", "model_printer_configs", "material_weight_grams"),
    ("model_printer_config", "model_printer_configs", "prints_per_plate"),
)

#: Levers of the seeded policy row, recorded as decisions rather than guesses.
_POLICY_LEVERS: tuple[str, ...] = (
    "print_labor_rate",
    "finishing_labor_rate",
    "staleness_threshold_days",
    "margin_alert_threshold_pct",
    "min_outcomes_before_auto_update",
    "estimate_divergence_threshold_pct",
)


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
    """``gen_random_uuid()`` on PostgreSQL, nothing on SQLite.

    The seeding statements below run in SQL rather than through the ORM, so
    they need the database to supply the primary key.
    """
    if op.get_bind().dialect.name == "postgresql":
        return sa.text("gen_random_uuid()")
    return None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.Uuid()
    now = sa.func.now()

    # ------------------------------------------------------------------
    # New tables
    # ------------------------------------------------------------------
    op.create_table(
        "tenant_pricing_policy",
        sa.Column("id", uuid_type, primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "tenant_id",
            uuid_type,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("print_labor_rate", sa.Numeric(12, 4), nullable=False),
        sa.Column("finishing_labor_rate", sa.Numeric(12, 4), nullable=False),
        sa.Column("default_machine_rate_per_hour", sa.Numeric(12, 4), nullable=True),
        sa.Column(
            "overhead_method",
            sa.String(20),
            nullable=False,
            server_default="per_machine_hour",
        ),
        sa.Column("overhead_monthly_pool", sa.Numeric(12, 4), nullable=True),
        sa.Column("expected_monthly_machine_hours", sa.Numeric(12, 4), nullable=True),
        sa.Column("electricity_rate_per_kwh", sa.Numeric(8, 4), nullable=True),
        sa.Column("margin_basis", sa.String(20), nullable=False, server_default="customer_total"),
        sa.Column("default_target_margin_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("rounding_rule", sa.String(20), nullable=True),
        sa.Column("sales_tax_recoverable", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("staleness_threshold_days", sa.Integer(), nullable=False, server_default="180"),
        sa.Column(
            "margin_alert_threshold_pct", sa.Numeric(7, 4), nullable=False, server_default="5"
        ),
        sa.Column(
            "min_outcomes_before_auto_update", sa.Integer(), nullable=False, server_default="5"
        ),
        sa.Column(
            "estimate_divergence_threshold_pct",
            sa.Numeric(7, 4),
            nullable=False,
            server_default="25",
        ),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "set_by_user_id",
            uuid_type,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("set_by_role", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint(
            "margin_basis IN ('customer_total', 'item_price', 'net_revenue')",
            name="check_pricing_policy_margin_basis",
        ),
        sa.CheckConstraint(
            "overhead_method IN ('per_machine_hour', 'percentage')",
            name="check_pricing_policy_overhead_method",
        ),
        sa.CheckConstraint(
            "overhead_method <> 'per_machine_hour'"
            " OR (expected_monthly_machine_hours IS NOT NULL"
            " AND expected_monthly_machine_hours > 0)",
            name="check_pricing_policy_capacity_when_absorbing_per_hour",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="check_pricing_policy_effective_range",
        ),
        comment="Operator monetary policy, one row per effective period (research.md D2)",
    )
    op.create_index("ix_tenant_pricing_policy_tenant_id", "tenant_pricing_policy", ["tenant_id"])
    # Exactly one current policy per tenant, said in the schema rather than
    # left to whoever writes the next update path.
    op.create_index(
        "uq_tenant_pricing_policy_current",
        "tenant_pricing_policy",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
        sqlite_where=sa.text("effective_to IS NULL"),
    )
    _enable_rls("tenant_pricing_policy")

    op.create_table(
        "pricing_input_provenance",
        sa.Column("id", uuid_type, primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "tenant_id",
            uuid_type,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", uuid_type, nullable=False),
        sa.Column("field_name", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "measured_by_user_id",
            uuid_type,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("authorised_by_role", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.UniqueConstraint(
            "tenant_id",
            "entity_type",
            "entity_id",
            "field_name",
            name="uq_pricing_input_provenance_field",
        ),
        sa.CheckConstraint(
            "source IN ('policy', 'observed', 'measured', 'assumed')",
            name="check_pricing_input_provenance_source",
        ),
        sa.CheckConstraint(
            "entity_type IN ("
            "'model', 'model_material', 'model_component', 'model_printer_config', "
            "'product', 'printer', 'spool', 'filament_purchase', "
            "'tenant_pricing_policy', 'sales_channel'"
            ")",
            name="check_pricing_input_provenance_entity_type",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence > 0 AND confidence <= 1)",
            name="check_pricing_input_provenance_confidence",
        ),
        comment="Origin, date and confidence of every numeric input to a cost (FR-001)",
    )
    op.create_index(
        "ix_pricing_input_provenance_tenant_id", "pricing_input_provenance", ["tenant_id"]
    )
    op.create_index(
        "ix_pricing_input_provenance_source",
        "pricing_input_provenance",
        ["tenant_id", "source"],
    )
    _enable_rls("pricing_input_provenance")

    op.create_table(
        "filament_purchases",
        sa.Column("id", uuid_type, primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "tenant_id",
            uuid_type,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("supplier", sa.String(200), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("inbound_shipping_cost", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("tax_recoverable", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("order_reference", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint(
            "inbound_shipping_cost >= 0",
            name="check_filament_purchase_shipping_non_negative",
        ),
        sa.CheckConstraint("tax_amount >= 0", name="check_filament_purchase_tax_non_negative"),
        comment="Filament purchases, from which per-spool landed costs are derived (FR-008a)",
    )
    op.create_index("ix_filament_purchases_tenant_id", "filament_purchases", ["tenant_id"])
    _enable_rls("filament_purchases")

    # ------------------------------------------------------------------
    # Machine cost policy on printers (FR-010)
    # ------------------------------------------------------------------
    op.add_column("printers", sa.Column("purchase_price", sa.Numeric(10, 2), nullable=True))
    op.add_column("printers", sa.Column("expected_lifetime_hours", sa.Integer(), nullable=True))
    op.add_column(
        "printers", sa.Column("maintenance_reserve_total", sa.Numeric(10, 2), nullable=True)
    )
    op.add_column("printers", sa.Column("measured_watts", sa.Numeric(8, 2), nullable=True))
    op.add_column(
        "printers", sa.Column("electricity_rate_per_kwh", sa.Numeric(8, 4), nullable=True)
    )
    op.create_check_constraint(
        "check_printer_lifetime_positive_when_priced",
        "printers",
        "purchase_price IS NULL"
        " OR (expected_lifetime_hours IS NOT NULL AND expected_lifetime_hours > 0)",
    )

    # ------------------------------------------------------------------
    # Waste, yield and the four labor components on models
    # ------------------------------------------------------------------
    op.add_column(
        "models",
        sa.Column("waste_grams", sa.Numeric(8, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "models",
        sa.Column("expected_yield", sa.Numeric(5, 4), nullable=False, server_default="1.0"),
    )
    op.add_column(
        "models",
        sa.Column("failure_mode", sa.String(10), nullable=False, server_default="per_part"),
    )
    for column in (
        "labor_hours_per_plate",
        "labor_hours_per_item",
        "finishing_hours_per_item",
        "packing_hours_per_item",
    ):
        op.add_column(
            "models",
            sa.Column(column, sa.Numeric(8, 3), nullable=False, server_default="0"),
        )
    op.create_check_constraint(
        "check_model_expected_yield_in_unit_interval",
        "models",
        "expected_yield > 0 AND expected_yield <= 1",
    )
    op.create_check_constraint(
        "check_model_failure_mode",
        "models",
        "failure_mode IN ('per_part', 'per_plate')",
    )

    # The deprecated single figure is copied, not moved: a rollback must not
    # lose the only labor figure a model ever had.
    op.execute("UPDATE models SET labor_hours_per_item = labor_hours WHERE labor_hours IS NOT NULL")

    # ------------------------------------------------------------------
    # Spools: a parent purchase, and the remainder that can never be printed
    # ------------------------------------------------------------------
    op.add_column(
        "spools",
        sa.Column(
            "filament_purchase_id",
            uuid_type,
            sa.ForeignKey("filament_purchases.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("spools", sa.Column("unusable_remainder_grams", sa.Numeric(8, 2), nullable=True))
    op.create_index("ix_spools_filament_purchase_id", "spools", ["filament_purchase_id"])
    op.create_check_constraint(
        "check_spool_unusable_remainder_non_negative",
        "spools",
        "unusable_remainder_grams IS NULL OR unusable_remainder_grams >= 0",
    )

    # ------------------------------------------------------------------
    # Seed one policy row per tenant, from what the operator already configured
    # ------------------------------------------------------------------
    labor_rate_sql = (
        "COALESCE((tenants.settings ->> 'default_labor_rate')::numeric, 0)"
        if is_postgres
        else "COALESCE(CAST(json_extract(tenants.settings, '$.default_labor_rate') AS NUMERIC), 0)"
    )
    uuid_sql = "gen_random_uuid()" if is_postgres else "lower(hex(randomblob(16)))"

    op.execute(
        f"""
        INSERT INTO tenant_pricing_policy (
            id, tenant_id, print_labor_rate, finishing_labor_rate,
            overhead_method, margin_basis, effective_from, effective_to,
            created_at, updated_at
        )
        SELECT
            {uuid_sql},
            tenants.id,
            {labor_rate_sql},
            {labor_rate_sql},
            'percentage',
            'customer_total',
            CAST(tenants.created_at AS DATE),
            NULL,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM tenants
        WHERE NOT EXISTS (
            SELECT 1 FROM tenant_pricing_policy
            WHERE tenant_pricing_policy.tenant_id = tenants.id
        )
        """
    )
    # 'percentage' rather than the column default: the per-machine-hour method
    # needs a pool and a capacity nobody has entered yet, and switching an
    # existing tenant's overhead method silently would move every cost on
    # every screen (FR-050). They opt in from the settings screen.

    # ------------------------------------------------------------------
    # Seed provenance
    # ------------------------------------------------------------------
    for entity_type, table, field, tenant_column in _ASSUMED_INPUTS:
        op.execute(
            f"""
            INSERT INTO pricing_input_provenance (
                id, tenant_id, entity_type, entity_id, field_name, source, as_of,
                created_at, updated_at
            )
            SELECT
                {uuid_sql}, {tenant_column}, '{entity_type}', {table}.id, '{field}',
                'assumed', CAST({table}.created_at AS DATE),
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM {table}
            WHERE {table}.{field} IS NOT NULL
            """
        )

    for entity_type, table, field in _ASSUMED_INPUTS_VIA_MODEL:
        op.execute(
            f"""
            INSERT INTO pricing_input_provenance (
                id, tenant_id, entity_type, entity_id, field_name, source, as_of,
                created_at, updated_at
            )
            SELECT
                {uuid_sql}, models.tenant_id, '{entity_type}', {table}.id, '{field}',
                'assumed', CAST({table}.created_at AS DATE),
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM {table}
            JOIN models ON models.id = {table}.model_id
            WHERE {table}.{field} IS NOT NULL
            """
        )

    for lever in _POLICY_LEVERS:
        op.execute(
            f"""
            INSERT INTO pricing_input_provenance (
                id, tenant_id, entity_type, entity_id, field_name, source, as_of,
                created_at, updated_at
            )
            SELECT
                {uuid_sql}, tenant_pricing_policy.tenant_id, 'tenant_pricing_policy',
                tenant_pricing_policy.id, '{lever}', 'policy',
                tenant_pricing_policy.effective_from,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM tenant_pricing_policy
            WHERE tenant_pricing_policy.effective_to IS NULL
            """
        )


def downgrade() -> None:
    op.drop_constraint("check_spool_unusable_remainder_non_negative", "spools", type_="check")
    op.drop_index("ix_spools_filament_purchase_id", table_name="spools")
    op.drop_column("spools", "unusable_remainder_grams")
    op.drop_column("spools", "filament_purchase_id")

    op.drop_constraint("check_model_failure_mode", "models", type_="check")
    op.drop_constraint("check_model_expected_yield_in_unit_interval", "models", type_="check")
    for column in (
        "packing_hours_per_item",
        "finishing_hours_per_item",
        "labor_hours_per_item",
        "labor_hours_per_plate",
        "failure_mode",
        "expected_yield",
        "waste_grams",
    ):
        op.drop_column("models", column)

    op.drop_constraint("check_printer_lifetime_positive_when_priced", "printers", type_="check")
    for column in (
        "electricity_rate_per_kwh",
        "measured_watts",
        "maintenance_reserve_total",
        "expected_lifetime_hours",
        "purchase_price",
    ):
        op.drop_column("printers", column)

    _disable_rls("filament_purchases")
    op.drop_index("ix_filament_purchases_tenant_id", table_name="filament_purchases")
    op.drop_table("filament_purchases")

    _disable_rls("pricing_input_provenance")
    op.drop_index("ix_pricing_input_provenance_source", table_name="pricing_input_provenance")
    op.drop_index("ix_pricing_input_provenance_tenant_id", table_name="pricing_input_provenance")
    op.drop_table("pricing_input_provenance")

    _disable_rls("tenant_pricing_policy")
    op.drop_index("uq_tenant_pricing_policy_current", table_name="tenant_pricing_policy")
    op.drop_index("ix_tenant_pricing_policy_tenant_id", table_name="tenant_pricing_policy")
    op.drop_table("tenant_pricing_policy")
