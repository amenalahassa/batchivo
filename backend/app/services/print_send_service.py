"""Sending a sliced file to a Bambu printer, with confirmation (spec 011).

Two steps, and nothing starts a print outside them (FR-006, SC-002):

1. :meth:`PrintSendService.prepare` reads the sliced project, builds the
   summary the operator (or an agent) must see — plate time and weight, and
   per filament the slot, the spool Batchivo maps there, what the printer
   reports, and mismatch warnings — and issues a single-use confirmation
   token. It sends nothing to the printer and creates no print job (FR-002).
2. :meth:`PrintSendService.confirm` checks the token, the acknowledgement of
   warnings and the printer's live state, consumes the token **before** any
   network call, uploads the file, sends the start command, and only then
   records the print job — so a failure leaves no half-started job (FR-009).

When the print ends, :mod:`app.services.print_send_tracker` opens a spool
deduction proposal; :meth:`accept_consumption` writes it to the inventory trail
only on the operator's word (FR-020).

The printer's access code is read only through
:func:`app.services.printer_secrets.get_access_code` (spec 009 switches it to
decryption) and is never logged or returned.
"""

import hashlib
import io
import logging
import math
import re
import secrets
import zipfile
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core import clock
from app.models.ams_slot_mapping import AMSSlotMapping
from app.models.filament_type import FilamentType
from app.models.model_file import ModelFileType
from app.models.print_job import JobPriority, JobStatus, PrintJob, PrinterStatus
from app.models.print_send import ConsumptionStatus, PrintSend, PrintSendStatus
from app.models.printer import Printer
from app.models.printer_connection import PrinterConnection
from app.models.spool import Spool
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.ams_slot_mapping import AMSTrayStatus
from app.schemas.print_send import (
    AmsMapping,
    ConsumptionAcceptLine,
    ConsumptionLine,
    ConsumptionView,
    PrintJobRef,
    UserRef,
    PrintSendResponse,
)
from app.services import bambu_ftps
from app.services.bambu_mqtt import (
    EXTERNAL_SPOOL_TRAY,
    BambuConnectionConfig,
    BambuMQTTService,
    BambuPrinterState,
    get_bambu_mqtt_service,
)
from app.services.inventory_transaction import InventoryTransactionService
from app.services.model_file_service import (
    MAX_FILE_SIZE,
    ModelFileService,
    ModelFileStorageError,
    parse_3mf_metadata,
)
from app.services.printer_secrets import get_access_code

logger = logging.getLogger(__name__)

#: Printer states in which a new print must not be started (FR-011).
BUSY_STATES = frozenset({"RUNNING", "PAUSE", "PREPARE", "SLICING"})
#: RGB distance beyond which two colours are "clearly different" (research R9).
COLOR_DISTANCE_LIMIT = 80.0
#: Seconds to wait for a first status report when (re)connecting.
PREPARE_STATUS_TIMEOUT = 5
CONFIRM_STATUS_TIMEOUT = 10

#: A send still "confirming" this long after its confirmation is treated as abandoned.
CONFIRMING_STALE_AFTER = timedelta(minutes=30)

CENT = Decimal("0.01")
_PLATE_GCODE = re.compile(r"^metadata/plate_(\d+)\.gcode$", re.IGNORECASE)

WARNING_MESSAGES = {
    "material_mismatch": "Plate expects {expected}, the spool mapped to this slot is {actual}",
    "color_mismatch": "Plate expects colour {expected}, the spool mapped here is {actual}",
    "empty_slot": "The printer reports this slot as empty",
    "unknown_spool": "No spool is recorded in Batchivo for this slot",
    "reported_mismatch": "The printer reports {actual} in this slot, the plate expects {expected}",
}


class PrintSendError(Exception):
    """A refusal with an HTTP status and a stable code (contracts/print-send-api.md)."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


# ============================================
# Mismatch rules (research R9) — pure functions
# ============================================


def material_key(material: Optional[str]) -> Optional[str]:
    """Material family for comparison: first word, upper case (``PLA``, ``PETG``, ``PLA-CF``)."""
    if not material or not material.strip():
        return None
    return material.strip().split()[0].upper()


def _rgb(color: Optional[str]) -> Optional[tuple[int, int, int]]:
    if not color:
        return None
    text = color.strip().lstrip("#")
    if len(text) < 6:
        return None
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError:
        return None


def normalize_color(color: Optional[str]) -> Optional[str]:
    """``#RRGGBB`` upper case, or None when unreadable."""
    rgb = _rgb(color)
    return None if rgb is None else "#{:02X}{:02X}{:02X}".format(*rgb)


def colors_differ(a: Optional[str], b: Optional[str]) -> bool:
    """True when both colours are known and their RGB distance exceeds the limit."""
    first, second = _rgb(a), _rgb(b)
    if first is None or second is None:
        return False
    return math.dist(first, second) > COLOR_DISTANCE_LIMIT


@dataclass(frozen=True)
class SlotFacts:
    """What is known about one mapped slot, from Batchivo and from the printer."""

    kind: str  # "ams" | "external"
    spool_known: bool
    spool_material: Optional[str] = None
    spool_color: Optional[str] = None
    reported_present: Optional[bool] = None  # None: printer report unknown
    reported_type: Optional[str] = None
    reported_color: Optional[str] = None


def line_warnings(
    expected_type: Optional[str], expected_color: Optional[str], facts: SlotFacts
) -> list[str]:
    """Warning codes for one filament mapped to one slot."""
    if facts.kind == "external":
        return []  # No AMS check for the external spool holder
    warnings: list[str] = []
    expected_key = material_key(expected_type)
    if not facts.spool_known:
        warnings.append("unknown_spool")
    else:
        spool_key = material_key(facts.spool_material)
        if expected_key and spool_key and expected_key != spool_key:
            warnings.append("material_mismatch")
        if colors_differ(expected_color, facts.spool_color):
            warnings.append("color_mismatch")
    if facts.reported_present is False:
        warnings.append("empty_slot")
    elif facts.reported_present:
        reported_key = material_key(facts.reported_type)
        if (expected_key and reported_key and expected_key != reported_key) or colors_differ(
            expected_color, facts.reported_color
        ):
            warnings.append("reported_mismatch")
    return warnings


def hash_token(token: str) -> str:
    """SHA-256 hex of a confirmation token (only the hash is stored)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def plate_gcodes(content: bytes) -> list[int]:
    """Plate numbers that carry G-code in a sliced project; empty when not sliced."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            plates = [
                int(match.group(1)) for name in zf.namelist() if (match := _PLATE_GCODE.match(name))
            ]
    except zipfile.BadZipFile:
        return []
    return sorted(set(plates))


def command_ams_mapping(entries: list[dict[str, Any]]) -> list[int]:
    """The start command's ``ams_mapping`` list from stored mapping entries (research R2)."""
    size = max(int(e["filament_id"]) for e in entries)
    mapping = [-1] * size
    for entry in entries:
        slot = entry["slot"]
        if slot["kind"] == "external":
            value = EXTERNAL_SPOOL_TRAY
        else:
            value = int(slot["ams_id"]) * 4 + int(slot["tray_id"])
        mapping[int(entry["filament_id"]) - 1] = value
    return mapping


def _grams(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(str(value)).quantize(CENT)


def _gstr(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else f"{value:.2f}"


def _slot_label(slot: dict[str, Any]) -> str:
    if slot["kind"] == "external":
        return "External spool"
    return f"AMS {int(slot['ams_id']) + 1} · slot {int(slot['tray_id']) + 1}"


# ============================================
# Uploaded files (research R8)
# ============================================


class _UploadStore:
    """Uploaded sliced files kept for the life of a send, in the model-file storage."""

    def __init__(self, files: ModelFileService) -> None:
        self._files = files

    async def save(self, tenant_id: UUID, send_id: UUID, name: str, content: bytes) -> str:
        directory = f"print-sends/{tenant_id}/{send_id}"
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[-120:] or "upload.gcode.3mf"
        if self._files.storage_type == "local":
            return await self._files._save_local(content, directory, safe_name)
        return await self._files._save_s3(content, directory, safe_name, "model/3mf")

    async def read(self, url: str) -> bytes:
        if self._files.storage_type == "local":
            return await self._files._get_local(url)
        return await self._files._get_s3(url)

    async def delete(self, url: str) -> None:
        if self._files.storage_type == "local":
            await self._files._delete_local(url)
        else:
            await self._files._delete_s3(url)


# ============================================
# Service
# ============================================


class PrintSendService:
    """Prepare, confirm and follow up print sends for one tenant."""

    def __init__(
        self,
        db: AsyncSession,
        tenant: Tenant,
        user: Optional[User] = None,
        mqtt: Optional[BambuMQTTService] = None,
    ) -> None:
        self.db = db
        self.tenant = tenant
        self.user = user
        self.mqtt = mqtt or get_bambu_mqtt_service()
        self.files = ModelFileService(db, tenant, user)
        self.uploads = _UploadStore(self.files)

    # ---------- loading ----------

    async def _printer(self, printer_id: UUID) -> Printer:
        printer = (
            await self.db.execute(
                select(Printer).where(Printer.id == printer_id, Printer.tenant_id == self.tenant.id)
            )
        ).scalar_one_or_none()
        if printer is None:
            raise PrintSendError(404, "printer_not_found", "Printer not found")
        return printer

    async def _connection(self, printer_id: UUID) -> PrinterConnection:
        connection = (
            await self.db.execute(
                select(PrinterConnection).where(
                    PrinterConnection.printer_id == printer_id,
                    PrinterConnection.tenant_id == self.tenant.id,
                )
            )
        ).scalar_one_or_none()
        if connection is None or not connection.can_send_prints:
            raise PrintSendError(
                409,
                "send_not_available",
                "Sending prints needs a Bambu LAN connection with Developer Mode on",
            )
        return connection

    def _config(self, printer_id: UUID, connection: PrinterConnection) -> BambuConnectionConfig:
        access_code = get_access_code(connection)
        if not (connection.serial_number and connection.ip_address and access_code):
            raise PrintSendError(
                409,
                "send_not_available",
                "The connection needs a serial number, an IP address and an access code",
            )
        return BambuConnectionConfig(
            printer_id=printer_id,
            serial_number=connection.serial_number,
            ip_address=connection.ip_address,
            port=connection.port,
            access_code=access_code,
            tenant_id=self.tenant.id,
        )

    async def _send(self, printer_id: UUID, send_id: UUID, *, lock: bool = False) -> PrintSend:
        query = select(PrintSend).where(
            PrintSend.id == send_id,
            PrintSend.printer_id == printer_id,
            PrintSend.tenant_id == self.tenant.id,
        )
        if lock:
            query = query.with_for_update()
        send = (await self.db.execute(query)).scalar_one_or_none()
        if send is None:
            raise PrintSendError(404, "send_not_found", "Print send not found")
        return send

    async def _slot_spools(self, printer_id: UUID) -> dict[tuple[int, int], Optional[Spool]]:
        rows = (
            await self.db.execute(
                select(AMSSlotMapping)
                .where(
                    AMSSlotMapping.printer_id == printer_id,
                    AMSSlotMapping.tenant_id == self.tenant.id,
                )
                .options(
                    selectinload(AMSSlotMapping.spool)
                    .selectinload(Spool.filament_type)
                    .selectinload(FilamentType.material_type)
                )
            )
        ).scalars()
        return {(row.ams_id, row.tray_id): row.spool for row in rows}

    async def _live_state(
        self, printer_id: UUID, connection: PrinterConnection, timeout: int
    ) -> Optional[BambuPrinterState]:
        try:
            config = self._config(printer_id, connection)
        except PrintSendError:
            return None
        try:
            return await self.mqtt.ensure_connected(config, timeout=timeout)
        except Exception as e:
            logger.warning(f"Could not reach printer {printer_id} over MQTT: {type(e).__name__}")
            return None

    # ---------- prepare ----------

    async def prepare(
        self,
        printer_id: UUID,
        *,
        plate: int,
        mapping: AmsMapping,
        model_file_id: Optional[UUID] = None,
        upload_name: Optional[str] = None,
        upload_content: Optional[bytes] = None,
        attach_to_model_id: Optional[UUID] = None,
    ) -> tuple[PrintSend, str]:
        """Build and store the summary of a send; return it with its confirmation token."""
        printer = await self._printer(printer_id)
        connection = await self._connection(printer_id)

        has_upload = upload_content is not None
        if (model_file_id is None) == (not has_upload):
            raise PrintSendError(
                422, "invalid_source", "Give either a stored model file or an uploaded file"
            )
        if attach_to_model_id is not None and not has_upload:
            raise PrintSendError(
                422, "invalid_source", "attach_to_model_id only applies to an uploaded file"
            )

        model_id: Optional[UUID] = None
        if model_file_id is not None:
            model_file = await self.files.get_file(model_file_id)
            if model_file is None:
                raise PrintSendError(404, "model_file_not_found", "Model file not found")
            try:
                content, _, file_name = await self.files.get_file_content(model_file_id)
            except ModelFileStorageError as e:
                raise PrintSendError(404, "model_file_not_found", str(e)) from None
            model_id = model_file.model_id
        else:
            content = upload_content or b""
            file_name = (upload_name or "upload.gcode.3mf").strip()
            if len(content) > MAX_FILE_SIZE:
                raise PrintSendError(413, "file_too_large", "The file is larger than 500 MB")
            if not file_name.lower().endswith(".3mf"):
                raise PrintSendError(422, "not_sliced", "Send a sliced Bambu project (.gcode.3mf)")

        lines, plate_view, entries = self._read_plate(content, plate, mapping)

        if has_upload and attach_to_model_id is not None:
            try:
                stored = await self.files.upload_file(
                    model_id=attach_to_model_id,
                    file_content=content,
                    content_type="model/3mf",
                    original_filename=file_name,
                    file_type=ModelFileType.GCODE,
                )
            except ModelFileStorageError as e:
                raise PrintSendError(404, "model_not_found", str(e)) from None
            model_file_id, model_id = stored.id, stored.model_id

        state = await self._live_state(printer_id, connection, PREPARE_STATUS_TIMEOUT)
        lines, warnings, blockers = await self._assess(printer_id, lines, state)

        now = clock.now()
        token = secrets.token_urlsafe(32)
        send_id = uuid4()
        send = PrintSend(
            id=send_id,
            tenant_id=self.tenant.id,
            printer_id=printer_id,
            prepared_by_user_id=self.user.id if self.user else None,
            model_id=model_id,
            model_file_id=model_file_id,
            file_name=file_name[:255],
            file_size=len(content),
            file_md5=hashlib.md5(content).hexdigest(),  # noqa: S324 — printer protocol field
            remote_file_name=f"batchivo-{send_id.hex[:8]}.gcode.3mf",
            plate_index=plate,
            ams_mapping=entries,
            summary={
                "printer": {"id": str(printer.id), "name": printer.name},
                "file": {
                    "name": file_name,
                    "model_id": str(model_id) if model_id else None,
                    "model_file_id": str(model_file_id) if model_file_id else None,
                },
                "plate": plate_view,
                "lines": lines,
                "warnings": warnings,
                "blockers": blockers,
            },
            warning_count=len(warnings),
            token_hash=hash_token(token),
            expires_at=now + timedelta(seconds=get_settings().print_send_confirm_window_seconds),
            status=PrintSendStatus.PREPARED.value,
        )
        if has_upload and model_file_id is None:
            send.upload_url = await self.uploads.save(self.tenant.id, send_id, file_name, content)
        self.db.add(send)
        await self._clean_expired_uploads(now)
        await self.db.commit()
        await self.db.refresh(send)
        logger.info(
            f"Prepared print send {send.id} for printer {printer_id}: plate {plate}, "
            f"{len(warnings)} warning(s), {len(blockers)} blocker(s)"
        )
        return send, token

    def _read_plate(
        self, content: bytes, plate: int, mapping: AmsMapping
    ) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
        """Plate summary and lines from the sliced file, validated against the mapping."""
        plates = plate_gcodes(content)
        if not plates:
            raise PrintSendError(
                422, "not_sliced", "The file is not a sliced project: slice it in Bambu Studio"
            )
        if plate not in plates:
            raise PrintSendError(
                422,
                "plate_not_found",
                f"Plate {plate} is not in the file; available plates: "
                + ", ".join(str(p) for p in plates),
            )
        metadata = parse_3mf_metadata(content)
        plate_meta = next((p for p in metadata.plates if p.index == plate), None)
        if plate_meta is None or not plate_meta.filaments:
            raise PrintSendError(
                422, "no_plate_metadata", "The file carries no Bambu slicing data for this plate"
            )
        if any(f.id is None for f in plate_meta.filaments):
            raise PrintSendError(
                422,
                "filament_without_id",
                "The plate's filaments are not numbered: re-slice with Bambu Studio",
            )
        expected_ids = {f.id for f in plate_meta.filaments}
        given = {e.filament_id: e for e in mapping.entries}
        if set(given) != expected_ids:
            raise PrintSendError(
                422,
                "mapping_mismatch",
                "Map exactly the plate's filaments: "
                + ", ".join(str(i) for i in sorted(expected_ids)),
            )

        lines: list[dict[str, Any]] = []
        entries: list[dict[str, Any]] = []
        for filament in plate_meta.filaments:
            slot = given[filament.id].slot.model_dump()
            entries.append({"filament_id": filament.id, "slot": slot})
            slot_view = {
                "kind": slot["kind"],
                "ams_id": slot.get("ams_id"),
                "tray_id": slot.get("tray_id"),
                "label": _slot_label(slot),
            }
            lines.append(
                {
                    "filament_id": filament.id,
                    "expected": {
                        "type": filament.type,
                        "color": normalize_color(filament.color),
                        "grams": _gstr(_grams(filament.grams)),
                    },
                    "slot": slot_view,
                    "mapped_spool": None,
                    "reported": None,
                    "warnings": [],
                }
            )
        plate_view = {
            "index": plate,
            "print_time_minutes": plate_meta.print_time_minutes,
            "filament_weight_grams": _gstr(_grams(plate_meta.filament_weight_grams)),
        }
        return lines, plate_view, entries

    async def _assess(
        self,
        printer_id: UUID,
        lines: list[dict[str, Any]],
        state: Optional[BambuPrinterState],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Fill mapped spool, printer report and warnings on each line."""
        spools = await self._slot_spools(printer_id)
        trays: dict[tuple[int, int], AMSTrayStatus] = {}
        blockers: list[dict[str, Any]] = []
        if state is None or not state.is_online:
            blockers.append(
                {
                    "code": "printer_unreachable",
                    "message": "The printer is not reachable; it must be online to start",
                    "filament_id": None,
                }
            )
        else:
            for unit in self.mqtt.get_ams_status(printer_id):
                for tray in unit.trays:
                    trays[(unit.ams_id, tray.tray_id)] = tray
            if (state.print_status or "").upper() in BUSY_STATES:
                blockers.append(
                    {
                        "code": "printer_busy",
                        "message": f"The printer is busy ({state.print_status})",
                        "filament_id": None,
                    }
                )

        warnings: list[dict[str, Any]] = []
        for line in lines:
            slot = line["slot"]
            expected = line["expected"]
            spool: Optional[Spool] = None
            tray: Optional[AMSTrayStatus] = None
            if slot["kind"] == "ams":
                key = (slot["ams_id"], slot["tray_id"])
                spool = spools.get(key)
                tray = trays.get(key)
            spool_material = spool_color = None
            if spool is not None:
                filament_type = spool.filament_type
                spool_material = (
                    filament_type.material_type.code
                    if filament_type and filament_type.material_type
                    else None
                )
                spool_color = normalize_color(filament_type.color_hex if filament_type else None)
                line["mapped_spool"] = {
                    "id": str(spool.id),
                    "spool_id": spool.spool_id,
                    "material": spool_material,
                    "color": spool_color,
                    "current_weight": _gstr(_grams(spool.current_weight)),
                }
            reported_present: Optional[bool] = None
            if slot["kind"] == "ams" and state is not None and state.is_online:
                reported_present = bool(tray is not None and tray.tray_type)
                line["reported"] = {
                    "type": tray.tray_type if tray else None,
                    "color": normalize_color(tray.tray_color) if tray else None,
                    "present": reported_present,
                }
            facts = SlotFacts(
                kind=slot["kind"],
                spool_known=spool is not None,
                spool_material=spool_material,
                spool_color=spool_color,
                reported_present=reported_present,
                reported_type=tray.tray_type if tray else None,
                reported_color=tray.tray_color if tray else None,
            )
            codes = line_warnings(expected["type"], expected["color"], facts)
            line["warnings"] = codes
            for code in codes:
                actual = {
                    "material_mismatch": spool_material,
                    "color_mismatch": spool_color,
                    "reported_mismatch": (tray.tray_type if tray else None),
                }.get(code)
                expected_text = expected["color"] if code == "color_mismatch" else expected["type"]
                warnings.append(
                    {
                        "code": code,
                        "message": WARNING_MESSAGES[code].format(
                            expected=expected_text or "?", actual=actual or "?"
                        ),
                        "filament_id": line["filament_id"],
                    }
                )
        return lines, warnings, blockers

    async def _clean_expired_uploads(self, now: Any) -> None:
        """Delete stored uploads of this tenant's expired, unconfirmed sends (research R8)."""
        expired = (
            await self.db.execute(
                select(PrintSend).where(
                    PrintSend.tenant_id == self.tenant.id,
                    PrintSend.status == PrintSendStatus.PREPARED.value,
                    PrintSend.expires_at < now,
                    PrintSend.upload_url.is_not(None),
                )
            )
        ).scalars()
        for send in expired:
            await self._drop_upload(send)

    async def _drop_upload(self, send: PrintSend) -> None:
        if not send.upload_url:
            return
        try:
            await self.uploads.delete(send.upload_url)
        except Exception as e:
            logger.warning(f"Could not delete uploaded file of print send {send.id}: {e}")
        send.upload_url = None

    # ---------- confirm ----------

    async def confirm(
        self, printer_id: UUID, token: str, *, acknowledge_warnings: bool
    ) -> PrintSend:
        """Start the print of a prepared summary (FR-006, FR-008, FR-009)."""
        send = (
            await self.db.execute(
                select(PrintSend)
                .where(
                    PrintSend.token_hash == hash_token(token),
                    PrintSend.printer_id == printer_id,
                    PrintSend.tenant_id == self.tenant.id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if send is None:
            raise PrintSendError(
                404, "send_not_found", "No prepared send matches this confirmation"
            )
        if send.status != PrintSendStatus.PREPARED.value:
            raise PrintSendError(409, "send_already_used", "This confirmation was already used")
        if send.is_expired(clock.now()):
            raise PrintSendError(
                410, "send_expired", "The confirmation window has passed: prepare again"
            )
        if send.warning_count > 0 and not acknowledge_warnings:
            raise PrintSendError(
                409,
                "acknowledgement_required",
                "The summary has warnings: acknowledge them to start the print",
            )

        connection = await self._connection(printer_id)
        config = self._config(printer_id, connection)
        try:
            state = await self.mqtt.ensure_connected(config, timeout=CONFIRM_STATUS_TIMEOUT)
        except Exception as e:
            logger.warning(f"Could not reach printer {printer_id} over MQTT: {type(e).__name__}")
            state = None
        if state is None:
            raise PrintSendError(503, "printer_unreachable", "The printer is not reachable")
        if (state.print_status or "").upper() in BUSY_STATES:
            raise PrintSendError(409, "printer_busy", f"The printer is busy ({state.print_status})")
        if await self._send_in_flight(printer_id, send.id):
            # The printer's last report can lag a start by a few seconds: a send already
            # confirming or printing on this printer wins over a second confirmation.
            raise PrintSendError(
                409, "printer_busy", "The printer is busy with another print sent from Batchivo"
            )

        # Consume the token before any network call: it can start at most one print.
        send.status = PrintSendStatus.CONFIRMING.value
        send.confirmed_at = clock.now()
        send.confirmed_by_user_id = self.user.id if self.user else None
        send.warnings_acknowledged = bool(acknowledge_warnings and send.warning_count > 0)
        await self.db.commit()

        try:
            content = await self._content(send)
            await bambu_ftps.upload(
                config.ip_address, config.access_code, send.remote_file_name, content
            )
        except (bambu_ftps.BambuFileTransferError, ModelFileStorageError) as e:
            return await self._fail(
                send, PrintSendStatus.TRANSFER_FAILED, "transfer_failed", str(e)
            )

        try:
            started = await self.mqtt.start_project_print(
                printer_id,
                remote_file_name=send.remote_file_name,
                plate_index=send.plate_index,
                ams_mapping=command_ams_mapping(send.ams_mapping),
                md5=send.file_md5,
            )
        except Exception as e:
            logger.warning(f"Start command for print send {send.id} raised {type(e).__name__}")
            started = False
        if not started:
            await bambu_ftps.delete(config.ip_address, config.access_code, send.remote_file_name)
            return await self._fail(
                send,
                PrintSendStatus.START_FAILED,
                "start_failed",
                "The printer did not accept the start command",
            )

        job = await self._record_job(send)
        await self._drop_upload(send)
        await self.db.commit()
        await self.db.refresh(send)
        logger.info(f"Started print send {send.id} on printer {printer_id} as job {job.id}")
        return send

    async def _send_in_flight(self, printer_id: UUID, excluding: UUID) -> bool:
        """True when another send on this printer is confirming or its job still prints."""
        query = (
            select(PrintSend.id)
            .outerjoin(PrintJob, PrintJob.id == PrintSend.print_job_id)
            .where(
                PrintSend.printer_id == printer_id,
                PrintSend.tenant_id == self.tenant.id,
                PrintSend.id != excluding,
                or_(
                    # A send left confirming by a crash stops counting after a while, so it
                    # cannot block the printer for good.
                    and_(
                        PrintSend.status == PrintSendStatus.CONFIRMING.value,
                        PrintSend.confirmed_at > clock.now() - CONFIRMING_STALE_AFTER,
                    ),
                    and_(
                        PrintSend.status == PrintSendStatus.STARTED.value,
                        PrintJob.status == JobStatus.PRINTING,
                    ),
                ),
            )
            .limit(1)
        )
        return (await self.db.execute(query)).first() is not None

    async def _content(self, send: PrintSend) -> bytes:
        if send.upload_url:
            return await self.uploads.read(send.upload_url)
        if send.model_file_id is None:
            raise ModelFileStorageError("The file of this send is no longer available")
        content, _, _ = await self.files.get_file_content(send.model_file_id)
        return content

    async def _fail(
        self, send: PrintSend, status: PrintSendStatus, code: str, message: str
    ) -> PrintSend:
        send.status = status.value
        send.error_message = message
        await self._drop_upload(send)
        await self.db.commit()
        logger.warning(f"Print send {send.id} failed ({code}): {message}")
        raise PrintSendError(502, code, message)

    async def _record_job(self, send: PrintSend) -> PrintJob:
        now = clock.now()
        minutes = (send.summary.get("plate") or {}).get("print_time_minutes")
        job = PrintJob(
            id=uuid4(),
            tenant_id=self.tenant.id,
            model_id=send.model_id,
            quantity=1,
            priority=JobPriority.NORMAL,
            status=JobStatus.PRINTING,
            assigned_printer_id=send.printer_id,
            started_at=now,
            estimated_duration_hours=(
                (Decimal(minutes) / Decimal(60)).quantize(CENT) if minutes else None
            ),
            reference=f"print-send {send.id}"[:100],
            notes=f"Sent {send.file_name}, plate {send.plate_index}",
        )
        self.db.add(job)
        await self.db.flush()
        printer = await self._printer(send.printer_id)
        printer.current_status = PrinterStatus.PRINTING.value
        printer.current_job_id = job.id
        send.status = PrintSendStatus.STARTED.value
        send.print_job_id = job.id
        send.error_message = None
        return job

    # ---------- reads ----------

    async def list_sends(self, printer_id: UUID, limit: int = 20) -> list[PrintSend]:
        await self._printer(printer_id)
        return list(
            (
                await self.db.execute(
                    select(PrintSend)
                    .where(
                        PrintSend.printer_id == printer_id,
                        PrintSend.tenant_id == self.tenant.id,
                    )
                    .order_by(PrintSend.created_at.desc())
                    .limit(limit)
                )
            ).scalars()
        )

    async def get_send(self, printer_id: UUID, send_id: UUID) -> PrintSend:
        return await self._send(printer_id, send_id)

    # ---------- spool deduction proposal (FR-020) ----------

    async def accept_consumption(
        self, printer_id: UUID, send_id: UUID, lines: list[ConsumptionAcceptLine]
    ) -> PrintSend:
        send = await self._send(printer_id, send_id, lock=True)
        if send.consumption_status != ConsumptionStatus.PENDING.value:
            raise PrintSendError(
                409, "consumption_not_pending", "There is no pending deduction for this print"
            )
        proposal = {int(line["filament_id"]): dict(line) for line in send.consumption_lines or []}
        seen: set[int] = set()
        for line in lines:
            if line.filament_id not in proposal or line.filament_id in seen:
                raise PrintSendError(
                    422, "unknown_filament", f"Filament {line.filament_id} is not in this proposal"
                )
            seen.add(line.filament_id)

        # Every spool is checked before anything is written: all lines or none.
        spools: dict[UUID, Spool] = {}
        for line in lines:
            spool = (
                await self.db.execute(
                    select(Spool).where(
                        Spool.id == line.spool_id, Spool.tenant_id == self.tenant.id
                    )
                )
            ).scalar_one_or_none()
            if spool is None:
                raise PrintSendError(422, "spool_not_found", "Spool not found")
            spools[line.spool_id] = spool

        inventory = InventoryTransactionService(self.db, self.tenant, self.user)
        for line in lines:
            spool = spools[line.spool_id]
            grams = line.grams.quantize(CENT)
            transaction = await inventory.create_print_usage_transaction(
                spool=spool,
                weight_used=grams,
                print_job_id=send.print_job_id,
                print_send_id=send.id,
            )
            entry = proposal[line.filament_id]
            entry["spool_id"] = str(spool.id)
            entry["accepted_grams"] = _gstr(grams)
            entry["transaction_id"] = str(transaction.id)

        send.consumption_lines = list(proposal.values())
        send.consumption_status = ConsumptionStatus.ACCEPTED.value
        send.consumption_decided_at = clock.now()
        send.consumption_decided_by_user_id = self.user.id if self.user else None
        await self.db.commit()
        await self.db.refresh(send)
        logger.info(f"Accepted spool deduction of print send {send.id} ({len(lines)} spool(s))")
        return send

    async def dismiss_consumption(self, printer_id: UUID, send_id: UUID) -> PrintSend:
        send = await self._send(printer_id, send_id, lock=True)
        if send.consumption_status != ConsumptionStatus.PENDING.value:
            raise PrintSendError(
                409, "consumption_not_pending", "There is no pending deduction for this print"
            )
        send.consumption_status = ConsumptionStatus.DISMISSED.value
        send.consumption_decided_at = clock.now()
        send.consumption_decided_by_user_id = self.user.id if self.user else None
        await self.db.commit()
        await self.db.refresh(send)
        return send


# ============================================
# Responses
# ============================================


def summary_fields(send: PrintSend) -> dict[str, Any]:
    """The summary part of a response, from the stored snapshot."""
    summary = send.summary or {}
    return {
        "id": send.id,
        "status": send.status,
        "expires_at": send.expires_at,
        "printer": summary.get("printer"),
        "file": summary.get("file"),
        "plate": summary.get("plate"),
        "lines": summary.get("lines", []),
        "warnings": summary.get("warnings", []),
        "blockers": summary.get("blockers", []),
        "requires_acknowledgement": send.warning_count > 0,
    }


def to_response(send: PrintSend) -> PrintSendResponse:
    """A send as returned by reads (never the token)."""
    job = send.print_job
    return PrintSendResponse(
        **summary_fields(send),
        created_at=send.created_at,
        confirmed_at=send.confirmed_at,
        confirmed_by=(
            UserRef(
                id=send.confirmed_by.id, name=send.confirmed_by.full_name or send.confirmed_by.email
            )
            if send.confirmed_by is not None
            else None
        ),
        warnings_acknowledged=send.warnings_acknowledged,
        error_message=send.error_message,
        print_job=(
            PrintJobRef(
                id=job.id,
                status=job.status.value if hasattr(job.status, "value") else str(job.status),
                started_at=job.started_at,
                completed_at=job.completed_at,
            )
            if job is not None
            else None
        ),
        consumption=ConsumptionView(
            status=send.consumption_status,  # type: ignore[arg-type]
            lines=[ConsumptionLine(**line) for line in send.consumption_lines or []],
            decided_at=send.consumption_decided_at,
        ),
    )
