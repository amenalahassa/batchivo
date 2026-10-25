"""Retire the rolling-average actual cost stored on a model.

Revision ID: pricing_drop_model_rolling_cost_v1
Revises: pricing_material_from_spool_v1

Task T255. `models.actual_production_cost` folded each completed run into a
running average, rounded to four places every time and fed back as the next
step's input: rounding between intermediate steps (Constitution IV) of a
figure derivable from the immutable per-run unit costs (Constitution V). It is
now derived on read from completed runs, so the three columns go.

Nothing computed moves: the planned make-cost never read these columns, and
the actual cost they reported is rebuilt from the same runs, without the
compounding rounding.

The downgrade restores the columns empty. They were a cache of the runs, and
the next completed run would have started refilling them under the old code;
recomputing the old rounded chain here would rebuild the very error this
removes.
"""

import sqlalchemy as sa

from alembic import op

revision = "pricing_drop_model_rolling_cost_v1"
down_revision = "pricing_material_from_spool_v1"
branch_labels = None
depends_on = None

TABLE = "models"


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("production_cost_updated_at")
        batch.drop_column("production_cost_count")
        batch.drop_column("actual_production_cost")


def downgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column(
                "actual_production_cost",
                sa.Numeric(10, 4),
                nullable=True,
                comment="Rolling average actual production cost per unit from completed runs",
            )
        )
        batch.add_column(
            sa.Column(
                "production_cost_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
                comment="Number of completed production runs included in rolling average",
            )
        )
        batch.add_column(
            sa.Column(
                "production_cost_updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="Last time actual_production_cost was updated",
            )
        )
