"""Printer serial number.

Revision ID: printer_serial_v1
Revises: print_sends_v1
Create Date: 2026-11-24

The printer form has always offered a Serial Number field, but the printers
table had no column for it, so the value was silently dropped
(.specify/bugs/printer-serial-dropped).

Adds a nullable `printers.serial_number`. No existing row changes value; the
table's tenant policies already cover the new column. Downgrade drops it.
"""

import sqlalchemy as sa
from alembic import op

revision = "printer_serial_v1"
down_revision = "print_sends_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "printers",
        sa.Column(
            "serial_number",
            sa.String(length=100),
            nullable=True,
            comment="Manufacturer serial number of the machine",
        ),
    )


def downgrade() -> None:
    op.drop_column("printers", "serial_number")
