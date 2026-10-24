"""Record the machine a printed item is planned on.

Revision ID: pricing_model_planned_printer_v1
Revises: pricing_order_actuals_origin_v1

Task T243. FR-011 costs an item at the rate of the machine it is planned on,
but nothing recorded one: the engine used a printer only when a caller passed
`printer_id` to `GET /models/{id}/cost`, so every product cost, margin, solve,
snapshot and the queue ranking used the policy's default rate. NULL keeps that
default, so no existing figure moves.
"""

import sqlalchemy as sa

from alembic import op

revision = "pricing_model_planned_printer_v1"
down_revision = "pricing_order_actuals_origin_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "models",
        sa.Column(
            "planned_printer_id",
            sa.Uuid(),
            sa.ForeignKey("printers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_models_planned_printer_id", "models", ["planned_printer_id"])


def downgrade() -> None:
    op.drop_index("ix_models_planned_printer_id", table_name="models")
    op.drop_column("models", "planned_printer_id")
