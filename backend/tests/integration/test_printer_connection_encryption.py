"""Printer secrets are encrypted at rest (spec 009, User Story 5, T015).

The API answers exactly as before (masked values) plus a state per secret;
the database holds only ciphertext; a value the server key can no longer read
shows as "unreadable" so the operator enters it again.
"""

import uuid

from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_value
from app.models.printer_connection import PrinterConnection
from app.services.printer_secrets import get_access_code

LAN = {
    "connection_type": "bambu_lan",
    "serial_number": "01P00A123456789",
    "ip_address": "192.168.1.100",
    "port": 8883,
    "access_code": "73519246",
    "ams_count": 1,
}


async def _stored(db: AsyncSession, printer_id) -> tuple:
    return (
        await db.execute(
            text("SELECT access_code, cloud_token FROM printer_connections WHERE printer_id = :p"),
            {"p": str(printer_id)},
        )
    ).one()


async def test_create_stores_ciphertext_and_answers_masked(
    client: AsyncClient, db_session: AsyncSession, test_printer
):
    response = await client.post(f"/api/v1/printers/{test_printer.id}/connection", json=LAN)
    assert response.status_code == 201, response.text
    body = response.json()
    assert "****" in body["access_code"] and body["access_code"].endswith("9246")
    assert "73519246" not in response.text
    assert body["access_code_state"] == "set"
    assert body["cloud_token_state"] == "unset"

    code, token = await _stored(db_session, test_printer.id)
    assert code != "73519246" and "73519246" not in code
    assert decrypt_value(code) == "73519246"
    assert token is None


async def test_update_reencrypts_and_the_printer_gets_the_clear_code(
    client: AsyncClient, db_session: AsyncSession, test_printer
):
    await client.post(f"/api/v1/printers/{test_printer.id}/connection", json=LAN)
    before, _ = await _stored(db_session, test_printer.id)
    response = await client.put(
        f"/api/v1/printers/{test_printer.id}/connection", json={"access_code": "87654321"}
    )
    assert response.status_code == 200, response.text
    after, _ = await _stored(db_session, test_printer.id)
    assert after != before and decrypt_value(after) == "87654321"

    db_session.expunge_all()
    connection = (
        await db_session.execute(
            text("SELECT id FROM printer_connections WHERE printer_id = :p"),
            {"p": str(test_printer.id)},
        )
    ).scalar_one()
    row = await db_session.get(PrinterConnection, uuid.UUID(str(connection)))
    assert get_access_code(row) == "87654321"


async def test_a_code_from_another_key_reads_as_unreadable(
    client: AsyncClient, db_session: AsyncSession, test_printer
):
    await client.post(f"/api/v1/printers/{test_printer.id}/connection", json=LAN)
    foreign = Fernet(Fernet.generate_key()).encrypt(b"73519246").decode()
    await db_session.execute(
        text("UPDATE printer_connections SET access_code = :c WHERE printer_id = :p"),
        {"c": foreign, "p": str(test_printer.id)},
    )
    await db_session.commit()
    db_session.expunge_all()

    response = await client.get(f"/api/v1/printers/{test_printer.id}/connection")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_code_state"] == "unreadable"
    assert foreign not in response.text

    fixed = await client.put(
        f"/api/v1/printers/{test_printer.id}/connection", json={"access_code": "11223344"}
    )
    assert fixed.json()["access_code_state"] == "set"
