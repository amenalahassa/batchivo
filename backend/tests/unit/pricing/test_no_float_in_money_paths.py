"""Ban binary floating point from the money paths (research.md D8).

Constitution principle IV requires exact decimal arithmetic end to end in
costing and pricing code. ruff has no rule for "this module may not use this
builtin type", so the ban is enforced here: each module is parsed with `ast`
and any `float` annotation or `float(...)` call fails with a file and line.

This is a guardrail, not a bug report. It is expected to pass on the day it is
written and to fail the moment someone reintroduces the defect that shipped
once already in `Product.calculate_make_cost`.
"""

import ast
import re
from pathlib import Path

import pytest

# The five money modules named in research.md D8. Modules belonging to a later
# tier do not exist yet; those are skipped by name so the gap is visible in the
# test report rather than silently passing.
#: Every module that handles money or a rate.
#:
#: The first five are Tier 0's list (research D8). The rest arrived with later
#: tiers and were never added, which left `cost_resolution.py` -- one of the
#: four authorities `CLAUDE.md` names -- free to grow a `float` without any
#: test objecting. There were none to find; the point of the ban is that a
#: future one fails here rather than in a margin six months later (task T137).
#:
#: `variance_service.py` is deliberately absent. It assigns an estimate back
#: onto a model field and must coerce to `float` where the column still is one;
#: that single documented conversion is a pre-existing wart it accommodates
#: rather than introduces, so the ban would fail on the one line written to
#: contain the problem. Its arithmetic is `Decimal` throughout, which
#: `test_variance.py` asserts directly.
MONEY_MODULES = [
    "costing.py",
    "landed_cost.py",
    "fee_engine.py",
    "pricing_solver.py",
    "channel_pnl.py",
    "cost_resolution.py",
    "provenance.py",
    "pricing_policy.py",
    "scenario_service.py",
    "fx_service.py",
    "temporal_pricing.py",
    "realised_margin.py",
    "tenant_cost_settings.py",
    # A reserve and a rounding threshold are money figures too (task T136).
    "channel_economics.py",
    # The realised-versus-planned comparison (task T134).
    "margin_alert.py",
]

#: Money modules outside `app/services/`, scanned by the same total ban.
#:
#: `email_service.py` typed `subtotal`, `shipping_cost`, `total` and
#: `refund_amount` as `float`, and the signature was the cause rather than the
#: symptom: every caller held an exact `Decimal` read from a `Numeric` column
#: and converted it away to satisfy the parameter list. These are the figures a
#: customer is told they were charged and that the operator reconciles a
#: statement against (task T190, FR-047).
OTHER_MONEY_MODULES: dict[str, str] = {
    "email_service.py": "app/services",
}

SERVICES_DIR = Path(__file__).resolve().parents[3] / "app" / "services"
APP_DIR = Path(__file__).resolve().parents[3] / "app"


def _module_paths() -> list[Path]:
    return [SERVICES_DIR / name for name in MONEY_MODULES] + [
        APP_DIR.parent / where / name for name, where in OTHER_MONEY_MODULES.items()
    ]


def _module_ids() -> list[str]:
    return MONEY_MODULES + list(OTHER_MONEY_MODULES)


class FloatVisitor(ast.NodeVisitor):
    """Collect every syntactic use of `float` in a module."""

    def __init__(self) -> None:
        self.violations: list[tuple[int, str]] = []

    def _flag(self, node: ast.AST, what: str) -> None:
        self.violations.append((getattr(node, "lineno", 0), what))

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "float":
            self._flag(node, "float(...) call")
        self.generic_visit(node)

    def _check_annotation(self, annotation: ast.expr | None) -> None:
        if annotation is None:
            return
        for sub in ast.walk(annotation):
            if isinstance(sub, ast.Name) and sub.id == "float":
                self._flag(sub, "float annotation")
            # String annotations such as "Optional[float]" hide from ast.walk.
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                try:
                    inner = ast.parse(sub.value, mode="eval")
                except SyntaxError:
                    continue
                for deep in ast.walk(inner):
                    if isinstance(deep, ast.Name) and deep.id == "float":
                        self._flag(sub, "float annotation (in string form)")

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = node.args
        for arg in [
            *args.posonlyargs,
            *args.args,
            *args.kwonlyargs,
            *([args.vararg] if args.vararg else []),
            *([args.kwarg] if args.kwarg else []),
        ]:
            self._check_annotation(arg.annotation)
        self._check_annotation(node.returns)
        self.generic_visit(node)

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_annotation(node.annotation)
        self.generic_visit(node)


@pytest.mark.parametrize("path", _module_paths(), ids=_module_ids())
def test_module_uses_no_float(path: Path) -> None:
    """No money module may annotate or construct a `float`."""
    # This used to skip for a module "a later tier has not written yet". Every
    # module on the list now exists, so a missing one means it was renamed or
    # deleted and the ban quietly stopped covering it -- which is a failure,
    # not a skip.
    assert path.exists(), (
        f"{path.name} is on the float-ban list but is not there. Rename it in "
        f"MONEY_MODULES, or drop it if the money really left it."
    )

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = FloatVisitor()
    visitor.visit(tree)

    if visitor.violations:
        listed = "\n".join(
            f"  {path}:{lineno}: {what}" for lineno, what in sorted(visitor.violations)
        )
        pytest.fail(
            f"binary floating point is not permitted in {path.name} "
            f"(Constitution IV, research.md D8):\n{listed}"
        )


def test_the_ban_covers_the_module_that_already_shipped_the_defect() -> None:
    """`costing.py` is the authoritative engine and must always be scanned."""
    assert (SERVICES_DIR / "costing.py").exists(), (
        "costing.py is the single authoritative cost implementation; "
        "if it moved, this ban moved with it or it is no longer enforced"
    )


def test_the_visitor_actually_detects_a_violation() -> None:
    """A ban nobody has seen fail is a ban nobody can trust."""
    sample = (
        "def rate(x: float) -> float:\n"
        "    y: float = 0.0\n"
        "    return float(x) + y\n"
        "def later(z: 'Optional[float]') -> None:\n"
        "    pass\n"
    )
    visitor = FloatVisitor()
    visitor.visit(ast.parse(sample))
    kinds = [what for _, what in visitor.violations]
    assert kinds.count("float(...) call") == 1
    assert kinds.count("float annotation") == 3  # x, the return type, and y
    assert kinds.count("float annotation (in string form)") == 1


# ---------------------------------------------------------------------------
# The model and schema layers (tasks T141, T144)
# ---------------------------------------------------------------------------
#
# The ban above covers `app/services/`, which is where the engine lives. It is
# not where money enters or leaves: a `Mapped[float]` on a `Numeric` column
# tells every reader a money figure is a float, and a `float` response field
# puts a binary approximation on the wire however exactly the engine computed
# it. Both defects shipped -- `ModelComponent.unit_cost` was annotated `float`
# over `Numeric(10, 2)`, and the production-run actuals coerced an exact sum to
# `float` on the way out.
#
# These two groups are narrower than the services ban on purpose. A model and a
# schema carry weights, temperatures, densities, durations and success rates
# beside their money, and a float is the right type for a gram. So the rule
# here is by name: an attribute whose name says money may not be a `float`.

MODEL_LAYER_MODULES = [
    # Its `unit_cost` was `Mapped[float]`, and it carried two float cost
    # properties duplicating the engine's components line (task T141).
    "model_component.py",
]

SCHEMA_LAYER_MODULES = [
    # `current_cost_per_unit` here is read by `costing.py` for a linked
    # packaging consumable, so a float entered the engine's inputs (task T144).
    "consumable.py",
    # The FR-040 actuals surface: `total_material_cost`, `total_estimated_cost`
    # and the per-material costs beneath them (task T144).
    "production_run.py",
    # `purchase_price`, which `landed_cost.py` divides across a batch and
    # `costing.py:cost_per_gram` divides by a weight: the per-gram figure every
    # material line is priced from starts here, so a float here was the one
    # lossy step in an otherwise exact chain (task T152).
    "spool.py",
    # The customer-facing order reads: `unit_price` and `total_price` on a line,
    # and `subtotal`, `shipping_cost`, `discount_amount` and `total` on the
    # order. These are the same `Numeric` columns `realised_margin.py` and
    # `channel_pnl.py` read exactly, served to the customer who paid them
    # through a binary double (task T176).
    "customer.py",
    # The outbound event payloads: `total_amount`, `amount` and `price`. A
    # subscriber reconciles against these, so the same rule applies on the way
    # out as on the way in (task T176).
    "webhook.py",
    # `total_revenue`, a `SUM` over every settled order's `Numeric` total. It
    # accumulates more error than any other figure in the system, and served
    # it as a binary double. Adding this module closes the money-name sweep
    # across `app/models/` and `app/schemas/` (task T186).
    "platform_admin.py",
]

MODELS_DIR = Path(__file__).resolve().parents[3] / "app" / "models"
SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "app" / "schemas"

#: Name fragments that mean "this is an amount of money".
#:
#: Deliberately without `rate` and `total` on their own: `success_rate` and
#: `total_used` (grams) are not money, and a rule that flagged them would be
#: turned off rather than obeyed. A money field in this codebase always carries
#: one of these, and `cost_per_gram` is caught by `cost`.
MONEY_NAME_PARTS = (
    "cost",
    "price",
    "fee",
    "amount",
    "revenue",
    "profit",
    "margin",
    "charge",
    "tax",
    "reserve",
    "subtotal",
    "discount",
    "refund",
    "markup",
    "surcharge",
    "postage",
    "value",
)

MONEY_NAME = re.compile(r"(^|_)(" + "|".join(MONEY_NAME_PARTS) + r")s?($|_)", re.IGNORECASE)


def names_money(name: str) -> bool:
    """Whether an attribute's name says it holds an amount of money."""
    return MONEY_NAME.search(name) is not None


class MoneyNamedFloatVisitor(ast.NodeVisitor):
    """Collect `float` annotations on anything whose name says money."""

    def __init__(self) -> None:
        self.violations: list[tuple[int, str]] = []

    @staticmethod
    def _mentions_float(annotation: ast.expr) -> bool:
        for node in ast.walk(annotation):
            if isinstance(node, ast.Name) and node.id == "float":
                return True
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                try:
                    inner = ast.parse(node.value, mode="eval")
                except SyntaxError:
                    continue
                for deep in ast.walk(inner):
                    if isinstance(deep, ast.Name) and deep.id == "float":
                        return True
        return False

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and names_money(node.target.id):
            if self._mentions_float(node.annotation):
                self.violations.append((node.lineno, f"{node.target.id}: float"))
        self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # A property or computed field named for money, returning a float.
        if node.returns is not None and names_money(node.name):
            if self._mentions_float(node.returns):
                self.violations.append((node.lineno, f"{node.name}() -> float"))
        self.generic_visit(node)

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function


def _money_named_floats(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = MoneyNamedFloatVisitor()
    visitor.visit(tree)
    return sorted(visitor.violations)


def test_the_money_name_rule_knows_money_from_grams() -> None:
    """The rule must catch a cost and leave a weight alone.

    Both halves matter. A rule that missed `stock_value` would not have caught
    the defect; one that flagged `success_rate` or `total_used` would be
    switched off within a week and then catch nothing.
    """
    for name in (
        "unit_cost",
        "total_cost",
        "cost_per_unit",
        "current_cost_per_unit",
        "stock_value",
        "list_price",
        "platform_fee",
        "total_amount",
        "discount_amount",
        "expected_refund_pct",
    ):
        assert names_money(name), f"{name} holds money and the rule misses it"

    for name in (
        "success_rate",
        "overall_success_rate",
        "total_used",
        "total_returned",
        "estimated_total_weight",
        "variance_grams",
        "variance_percentage",
        "typical_density",
        "diameter",
        "assembly_minutes",
        "quantity_on_hand",
    ):
        assert not names_money(name), f"{name} is not money and the rule flags it"


def test_the_money_named_visitor_detects_a_violation() -> None:
    """A ban nobody has seen fail is a ban nobody can trust."""
    sample = (
        "class Thing:\n"
        "    unit_cost: float = 0.0\n"
        "    weight_grams: float = 0.0\n"
        '    stock_value: "Optional[float]" = None\n'
        "    def total_cost(self) -> float:\n"
        "        return 0.0\n"
        "    def variance_grams(self) -> float:\n"
        "        return 0.0\n"
    )
    visitor = MoneyNamedFloatVisitor()
    visitor.visit(ast.parse(sample))
    flagged = {what for _, what in visitor.violations}
    assert flagged == {"unit_cost: float", "stock_value: float", "total_cost() -> float"}


# ---------------------------------------------------------------------------
# The route layer (tasks T182, T183, T185, T186)
# ---------------------------------------------------------------------------
#
# The services ban covers the engine and the schema ban covers the wire. The
# gap between them was the route handler, where money enters the system: three
# routers divided integer pence by a hundred at twenty-one sites, and in Python
# `int / int` is binary floating point, so `7999 / 100` is
# `79.989999999999994884`. Those values went into `Order.subtotal`,
# `shipping_cost`, `total`, `discount_amount` and `OrderItem.unit_price`,
# `total_price` -- the `Numeric` columns `realised_margin.py` and
# `channel_pnl.py` read exactly and that `sale_snapshot` freezes onto a settled
# order.
#
# Postgres rounds a `Numeric(10, 2)` on the way in, which is why this never
# showed up as a wrong figure on a screen and why only a syntactic ban catches
# it. What it did do was decide a refund: `int(request.amount * 100)` on a
# float `79.99` is `7998`, a penny short of what was asked for.
#
# The rule here is the money-name rule, same as the schema layer, plus a flat
# ban on `float(...)` over a money name's value. A route module carries weights
# and durations beside its money, so a blanket ban would be switched off rather
# than obeyed.

ROUTE_LAYER_MODULES = [
    # The two Square checkout surfaces: the hosted link and the Web Payments
    # SDK, both of which write an order, its lines and its sale snapshot
    # (tasks T180, T182).
    "payments.py",
    # The console's order surface, where a refund is taken and a confirmation
    # is resent. The resend divided an already-in-pounds column by a hundred a
    # second time, so it quoted £0.80 for an £79.99 order (task T182).
    "orders.py",
    # The storefront, whose checkout writes the sale. Two `float(...)` calls
    # remain in it by design and are excused by name below (task T182).
    "shop.py",
    # The production-history reads, whose cost figures were derived in the
    # handler in float and are now the service's recorded actuals
    # (tasks T183, T185).
    "analytics.py",
]

ROUTES_DIR = Path(__file__).resolve().parents[3] / "app" / "api" / "v1"

#: The hold mechanisms these two lists used are gone with their tests (T206).
#:
#: `ROUTE_LAYER_ALLOWED` named two `float(session.total)` calls in `shop.py`
#: that `names_money` never matched -- it omits the bare word `total` on
#: purpose -- so the excuse covered nothing, which the sweep's own
#: `test_every_named_exception_is_still_live` found.
#: `ROUTE_LAYER_LEGACY_FLOAT_FIELDS` pinned a count of four on `orders.py`,
#: and T201 retyped all five fields. Exceptions now live in
#: `MONEY_FLOAT_CALL_EXCEPTIONS` and `MONEY_FLOAT_FIELD_EXCEPTIONS` below,
#: which are checked against the whole population rather than a nominated
#: subset of it.


class MoneyFloatCallVisitor(ast.NodeVisitor):
    """Collect `float(...)` calls whose argument or target names money."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.violations: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "float":
            if any(names_money(name) for name in _names_in(node)):
                self.violations.append((node.lineno, ast.unparse(node)))
        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> None:  # pragma: no cover - via walk
        self.generic_visit(node)


def _names_in(node: ast.AST) -> list[str]:
    """Every identifier and attribute name appearing under `node`."""
    found: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            found.append(sub.id)
        elif isinstance(sub, ast.Attribute):
            found.append(sub.attr)
    return found


def _money_float_calls(path: Path) -> list[tuple[int, str]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    visitor = MoneyFloatCallVisitor(source)
    visitor.visit(tree)
    return sorted(visitor.violations)


def test_the_route_ban_catches_the_defect_it_was_written_for() -> None:
    """A ban nobody has seen fail is a ban nobody can trust.

    Both halves of what shipped: an exact column coerced on the way out, and
    integer pence divided by a hundred on the way in.
    """
    sample = (
        "def handler(order, item):\n"
        "    subtotal = float(order.subtotal) / 100\n"
        "    grams = float(item.weight_grams)\n"
        "    unit_price = item.price / 100\n"
        "    quantity = item.count / 100\n"
    )
    tree = ast.parse(sample)

    calls = MoneyFloatCallVisitor(sample)
    calls.visit(tree)
    assert [text for _, text in calls.violations] == ["float(order.subtotal)"], (
        "the call ban must catch the money coercion and leave the weight alone"
    )

    divisions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if isinstance(node.right, ast.Constant) and node.right.value == 100:
                if any(names_money(n) for n in _names_in(node.left)):
                    divisions.append(ast.unparse(node))
    assert divisions == ["float(order.subtotal) / 100", "item.price / 100"], (
        "the division ban must catch both money divisions and leave item.count / 100 alone"
    )


# ---------------------------------------------------------------------------
# The whole population, swept (T206)
# ---------------------------------------------------------------------------
#
# Everything above names its subjects: `MONEY_MODULES` lists 16 of the 60
# modules in `app/services/`, `SCHEMA_LAYER_MODULES` 7 of 50, and
# `ROUTE_LAYER_MODULES` 4 of 54. So a money `float` in any of the others
# passed. That is how `platform_admin.py` reached T186 and `email_service.py`
# reached T190: each was found by hand, and then *added to a list*, which
# fixes one module and leaves the guard as narrow as it was.
#
# So the money-name rules are applied to every module in the four directories
# money passes through, and the **exceptions** are named instead of the
# subjects. The three lists above stay as the record of what was fixed and
# which modules carry the stricter total ban; they no longer decide what is
# checked.
#
# The sweep found one real defect on the day it was written:
# `shopify_sync.py` built a Shopify price as `f"{price_pence / 100:.2f}"`,
# which is binary float division on two ints -- `7999 / 100` is
# `79.989999999999994884` -- in a module no list named. That is the whole
# argument for inverting this.

SWEPT_DIRECTORIES: dict[str, Path] = {
    "app/services": SERVICES_DIR,
    "app/schemas": SCHEMAS_DIR,
    "app/api/v1": ROUTES_DIR,
    "app/models": MODELS_DIR,
}

#: Money-named `float(...)` calls that are correct, by module path.
#:
#: Each entry is matched as a substring of the unparsed call, so it names the
#: exact expression rather than excusing the file. An entry that stops matching
#: anything fails `test_every_named_exception_is_still_live`, so a stale
#: excuse is deleted rather than accumulating.
#:
#: Every one is a figure leaving the system for something that takes a float by
#: construction, or a name that only looks monetary:
#:
#: * Prometheus gauges are typed `float` by the client library, and the figure
#:   has already been computed exactly -- the display rounding Constitution IV
#:   permits.
#: * An OpenTelemetry span attribute is the same: a trace carries no money.
#: * `waste_grams` and `_positive_or_none`'s `value` are not money at all.
#:   `waste_amount` is grams and the parser reads a slicer's metadata string;
#:   both are caught only because `amount` and `value` are money-name parts.
#: * `variance_service` coerces where the model column still is a `float`. That
#:   one line exists to contain a pre-existing wart, which is why the module is
#:   deliberately absent from `MONEY_MODULES` too; its arithmetic is `Decimal`
#:   throughout and `test_variance.py` asserts it directly.
MONEY_FLOAT_CALL_EXCEPTIONS: dict[str, tuple[str, ...]] = {
    "app/services/model_file_service.py": (
        # `_positive_or_none(value)`: a slicer metadata string, not an amount.
        "float(value)",
    ),
    "app/services/production_run.py": (
        # A Prometheus gauge and an OTel span attribute.
        "float(total_material_cost)",
        # `waste_grams` in a transaction's metadata: grams.
        "float(waste_amount)",
    ),
    "app/services/variance_service.py": (
        # Writing back to a column that is still a float.
        "float(str(value))",
    ),
    "app/api/v1/production_runs.py": (
        # The same Prometheus gauge, from the route.
        "float(production_run.actual_total_cost or 0)",
    ),
}

#: Money-named `float` *annotations* that are correct, by module path.
#:
#: Empty. Every money-named annotation in the four directories is `Decimal`,
#: and the mechanism is kept because the next legacy one will want it.
MONEY_FLOAT_FIELD_EXCEPTIONS: dict[str, tuple[str, ...]] = {}


def _swept_modules() -> list[tuple[str, Path]]:
    """Every module in the four directories money passes through."""
    found: list[tuple[str, Path]] = []
    for label, directory in SWEPT_DIRECTORIES.items():
        for path in sorted(directory.glob("*.py")):
            if path.name == "__init__.py":
                continue
            found.append((f"{label}/{path.name}", path))
    return found


def _swept_ids() -> list[str]:
    return [key for key, _ in _swept_modules()]


def _pence_divisions(path: Path) -> list[tuple[int, str]]:
    """Money-named `/ 100` divisions that are not already exact.

    A `Decimal` numerator and the shared converter are exact; what this finds
    is a bare int or float over 100, which is the arithmetic that turns
    `7999` pence into `79.989999999999994884`.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        divisor = node.right
        if not (isinstance(divisor, ast.Constant) and divisor.value == 100):
            continue
        text = ast.unparse(node)
        if "Decimal" in text or "pence_to_pounds" in text:
            continue
        if any(names_money(name) for name in _names_in(node.left)):
            offenders.append((node.lineno, text))
    return sorted(offenders)


@pytest.mark.parametrize(("key", "path"), _swept_modules(), ids=_swept_ids())
def test_no_module_coerces_money_to_float(key: str, path: Path) -> None:
    """No module anywhere in the money path pushes an amount through a double.

    Applied to the whole directory rather than to a list of modules, so a
    money `float(...)` in a module nobody thought of fails here instead of
    being discovered by reading (Constitution II and IV, FR-047).
    """
    allowed = MONEY_FLOAT_CALL_EXCEPTIONS.get(key, ())
    violations = [
        (lineno, text)
        for lineno, text in _money_float_calls(path)
        if not any(permitted in text for permitted in allowed)
    ]
    if violations:
        listed = "\n".join(f"  {path}:{lineno}: {text}" for lineno, text in violations)
        pytest.fail(
            f"a money figure is coerced to float in {key} (Constitution IV, "
            f"FR-047):\n{listed}\n"
            f"The column is Numeric, so the read is already exact. Hold it as "
            f"a Decimal; convert once at the edge, and only where something "
            f"outside this system requires a JSON number -- and then name the "
            f"expression in MONEY_FLOAT_CALL_EXCEPTIONS with the reason."
        )


@pytest.mark.parametrize(("key", "path"), _swept_modules(), ids=_swept_ids())
def test_no_module_annotates_money_as_float(key: str, path: Path) -> None:
    """No attribute, field or property named for money is a `float`."""
    allowed = MONEY_FLOAT_FIELD_EXCEPTIONS.get(key, ())
    violations = [
        (lineno, what)
        for lineno, what in _money_named_floats(path)
        if not any(permitted in what for permitted in allowed)
    ]
    if violations:
        listed = "\n".join(f"  {path}:{lineno}: {what}" for lineno, what in violations)
        pytest.fail(
            f"a money figure is annotated float in {key} (Constitution IV, "
            f"FR-047):\n{listed}\n"
            f"Money is Decimal in the engine, Numeric in the database and a "
            f"decimal string on the wire. Annotate it Decimal."
        )


@pytest.mark.parametrize(("key", "path"), _swept_modules(), ids=_swept_ids())
def test_no_module_divides_pence_in_binary(key: str, path: Path) -> None:
    """`/ 100` on a money figure must go through the exact converter.

    Checked syntactically rather than by value, because Postgres rounds a
    `Numeric(10, 2)` on the way in and hides the difference. What it does not
    hide is the arithmetic done before the write, or a figure handed to
    another system -- which is how `shopify_sync.py` came to quote
    `f"{7999 / 100:.2f}"` to Shopify.
    """
    offenders = _pence_divisions(path)
    if offenders:
        listed = "\n".join(f"  {path}:{lineno}: {text}" for lineno, text in offenders)
        pytest.fail(
            f"pence are divided by 100 in binary floating point in {key} "
            f"(Constitution IV, FR-047):\n{listed}\n"
            f"Use app.core.money.pence_to_pounds, which divides by Decimal(100)."
        )


class TestTheSweepCoversWhatItClaimsTo:
    """An inverted guard that swept nothing would be worse than a narrow one."""

    def test_each_directory_contributes_its_modules(self) -> None:
        for label, directory in SWEPT_DIRECTORIES.items():
            assert directory.is_dir(), f"{label} is not a directory; the sweep covers nothing"
            count = sum(1 for _key, path in _swept_modules() if path.parent == directory)
            assert count > 10, (
                f"the sweep found only {count} modules in {label}; the glob has "
                f"stopped matching and most of the directory is unchecked"
            )

    def test_the_sweep_is_wider_than_the_lists_it_replaces(self) -> None:
        """The whole point: the population, not a nominated subset."""
        swept = {key for key, _ in _swept_modules()}
        named = (
            {f"app/services/{name}" for name in MONEY_MODULES}
            | {f"app/services/{name}" for name in OTHER_MONEY_MODULES}
            | {f"app/schemas/{name}" for name in SCHEMA_LAYER_MODULES}
            | {f"app/api/v1/{name}" for name in ROUTE_LAYER_MODULES}
            | {f"app/models/{name}" for name in MODEL_LAYER_MODULES}
        )
        assert named <= swept, (
            f"modules are named above that the sweep never visits, so the two "
            f"disagree about where the code is: {sorted(named - swept)}"
        )
        assert len(swept) > 3 * len(named), (
            f"the sweep covers {len(swept)} modules against {len(named)} named "
            f"ones; if these are close, the inversion has been undone"
        )

    def test_every_named_exception_is_still_live(self) -> None:
        """A stale excuse is deleted, not left to cover a future defect."""
        swept = dict(_swept_modules())
        dead: list[str] = []

        for key, allowed in MONEY_FLOAT_CALL_EXCEPTIONS.items():
            path = swept.get(key)
            assert path is not None, f"{key} is excused but the sweep does not visit it"
            texts = [text for _lineno, text in _money_float_calls(path)]
            for permitted in allowed:
                if not any(permitted in text for text in texts):
                    dead.append(f"{key}: {permitted}")

        for key, allowed in MONEY_FLOAT_FIELD_EXCEPTIONS.items():
            path = swept.get(key)
            assert path is not None, f"{key} is excused but the sweep does not visit it"
            whats = [what for _lineno, what in _money_named_floats(path)]
            for permitted in allowed:
                if not any(permitted in what for what in whats):
                    dead.append(f"{key}: {permitted}")

        assert dead == [], (
            f"these exceptions no longer match anything; delete them, or the "
            f"next float on the same line passes unnoticed: {sorted(dead)}"
        )

    def test_an_excused_module_is_not_excused_wholesale(self) -> None:
        """An exception names an expression, never a file.

        An empty tuple would read as "this module is fine" and silence every
        future violation in it, which is the shape this task removed.
        """
        empty = sorted(
            key
            for key, allowed in list(MONEY_FLOAT_CALL_EXCEPTIONS.items())
            + list(MONEY_FLOAT_FIELD_EXCEPTIONS.items())
            if not allowed
        )
        assert empty == [], (
            f"these modules have an exception entry with nothing in it, which "
            f"excuses nothing and documents nothing; remove them: {empty}"
        )

    def test_the_sweep_would_have_caught_the_defect_it_found(self) -> None:
        """The `shopify_sync` division, as the rule sees it.

        `price_pence / 100` is two ints over a constant and would have been
        caught the day the module was written, had anything been looking at
        it. The fix is asserted in the same breath, so a revert fails.
        """
        sample = (
            "def push(product, variant):\n"
            "    price_pence = product.base_price_pence + variant.price_adjustment_pence\n"
            "    before = f'{price_pence / 100:.2f}'\n"
            "    after = f'{pence_to_pounds(price_pence):.2f}'\n"
            "    grams = product.weight_grams / 100\n"
        )
        offenders = []
        for node in ast.walk(ast.parse(sample)):
            if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
                continue
            if not (isinstance(node.right, ast.Constant) and node.right.value == 100):
                continue
            text = ast.unparse(node)
            if "Decimal" in text or "pence_to_pounds" in text:
                continue
            if any(names_money(name) for name in _names_in(node.left)):
                offenders.append(text)

        assert offenders == ["price_pence / 100"], (
            "the rule must catch the pence division, accept the converter and "
            "leave the weight alone"
        )
        assert _pence_divisions(SERVICES_DIR / "shopify_sync.py") == [], (
            "shopify_sync.py divides pence in binary again; it quotes that "
            "figure to Shopify as a price"
        )
