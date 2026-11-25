"""Every Alembic revision id fits the column Alembic stores it in.

`alembic_version.version_num` is ``VARCHAR(32)``. A longer id passes every test
that builds the schema from the models and fails only when a database is
migrated -- in production, at deploy, half way through a chain. One id in the
pricing chain was 34 characters and was caught on a scratch copy of dev.
"""

import ast
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
VERSION_NUM_WIDTH = 32


def _revision_ids() -> dict[str, str]:
    ids: dict[str, str] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if (
                isinstance(node, (ast.Assign, ast.AnnAssign))
                and isinstance(getattr(node, "value", None), ast.Constant)
                and any(
                    isinstance(target, ast.Name) and target.id == "revision"
                    for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                )
            ):
                ids[path.name] = str(node.value.value)
    return ids


def test_every_revision_id_fits_alembic_version() -> None:
    too_long = {name: rid for name, rid in _revision_ids().items() if len(rid) > VERSION_NUM_WIDTH}
    assert not too_long, (
        f"alembic_version.version_num is VARCHAR({VERSION_NUM_WIDTH}); these ids would "
        f"fail the migration that records them: {too_long}"
    )


def test_the_sweep_finds_the_revisions() -> None:
    assert len(_revision_ids()) > 50
