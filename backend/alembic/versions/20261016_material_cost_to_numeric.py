"""Make a material type's typical cost per kg exact (task T154).

Revision ID: pricing_material_cost_numeric_v1
Revises: pricing_channel_economics_v1

``material_types.typical_cost_per_kg`` is money on a binary float column. It is
the last one left in ``app/models/`` after T024's sweep, which converted the
money columns that were already ``Numeric`` and passed this one over: it was
declared with no SQL type at all, so SQLAlchemy inferred ``Float`` from the
``float | None`` annotation and nothing in the diff said "money".

## Why it matters, given it is only a default

The figure prefills a spool's ``purchase_price``, and that price is what
``costing.py:cost_per_gram`` divides by the spool's weight to reach the
per-gram cost every material line on every model is priced from. So the
inexactness sat one keystroke upstream of the cost of every print, which is
exactly the position FR-047 and Constitution IV exist to keep floats out of.
``typical_density`` beside it stays a float on purpose: a density is a physical
measurement, not an amount of money.

## Precision

``Numeric(10, 2)``, matching ``spools.purchase_price`` -- the column this one
feeds. A reference cost per kilogram in whole pence is as precise as the figure
can honestly be; the operator is quoting a supplier's list price, not a
measurement.

## The conversion

A straight ``ALTER`` with a cast. PostgreSQL rounds each stored double to two
decimal places on the way in, which is the only thing it can do and is also the
right answer: the seeded values are 20.0, 25.0, 22.0, 35.0, 30.0, 40.0, 28.0
and 45.0, every one of them exact in two places already. A tenant who typed
19.995 gets 20.00, the figure they meant.

Reversible: ``downgrade()`` casts back to double precision. Values that round
tripped through two decimal places do not recover the digits they never had,
and nothing reads the column expecting them to.
"""

import sqlalchemy as sa

from alembic import op

revision = "pricing_material_cost_numeric_v1"
down_revision = "pricing_channel_economics_v1"
branch_labels = None
depends_on = None

TABLE = "material_types"
COLUMN = "typical_cost_per_kg"


def upgrade() -> None:
    # `batch_alter_table` so the migration also runs on SQLite, which cannot
    # alter a column in place and needs the table rebuilt around it.
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            COLUMN,
            existing_type=sa.Float(),
            type_=sa.Numeric(10, 2),
            existing_nullable=True,
            postgresql_using=f"{COLUMN}::numeric(10,2)",
        )


def downgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            COLUMN,
            existing_type=sa.Numeric(10, 2),
            type_=sa.Float(),
            existing_nullable=True,
            postgresql_using=f"{COLUMN}::double precision",
        )
