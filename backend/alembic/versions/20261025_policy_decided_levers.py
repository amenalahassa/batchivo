"""Record which pricing-policy levers an operator decided (T260).

A policy write copies the levers it does not name forward, and the row used to
be labelled ``policy`` as a whole once anybody wrote it. Changing only the
margin basis on a seeded row therefore relabelled the carried CA$20.00 labour
rate as a decision -- the relabelling T219 removed, on the copy-forward path.

``decided_levers`` names each lever an operator chose, with the day and role.

Backfill, per tenant, oldest row first:

* a row nobody wrote (``set_by_user_id`` null) decides nothing and carries its
  predecessor's entries;
* a row somebody wrote adds the levers whose value differs from its
  predecessor's, dated to the row. The settings screen re-sent every lever, so
  "sent" is no evidence; "moved" is the evidence there is;
* a written row with no predecessor had nothing to copy, so every lever on it
  was the operator's.

Revision ID: pricing_policy_decided_levers_v1
Revises: pricing_failure_mode_since_v1
"""

import json
from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "pricing_policy_decided_levers_v1"
down_revision = "pricing_failure_mode_since_v1"
branch_labels = None
depends_on = None

LEVERS = (
    "print_labor_rate",
    "finishing_labor_rate",
    "default_machine_rate_per_hour",
    "overhead_method",
    "overhead_monthly_pool",
    "expected_monthly_machine_hours",
    "electricity_rate_per_kwh",
    "overhead_percentage",
    "margin_basis",
    "default_target_margin_pct",
    "rounding_rule",
    "sales_tax_recoverable",
    "staleness_threshold_days",
    "margin_alert_threshold_pct",
    "min_outcomes_before_auto_update",
    "estimate_divergence_threshold_pct",
)


def upgrade() -> None:
    op.add_column(
        "tenant_pricing_policy",
        sa.Column(
            "decided_levers",
            sa.JSON(),
            nullable=False,
            server_default="{}",
            comment="Levers an operator decided: lever -> {as_of, role} (T260)",
        ),
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, tenant_id, effective_from, set_by_user_id, set_by_role, "
            + ", ".join(LEVERS)
            + " FROM tenant_pricing_policy ORDER BY tenant_id, effective_from, created_at"
        )
    ).mappings()

    by_tenant: dict = defaultdict(list)
    for row in rows:
        by_tenant[row["tenant_id"]].append(row)

    for history in by_tenant.values():
        previous = None
        decided: dict = {}
        for row in history:
            decided = dict(decided)
            if row["set_by_user_id"] is not None:
                for lever in LEVERS:
                    if previous is None or row[lever] != previous[lever]:
                        decided[lever] = {
                            "as_of": row["effective_from"].isoformat(),
                            "role": row["set_by_role"],
                        }
            bind.execute(
                sa.text(
                    "UPDATE tenant_pricing_policy SET decided_levers = CAST(:d AS json) WHERE id = :id"
                ),
                {"d": json.dumps(decided), "id": row["id"]},
            )
            previous = row


def downgrade() -> None:
    op.drop_column("tenant_pricing_policy", "decided_levers")
