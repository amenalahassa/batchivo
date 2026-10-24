"""Let an order say its postage or tax is unrecorded, and that its figures were derived.

Revision ID: pricing_order_tax_unrecorded_v1
Revises: pricing_order_item_fx_v1

Task T230. `postage_paid` and `sales_tax_collected` were NOT NULL with a zero
default, so every order from a source that did not report them -- the
storefront's Square path, the Shopify webhook, the commerce bridge -- read as
free to post and tax-free. They become nullable: NULL is unrecorded. Existing
rows keep the figure they hold; nothing recorded whether their zero was a
measurement, and inventing that it was not would restate them (FR-038).

`tax_exclusive_derived` marks an order whose source quoted prices with tax in,
so its stored figures were derived by taking the tax out (FR-028e).
"""

import sqlalchemy as sa

from alembic import op

revision = "pricing_order_tax_unrecorded_v1"
down_revision = "pricing_order_item_fx_v1"
branch_labels = None
depends_on = None

TABLE = "orders"


def upgrade() -> None:
    for column in ("postage_paid", "sales_tax_collected"):
        op.alter_column(
            TABLE,
            column,
            existing_type=sa.Numeric(10, 2),
            nullable=True,
            server_default=None,
        )
    op.add_column(
        TABLE,
        sa.Column(
            "tax_exclusive_derived",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column(TABLE, "tax_exclusive_derived")
    for column in ("postage_paid", "sales_tax_collected"):
        op.execute(f"UPDATE {TABLE} SET {column} = 0 WHERE {column} IS NULL")
        op.alter_column(
            TABLE,
            column,
            existing_type=sa.Numeric(10, 2),
            nullable=False,
            server_default="0",
        )
