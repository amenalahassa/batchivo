"""A proposal records how far to believe its observation (T259).

The observed figure's confidence is set from the count and spread of the
outcomes behind it. A held proposal freezes that figure with its evidence, so
accepting it records the confidence the operator was shown.

Revision ID: pricing_estimate_confidence_v1
Revises: pricing_policy_decided_levers_v1
"""

import sqlalchemy as sa
from alembic import op

revision = "pricing_estimate_confidence_v1"
down_revision = "pricing_policy_decided_levers_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "estimate_revisions",
        sa.Column(
            "confidence",
            sa.Numeric(5, 4),
            nullable=True,
            comment=(
                "How far to believe the observed value, in (0, 1], from the count "
                "and spread of the outcomes behind it (T259)"
            ),
        ),
    )
    op.create_check_constraint(
        "ck_estimate_revision_confidence",
        "estimate_revisions",
        "confidence IS NULL OR (confidence > 0 AND confidence <= 1)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_estimate_revision_confidence", "estimate_revisions", type_="check")
    op.drop_column("estimate_revisions", "confidence")
