"""Run alembic against a scratch database, and only against a scratch database.

`alembic/env.py` sets `sqlalchemy.url` from the application settings:

    settings = get_settings()
    config.set_main_option("sqlalchemy.url", settings.database_url)

which means a `Config` built in a test and handed its own URL is *ignored* —
alembic migrates whatever `DATABASE_URL` points at. A migration test that does
not account for that does not test a scratch database; it migrates the
developer's own one, and a downgrade test would take it apart.

:func:`alembic_against` is the guard: it points `DATABASE_URL` at the scratch
database, clears the settings cache so `env.py` reads the new value, and puts
both back afterwards.
"""

import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from alembic.config import Config

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"


def sync_url(url: str) -> str:
    """The same database through psycopg's synchronous driver."""
    return url.replace("+asyncpg", "+psycopg")


def database_named(url: str, name: str) -> str:
    """``url`` with its database name replaced by ``name``."""
    return re.sub(r"/[^/?]+(\?|$)", rf"/{name}\1", url)


@contextmanager
def alembic_against(url: str) -> Iterator[Config]:
    """An alembic `Config` that really does act on ``url``.

    Yields inside a window where `DATABASE_URL` names ``url``, so `env.py`
    resolves to it. Both the variable and the settings cache are restored on
    the way out, whether or not the migration succeeded.
    """
    from app.config import get_settings

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", sync_url(url))

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = sync_url(url)
    get_settings.cache_clear()
    try:
        yield config
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
