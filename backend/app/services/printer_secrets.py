"""Single access point for printer connection secrets (spec 011, FR-017).

Every read of a printer's LAN access code goes through :func:`get_access_code`.
Today the column holds the code in clear; spec 009 (Preflight foundations)
encrypts it and changes only this function to decrypt, so the code that sends
files and print commands does not change.

The value returned here is a secret: never log it, never put it in an error
message, never return it from an endpoint.
"""

from typing import Optional

from app.models.printer_connection import PrinterConnection


def get_access_code(connection: PrinterConnection) -> Optional[str]:
    """The LAN access code of ``connection``, or None when none is set."""
    return connection.access_code or None
