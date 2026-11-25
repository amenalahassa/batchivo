"""Single access point for printer connection secrets (spec 011 FR-017, spec 009 US5).

The access code and cloud token are stored encrypted (spec 009): the
``PrinterConnection.access_code`` / ``cloud_token`` properties decrypt on read
and encrypt on write, so every caller gets the clear value it needs without
change. Printer operations read the access code through :func:`get_access_code`.

:func:`secret_state` is the one place that tells "set", "unset" and
"unreadable" apart; a stored secret becomes unreadable when the server key it
was encrypted with changes, and the operator must then enter it again.

Values returned here are secrets: never log them, never put them in an error
message, never return them from an endpoint.
"""

import logging
from typing import Literal, Optional

from app.models.printer_connection import PrinterConnection

logger = logging.getLogger(__name__)

SecretField = Literal["access_code", "cloud_token"]
SecretState = Literal["set", "unset", "unreadable"]


def get_access_code(connection: PrinterConnection) -> Optional[str]:
    """The clear LAN access code of ``connection``, or None when none is usable."""
    return connection.access_code or None


def secret_state(connection: PrinterConnection, field: SecretField) -> SecretState:
    """Whether a secret is set, unset, or stored but no longer decryptable."""
    stored = getattr(connection, f"{field}_encrypted")
    if not stored:
        return "unset"
    if getattr(connection, field):
        return "set"
    # Only the connection id: neither the secret nor its ciphertext is logged.
    logger.warning(f"Printer connection {connection.id}: stored {field} cannot be decrypted")
    return "unreadable"
