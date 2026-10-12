"""A fresh database must be able to reach head, through exactly one head.

The Constitution's Additional Constraints section requires that a fresh
database reach head after every migration lands, and this repository has
already had to repair a broken chain once (commit b484b00, "fix: repair
migration chain so a fresh database can reach head"). Each tier of the pricing
rebuild adds a migration chained onto `commerce_handover_v1`, so the check
belongs in the suite rather than in someone's memory.

Two things are asserted, and they need different amounts of machinery:

* **Exactly one head, and one connected chain.** Pure revision metadata. It
  runs anywhere, in milliseconds, and catches the failure that actually
  happens: two tiers branching off the same parent and never merging.
* **`alembic upgrade head` against an empty database.** This needs the real
  PostgreSQL dialect -- JSONB, partial indexes, RLS policies and `gen_random_uuid`
  have no SQLite equivalent. It is skipped, loudly, when the suite is running on
  SQLite, and runs in CI where `DATABASE_URL` points at PostgreSQL.
"""

import os
import re
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
VERSIONS_DIR = BACKEND_ROOT / "alembic" / "versions"

#: The head every tier of this feature chains onto (plan.md, data-model.md).
EXPECTED_BASE_FOR_THIS_FEATURE = "commerce_handover_v1"


def _script_directory() -> ScriptDirectory:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


def _is_postgres() -> bool:
    return "postgres" in _database_url()


class TestExactlyOneHead:
    def test_there_is_exactly_one_head(self) -> None:
        heads = _script_directory().get_heads()
        assert len(heads) == 1, (
            f"the migration graph has {len(heads)} heads: {heads}. Two tiers "
            f"branching off the same parent must be merged before either ships, "
            f"or a fresh database cannot reach head."
        )

    def test_every_revision_is_reachable_from_the_single_head(self) -> None:
        """No orphan revision may sit outside the chain."""
        script = _script_directory()
        head = script.get_heads()[0]
        walked = {revision.revision for revision in script.walk_revisions("base", head)}
        all_revisions = {revision.revision for revision in script.walk_revisions()}
        orphans = all_revisions - walked
        assert not orphans, (
            f"{len(orphans)} revision(s) are not reachable from head {head}: {sorted(orphans)}"
        )

    def test_the_feature_base_revision_is_in_the_chain(self) -> None:
        """Every tier of this feature chains onto `commerce_handover_v1`."""
        script = _script_directory()
        head = script.get_heads()[0]
        chain = {revision.revision for revision in script.walk_revisions("base", head)}
        assert EXPECTED_BASE_FOR_THIS_FEATURE in chain, (
            f"{EXPECTED_BASE_FOR_THIS_FEATURE} is not in the migration chain; the "
            f"tier migrations in plan.md are chained onto a revision that no "
            f"longer exists"
        )

    def test_no_two_revision_files_declare_the_same_revision_id(self) -> None:
        """A duplicated id makes the graph ambiguous and the error obscure."""
        seen: dict[str, str] = {}
        pattern = re.compile(r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
        for path in sorted(VERSIONS_DIR.glob("*.py")):
            match = pattern.search(path.read_text(encoding="utf-8"))
            if match is None:
                continue
            revision = match.group(1)
            assert revision not in seen, (
                f"revision id {revision!r} is declared by both {seen[revision]} and {path.name}"
            )
            seen[revision] = path.name
        assert seen, "no revision files were found; this test is proving nothing"

    def test_down_revision_targets_all_exist(self) -> None:
        """A `down_revision` pointing at nothing is the broken-chain failure."""
        script = _script_directory()
        known = {revision.revision for revision in script.walk_revisions()}
        for revision in script.walk_revisions():
            for parent in revision._all_down_revisions or ():
                assert parent in known, (
                    f"revision {revision.revision} ({revision.doc}) points down at "
                    f"{parent}, which does not exist"
                )


@pytest.mark.skipif(
    not _is_postgres(),
    reason=(
        "upgrading an empty database needs the PostgreSQL dialect (JSONB, partial "
        "indexes, RLS policies); set DATABASE_URL to a PostgreSQL instance to run it"
    ),
)
class TestAFreshDatabaseReachesHead:
    async def test_upgrade_head_succeeds_on_an_empty_database(self) -> None:
        """Run the whole chain from base against a scratch database."""
        import uuid

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from alembic import command

        base_url = _database_url()
        scratch = f"migration_head_{uuid.uuid4().hex[:10]}"
        admin_url = re.sub(r"/[^/]+$", "/postgres", base_url)
        scratch_url = re.sub(r"/[^/]+$", f"/{scratch}", base_url)

        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with admin.connect() as conn:
                await conn.execute(text(f'CREATE DATABASE "{scratch}"'))

            config = Config(str(ALEMBIC_INI))
            config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
            config.set_main_option(
                "sqlalchemy.url",
                scratch_url.replace("+asyncpg", "").replace("+psycopg", ""),
            )
            command.upgrade(config, "head")

            engine = create_async_engine(scratch_url)
            try:
                async with engine.connect() as conn:
                    current = (
                        (await conn.execute(text("SELECT version_num FROM alembic_version")))
                        .scalars()
                        .all()
                    )
            finally:
                await engine.dispose()

            assert current == _script_directory().get_heads(), (
                f"a fresh database stopped at {current} rather than at head"
            )
        finally:
            async with admin.connect() as conn:
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
            await admin.dispose()
