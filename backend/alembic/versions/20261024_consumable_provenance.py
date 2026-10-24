"""Let the packaging consumable's unit cost carry provenance.

Revision ID: pricing_consumable_provenance_v1
Revises: pricing_model_planned_printer_v1

Task T249. A product's packaging line takes its amount from the linked
consumable's `current_cost_per_unit`, but that figure had no origin, so the
line showed the origin of the product's packaging quantity instead. The
provenance table's entity CHECK is recreated to admit `consumable_type`; a
CHECK cannot be extended in place.
"""

from alembic import op

revision = "pricing_consumable_provenance_v1"
down_revision = "pricing_model_planned_printer_v1"
branch_labels = None
depends_on = None

TABLE = "pricing_input_provenance"
CHECK = "check_pricing_input_provenance_entity_type"

BEFORE = (
    "'model', 'model_material', 'model_component', 'model_printer_config', "
    "'product', 'printer', 'spool', 'filament_purchase', "
    "'tenant_pricing_policy', 'sales_channel', "
    "'fee_rule', 'shipping_profile'"
)
AFTER = BEFORE + ", 'consumable_type'"


def _recreate(values: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.create_check_constraint(CHECK, TABLE, f"entity_type IN ({values})")


def upgrade() -> None:
    _recreate(AFTER)


def downgrade() -> None:
    op.execute(f"DELETE FROM {TABLE} WHERE entity_type = 'consumable_type'")
    _recreate(BEFORE)
