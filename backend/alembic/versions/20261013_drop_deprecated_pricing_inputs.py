"""Drop the superseded fee columns and the legacy labor-rate key (task T123).

Revision ID: pricing_drop_legacy_v1
Revises: pricing_tier4b_v1

Three figures that two things now claim to own, reduced to one owner each:

* ``sales_channels.fee_percentage`` and ``fee_fixed`` -- one blended percentage
  plus one fixed amount, superseded by the channel's ``fee_rules`` (FR-020).
  The Tier 2 migration converted every pair into equivalent dated rules and
  FR-030 required the converted rules to charge the same amounts, which
  ``tests/integration/test_fee_migration_parity.py`` proves per channel.
* ``tenants.settings['default_labor_rate']`` -- a `float` in a JSON blob,
  superseded by ``tenant_pricing_policy.print_labor_rate``. The Tier 1
  migration seeded one policy row per tenant from exactly this key, so the
  figure already exists in a typed, dated column.

## Why now and not in Tier 2

The pair stayed populated on purpose. While both implementations existed, a
parity check could compare them; drop the originals and the check becomes a
comparison against a transcription, which passes when the transcription and
the migration are wrong in the same direction. They are dropped here, last in
the feature, because only now does no read path remain: the product detail
response was the final caller, and it computes its margin through the fee
engine as of this change.

Leaving them would be worse than redundant. A column that still holds a
plausible-looking number is a column somebody reads: the next person to add a
margin to a screen finds `fee_percentage` sitting on the channel and uses it,
and the figure they ship is wrong by every fee the stack has gained since.

## The downgrade

Reversible in shape, not in content. ``downgrade()`` restores the three places
and backfills what can be derived: a channel's percentage and fixed amount are
recomputed by summing its currently-effective rules on the bases the old pair
could express, and the labor rate is copied back from the current policy row.
A channel whose fees have since grown past one percentage and one fixed amount
cannot be expressed in the restored columns, and the sum it receives is the
closest equivalent rather than the original figure. Nothing in the application
reads either place any more, so the restored values exist for inspection, not
for costing.
"""

import sqlalchemy as sa

from alembic import op

revision = "pricing_drop_legacy_v1"
down_revision = "pricing_tier4b_v1"
branch_labels = None
depends_on = None

LABOR_RATE_KEY = "default_labor_rate"

#: The bases the old blended pair could express. A rule on any other basis --
#: per unit, per listing, periodic -- has no representation in a single
#: percentage-plus-fixed pair, which is the point of FR-020 and the reason the
#: downgrade below is an approximation.
PERCENTAGE_BASES = ("item_subtotal", "item_plus_shipping", "order_total")
FIXED_BASES = ("per_order",)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _settings_is_jsonb() -> bool:
    """Whether `tenants.settings` is `jsonb` or plain `json` in this database.

    The model declares `JSONB` on PostgreSQL, but the migration that created
    the column used `json`, so a deployed database may hold either. It matters:
    `-` and `?` are jsonb operators and simply do not exist for `json`, so a
    statement written for one fails outright against the other -- which is how
    this migration first failed against a real database.
    """
    row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'tenants' AND column_name = 'settings'"
            )
        )
        .scalar()
    )
    return row == "jsonb"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # The blended fee pair
    # ------------------------------------------------------------------
    with op.batch_alter_table("sales_channels") as batch:
        batch.drop_column("fee_percentage")
        batch.drop_column("fee_fixed")

    # Their provenance rows go with them. Left behind, they would be
    # provenance for fields that no longer exist -- and the provenance screen
    # reads the registry, so an operator would be shown the origin of a figure
    # nothing can display (FR-001).
    op.execute(
        "DELETE FROM pricing_input_provenance "
        "WHERE entity_type = 'sales_channel' "
        "AND field_name IN ('fee_percentage', 'fee_fixed')"
    )

    # ------------------------------------------------------------------
    # The legacy labor rate in the settings blob
    # ------------------------------------------------------------------
    if _is_postgres():
        # Cast through jsonb where the column is `json`, and cast the result
        # back so the column keeps the type it had.
        if _settings_is_jsonb():
            expression = f"settings - '{LABOR_RATE_KEY}'"
        else:
            expression = f"(settings::jsonb - '{LABOR_RATE_KEY}')::json"
        op.execute(
            f"UPDATE tenants SET settings = {expression} "
            f"WHERE settings IS NOT NULL "
            f"AND (settings::jsonb) ? '{LABOR_RATE_KEY}'"
        )
    else:
        # SQLite's json_remove, for the test database. `json_valid` guards a
        # settings column holding NULL or something that was never JSON.
        op.execute(
            f"UPDATE tenants SET settings = json_remove(settings, '$.{LABOR_RATE_KEY}') "
            f"WHERE settings IS NOT NULL AND json_valid(settings)"
        )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # The blended fee pair, restored and backfilled from the rules
    # ------------------------------------------------------------------
    op.add_column(
        "sales_channels",
        sa.Column(
            "fee_percentage",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="0",
            comment="DEPRECATED (FR-020): platform percentage fee; see fee_rules",
        ),
    )
    op.add_column(
        "sales_channels",
        sa.Column(
            "fee_fixed",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="0",
            comment="DEPRECATED (FR-020): fixed fee per transaction; see fee_rules",
        ),
    )

    percentage_bases = ", ".join(f"'{basis}'" for basis in PERCENTAGE_BASES)
    fixed_bases = ", ".join(f"'{basis}'" for basis in FIXED_BASES)
    today = "CURRENT_DATE" if _is_postgres() else "DATE('now')"

    op.execute(
        f"""
        UPDATE sales_channels SET fee_percentage = COALESCE((
            SELECT SUM(fee_rules.rate_pct) FROM fee_rules
            WHERE fee_rules.sales_channel_id = sales_channels.id
              AND fee_rules.basis IN ({percentage_bases})
              AND fee_rules.applies_from <= {today}
              AND (fee_rules.applies_to IS NULL OR fee_rules.applies_to >= {today})
        ), 0)
        """
    )
    op.execute(
        f"""
        UPDATE sales_channels SET fee_fixed = COALESCE((
            SELECT SUM(fee_rules.fixed_amount) FROM fee_rules
            WHERE fee_rules.sales_channel_id = sales_channels.id
              AND fee_rules.basis IN ({fixed_bases})
              AND fee_rules.applies_from <= {today}
              AND (fee_rules.applies_to IS NULL OR fee_rules.applies_to >= {today})
        ), 0)
        """
    )

    # ------------------------------------------------------------------
    # The legacy labor rate, copied back from the policy row
    # ------------------------------------------------------------------
    if _is_postgres():
        # As in `upgrade`: `||` and `jsonb_build_object` are jsonb, so the
        # column is cast through jsonb and the result cast back to whatever it
        # actually is.
        merged = (
            f"COALESCE(settings::jsonb, '{{}}'::jsonb) || jsonb_build_object("
            f"'{LABOR_RATE_KEY}', "
            f"(SELECT tenant_pricing_policy.print_labor_rate FROM tenant_pricing_policy"
            f" WHERE tenant_pricing_policy.tenant_id = tenants.id"
            f"   AND tenant_pricing_policy.effective_to IS NULL"
            f" ORDER BY tenant_pricing_policy.effective_from DESC"
            f" LIMIT 1))"
        )
        if not _settings_is_jsonb():
            merged = f"({merged})::json"
        op.execute(
            f"""
            UPDATE tenants SET settings = {merged}
            WHERE EXISTS (
                SELECT 1 FROM tenant_pricing_policy
                WHERE tenant_pricing_policy.tenant_id = tenants.id
                  AND tenant_pricing_policy.effective_to IS NULL
            )
            """
        )
    else:
        op.execute(
            f"""
            UPDATE tenants SET settings = json_set(
                COALESCE(settings, '{{}}'), '$.{LABOR_RATE_KEY}',
                (SELECT tenant_pricing_policy.print_labor_rate FROM tenant_pricing_policy
                 WHERE tenant_pricing_policy.tenant_id = tenants.id
                   AND tenant_pricing_policy.effective_to IS NULL
                 ORDER BY tenant_pricing_policy.effective_from DESC
                 LIMIT 1)
            )
            WHERE EXISTS (
                SELECT 1 FROM tenant_pricing_policy
                WHERE tenant_pricing_policy.tenant_id = tenants.id
                  AND tenant_pricing_policy.effective_to IS NULL
            )
            """
        )
