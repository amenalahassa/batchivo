"""Per-product cost delta report.

The Constitution's Additional Constraints section requires that a change which
alters a computed value report the per-record difference before the change is
accepted. Tiers 0 through 3 of the pricing rebuild all change reported costs on
purpose, so this script is a deliverable of each one, not a diagnostic.

It computes every product's make-cost twice -- once with the costing code at a
given git ref, once with the working tree's -- and emits one row per product
with its before cost, its after cost and the cause the change is attributed to.
A product whose cost moved without a cause that *explains the movement* is
reported as unattributed and the script exits non-zero.

Attribution is verified, not asserted. Each cause knows how to predict the delta
it claims; a cause that does not reproduce the before cost is rejected.

Usage
-----
    poetry run python scripts/cost_delta_report.py \
        --before-ref HEAD \
        --cause labor-rate \
        --out ../specs/002-pricing-engine-rebuild/delta-tier0.md

Causes
------
    labor-rate        the before engine's hardcoded rate is replaced by the
                      tenant's configured rate; verified by re-running the
                      current engine at the old rate and reproducing the before
                      cost exactly.
    new-line:<key>    a newly introduced breakdown line (machine, waste, yield,
                      overhead, landed_cost, ...) accounts for the delta;
                      verified by comparing the delta against that line.

``--emit-costs`` is the internal mode the script runs in when invoked inside the
before-ref worktree. It prints JSON on stdout and nothing else.
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_BACKEND = Path(__file__).resolve().parents[1]

# A report tool should emit a report, not a SQL log. `app.database` sets
# `echo=settings.debug` at import time, so this has to be in place first.
os.environ.setdefault("DEBUG", "false")
os.environ["DEBUG"] = "false"


def _run(coroutine: Any) -> Any:
    """Run a coroutine on an event loop psycopg can use.

    On Windows, Python defaults to the Proactor loop, which psycopg's async
    driver refuses. Selecting the Selector loop here keeps the script usable on
    a developer's Windows machine as well as in CI.
    """
    if sys.platform == "win32":
        import asyncio as _asyncio

        _asyncio.set_event_loop_policy(_asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(coroutine)


# --------------------------------------------------------------------------
# Cost collection (runs against whichever `app` package is importable)
# --------------------------------------------------------------------------


async def _collect_costs() -> list[dict[str, Any]]:
    """Compute every product's make-cost with the importable costing engine."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.database import async_session_maker
    from app.models.product import Product
    from app.models.tenant import Tenant
    from app.services import costing as costing_module
    from app.services.costing import CostingService

    # The tenant-rate resolver is introduced by this feature's Tier 0. A ref
    # from before that lands has no such module, and its engine default is the
    # very figure whose removal this report documents.
    try:
        from app.services.tenant_cost_settings import (
            tenant_labor_rate,
            tenant_overhead_percentage,
        )
    except ImportError:  # pragma: no cover - only on a pre-Tier-0 ref
        tenant_labor_rate = None  # type: ignore[assignment]
        tenant_overhead_percentage = None  # type: ignore[assignment]

    engine_default_rate = str(getattr(costing_module, "DEFAULT_LABOR_RATE", "") or "")

    rows: list[dict[str, Any]] = []

    async with async_session_maker() as db:
        tenants = (await db.execute(select(Tenant))).scalars().all()

        for tenant in tenants:
            products = (
                (
                    await db.execute(
                        select(Product)
                        .where(Product.tenant_id == tenant.id)
                        .options(
                            selectinload(Product.product_models),
                            selectinload(Product.child_products),
                            selectinload(Product.packaging_consumable),
                        )
                    )
                )
                .scalars()
                .all()
            )

            rate = None
            overhead = None
            if tenant_labor_rate is not None:
                rate = tenant_labor_rate(tenant)
                overhead = tenant_overhead_percentage(tenant)

            for product in products:
                kwargs: dict[str, Any] = {}
                if rate is not None:
                    kwargs["labor_rate"] = rate

                try:
                    breakdown = CostingService.calculate_product_cost(product, **kwargs)
                except Exception as exc:  # a cycle or depth limit is data, not a crash
                    rows.append(
                        {
                            "tenant": tenant.slug,
                            "product_id": str(product.id),
                            "sku": product.sku,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    continue

                rows.append(
                    {
                        "tenant": tenant.slug,
                        "product_id": str(product.id),
                        "sku": product.sku,
                        "total_make_cost": str(breakdown.total_make_cost),
                        "lines": {
                            key: str(value)
                            for key, value in breakdown.model_dump().items()
                            if isinstance(value, Decimal)
                        },
                        "labor_rate_used": str(rate) if rate is not None else engine_default_rate,
                        "overhead_pct_used": str(overhead) if overhead is not None else "",
                        "engine_default_labor_rate": engine_default_rate,
                    }
                )

    return rows


def _settings_for_subprocess() -> dict[str, str]:
    """The settings the before-ref tree needs, resolved from this tree's `.env`.

    Only what `app.config.Settings` requires to open a database connection: the
    database URL, so both trees read the same rows, and the secret key, because
    `Settings` refuses to construct without one.
    """
    from app.config import get_settings

    settings = get_settings()
    return {
        "DATABASE_URL": settings.database_url,
        "SECRET_KEY": settings.secret_key,
        "RLS_ENABLED": str(settings.rls_enabled),
    }


def _costs_at_before_ref(ref: str) -> list[dict[str, Any]]:
    """Run this script inside a checkout of `ref` and read back its costs."""
    repo_root = REPO_BACKEND.parent
    workdir = Path(tempfile.mkdtemp(prefix="cost-delta-"))
    try:
        archive = workdir / "before.tar"
        with archive.open("wb") as handle:
            subprocess.run(
                ["git", "archive", ref, "--", "backend/app", "backend/pyproject.toml"],
                cwd=repo_root,
                stdout=handle,
                check=True,
            )

        extracted = workdir / "tree"
        extracted.mkdir()
        subprocess.run(["tar", "-xf", str(archive), "-C", str(extracted)], check=True)

        before_backend = extracted / "backend"
        scripts_dir = before_backend / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        (scripts_dir / "__init__.py").write_text("", encoding="utf-8")
        shutil.copy2(Path(__file__).resolve(), scripts_dir / "cost_delta_report.py")

        env = dict(os.environ)
        env["PYTHONPATH"] = str(before_backend)
        # The before-ref tree is a temp directory, so it has no `.env` to read.
        # Both trees must compute against the *same* database for the comparison
        # to mean anything, so the parent's resolved settings are handed over
        # explicitly rather than left to be rediscovered.
        env.update(_settings_for_subprocess())

        result = subprocess.run(
            [sys.executable, str(scripts_dir / "cost_delta_report.py"), "--emit-costs"],
            cwd=str(before_backend),
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SystemExit(
                f"could not compute costs at {ref}:\n{result.stderr.strip() or result.stdout}"
            )
        return json.loads(result.stdout)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# --------------------------------------------------------------------------
# Attribution
# --------------------------------------------------------------------------


class Unattributed(Exception):
    """No declared cause explains a product's cost movement."""


#: Filled before rendering: (product_id, rate) -> make-cost replayed at that rate.
_REPLAY: dict[tuple[str, str], str] = {}


def _explain_labor_rate(before: dict[str, Any], after: dict[str, Any]) -> str | None:
    """Verify the delta is exactly the labor-rate correction.

    Re-runs the *current* engine at the before engine's hardcoded rate. If that
    reproduces the before cost to the cent, the rate is the whole story and
    nothing else in the change moved this product's cost.
    """
    old_rate = before.get("engine_default_labor_rate") or ""
    new_rate = after.get("labor_rate_used") or ""
    if not old_rate or old_rate == new_rate:
        return None

    replayed = _REPLAY.get((after["product_id"], old_rate))
    if replayed is None:
        return None
    if Decimal(replayed) == Decimal(before["total_make_cost"]):
        return f"labor rate {old_rate} -> {new_rate}"
    return None


def _explain_new_line(key: str, before: dict[str, Any], after: dict[str, Any]) -> str | None:
    """Verify the delta is accounted for by a newly appearing breakdown line."""
    after_lines = after.get("lines", {})
    before_lines = before.get("lines", {})
    if key not in after_lines:
        return None
    amount = Decimal(after_lines[key]) - Decimal(before_lines.get(key, "0"))
    delta = Decimal(after["total_make_cost"]) - Decimal(before["total_make_cost"])
    if amount == delta:
        return f"new line '{key}' of {amount}"
    return None


def attribute(before: dict[str, Any], after: dict[str, Any], causes: list[str]) -> str:
    """Return the verified explanation for one product's delta."""
    for cause in causes:
        if cause == "labor-rate":
            found = _explain_labor_rate(before, after)
        elif cause.startswith("new-line:"):
            found = _explain_new_line(cause.split(":", 1)[1], before, after)
        else:
            raise SystemExit(f"unknown cause '{cause}'. Known causes: labor-rate, new-line:<key>")
        if found:
            return f"{cause} ({found})"
    raise Unattributed(after["sku"])


async def _replay_at_rates(pairs: set[tuple[str, str]]) -> None:
    """Recompute specific products at specific labor rates, for verification."""
    if not pairs:
        return

    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.database import async_session_maker
    from app.models.product import Product
    from app.services.costing import CostingService

    wanted = {UUID(product_id) for product_id, _ in pairs}
    async with async_session_maker() as db:
        loaded = (
            (
                await db.execute(
                    select(Product)
                    .where(Product.id.in_(wanted))
                    .options(
                        selectinload(Product.product_models),
                        selectinload(Product.child_products),
                        selectinload(Product.packaging_consumable),
                    )
                )
            )
            .scalars()
            .all()
        )
        products = {product.id: product for product in loaded}

        for product_id, rate in pairs:
            product = products.get(UUID(product_id))
            if product is None:
                continue
            try:
                breakdown = CostingService.calculate_product_cost(product, labor_rate=Decimal(rate))
            except Exception:
                continue
            _REPLAY[(product_id, rate)] = str(breakdown.total_make_cost)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def render(
    before_rows: list[dict[str, Any]],
    after_rows: list[dict[str, Any]],
    causes: list[str],
    before_ref: str,
) -> tuple[str, list[str]]:
    """Render the markdown report; return it with the unattributed SKUs."""
    before_by_id = {row["product_id"]: row for row in before_rows}
    unattributed: list[str] = []
    changed = 0

    lines = [
        "# Per-product cost delta",
        "",
        f"**Before**: `{before_ref}` | **After**: working tree | "
        f"**Declared causes**: {', '.join(causes)}",
        "",
        "Every row whose cost moved carries a cause that was *verified* to predict",
        "the movement, not merely declared alongside it. A product missing from the",
        "before ref is reported as new rather than as a delta.",
        "",
        "| Tenant | SKU | Before | After | Delta | Attributed to |",
        "|---|---|---:|---:|---:|---|",
    ]

    for after in sorted(after_rows, key=lambda row: (row["tenant"], row["sku"])):
        before = before_by_id.get(after["product_id"])

        if "error" in after:
            lines.append(
                f"| {after['tenant']} | {after['sku']} | - | - | - | "
                f"not costable: {after['error']} |"
            )
            continue
        if before is None:
            lines.append(
                f"| {after['tenant']} | {after['sku']} | - | "
                f"{after['total_make_cost']} | - | new product, no before figure |"
            )
            continue
        if "error" in before:
            lines.append(
                f"| {after['tenant']} | {after['sku']} | not costable | "
                f"{after['total_make_cost']} | - | newly costable |"
            )
            continue

        before_cost = Decimal(before["total_make_cost"])
        after_cost = Decimal(after["total_make_cost"])
        delta = after_cost - before_cost

        if delta == 0:
            lines.append(
                f"| {after['tenant']} | {after['sku']} | {before_cost} | "
                f"{after_cost} | 0.00 | unchanged |"
            )
            continue

        changed += 1
        try:
            why = attribute(before, after, causes)
        except Unattributed:
            unattributed.append(f"{after['tenant']}/{after['sku']}")
            why = "**UNATTRIBUTED**"
        lines.append(
            f"| {after['tenant']} | {after['sku']} | {before_cost} | "
            f"{after_cost} | {delta:+} | {why} |"
        )

    # "0 changed" is ambiguous between "the change was safe" and "there was
    # nothing here to measure". A reader accepting this report needs to be able
    # to tell those apart, so the sensitive population is stated outright.
    costed = sum(
        1 for row in after_rows if "error" not in row and Decimal(row["total_make_cost"]) > 0
    )
    labor_bearing = sum(
        1
        for row in after_rows
        if "error" not in row
        and any(
            Decimal(amount) > 0
            for key, amount in row.get("lines", {}).items()
            if key in {"assembly_cost", "models_cost", "child_products_cost"}
        )
    )

    lines += [
        "",
        f"**{len(after_rows)} products, {changed} changed, {len(unattributed)} unattributed.**",
        "",
        f"Of those, {costed} report a non-zero cost and {labor_bearing} carry a "
        f"labor-bearing line (assembly, models or child products). A product with "
        f"neither cannot move when the labor rate does, so it is not evidence "
        f"either way.",
        "",
    ]
    if labor_bearing == 0:
        lines += [
            "> **This report is weak evidence.** No product in this database has an",
            "> input the labor rate reaches, so nothing could have moved. It confirms",
            "> the change broke no costing path; it does not show what the change does",
            "> to real figures. Re-run it against a database with representative",
            "> products before accepting the change on their behalf.",
            "",
        ]
    if unattributed:
        lines += [
            "## Unattributed changes",
            "",
            "These costs moved and no declared cause predicts the movement. The",
            "change is not acceptable until each is explained or a cause is added.",
            "",
            *(f"- {sku}" for sku in unattributed),
            "",
        ]
    else:
        lines.append("No cost moved without a verified cause.")

    return "\n".join(lines) + "\n", unattributed


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-product cost delta report.")
    parser.add_argument("--before-ref", help="git ref holding the costing code to compare against")
    parser.add_argument(
        "--cause",
        action="append",
        default=[],
        help="a cause the changes are attributed to; repeatable",
    )
    parser.add_argument("--out", help="write the markdown report here instead of stdout")
    parser.add_argument(
        "--emit-costs",
        action="store_true",
        help="internal: print this tree's per-product costs as JSON and exit",
    )
    args = parser.parse_args()

    if args.emit_costs:
        print(json.dumps(_run(_collect_costs())))
        return 0

    if not args.before_ref:
        parser.error("--before-ref is required")
    if not args.cause:
        parser.error("--cause is required; an unexplained cost change is not acceptable")

    before_rows = _costs_at_before_ref(args.before_ref)
    after_rows = _run(_collect_costs())

    if "labor-rate" in args.cause:
        _run(
            _replay_at_rates(
                {
                    (row["product_id"], row["engine_default_labor_rate"])
                    for row in before_rows
                    if row.get("engine_default_labor_rate") and "error" not in row
                }
            )
        )

    report, unattributed = render(before_rows, after_rows, args.cause, args.before_ref)

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(report)

    if unattributed:
        print(
            f"FAILED: {len(unattributed)} product(s) changed cost with no verified cause.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
