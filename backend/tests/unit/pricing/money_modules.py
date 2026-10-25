"""Which services are money paths, derived rather than listed by hand (T265).

The mypy override in `pyproject.toml` and the float ban each kept their own
list, and both fell behind: postage on every margin and snapshot, realised
refunds and the cost-input estimates were on neither. A list maintained by
memory is only as current as the last person to remember it.

The rule here is mechanical. A service is a money path when it imports
``Decimal`` and either

* imports one of the pricing authorities (``CLAUDE.md``), or
* imports a model with a money column: a ``Numeric`` column named for a cost,
  price, fee, amount, postage, revenue, refund or total.

A service the rule flags that is deliberately not held to the money standard
is named in :data:`NOT_MONEY_PATHS` with the reason, so leaving one out is a
decision someone wrote down rather than an omission nobody noticed.
"""

import ast
import re
from pathlib import Path

from sqlalchemy import Numeric

import app.models  # noqa: F401 -- registers every mapper
from app.database import Base

SERVICES_DIR = Path(__file__).resolve().parents[3] / "app" / "services"

#: The authorities of the pricing engine, plus the provenance registry every
#: cost input writes through.
AUTHORITIES = frozenset(
    {"costing", "fee_engine", "pricing_solver", "cost_resolution", "landed_cost", "provenance"}
)

MONEY_COLUMN = re.compile(r"(cost|price|fee|amount|postage|revenue|refund|paid|total)", re.I)

#: Services the rule flags that carry a money figure without computing one.
NOT_MONEY_PATHS: dict[str, str] = {
    "etsy_sync": "pushes the Etsy price `temporal_pricing.platform_price` resolves; computes none",
    "shopify_sync": "pushes the Shopify price `temporal_pricing.platform_price` resolves",
    "export_service": (
        "formats CSV rows; the price comes from `temporal_pricing` and the cost "
        "column is left blank (T274)"
    ),
    "platform_admin": "counts tenants' orders and products for the admin console",
    "inventory_transaction": "moves grams between spools; the money is `run_costs`'",
    "print_queue_service": "ranks jobs by the margin the engine serves; computes none",
    "production_run": "the run workflow; its money lives in `run_costs`, which is listed",
}


def _money_models() -> frozenset[str]:
    names = set()
    for mapper in Base.registry.mappers:
        for column in mapper.local_table.columns:
            if isinstance(column.type, Numeric) and MONEY_COLUMN.search(column.name):
                names.add(mapper.class_.__name__)
                break
    return frozenset(names)


def flagged_services() -> dict[str, list[str]]:
    """Every service the rule calls a money path, with what flagged it."""
    models = _money_models()
    flagged: dict[str, list[str]] = {}
    for path in sorted(SERVICES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        if not any(node.module == "decimal" for node in imports):
            continue
        why: set[str] = set()
        for node in imports:
            module = node.module or ""
            if module.startswith("app.services.") and module.rsplit(".", 1)[-1] in AUTHORITIES:
                why.add(module.rsplit(".", 1)[-1])
            if module.startswith("app.models"):
                why.update(alias.name for alias in node.names if alias.name in models)
        if why:
            flagged[path.stem] = sorted(why)
    return flagged


def money_services() -> dict[str, list[str]]:
    """The flagged services that must be held to the money standard."""
    return {name: why for name, why in flagged_services().items() if name not in NOT_MONEY_PATHS}
