"""Every datetime column stores an instant with its time zone.

A bare ``Mapped[datetime]`` maps to ``timestamp without time zone``. Every
writer in this codebase stores ``datetime.now(UTC)``, so a naive column either
shifts the value through the session time zone (psycopg) or refuses it
(asyncpg). Bug postgres-naive-datetime-writes found seven such columns; this
walk keeps an eighth from appearing.
"""

import importlib
import pkgutil
from pathlib import Path

from sqlalchemy import DateTime

import app.models
from app.database import Base

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261025_timestamptz_instants.py"
)


def _load_every_model() -> None:
    for module in pkgutil.iter_modules(app.models.__path__):
        importlib.import_module(f"app.models.{module.name}")


def test_every_datetime_column_is_timezone_aware() -> None:
    _load_every_model()
    naive = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if isinstance(column.type, DateTime) and not column.type.timezone
    ]
    assert naive == [], (
        f"Declare these columns mapped_column(DateTime(timezone=True), ...) and "
        f"migrate them to timestamptz: {naive}"
    )


def test_the_migration_converts_every_column_the_models_fixed() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for table, column in (
        ("platform_admin_audit_logs", "created_at"),
        ("platform_settings", "updated_at"),
        ("webhook_subscriptions", "last_triggered_at"),
        ("webhook_subscriptions", "last_success_at"),
        ("webhook_deliveries", "next_retry_at"),
        ("webhook_deliveries", "completed_at"),
        ("external_listings", "last_synced_at"),
    ):
        assert f'("{table}", "{column}")' in source
    assert "AT TIME ZONE 'UTC'" in source
