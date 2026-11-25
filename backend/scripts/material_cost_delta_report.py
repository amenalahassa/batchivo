"""Per-product delta for migration `pricing_material_from_spool_v1` (task T254).

The constitution requires a migration that changes computed values to report
the per-record difference before it is accepted. That migration empties every
`model_materials.cost_per_gram` equal to the browser's prefill -- purchase
price over nominal weight -- so those lines cost at the spool's landed figure
instead: usable weight, allocated inbound shipping and non-recoverable tax.

Run it against the database **before** migrating. It costs every product
twice in one session, once as stored and once with the lines the migration
would empty set to empty, and rolls back, so nothing is written:

    poetry run python scripts/material_cost_delta_report.py \
        --out ../specs/002-pricing-engine-rebuild/delta-t254.md

Every change is attributed to landed cost by construction: the only input
that differs between the two computations is which per-gram figure the lines
use.
"""

import argparse
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DEBUG"] = "false"

FOUR_PLACES = Decimal("0.0001")


def is_browser_prefill(
    stored: Optional[Decimal],
    purchase_price: Optional[Decimal],
    initial_weight: Optional[Decimal],
) -> bool:
    """Whether a stored per-gram figure is the browser's derivation.

    Mirrors the migration's SQL: purchase price over nominal weight, rounded to
    four places, which is what `BOMEditor` prefilled.
    """
    if stored is None or purchase_price is None or initial_weight is None:
        return False
    if initial_weight <= 0:
        return False
    prefill = (Decimal(str(purchase_price)) / Decimal(str(initial_weight))).quantize(FOUR_PLACES)
    return Decimal(str(stored)) == prefill


async def collect() -> list[dict[str, Any]]:
    """Every product's make-cost as stored and as the migration would leave it."""
    from sqlalchemy import select

    from app.database import async_session_maker
    from app.models.product import Product
    from app.models.tenant import Tenant
    from app.services.cost_resolution import cost_load_options, product_cost_breakdown

    rows: list[dict[str, Any]] = []
    async with async_session_maker() as db:
        with db.no_autoflush:
            for tenant in (await db.execute(select(Tenant))).scalars().all():
                products = (
                    (
                        await db.execute(
                            select(Product)
                            .where(Product.tenant_id == tenant.id)
                            .options(*cost_load_options())
                        )
                    )
                    .scalars()
                    .all()
                )
                for product in products:
                    try:
                        before = await product_cost_breakdown(db, tenant, product)
                    except Exception as exc:  # a cycle is the operator's data, not a crash
                        rows.append({"tenant": tenant.slug, "sku": product.sku, "error": str(exc)})
                        continue
                    cleared = _clear_prefills(product)
                    after = await product_cost_breakdown(db, tenant, product)
                    _restore(cleared)
                    rows.append(
                        {
                            "tenant": tenant.slug,
                            "sku": product.sku,
                            "before": before.total_make_cost,
                            "after": after.total_make_cost,
                            "lines_cleared": len(cleared),
                            "incomplete": after.incomplete_reasons,
                        }
                    )
        await db.rollback()
    return rows


def _clear_prefills(product: Any) -> list[tuple[Any, Decimal]]:
    """Empty, in memory, the lines the migration would empty; return them."""
    cleared: list[tuple[Any, Decimal]] = []
    for product_model in product.product_models or []:
        for material in product_model.model.materials or []:
            spool = material.spool
            if is_browser_prefill(
                material.cost_per_gram, spool.purchase_price, spool.initial_weight
            ):
                cleared.append((material, material.cost_per_gram))
                material.cost_per_gram = None
    for component in product.child_products or []:
        cleared.extend(_clear_prefills(component.child_product))
    return cleared


def _restore(cleared: list[tuple[Any, Decimal]]) -> None:
    for material, value in cleared:
        material.cost_per_gram = value


def render(rows: list[dict[str, Any]]) -> str:
    """The report, as markdown."""
    lines = [
        "# Per-product delta — T254 (material cost from the spool's landed cost)",
        "",
        "**Cause**: `landed_cost` — lines whose stored per-gram figure was the browser's",
        "prefill now cost at the spool's landed figure (usable weight, allocated shipping,",
        "non-recoverable tax). No other input differs between the two columns.",
        "",
        "| Tenant | SKU | Before | After | Delta | Lines re-derived | Attributed to |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        if "error" in row:
            lines.append(
                f"| {row['tenant']} | {row['sku']} | — | — | — | — | not costed: {row['error']} |"
            )
            continue
        delta = row["after"] - row["before"]
        cause = "landed_cost" if delta != 0 else "unchanged"
        if row["incomplete"]:
            cause += " (now reported incomplete)"
        lines.append(
            f"| {row['tenant']} | {row['sku']} | {row['before']} | {row['after']} | {delta} "
            f"| {row['lines_cleared']} | {cause} |"
        )
    if not rows:
        lines.append("| (none) | (no products) | — | — | 0.00 | 0 | nothing to migrate |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", help="write the markdown report here instead of stdout")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    report = render(asyncio.run(collect()))
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
