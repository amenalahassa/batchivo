"""The single access-code accessor (spec 011, FR-017; switched to decryption by spec 009)."""

from app.models.printer_connection import PrinterConnection
from app.services.printer_secrets import get_access_code


def test_returns_the_stored_code():
    assert get_access_code(PrinterConnection(access_code="12345678")) == "12345678"


def test_missing_or_empty_code_is_none():
    assert get_access_code(PrinterConnection(access_code=None)) is None
    assert get_access_code(PrinterConnection(access_code="")) is None
