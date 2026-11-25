"""Release step: seed the packaging catalogue and carrier postage for existing shops (spec 006).

Run after ``alembic upgrade heads`` -- by the backend init container on the
cluster, by the VPS update command and by the dev deploy (research D10)::

    python -m app.cli.seed_catalogues --all-tenants
    python -m app.cli.seed_catalogues --tenant mystmereforge
    python -m app.cli.seed_catalogues --all-tenants --dry-run --report delta-postage.md

It is the same seeding the onboarding step and the catalogue routes use
(:mod:`app.services.catalogue_seed`) in its ``release`` mode: a shop already at
the shipped catalogue version, or whose postage was seeded (or found to have no
carrier) before, is left alone, so running it on every deploy is a no-op after
the first. A PostgreSQL advisory lock keeps two replicas from running it at
once. Each tenant is its own transaction; one tenant's failure is logged and
the others go on, and the process still exits 0 so a bad tenant never blocks a
deploy.

``--dry-run`` seeds inside a transaction that is always rolled back and writes
the per-product postage before and after for every zone -- the report the
constitution requires before a change to computed values is accepted (FR-018a).
"""

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("app.cli.seed_catalogues")

#: The advisory lock key: an arbitrary constant, the same for every replica.
LOCK_KEY = 6_006_000_001

SessionFactory = Callable[[], Any]


@dataclass
class TenantOutcome:
    slug: str
    packaging: str = ""
    postage: str = ""
    error: Optional[str] = None


@dataclass
class RunSummary:
    tenants: list[TenantOutcome] = field(default_factory=list)
    locked_out: bool = False
    delta_rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def failures(self) -> int:
        return sum(1 for t in self.tenants if t.error)

    def render(self) -> str:
        if self.locked_out:
            return "another seed_catalogues run holds the lock; nothing done"
        lines = [
            f"{t.slug}: packaging {t.packaging}; postage {t.postage}"
            + (f"; FAILED: {t.error}" if t.error else "")
            for t in self.tenants
        ]
        if not lines:
            return "no tenants"
        if all(
            t.packaging == "nothing to do" and t.postage == "nothing to do" for t in self.tenants
        ):
            lines.append("nothing to do")
        return "\n".join(lines)


def _describe(result: Any) -> str:
    if result.not_due:
        return "nothing to do"
    if result.reason:
        return f"none ({result.reason})"
    text_ = f"{len(result.added)} added, {len(result.skipped)} skipped"
    if getattr(result, "superseded", 0):
        text_ += f", {result.superseded} superseded"
    if result.part == "postage" and result.carrier:
        text_ = f"{result.carrier}: {text_}"
    return text_


async def _postage_by_product(db: AsyncSession, tenant: Any) -> dict[tuple[str, str], Any]:
    """Each product's postage for one unit in every zone with a profile in force."""
    from app.core import clock
    from app.models.product import Product
    from app.services.catalogue_seed import tenant_profiles
    from app.services.postage import postage_for_product

    today = clock.today()
    zones = sorted(
        {p.destination_zone for p in await tenant_profiles(db, tenant) if p.applies_on(today)}
    )
    products = (
        (
            await db.execute(
                select(Product)
                .where(Product.tenant_id == tenant.id, Product.is_active.is_(True))
                .order_by(Product.sku)
            )
        )
        .scalars()
        .all()
    )
    found: dict[tuple[str, str], Any] = {}
    for product in products:
        for zone in zones:
            found[(product.sku, zone)] = await postage_for_product(db, tenant, product, zone=zone)
    return found


def delta_rows(
    slug: str, before: dict[tuple[str, str], Any], after: dict[tuple[str, str], Any]
) -> list[dict[str, Any]]:
    """One row per product and zone whose postage the seeding changes."""
    rows: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        old = before.get(key)
        new = after.get(key)
        old_amount = old.amount if old is not None else None
        new_amount = new.amount if new is not None else None
        if old_amount == new_amount:
            continue
        difference: Optional[Decimal] = (
            new_amount - old_amount if new_amount is not None and old_amount is not None else None
        )
        rows.append(
            {
                "tenant": slug,
                "sku": key[0],
                "zone": key[1],
                "before": old_amount,
                "after": new_amount,
                "difference": difference,
                "note": "; ".join(new.notes) if new is not None and new.notes else "",
            }
        )
    return rows


def render_report(summary: RunSummary, generated_on: date) -> str:
    """The dry-run report as Markdown: what each tenant would get, and the postage delta."""

    def amount(value: Optional[Decimal]) -> str:
        return "unknown" if value is None else str(value)

    out = [
        "# Postage delta from the catalogue release step (dry run)",
        "",
        f"Generated {generated_on.isoformat()} by `python -m app.cli.seed_catalogues "
        "--all-tenants --dry-run`. Nothing was written: every tenant's seeding ran in a "
        "transaction that was rolled back.",
        "",
        "## Per tenant",
        "",
        "| Tenant | Packaging | Postage |",
        "|---|---|---|",
        *(
            f"| {t.slug} | {t.packaging} | {t.postage}{' — FAILED: ' + t.error if t.error else ''} |"
            for t in summary.tenants
        ),
        "",
        "## Postage per product and zone that changes",
        "",
        "One unit, packed as an order of one is. `unknown` means no profile covered the "
        "parcel, so the margin carried no postage line.",
        "",
        "| Tenant | SKU | Zone | Before | After | Difference | Note |",
        "|---|---|---|---|---|---|---|",
        *(
            f"| {r['tenant']} | {r['sku']} | {r['zone']} | {amount(r['before'])} | "
            f"{amount(r['after'])} | {amount(r['difference'])} | {r['note']} |"
            for r in summary.delta_rows
        ),
    ]
    if not summary.delta_rows:
        out.append("| — | — | — | — | — | — | no product's postage changes |")
    return "\n".join(out) + "\n"


async def _seed_tenant(db: AsyncSession, tenant: Any) -> tuple[str, str]:
    from app.services import catalogue_seed

    packaging = await catalogue_seed.seed_packaging(db, tenant, release=True)
    postage = await catalogue_seed.seed_postage(db, tenant, release=True)
    return _describe(packaging), _describe(postage)


async def run(
    session_factory: SessionFactory,
    *,
    tenant_slug: Optional[str] = None,
    dry_run: bool = False,
) -> RunSummary:
    """Seed every active tenant (or one), each in its own transaction, under a lock."""
    from app.core import clock
    from app.core.rls import set_rls_context
    from app.models.tenant import Tenant

    summary = RunSummary()
    # The lock is transaction-scoped and the lock session's transaction stays
    # open for the whole run: a session lock would be taken on one pooled
    # connection and could be "released" on another after a commit.
    async with session_factory() as lock_db:
        got = (await lock_db.execute(select(func.pg_try_advisory_xact_lock(LOCK_KEY)))).scalar_one()
        if not got:
            summary.locked_out = True
            logger.warning("seed_catalogues: another run holds the lock")
            return summary
        try:
            statement = select(Tenant.id, Tenant.slug).where(Tenant.is_active.is_(True))
            if tenant_slug:
                statement = statement.where(Tenant.slug == tenant_slug)
            targets = (await lock_db.execute(statement.order_by(Tenant.slug))).all()
            for tenant_id, slug in targets:
                outcome = TenantOutcome(slug=slug)
                async with session_factory() as db:
                    try:
                        await set_rls_context(db, tenant_id=tenant_id)
                        tenant = await db.get(Tenant, tenant_id)
                        before = await _postage_by_product(db, tenant) if dry_run else {}
                        outcome.packaging, outcome.postage = await _seed_tenant(db, tenant)
                        if dry_run:
                            after = await _postage_by_product(db, tenant)
                            summary.delta_rows.extend(delta_rows(slug, before, after))
                            await db.rollback()
                        else:
                            await db.commit()
                    except Exception as exc:  # noqa: BLE001 -- one tenant never stops the rest
                        await db.rollback()
                        outcome.error = str(exc) or type(exc).__name__
                        logger.error(f"seed_catalogues: tenant {slug} failed: {exc}")
                summary.tenants.append(outcome)
        finally:
            await lock_db.rollback()  # ends the transaction, releasing the lock
    logger.info(
        f"seed_catalogues: {len(summary.tenants)} tenants, {summary.failures} failed"
        f"{' (dry run)' if dry_run else ''} on {clock.today()}"
    )
    return summary


def event_loop_factory() -> Optional[Callable[[], asyncio.AbstractEventLoop]]:
    """The loop to run on: a selector loop on Windows, the default elsewhere.

    psycopg's async mode cannot run on Windows' default ProactorEventLoop, and
    the dev database URL uses psycopg, so the deploy-dev step on Windows would
    fail before seeding anything.
    """
    return asyncio.SelectorEventLoop if sys.platform == "win32" else None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all-tenants", action="store_true", help="Every active tenant")
    scope.add_argument("--tenant", help="Only the tenant with this slug")
    parser.add_argument(
        "--dry-run", action="store_true", help="Roll every tenant back; write nothing"
    )
    parser.add_argument("--report", type=Path, help="With --dry-run: write the delta report here")
    args = parser.parse_args(argv)
    if args.report and not args.dry_run:
        parser.error("--report needs --dry-run")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    os.environ.setdefault("DEBUG", "false")
    from app.core import clock
    from app.database import async_session_maker

    summary = asyncio.run(
        run(async_session_maker, tenant_slug=args.tenant, dry_run=args.dry_run),
        loop_factory=event_loop_factory(),
    )
    print(summary.render())
    if args.report:
        args.report.write_text(render_report(summary, clock.today()), encoding="utf-8")
        print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
