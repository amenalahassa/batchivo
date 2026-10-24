"""Let an order-level fee actual name the statement it appeared on (task T235).

Revision ID: pricing_fee_actual_statement_v1
Revises: pricing_channel_levers_v1

The spec's edge case: "the order-level actual belongs to the period its
statement assigned it to, not the period it was placed in". An order placed on
the 31st and settled on next month's statement was reconciled against the
wrong statement, because an order-scoped row carried no period and was
selected by the order's placed date.

Two nullable columns, set only on an order-scoped row. Existing rows keep them
null and are read as before -- by the period containing the placed date --
which is the only reading available for a row recorded without one.
"""

import sqlalchemy as sa

from alembic import op

revision = "pricing_fee_actual_statement_v1"
down_revision = "pricing_channel_levers_v1"
branch_labels = None
depends_on = None

TABLE = "fee_actuals"
CHECK = "check_fee_actual_statement_period"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "statement_period_start",
            sa.Date,
            nullable=True,
            comment="Order-scoped rows: first day of the statement period it appeared on",
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "statement_period_end",
            sa.Date,
            nullable=True,
            comment="Order-scoped rows: last day of that statement period",
        ),
    )
    op.create_check_constraint(
        CHECK,
        TABLE,
        "(statement_period_start IS NULL AND statement_period_end IS NULL) OR ("
        " order_id IS NOT NULL"
        " AND statement_period_start IS NOT NULL"
        " AND statement_period_end IS NOT NULL"
        " AND statement_period_end >= statement_period_start)",
    )


def downgrade() -> None:
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.drop_column(TABLE, "statement_period_end")
    op.drop_column(TABLE, "statement_period_start")
