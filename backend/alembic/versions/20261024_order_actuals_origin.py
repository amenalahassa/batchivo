"""Record who entered an order's postage and tax, and how they arrived.

Revision ID: pricing_order_actuals_origin_v1
Revises: pricing_order_tax_unrecorded_v1

Task T241. `postage_paid` and `sales_tax_collected` are the realised margin's
postage and the P&L's tax liability, and anyone could overwrite them with no
trace of who did. They now carry their origin the way a fee actual does
(FR-041e): `entered` by a person, whose id is kept, `ingested` from a feed, or
`derived` by the system from the operator's own tables (the storefront's
shipping profile). Existing rows keep NULL: nothing recorded how their figures
arrived, and inventing an origin would relabel them (FR-001).
"""

import sqlalchemy as sa

from alembic import op

revision = "pricing_order_actuals_origin_v1"
down_revision = "pricing_order_tax_unrecorded_v1"
branch_labels = None
depends_on = None

TABLE = "orders"
CHECK = "ck_orders_actuals_source"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("actuals_source", sa.String(12), nullable=True))
    op.add_column(
        TABLE,
        sa.Column(
            "actuals_recorded_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        TABLE,
        sa.Column("actuals_recorded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        CHECK,
        TABLE,
        "actuals_source IS NULL OR actuals_source IN ('entered', 'ingested', 'derived')",
    )


def downgrade() -> None:
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.drop_column(TABLE, "actuals_recorded_at")
    op.drop_column(TABLE, "actuals_recorded_by_user_id")
    op.drop_column(TABLE, "actuals_source")
