"""Per-product postage delta for the packed parcel (packaging advisor, T055).

The constitution requires a change to computed values to report the
per-record difference before it is accepted. Phase 2 prices postage from the
packed parcel -- the item plus its box's empty weight, and the box's outer
size against a profile's size class -- where it used the item's weight alone.

For every product and every zone with a profile in force, this prints the
indicative postage for one unit both ways, as CSV:

- ``weight_only``: a parcel of the product's weight with no size, the figure
  postage gave before (a size-limited profile never matches it);
- ``packed``: the parcel ``postage.build_parcel`` assembles from the product's
  accepted packaging, as postage now prices it.

Nothing is written. Run it against a copy of production data before the
Phase 2 release is accepted (T056):

    poetry run python scripts/postage_delta_report.py --out postage-delta.csv
    poetry run python scripts/postage_delta_report.py --tenant mystmereforge

The spec-006 catalogue release has its own before-and-after report, built by
the release step itself so it prices exactly what it would seed (T055):

    poetry run python -m app.cli.seed_catalogues --all-tenants --dry-run --report delta.md
"""

import argparse
import asyncio
import csv
import io
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DEBUG", "false")

COLUMNS = (
    "tenant",
    "sku",
    "zone",
    "weight_only",
    "packed",
    "difference",
    "note",
)


def _amount(value: Optional[Decimal]) -> str:
    return "" if value is None else str(value)


async def collect(db: Any, tenant_slug: Optional[str] = None) -> list[dict[str, Any]]:
    """One row per product per zone: the postage weight-only and packed."""
    from sqlalchemy import select

    from app.core import clock
    from app.models.product import Product
    from app.models.shipping_profile import ShippingProfile
    from app.models.tenant import Tenant
    from app.services.postage import postage_for_grams, postage_for_product

    statement = select(Tenant)
    if tenant_slug:
        statement = statement.where(Tenant.slug == tenant_slug)
    today = clock.today()
    rows: list[dict[str, Any]] = []
    for tenant in (await db.execute(statement)).scalars().all():
        profiles = (
            (
                await db.execute(
                    select(ShippingProfile).where(ShippingProfile.tenant_id == tenant.id)
                )
            )
            .scalars()
            .all()
        )
        zones = sorted({p.destination_zone for p in profiles if p.applies_on(today)})
        products = (
            (
                await db.execute(
                    select(Product).where(Product.tenant_id == tenant.id).order_by(Product.sku)
                )
            )
            .scalars()
            .all()
        )
        for product in products:
            weight = product.weight_grams
            for zone in zones:
                old = await postage_for_grams(
                    db, tenant, Decimal(weight) if weight is not None else None, zone=zone
                )
                new = await postage_for_product(db, tenant, product, zone=zone)
                difference = (
                    new.amount - old.amount
                    if new.amount is not None and old.amount is not None
                    else None
                )
                note = "; ".join([*new.notes, *([new.reason] if new.reason else [])])
                rows.append(
                    {
                        "tenant": tenant.slug,
                        "sku": product.sku,
                        "zone": zone,
                        "weight_only": old.amount,
                        "packed": new.amount,
                        "difference": difference,
                        "note": note,
                    }
                )
    return rows


def render(rows: list[dict[str, Any]]) -> str:
    """The report as CSV, amounts as exact decimal strings."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                **row,
                "weight_only": _amount(row["weight_only"]),
                "packed": _amount(row["packed"]),
                "difference": _amount(row["difference"]),
            }
        )
    return out.getvalue()


async def _main(tenant_slug: Optional[str]) -> str:
    from app.database import async_session_maker

    async with async_session_maker() as db:
        rows = await collect(db, tenant_slug)
        await db.rollback()
    return render(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tenant", help="Only this tenant's slug")
    parser.add_argument("--out", type=Path, help="Write the CSV here instead of stdout")
    args = parser.parse_args()
    report = asyncio.run(_main(args.tenant))
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(report)


if __name__ == "__main__":
    main()
