"""Run duration helper (.specify/bugs/complete-run-timezone-500)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.services.production_run import elapsed_hours

START = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def test_elapsed_hours_rounds_to_two_places():
    assert elapsed_hours(START, START + timedelta(hours=4, minutes=30)) == Decimal("4.50")


def test_elapsed_hours_never_negative():
    """A start after the end gives 0, not a negative duration the schema refuses."""
    assert elapsed_hours(START + timedelta(hours=5), START) == Decimal("0.00")


def test_elapsed_hours_takes_naive_datetimes_as_utc():
    naive_start = START.replace(tzinfo=None)
    assert elapsed_hours(naive_start, START + timedelta(hours=2)) == Decimal("2.00")
    assert elapsed_hours(START, (START + timedelta(hours=1)).replace(tzinfo=None)) == Decimal(
        "1.00"
    )
