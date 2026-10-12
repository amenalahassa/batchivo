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
from pathlib import Path

import pytest

# The five money modules named in research.md D8. Modules belonging to a later
# tier do not exist yet; those are skipped by name so the gap is visible in the
# test report rather than silently passing.
MONEY_MODULES = [
    "costing.py",
    "landed_cost.py",
    "fee_engine.py",
    "pricing_solver.py",
    "channel_pnl.py",
]

SERVICES_DIR = Path(__file__).resolve().parents[3] / "app" / "services"


def _module_paths() -> list[Path]:
    return [SERVICES_DIR / name for name in MONEY_MODULES]


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


@pytest.mark.parametrize("path", _module_paths(), ids=MONEY_MODULES)
def test_module_uses_no_float(path: Path) -> None:
    """No money module may annotate or construct a `float`."""
    if not path.exists():
        pytest.skip(f"{path.name} belongs to a later tier and does not exist yet")

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
