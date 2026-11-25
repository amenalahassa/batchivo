"""Converting a money column must not move the money (task T154).

`material_types.typical_cost_per_kg` held money on a `double precision`
column. The schema half of this migration fails loudly — a column that will not
alter raises — so what needs pinning is the **conversion**: a cast that silently
rounded, truncated or nulled a figure would leave every material type still
resolving, still prefilling a spool's purchase price, and quietly wrong.

Three things are asserted, and each has a wrong answer that would look fine:

* **The stored type really changes.** `Float` is a subclass of `Numeric` in
  SQLAlchemy, so a model-level `isinstance` check passes against the exact
  thing this task removes. Here the type is read from the live catalogue, with
  its precision and scale, which cannot be mistaken either way.
* **Every value survives, exactly.** Including the seeded ones, which a
  migration that recreated the column instead of altering it would drop to
  null without failing.
* **The downgrade puts the column back.** The half that is normally written
  and never run. It cannot restore digits a two-place column never held, and
  nothing reads it expecting them — but it must leave a usable column rather
  than a missing one.

Everything is synchronous, like the other migration suites and for the same
reason: a migration is synchronous, and psycopg's async mode cannot run on
Windows' default event loop, so an async version would only ever run in CI —
the opposite of what a data-migration check is for.
"""

import os
import uuid
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from tests.integration.migration_support import (
    alembic_against,
    database_named,
    sync_url,
)

REVISION = "pricing_material_cost_numeric_v1"
PARENT = "pricing_channel_economics_v1"

#: Figures inserted before the migration, each chosen for what it would catch.
#:
#: `24.99` is the ordinary case and the one a careless cast rounds to 25.
#: `0.00` is falsy, which a backfill written with `if value:` would skip.
#: `None` must stay null rather than becoming a zero that reads as free.
#: `1234.56` exercises the precision: `Numeric(10, 2)` holds it, and a narrower
#: column chosen by guesswork would raise on it rather than silently truncate.
CASES = {
    "TESTPLA": Decimal("24.99"),
    "TESTFREE": Decimal("0.00"),
    "TESTNONE": None,
    "TESTWIDE": Decimal("1234.56"),
}


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


def _is_postgres() -> bool:
    return "postgres" in _database_url()


pytestmark = pytest.mark.skipif(
    not _is_postgres(),
    reason=(
        "altering a column's type and reading it back needs the PostgreSQL "
        "dialect and catalogue; set DATABASE_URL to a PostgreSQL instance to "
        "run it"
    ),
)


@pytest.fixture
def scratch_database():
    """A scratch database at the migration's parent, with material types in it.

    The rows go in *between* the upgrades: against an empty table the cast
    touches nothing and proves nothing.
    """
    base_url = _database_url()
    scratch = f"mat_cost_{uuid.uuid4().hex[:10]}"
    admin_url = database_named(base_url, "postgres")
    scratch_url = database_named(base_url, scratch)

    admin = create_engine(sync_url(admin_url), isolation_level="AUTOCOMMIT")
    engine = None
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{scratch}"'))

        engine = create_engine(sync_url(scratch_url), isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

        with alembic_against(scratch_url) as config:
            command.upgrade(config, PARENT)

        with engine.connect() as conn:
            for code, cost in CASES.items():
                conn.execute(
                    text(
                        """
                        INSERT INTO material_types (
                            id, code, name, typical_density, typical_cost_per_kg,
                            is_active, created_at, updated_at
                        )
                        VALUES (gen_random_uuid(), :code, :name, 1.24, :cost,
                                true, now(), now())
                        """
                    ),
                    {"code": code, "name": f"Material {code}", "cost": cost},
                )

        yield engine, scratch_url
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        admin.dispose()


def _column(engine, name: str) -> dict:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT data_type, numeric_precision, numeric_scale
                FROM information_schema.columns
                WHERE table_name = 'material_types' AND column_name = :name
                """
            ),
            {"name": name},
        ).one()
    return {"type": row[0], "precision": row[1], "scale": row[2]}


def _costs(engine) -> dict[str, Decimal | None]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT code, typical_cost_per_kg FROM material_types
                WHERE code = ANY(:codes)
                """
            ),
            {"codes": list(CASES)},
        ).all()
    return {code: cost for code, cost in rows}


class TestTheColumnBecomesExact:
    def test_it_starts_as_a_binary_float(self, scratch_database) -> None:
        """Otherwise the migration is a no-op and the rest of this file is
        asserting something that was already true."""
        engine, _ = scratch_database

        assert _column(engine, "typical_cost_per_kg")["type"] == "double precision"

    def test_it_ends_as_numeric_with_two_places(self, scratch_database) -> None:
        engine, url = scratch_database
        with alembic_against(url) as config:
            command.upgrade(config, REVISION)

        column = _column(engine, "typical_cost_per_kg")
        assert column["type"] == "numeric"
        assert column["scale"] == 2, "whole pence, matching spools.purchase_price"
        assert column["precision"] == 10

    def test_the_density_beside_it_is_left_alone(self, scratch_database) -> None:
        """A density is a measurement, not money. Converting it would make
        `numeric` in this schema mean "number" instead of "money"."""
        engine, url = scratch_database
        with alembic_against(url) as config:
            command.upgrade(config, REVISION)

        assert _column(engine, "typical_density")["type"] == "double precision"


class TestNoFigureMoves:
    def test_every_recorded_cost_survives_exactly(self, scratch_database) -> None:
        engine, url = scratch_database
        with alembic_against(url) as config:
            command.upgrade(config, REVISION)

        after = _costs(engine)
        for code, expected in CASES.items():
            if expected is None:
                continue
            assert after[code] == expected, f"{code} moved from {expected} to {after[code]}"

    def test_a_zero_cost_stays_zero_rather_than_becoming_null(self, scratch_database) -> None:
        """`0.00` is falsy. A conversion written with a truthiness test would
        drop it, and a null here reads as "nobody has said" rather than
        "free"."""
        engine, url = scratch_database
        with alembic_against(url) as config:
            command.upgrade(config, REVISION)

        assert _costs(engine)["TESTFREE"] == Decimal("0.00")

    def test_an_unrecorded_cost_stays_null_rather_than_becoming_zero(
        self, scratch_database
    ) -> None:
        """The other direction, and the more dangerous one: a zero is
        indistinguishable from a real figure (FR-019)."""
        engine, url = scratch_database
        with alembic_against(url) as config:
            command.upgrade(config, REVISION)

        assert _costs(engine)["TESTNONE"] is None

    def test_the_seeded_material_types_survive(self, scratch_database) -> None:
        """A migration that recreated the column instead of altering it would
        null these eight without failing."""
        engine, url = scratch_database
        with alembic_against(url) as config:
            command.upgrade(config, REVISION)

        with engine.connect() as conn:
            unrecorded = conn.execute(
                text(
                    """
                    SELECT count(*) FROM material_types
                    WHERE typical_cost_per_kg IS NULL AND code <> 'TESTNONE'
                    """
                )
            ).scalar_one()

        assert unrecorded == 0, f"{unrecorded} material type(s) lost their reference cost"


class TestTheDowngradeLeavesAUsableColumn:
    def test_the_column_goes_back_to_a_float(self, scratch_database) -> None:
        engine, url = scratch_database
        with alembic_against(url) as config:
            command.upgrade(config, REVISION)
            command.downgrade(config, PARENT)

        assert _column(engine, "typical_cost_per_kg")["type"] == "double precision"

    def test_the_figures_are_still_there_afterwards(self, scratch_database) -> None:
        """It cannot restore digits a two-place column never held — nothing
        reads it expecting them — but it must not lose the figures it has."""
        engine, url = scratch_database
        with alembic_against(url) as config:
            command.upgrade(config, REVISION)
            command.downgrade(config, PARENT)

        after = _costs(engine)
        assert after["TESTPLA"] == pytest.approx(24.99)
        assert after["TESTNONE"] is None
