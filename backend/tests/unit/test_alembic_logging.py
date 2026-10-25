"""Running a migration must not silence the application's loggers (task T271).

`alembic/env.py` configures logging from `alembic.ini`. With `fileConfig`'s
default `disable_existing_loggers=True`, every logger created before a
migration ran in the same process was disabled for good -- in a test worker
that meant the margin-alert sweep's divergence warnings (FR-042) vanished from
whatever test ran next, and the suite failed by test order.
"""

import ast
import logging
from logging.config import fileConfig
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ENV_PY = BACKEND / "alembic" / "env.py"
ALEMBIC_INI = BACKEND / "alembic.ini"


def _file_config_calls() -> list[ast.Call]:
    tree = ast.parse(ENV_PY.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "fileConfig"
    ]


def test_env_keeps_existing_loggers_enabled() -> None:
    calls = _file_config_calls()
    assert calls, "env.py no longer configures logging; this test is proving nothing"
    for call in calls:
        flags = {kw.arg: kw.value for kw in call.keywords}
        value = flags.get("disable_existing_loggers")
        assert isinstance(value, ast.Constant) and value.value is False, (
            "env.py must call fileConfig(..., disable_existing_loggers=False)"
        )


def test_an_application_logger_still_logs_after_the_config_is_read() -> None:
    logger = logging.getLogger("app.services.margin_alert")
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        fileConfig(str(ALEMBIC_INI), disable_existing_loggers=False)

        assert not logger.disabled
        assert logger.isEnabledFor(logging.WARNING)
    finally:
        # fileConfig replaces the root handlers; give the rest of the
        # process back the logging it had.
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
