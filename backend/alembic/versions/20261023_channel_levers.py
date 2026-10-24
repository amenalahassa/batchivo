"""Effective-date the rest of a channel's levers (task T216).

Revision ID: pricing_channel_levers_v1
Revises: pricing_refund_actuals_v1

Task T136 moved four planning figures into ``sales_channel_economics``. Four
more stayed behind as plain columns on ``sales_channels`` -- ``monthly_cost``,
``tax_remitter``, ``offsite_ads_opt_in`` and ``currency_code`` -- although the
spec's Channel economics entity lists them as the same kind of figure. While
they stayed there any role could flip who remits the tax, and a subscription
change silently restated every past period's channel P&L (FR-003, FR-007a).

## Every existing period is seeded with the channel's current values

The columns had no history, so the current value is the only one known. It is
written onto every period a channel already has, open or closed: a closed
period predating this migration was planned against whatever the column held
then, which is unrecoverable, and today's value is the honest best answer.

## The columns stay, as T136's did

``app/services/channel_economics.channel_defaults`` reads them for a channel
with no period at all -- a unit test's stand-in. No live channel is in that
state, and nothing writes them any more.

## The downgrade copies the open period back

As T136's downgrade does: no figure moves, and the history of these four is
lost.
"""

import sqlalchemy as sa

from alembic import op

revision = "pricing_channel_levers_v1"
down_revision = "pricing_refund_actuals_v1"
branch_labels = None
depends_on = None

TABLE = "sales_channel_economics"

#: The levers that move, named once for the backfill and the copy-back.
LEVERS = ("monthly_cost", "tax_remitter", "offsite_ads_opt_in", "currency_code")


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "monthly_cost",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="0",
            comment="Monthly subscription or booth fee, absorbed over order volume (FR-025)",
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "tax_remitter",
            sa.String(12),
            nullable=False,
            server_default="operator",
            comment="Who remits sales tax on this channel's sales (FR-028b)",
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "offsite_ads_opt_in",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
            comment="Whether the operator opted into marketplace offsite advertising (FR-002)",
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "currency_code",
            sa.String(3),
            nullable=False,
            server_default="GBP",
            comment="Currency the channel sells in (FR-028)",
        ),
    )

    assignments = ",\n            ".join(
        f"{lever} = (SELECT c.{lever} FROM sales_channels c WHERE c.id = {TABLE}.sales_channel_id)"
        for lever in LEVERS
    )
    op.execute(f"UPDATE {TABLE} SET {assignments}")

    op.create_check_constraint(
        "ck_channel_economics_monthly_cost_is_not_negative", TABLE, "monthly_cost >= 0"
    )
    op.create_check_constraint(
        "ck_channel_economics_tax_remitter",
        TABLE,
        "tax_remitter IN ('marketplace', 'operator')",
    )


def downgrade() -> None:
    assignments = ",\n            ".join(
        f"{lever} = (SELECT e.{lever} FROM {TABLE} e "
        f"WHERE e.sales_channel_id = sales_channels.id AND e.effective_to IS NULL LIMIT 1)"
        for lever in LEVERS
    )
    op.execute(
        f"""
        UPDATE sales_channels
        SET {assignments}
        WHERE EXISTS (
            SELECT 1 FROM {TABLE} e
            WHERE e.sales_channel_id = sales_channels.id AND e.effective_to IS NULL
        )
        """
    )
    op.drop_constraint("ck_channel_economics_tax_remitter", TABLE, type_="check")
    op.drop_constraint("ck_channel_economics_monthly_cost_is_not_negative", TABLE, type_="check")
    for lever in reversed(LEVERS):
        op.drop_column(TABLE, lever)
