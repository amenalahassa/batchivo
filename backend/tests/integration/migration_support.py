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

:func:`scratch_database_at` is the fast way to the state most migration tests
start from: a fresh database already at a given revision. Migrating a database
from empty takes 12 to 17 seconds; copying one that is already there takes a
fraction of that. So the first request for a revision migrates a *template*
database once, under the same lock, and every scratch database after that is
a ``CREATE DATABASE ... TEMPLATE`` copy of it: still a database of its own,
which the test may upgrade, downgrade or fill as it likes.
"""

import hashlib
import os
import re
import time
import uuid
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError

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


# ---------------------------------------------------------------------------
# Scratch databases copied from a migrated template
# ---------------------------------------------------------------------------

#: Every template database starts with this, so the end of the session can
#: find them and nothing else.
TEMPLATE_PREFIX = "mtpl_"

#: Revisions some test module will ask :func:`scratch_database_at` for. Test
#: modules declare theirs with :func:`templates_needed` at import, which every
#: pytest-xdist worker does for every module before running any test, so the
#: first template build migrates one database up through all of them in order
#: rather than migrating from empty once per revision.
_wanted: set[str] = set()

#: Revisions whose template this process has already seen exist.
_ready: set[str] = set()


def templates_needed(*revisions: str) -> None:
    """Declare, at import, the revisions a module copies scratch databases at.

    Optional: a revision nobody declared is still built on first use, only in
    a pass of its own rather than alongside the others.
    """
    _wanted.update(revisions)


@lru_cache(maxsize=1)
def _script() -> ScriptDirectory:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


@lru_cache(maxsize=None)
def _ancestry(revision: str) -> frozenset[str]:
    """``revision`` and every revision below it."""
    return frozenset(rev.revision for rev in _script().iterate_revisions(revision, "base"))


@lru_cache(maxsize=1)
def _fingerprint() -> str:
    """A digest of the migration code, so an edited migration never reuses a
    template built from the previous version of it."""
    digest = hashlib.sha256()
    root = BACKEND_ROOT / "alembic"
    for path in sorted([root / "env.py", *(root / "versions").glob("*.py")]):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def template_name(revision: str) -> str:
    """The template database holding a fresh database migrated to ``revision``."""
    name = f"{TEMPLATE_PREFIX}{_fingerprint()}_{revision}"
    if len(name) > 63:  # PostgreSQL truncates identifiers past 63 bytes
        short = hashlib.sha256(revision.encode()).hexdigest()[:16]
        name = f"{TEMPLATE_PREFIX}{_fingerprint()}_{short}"
    return name


def _base_url() -> str:
    return os.environ.get("DATABASE_URL", "")


def _admin(url: str) -> Engine:
    return create_engine(sync_url(database_named(url, "postgres")), isolation_level="AUTOCOMMIT")


def _existing(admin: Engine) -> set[str]:
    """The template databases on the server, by name."""
    with admin.connect() as conn:
        return set(
            conn.execute(
                text("SELECT datname FROM pg_database WHERE datname LIKE :prefix"),
                {"prefix": f"{TEMPLATE_PREFIX}%"},
            )
            .scalars()
            .all()
        )


def _create_from(admin: Engine, name: str, template: str | None) -> None:
    """``CREATE DATABASE``, copied from ``template`` when one is given.

    PostgreSQL refuses a copy while another session is connected to the
    template. Nothing connects to a finished template except, briefly, the
    autovacuum launcher, so a refusal is retried rather than failed.
    """
    source = f' TEMPLATE "{template}"' if template else ""
    for attempt in range(40):
        try:
            with admin.connect() as conn:
                conn.execute(text(f'CREATE DATABASE "{name}"{source}'))
            return
        except OperationalError as error:
            if "is being accessed by other users" not in str(error) or attempt == 39:
                raise
            time.sleep(0.25)


def _build_templates(admin: Engine, base_url: str, revisions: set[str]) -> None:
    """Migrate one database up through ``revisions``, snapshotting each.

    Runs under the migration lock. Each revision starts from the deepest
    template it descends from -- the previous step's, usually -- so the chain
    is migrated from empty at most once per pass.
    """
    present = _existing(admin)
    available = {rev for rev in _wanted if template_name(rev) in present}
    build = f"{TEMPLATE_PREFIX}build_{uuid.uuid4().hex[:10]}"
    build_url = database_named(base_url, build)
    at: str | None = None
    try:
        for revision in sorted(revisions, key=lambda rev: len(_ancestry(rev))):
            if at is None or at not in _ancestry(revision):
                start = max(
                    (rev for rev in available if rev in _ancestry(revision)),
                    key=lambda rev: len(_ancestry(rev)),
                    default=None,
                )
                with admin.connect() as conn:
                    conn.execute(text(f'DROP DATABASE IF EXISTS "{build}" WITH (FORCE)'))
                _create_from(admin, build, template_name(start) if start else None)
                if start is None:
                    engine = create_engine(sync_url(build_url), isolation_level="AUTOCOMMIT")
                    try:
                        with engine.connect() as conn:
                            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
                    finally:
                        engine.dispose()
            with alembic_against(build_url) as config:
                command.upgrade(config, revision)
            # CREATE DATABASE commits whole or not at all: a template another
            # worker can see is a finished one.
            _create_from(admin, template_name(revision), build)
            available.add(revision)
            at = revision
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{build}" WITH (FORCE)'))


def _ensure_template(revision: str) -> str:
    """The template for ``revision``; built, with every missing wanted one, if absent."""
    name = template_name(revision)
    if revision in _ready:
        return name
    base_url = _base_url()
    admin = _admin(base_url)
    try:
        if name not in _existing(admin):
            with _one_migration_at_a_time(base_url):
                # Another worker may have built them while this one waited.
                present = _existing(admin)
                missing = {rev for rev in _wanted | {revision} if template_name(rev) not in present}
                if missing:
                    _build_templates(admin, base_url, missing)
        _ready.add(revision)
    finally:
        admin.dispose()
    return name


@contextmanager
def scratch_database_at(revision: str, prefix: str) -> Iterator[tuple[Engine, str]]:
    """A database of its own, already migrated to ``revision``; dropped on exit.

    Yields an AUTOCOMMIT engine on it and its URL, to hand to
    :func:`alembic_against`. It holds exactly what an empty database with
    ``pgcrypto`` holds once migrated to ``revision``, and nothing any other
    test wrote.
    """
    template = _ensure_template(revision)
    base_url = _base_url()
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    url = database_named(base_url, name)
    admin = _admin(base_url)
    engine = None
    try:
        _create_from(admin, name, template)
        engine = create_engine(sync_url(url), isolation_level="AUTOCOMMIT")
        yield engine, url
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def drop_templates(url: str) -> None:
    """Drop the template databases, at the end of a session.

    One something is still connected to -- a copy being taken by another run
    against the same server -- is left for that run to drop.
    """
    admin = _admin(url)
    try:
        for name in sorted(_existing(admin)):
            try:
                with admin.connect() as conn:
                    conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            except OperationalError:
                pass
    finally:
        admin.dispose()
