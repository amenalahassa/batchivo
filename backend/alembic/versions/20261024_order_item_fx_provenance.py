"""Keep the exchange rate's date and origin, and the snapshot's warnings, on the line.

Revision ID: pricing_order_item_fx_v1
Revises: pricing_policy_overhead_seed_v1

Task T232. An order line stored its frozen rate alone: the day the rate applied
to and whether it was fetched or entered by hand were lost at the moment of
sale, though FR-028g requires the figure to show its date and FR-028h its
origin. The snapshot's own warnings were only logged. Existing lines are left
as they are -- nothing recorded what their rate's date or origin was, and
inventing one would be the restatement FR-038 forbids.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "pricing_order_item_fx_v1"
down_revision = "pricing_policy_overhead_seed_v1"
branch_labels = None
depends_on = None

TABLE = "order_items"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("fx_rate_date", sa.Date, nullable=True))
    op.add_column(TABLE, sa.Column("fx_rate_source", sa.String(20), nullable=True))
    op.add_column(TABLE, sa.Column("fx_quote_currency", sa.String(3), nullable=True))
    op.add_column(
        TABLE,
        sa.Column(
            "snapshot_incomplete",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    for column in ("snapshot_incomplete", "fx_quote_currency", "fx_rate_source", "fx_rate_date"):
        op.drop_column(TABLE, column)
