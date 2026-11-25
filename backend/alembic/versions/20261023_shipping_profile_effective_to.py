"""Let a repriced shipping profile close rather than be rewritten (task T233).

Revision ID: pricing_shipping_effective_to_v1
Revises: pricing_fee_actual_statement_v1

``update_shipping_profile`` rewrote a postage price in place, so every plan
and margin computed under the old price silently moved to the new one -- the
in-place update CLAUDE.md and FR-003 forbid. A profile now carries the last day
it applied; a repricing closes it and opens a successor. Existing profiles are
left open, which is what they were.
"""

import sqlalchemy as sa

from alembic import op

revision = "pricing_shipping_effective_to_v1"
down_revision = "pricing_fee_actual_statement_v1"
branch_labels = None
depends_on = None

TABLE = "shipping_profiles"
CHECK = "check_shipping_profile_effective_range"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "effective_to",
            sa.Date,
            nullable=True,
            comment="Last day this postage applied; NULL while it still does (FR-003)",
        ),
    )
    op.create_check_constraint(
        CHECK, TABLE, "effective_to IS NULL OR effective_to >= effective_from"
    )


def downgrade() -> None:
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.drop_column(TABLE, "effective_to")
