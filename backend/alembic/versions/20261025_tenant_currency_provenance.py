"""Let the books currency carry provenance.

Revision ID: pricing_tenant_currency_prov_v1
Revises: create_product_variants_v1

Task T272. `PUT /settings/tenant` sets `Tenant.currency_code`, the currency
every cost input is entered in and every sale is converted to -- a monetary
policy decision with no recorded origin. The provenance table's entity CHECK is
recreated to admit `tenant`; a CHECK cannot be extended in place.
"""

from alembic import op

revision = "pricing_tenant_currency_prov_v1"
down_revision = "create_product_variants_v1"
branch_labels = None
depends_on = None

TABLE = "pricing_input_provenance"
CHECK = "check_pricing_input_provenance_entity_type"

BEFORE = (
    "'model', 'model_material', 'model_component', 'model_printer_config', "
    "'product', 'printer', 'spool', 'filament_purchase', "
    "'tenant_pricing_policy', 'sales_channel', "
    "'fee_rule', 'shipping_profile', 'consumable_type'"
)
AFTER = BEFORE + ", 'tenant'"


def _recreate(values: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.create_check_constraint(CHECK, TABLE, f"entity_type IN ({values})")


def upgrade() -> None:
    _recreate(AFTER)


def downgrade() -> None:
    op.execute(f"DELETE FROM {TABLE} WHERE entity_type = 'tenant'")
    _recreate(BEFORE)
