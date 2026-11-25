"""The single access-code accessor (spec 011, FR-017; switched to decryption by spec 009)."""

import logging
import uuid

from cryptography.fernet import Fernet

from app.core.encryption import decrypt_value
from app.models.printer_connection import PrinterConnection
from app.services.printer_secrets import get_access_code, secret_state


def test_returns_the_stored_code():
    assert get_access_code(PrinterConnection(access_code="12345678")) == "12345678"


def test_missing_or_empty_code_is_none():
    assert get_access_code(PrinterConnection(access_code=None)) is None
    assert get_access_code(PrinterConnection(access_code="")) is None


# ============================================
# Encryption at rest (spec 009, US5)
# ============================================


def test_secrets_are_stored_encrypted_and_read_clear():
    connection = PrinterConnection(access_code="12345678", cloud_token="tok-secret")
    assert connection.access_code_encrypted not in (None, "12345678")
    assert "12345678" not in connection.access_code_encrypted
    assert decrypt_value(connection.access_code_encrypted) == "12345678"
    assert connection.cloud_token_encrypted != "tok-secret"
    assert (connection.access_code, connection.cloud_token) == ("12345678", "tok-secret")


def test_each_write_gives_a_fresh_ciphertext():
    first = PrinterConnection(access_code="12345678").access_code_encrypted
    second = PrinterConnection(access_code="12345678").access_code_encrypted
    assert first != second  # Fernet tokens carry a random IV


def test_states():
    assert secret_state(PrinterConnection(access_code=None), "access_code") == "unset"
    assert secret_state(PrinterConnection(access_code="12345678"), "access_code") == "set"
    assert secret_state(PrinterConnection(cloud_token="t"), "cloud_token") == "set"
    assert PrinterConnection(access_code="12345678").access_code_state == "set"
    assert PrinterConnection().cloud_token_state == "unset"


def test_a_value_encrypted_with_another_key_is_unreadable(caplog):
    """After a server key change the code reads as unreadable, never as garbage."""
    foreign = Fernet(Fernet.generate_key()).encrypt(b"12345678").decode()
    connection = PrinterConnection(id=uuid.uuid4())
    connection.access_code_encrypted = foreign
    with caplog.at_level(logging.WARNING):
        assert connection.access_code is None
        assert get_access_code(connection) is None
        assert secret_state(connection, "access_code") == "unreadable"
    assert str(connection.id) in caplog.text
    assert foreign not in caplog.text and "12345678" not in caplog.text


def test_a_clear_legacy_value_is_unreadable_not_returned():
    """A row the data migration missed must not be sent to a printer as is."""
    connection = PrinterConnection(id=uuid.uuid4())
    connection.access_code_encrypted = "12345678"
    assert connection.access_code is None
    assert secret_state(connection, "access_code") == "unreadable"
