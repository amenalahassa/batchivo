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
both back afterwards. It also holds a lock that lets one migration run at a
time across pytest-xdist workers: see :func:`_one_migration_at_a_time`.
"""

import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from alembic.config import Config
from sqlalchemy import create_engine, text

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"


def sync_url(url: str) -> str:
    """The same database through psycopg's synchronous driver."""
    return url.replace("+asyncpg", "+psycopg")


def database_named(url: str, name: str) -> str:
    """``url`` with its database name replaced by ``name``."""
    return re.sub(r"/[^/?]+(\?|$)", rf"/{name}\1", url)


#: Any constant; it only has to be the same in every worker.
MIGRATION_LOCK_KEY = 7_001_000_001

_held = 0


@contextmanager
def _one_migration_at_a_time(url: str) -> Iterator[None]:
    """Hold a server-wide lock while a scratch database is migrated.

    Migration ``ecce200bf082`` creates the cluster-wide ``app_user`` role
    after checking that it does not exist yet. Two workers migrating fresh
    scratch databases at the same moment both see it missing, and the second
    CREATE fails on the role's unique name -- an error in whichever module's
    setup lost the race, more likely the faster the suite runs. The lock is
    taken on the ``postgres`` database, which every worker reaches, and is
    re-entrant within a process so a nested window cannot wait on itself.
    """
    global _held
    if _held:
        _held += 1
        try:
            yield
        finally:
            _held -= 1
        return
    engine = create_engine(sync_url(database_named(url, "postgres")), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY})
            _held = 1
            try:
                yield
            finally:
                _held = 0
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_KEY})
    finally:
        engine.dispose()


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
        with _one_migration_at_a_time(url):
            yield config
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
