"""Cost a bill-of-materials line from its spool, keeping a typed figure as an override.

Revision ID: pricing_material_from_spool_v1
Revises: pricing_consumable_provenance_v1

Task T254. `model_materials.cost_per_gram` held whatever the browser sent when
the line was added, and the console always sent purchase price over nominal
weight: no unusable remainder, no allocated inbound shipping, no tax
treatment. The engine read that figure, so the landed cost of FR-008 never
reached a make-cost, and a later change to the spool's price never reached it
either (FR-049).

The column becomes an operator override and is normally empty; the engine
then derives the per-gram figure from the spool on read.

Which existing rows become empty: those equal to purchase price over nominal
weight at four places, which is exactly what the browser prefilled. That
figure was a derivation, not a decision. A row that differs was typed over by
someone, or its spool's price moved after it was added; either way nobody can
now say it was not meant, so it is kept, as an override, and keeps today's
cost (FR-050). The per-product difference is reported before migrating by
``scripts/material_cost_delta_report.py`` (Constitution, Additional
Constraints).
"""

import sqlalchemy as sa

from alembic import op

revision = "pricing_material_from_spool_v1"
down_revision = "pricing_consumable_provenance_v1"
branch_labels = None
depends_on = None

TABLE = "model_materials"

#: The browser's prefill, as SQL, for the row's own spool.
PREFILL = (
    "(SELECT ROUND(spools.purchase_price / spools.initial_weight, 4) FROM spools "
    "WHERE spools.id = model_materials.spool_id "
    "AND spools.purchase_price IS NOT NULL AND spools.initial_weight > 0)"
)


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            "cost_per_gram",
            existing_type=sa.Numeric(10, 4),
            nullable=True,
            comment="Operator override of the per-gram cost; NULL derives it from the spool",
        )

    op.execute(f"UPDATE {TABLE} SET cost_per_gram = NULL WHERE cost_per_gram = {PREFILL}")

    # An origin recorded for a figure that is no longer there would describe
    # nothing; the derived figure takes its origins from the spool.
    op.execute(
        "DELETE FROM pricing_input_provenance "
        "WHERE entity_type = 'model_material' AND field_name = 'cost_per_gram' "
        f"AND entity_id IN (SELECT id FROM {TABLE} WHERE cost_per_gram IS NULL)"
    )


def downgrade() -> None:
    # The old column could not be empty: put back the browser's figure, or zero
    # where the spool cannot give one, as the old route would have stored.
    op.execute(
        f"UPDATE {TABLE} SET cost_per_gram = COALESCE({PREFILL}, 0) WHERE cost_per_gram IS NULL"
    )
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            "cost_per_gram",
            existing_type=sa.Numeric(10, 4),
            nullable=False,
            comment="Cost per gram at time of adding (snapshot for historical accuracy)",
        )
