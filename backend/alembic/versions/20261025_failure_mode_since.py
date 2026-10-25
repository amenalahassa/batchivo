"""Date an item's failure-mode change, so yield is learned only under the current mode.

Revision ID: pricing_failure_mode_since_v1
Revises: pricing_drop_model_rolling_v1

Task T256. Expected yield is now learned from production history (FR-015d,
SC-010), and the same yield figure means something different under each
failure mode (research D3). Runs carry no record of the mode they were printed
under, so the item records when its mode last changed and the learning sweep
reads only runs completed since. Existing items have never changed mode, so
the column starts empty and every run counts. Nothing computed moves.
"""

import sqlalchemy as sa

from alembic import op

revision = "pricing_failure_mode_since_v1"
down_revision = "pricing_drop_model_rolling_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "models",
        sa.Column(
            "failure_mode_since",
            sa.Date(),
            nullable=True,
            comment="Date the failure mode last changed; yield is learned only from runs since",
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("models") as batch:
        batch.drop_column("failure_mode_since")
