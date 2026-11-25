"""The money paths type-check under the stricter settings research D8 sets (T248).

`pyproject.toml` holds the money modules to a stricter mypy standard, and
nothing ran it: the list still named a module deleted in an earlier task,
missed two that handle money, and the modules on it carried eleven errors. Run
here, it is part of the unit suite CI already runs, so the list and the code
cannot drift apart unnoticed again.
"""

import importlib.util
import tomllib
from pathlib import Path

import pytest

from tests.unit.pricing.money_modules import NOT_MONEY_PATHS, flagged_services, money_services

BACKEND = Path(__file__).resolve().parents[3]


def _money_modules() -> list[str]:
    config = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    return [
        module for override in config["tool"]["mypy"]["overrides"] for module in override["module"]
    ]


def test_every_listed_module_exists() -> None:
    missing = [m for m in _money_modules() if importlib.util.find_spec(m) is None]
    assert not missing, f"the mypy money list names modules that do not exist: {missing}"


def test_every_service_that_handles_money_is_listed() -> None:
    """The list covers every service the money rule flags (T265).

    Checking two names by hand let postage, realised refunds and the
    cost-input estimates go unchecked; the rule finds them instead.
    """
    listed = set(_money_modules())
    unlisted = {
        name: why for name, why in money_services().items() if f"app.services.{name}" not in listed
    }
    assert not unlisted, (
        "these services handle money and are not type-checked strictly; add them to "
        "the mypy override in pyproject.toml, or to NOT_MONEY_PATHS with the reason: "
        f"{unlisted}"
    )


def test_an_exempt_service_is_one_the_rule_still_flags() -> None:
    stale = set(NOT_MONEY_PATHS) - set(flagged_services())
    assert not stale, f"NOT_MONEY_PATHS names services the rule no longer flags: {stale}"


@pytest.mark.timeout(600)
def test_the_money_paths_type_check() -> None:
    mypy_api = pytest.importorskip("mypy.api")
    args = ["--follow-imports=silent", "--no-error-summary"]
    for module in _money_modules():
        args += ["-m", module]
    stdout, stderr, status = mypy_api.run(args)
    assert status == 0, f"mypy found errors in the money paths:\n{stdout}{stderr}"
