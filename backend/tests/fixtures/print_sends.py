"""Shared setup for the print send tests (spec 011).

A Bambu LAN printer in Developer Mode whose AMS slot 1 holds a red PLA spool
and slot 2 a green PETG spool (as recorded in Batchivo), a fake MQTT service
standing in for the printer, mocked FTPS, and an in-memory store for uploaded
files. Nothing here reaches a network.

Import the fixtures into a test module with
``from tests.fixtures.print_sends import *  # noqa: F401,F403``.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ams_slot_mapping import AMSSlotMapping
from app.models.filament_type import FilamentType
from app.models.material import MaterialType
from app.models.printer_connection import PrinterConnection
from app.models.spool import Spool
from app.schemas.ams_slot_mapping import AMSStatusFromMQTT, AMSTrayStatus
from app.services.bambu_mqtt import BambuConnectionConfig, BambuPrinterState
from app.services.print_send_service import PrintSendService
from tests.fixtures.sliced_3mf import sliced_project

ACCESS_CODE = "87654321"

# Plate 1 of the sample file: filament 1 PLA red, filament 3 PETG green.
GOOD_MAPPING = [
    {"filament_id": 1, "slot": {"kind": "ams", "ams_id": 0, "tray_id": 0}},
    {"filament_id": 3, "slot": {"kind": "ams", "ams_id": 0, "tray_id": 1}},
]
# Filament 1 (PLA) mapped to the PETG slot: a material mismatch.
WRONG_MAPPING = [
    {"filament_id": 1, "slot": {"kind": "ams", "ams_id": 0, "tray_id": 1}},
    {"filament_id": 3, "slot": {"kind": "ams", "ams_id": 0, "tray_id": 0}},
]


def tray(tray_id: int, tray_type: Optional[str], color: Optional[str]) -> AMSTrayStatus:
    return AMSTrayStatus(tray_id=tray_id, tray_type=tray_type, tray_color=color)


@dataclass
class FakeMQTT:
    """Stands in for BambuMQTTService: a printer that answers, or not."""

    state: Optional[BambuPrinterState] = None
    trays: list[AMSTrayStatus] = field(default_factory=list)
    start_ok: bool = True
    configs: dict[UUID, BambuConnectionConfig] = field(default_factory=dict)
    start_calls: list[dict[str, Any]] = field(default_factory=list)

    async def ensure_connected(
        self, config: BambuConnectionConfig, timeout: float = 10.0
    ) -> Optional[BambuPrinterState]:
        self.configs[config.printer_id] = config
        return self.state

    def get_ams_status(self, printer_id: UUID) -> list[AMSStatusFromMQTT]:
        return [AMSStatusFromMQTT(ams_id=0, trays=self.trays)] if self.trays else []

    def get_config(self, printer_id: UUID) -> Optional[BambuConnectionConfig]:
        return self.configs.get(printer_id)

    async def start_project_print(self, printer_id: UUID, **kwargs: Any) -> bool:
        self.start_calls.append({"printer_id": printer_id, **kwargs})
        return self.start_ok


def idle_state(status: str = "IDLE") -> BambuPrinterState:
    return BambuPrinterState(serial_number="01S00C123456789", is_online=True, print_status=status)


class MemoryUploads:
    """In-memory replacement for the uploaded-file store."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def save(self, tenant_id: UUID, send_id: UUID, name: str, content: bytes) -> str:
        url = f"/uploads/print-sends/{tenant_id}/{send_id}/{name}"
        self.files[url] = content
        return url

    async def read(self, url: str) -> bytes:
        return self.files[url]

    async def delete(self, url: str) -> None:
        self.files.pop(url, None)


@pytest.fixture
def fake_mqtt() -> FakeMQTT:
    return FakeMQTT(
        state=idle_state(),
        trays=[tray(0, "PLA", "FF0000FF"), tray(1, "PETG", "00FF00FF")],
    )


@pytest.fixture
def memory_uploads() -> MemoryUploads:
    return MemoryUploads()


@pytest.fixture
def ftps():
    """Mocked FTPS: ``ftps.upload`` / ``ftps.delete`` are AsyncMocks."""
    with (
        patch("app.services.print_send_service.bambu_ftps.upload", new_callable=AsyncMock) as up,
        patch(
            "app.services.print_send_service.bambu_ftps.delete",
            new_callable=AsyncMock,
            return_value=True,
        ) as delete,
    ):
        yield SimpleNamespace(upload=up, delete=delete)


@pytest.fixture
def wired(fake_mqtt: FakeMQTT, memory_uploads: MemoryUploads):
    """Route every PrintSendService to the fake MQTT and the in-memory uploads."""
    original_init = PrintSendService.__init__

    def _init(self, db, tenant, user=None, mqtt=None):  # type: ignore[no-untyped-def]
        original_init(self, db, tenant, user, mqtt or fake_mqtt)
        self.uploads = memory_uploads

    with patch.object(PrintSendService, "__init__", _init):
        yield fake_mqtt


async def _filament_type(
    db: AsyncSession, tenant_id: UUID, code: str, color: str, color_hex: str
) -> FilamentType:
    material = (
        await db.execute(select(MaterialType).where(MaterialType.code == code))
    ).scalar_one()
    ft = FilamentType(
        id=uuid4(),
        tenant_id=tenant_id,
        material_type_id=material.id,
        brand="Bambu",
        color=color,
        color_hex=color_hex,
        diameter=1.75,
        has_sample=False,
        translucent=False,
        glow=False,
    )
    db.add(ft)
    await db.flush()
    return ft


@dataclass
class BambuSetup:
    printer: Any
    connection: PrinterConnection
    pla_spool: Spool
    petg_spool: Spool


@pytest_asyncio.fixture
async def bambu_setup(
    db_session: AsyncSession, seed_material_types, test_tenant, test_printer
) -> BambuSetup:
    connection = PrinterConnection(
        tenant_id=test_tenant.id,
        printer_id=test_printer.id,
        connection_type="bambu_lan",
        serial_number="01S00C123456789",
        ip_address="192.168.1.50",
        access_code=ACCESS_CODE,
        developer_mode=True,
    )
    db_session.add(connection)
    pla = await _filament_type(db_session, test_tenant.id, "PLA", "Red", "#FF0000")
    petg = await _filament_type(db_session, test_tenant.id, "PETG", "Green", "#00FF00")
    spools = []
    for ft, label in ((pla, "SP-PLA"), (petg, "SP-PETG")):
        spool = Spool(
            id=uuid4(),
            tenant_id=test_tenant.id,
            filament_type_id=ft.id,
            spool_id=label,
            initial_weight=Decimal("1000"),
            current_weight=Decimal("800"),
            is_active=True,
            is_labeled=False,
        )
        db_session.add(spool)
        spools.append(spool)
    await db_session.flush()
    for tray_id, spool in enumerate(spools):
        db_session.add(
            AMSSlotMapping(
                tenant_id=test_tenant.id,
                printer_id=test_printer.id,
                ams_id=0,
                tray_id=tray_id,
                spool_id=spool.id,
                has_filament=True,
            )
        )
    await db_session.commit()
    return BambuSetup(test_printer, connection, spools[0], spools[1])


SAMPLE = sliced_project()
