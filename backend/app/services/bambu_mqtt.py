"""
Bambu Lab MQTT Service for printer communication.

This service handles all MQTT communication with Bambu Lab printers including:
- Connection management (connect, disconnect, reconnect)
- Status message parsing (print progress, temperatures, AMS)
- AMS slot tracking and spool mapping
- Command sending (pause, resume, stop, start a sliced project — spec 011)

Based on community-documented Bambu MQTT protocol:
- Local LAN: mqtt://{printer_ip}:8883 (TLS, username=bblp, password=access_code)
- Topics: device/{serial}/report (status), device/{serial}/request (commands)
"""

import asyncio
import json
import logging
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import UUID

import paho.mqtt.client as mqtt

from app.schemas.ams_slot_mapping import AMSStatusFromMQTT, AMSTrayStatus
from app.schemas.printer_connection import BambuPrinterStatus

logger = logging.getLogger(__name__)

#: Global tray index the start command uses for the external spool holder.
EXTERNAL_SPOOL_TRAY = 254
#: ``print_error`` a printer reports when its print was cancelled.
PRINT_ERROR_CANCELLED = 50348044


@dataclass
class BambuConnectionConfig:
    """Configuration for Bambu printer MQTT connection."""

    printer_id: UUID
    serial_number: str
    ip_address: str
    port: int = 8883
    access_code: str = ""
    use_tls: bool = True
    # Tenant of the printer, so status listeners can open a tenant-scoped session
    tenant_id: Optional[UUID] = None


@dataclass
class BambuPrinterState:
    """Current state of a connected Bambu printer."""

    serial_number: str
    is_online: bool = False
    last_seen_at: Optional[datetime] = None

    # Print progress
    print_status: Optional[str] = None  # RUNNING, PAUSED, IDLE, FINISH, etc.
    print_percentage: int = 0
    current_layer: int = 0
    total_layers: int = 0
    remaining_time_seconds: int = 0
    current_file: Optional[str] = None
    subtask_name: Optional[str] = None

    # Temperatures
    nozzle_temp: float = 0.0
    nozzle_target_temp: float = 0.0
    bed_temp: float = 0.0
    bed_target_temp: float = 0.0
    chamber_temp: float = 0.0

    # AMS state
    ams_units: list[dict[str, Any]] = field(default_factory=list)
    tray_now: int = 255  # Currently active tray (255 = none)
    ams_exist_bits: str = "0"
    tray_exist_bits: str = "0"
    tray_is_bbl_bits: str = "0"

    # Error state
    hms_errors: list[dict[str, Any]] = field(default_factory=list)
    print_error: int = 0  # Bambu print_error code (50348044 = task cancelled)


class BambuMQTTService:
    """
    Service for managing MQTT connections to Bambu Lab printers.

    Handles connection lifecycle, message parsing, and state tracking.
    Can manage multiple printer connections simultaneously.
    """

    def __init__(self) -> None:
        """Initialize the MQTT service."""
        self._connections: dict[UUID, mqtt.Client] = {}
        self._states: dict[UUID, BambuPrinterState] = {}
        self._configs: dict[UUID, BambuConnectionConfig] = {}
        self._callbacks: dict[str, list[Callable]] = {
            "status_update": [],
            "ams_update": [],
            "print_progress": [],
            "error": [],
            "connected": [],
            "disconnected": [],
        }
        self._sequence_id: int = 0
        self._lock = asyncio.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def register_callback(self, event: str, callback: Callable) -> None:
        """Register a callback for a specific event type."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def unregister_callback(self, event: str, callback: Callable) -> None:
        """Unregister a callback."""
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)

    async def _emit_event(self, event: str, *args: Any, **kwargs: Any) -> None:
        """Emit an event to all registered callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(*args, **kwargs)
                else:
                    callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in callback for event {event}: {e}")

    def _schedule(self, coro: Any) -> None:
        """Run a coroutine on the service's event loop from paho's network thread.

        paho calls its callbacks from its own thread, where no event loop runs;
        ``asyncio.create_task`` there raises and the message is lost. The loop
        captured in :meth:`connect` is the one the coroutines must run on.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            coro.close()
            logger.warning("Dropped an MQTT event: no event loop captured")
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            loop.create_task(coro)
        else:
            asyncio.run_coroutine_threadsafe(coro, loop)

    def _get_next_sequence_id(self) -> str:
        """Get next sequence ID for MQTT commands."""
        self._sequence_id += 1
        return str(self._sequence_id)

    async def connect(self, config: BambuConnectionConfig) -> bool:
        """
        Connect to a Bambu printer via MQTT.

        Args:
            config: Connection configuration

        Returns:
            True if connection initiated successfully, False otherwise
        """
        self._loop = asyncio.get_running_loop()
        # Disconnect existing connection if any (outside the lock: disconnect takes it)
        if config.printer_id in self._connections:
            await self.disconnect(config.printer_id)

        async with self._lock:
            printer_id = config.printer_id

            try:
                # Create MQTT client
                client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"batchivo_{config.serial_number}_{printer_id.hex[:8]}",
                    protocol=mqtt.MQTTv311,
                )

                # Set credentials
                client.username_pw_set("bblp", config.access_code)

                # Configure TLS (Bambu uses self-signed certs)
                if config.use_tls:
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                    client.tls_set_context(ssl_context)

                # Set up callbacks
                client.on_connect = lambda c, u, f, rc, p: self._schedule(
                    self._on_connect(printer_id, rc)
                )
                client.on_disconnect = lambda c, u, d, rc, p: self._schedule(
                    self._on_disconnect(printer_id, rc)
                )
                client.on_message = lambda c, u, msg: self._schedule(
                    self._on_message(printer_id, msg)
                )

                # Store config and initialize state
                self._configs[printer_id] = config
                self._states[printer_id] = BambuPrinterState(serial_number=config.serial_number)
                self._connections[printer_id] = client

                # Connect (non-blocking)
                client.connect_async(config.ip_address, config.port, keepalive=60)
                client.loop_start()

                logger.info(
                    f"Initiated connection to Bambu printer {config.serial_number} "
                    f"at {config.ip_address}:{config.port}"
                )
                return True

            except Exception as e:
                logger.error(f"Failed to connect to Bambu printer: {e}")
                return False

    async def disconnect(self, printer_id: UUID) -> None:
        """Disconnect from a Bambu printer."""
        async with self._lock:
            if printer_id in self._connections:
                client = self._connections[printer_id]
                client.loop_stop()
                client.disconnect()
                del self._connections[printer_id]

            if printer_id in self._states:
                del self._states[printer_id]

            if printer_id in self._configs:
                del self._configs[printer_id]

            logger.info(f"Disconnected from Bambu printer {printer_id}")

    async def _on_connect(self, printer_id: UUID, rc: int) -> None:
        """Handle MQTT connection established."""
        if rc == 0:
            config = self._configs.get(printer_id)
            if config and printer_id in self._connections:
                client = self._connections[printer_id]
                serial = config.serial_number

                # Subscribe to printer reports
                topic = f"device/{serial}/report"
                client.subscribe(topic)
                logger.info(f"Connected to Bambu printer {serial}, subscribed to {topic}")

                # Update state
                if printer_id in self._states:
                    self._states[printer_id].is_online = True
                    self._states[printer_id].last_seen_at = datetime.now(timezone.utc)

                # Request full status
                await self.request_full_status(printer_id)

                await self._emit_event("connected", printer_id)
        else:
            logger.error(f"Bambu MQTT connection failed with code {rc}")
            await self._emit_event("error", printer_id, f"Connection failed: {rc}")

    async def _on_disconnect(self, printer_id: UUID, rc: int) -> None:
        """Handle MQTT disconnection."""
        if printer_id in self._states:
            self._states[printer_id].is_online = False

        if rc != 0:
            logger.warning(f"Unexpected disconnect from Bambu printer {printer_id}: {rc}")
        else:
            logger.info(f"Disconnected from Bambu printer {printer_id}")

        await self._emit_event("disconnected", printer_id, rc)

    async def _on_message(self, printer_id: UUID, msg: mqtt.MQTTMessage) -> None:
        """Handle incoming MQTT messages."""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            await self._process_status_message(printer_id, payload)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse MQTT message: {e}")
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")

    async def _process_status_message(self, printer_id: UUID, payload: dict[str, Any]) -> None:
        """Process a status message from the printer."""
        if printer_id not in self._states:
            return

        state = self._states[printer_id]
        state.last_seen_at = datetime.now(timezone.utc)

        # Extract print data if present
        if "print" in payload:
            print_data = payload["print"]
            await self._update_print_status(state, print_data)
            await self._update_ams_status(printer_id, state, print_data)

        await self._emit_event("status_update", printer_id, state)

    async def _update_print_status(
        self, state: BambuPrinterState, print_data: dict[str, Any]
    ) -> None:
        """Update print status from MQTT data."""
        # Print state
        if "gcode_state" in print_data:
            state.print_status = print_data["gcode_state"]

        # Progress
        if "mc_percent" in print_data:
            state.print_percentage = int(print_data["mc_percent"])

        if "layer_num" in print_data:
            state.current_layer = int(print_data["layer_num"])

        if "total_layer_num" in print_data:
            state.total_layers = int(print_data["total_layer_num"])

        if "mc_remaining_time" in print_data:
            state.remaining_time_seconds = int(print_data["mc_remaining_time"])

        if "gcode_file" in print_data:
            state.current_file = print_data["gcode_file"]

        if "subtask_name" in print_data:
            state.subtask_name = print_data["subtask_name"]

        # Temperatures
        if "nozzle_temper" in print_data:
            state.nozzle_temp = float(print_data["nozzle_temper"])
        if "nozzle_target_temper" in print_data:
            state.nozzle_target_temp = float(print_data["nozzle_target_temper"])
        if "bed_temper" in print_data:
            state.bed_temp = float(print_data["bed_temper"])
        if "bed_target_temper" in print_data:
            state.bed_target_temp = float(print_data["bed_target_temper"])
        if "chamber_temper" in print_data:
            state.chamber_temp = float(print_data["chamber_temper"])

        # HMS errors
        if "hms" in print_data:
            state.hms_errors = print_data["hms"]

        if "print_error" in print_data:
            try:
                state.print_error = int(print_data["print_error"])
            except (TypeError, ValueError):
                state.print_error = 0

    async def _update_ams_status(
        self,
        printer_id: UUID,
        state: BambuPrinterState,
        print_data: dict[str, Any],
    ) -> None:
        """Update AMS status from MQTT data."""
        if "ams" not in print_data:
            return

        ams_data = print_data["ams"]

        # Update AMS metadata
        if "tray_now" in ams_data:
            state.tray_now = int(ams_data["tray_now"])
        if "ams_exist_bits" in ams_data:
            state.ams_exist_bits = ams_data["ams_exist_bits"]
        if "tray_exist_bits" in ams_data:
            state.tray_exist_bits = ams_data["tray_exist_bits"]
        if "tray_is_bbl_bits" in ams_data:
            state.tray_is_bbl_bits = ams_data["tray_is_bbl_bits"]

        # Update AMS units
        if "ams" in ams_data:
            state.ams_units = ams_data["ams"]
            await self._emit_event("ams_update", printer_id, state.ams_units)

    async def request_full_status(self, printer_id: UUID) -> bool:
        """
        Request full status from the printer (pushall command).

        Note: On P1P, limit to once per 5 minutes due to performance impact.
        """
        config = self._configs.get(printer_id)
        if not config or printer_id not in self._connections:
            return False

        command = {
            "pushing": {
                "sequence_id": self._get_next_sequence_id(),
                "command": "pushall",
            }
        }

        return await self._send_command(printer_id, command)

    async def pause_print(self, printer_id: UUID) -> bool:
        """Pause the current print job."""
        command = {
            "print": {
                "sequence_id": self._get_next_sequence_id(),
                "command": "pause",
            }
        }
        return await self._send_command(printer_id, command)

    async def resume_print(self, printer_id: UUID) -> bool:
        """Resume a paused print job."""
        command = {
            "print": {
                "sequence_id": self._get_next_sequence_id(),
                "command": "resume",
            }
        }
        return await self._send_command(printer_id, command)

    async def stop_print(self, printer_id: UUID) -> bool:
        """Stop the current print job."""
        command = {
            "print": {
                "sequence_id": self._get_next_sequence_id(),
                "command": "stop",
            }
        }
        return await self._send_command(printer_id, command, qos=1)

    async def start_project_print(
        self,
        printer_id: UUID,
        *,
        remote_file_name: str,
        plate_index: int,
        ams_mapping: list[int],
        md5: str,
    ) -> bool:
        """Start printing a plate of a sliced project already on the printer (spec 011).

        Only :class:`~app.services.print_send_service.PrintSendService` calls
        this, after a confirmed summary (FR-006). ``ams_mapping`` is indexed by
        the plate's slicer filament number minus one; each value is a global
        tray index (``ams_id * 4 + tray_id``), ``254`` for the external spool,
        ``-1`` for a filament the plate does not use.
        """
        subtask = remote_file_name.removesuffix(".gcode.3mf")
        command = {
            "print": {
                "sequence_id": self._get_next_sequence_id(),
                "command": "project_file",
                "param": f"Metadata/plate_{plate_index}.gcode",
                "url": f"ftp:///{remote_file_name}",
                "subtask_name": subtask,
                "project_id": "0",
                "profile_id": "0",
                "task_id": "0",
                "subtask_id": "0",
                "md5": md5,
                "timelapse": False,
                "bed_type": "auto",
                "bed_levelling": True,
                "flow_cali": True,
                "vibration_cali": True,
                "layer_inspect": False,
                "use_ams": any(0 <= slot < EXTERNAL_SPOOL_TRAY for slot in ams_mapping),
                "ams_mapping": ams_mapping,
            }
        }
        return await self._send_command(printer_id, command, qos=1)

    async def ensure_connected(
        self, config: BambuConnectionConfig, timeout: float = 10.0
    ) -> Optional[BambuPrinterState]:
        """This process's live state of the printer, connecting first if needed.

        Two backend pods each hold their own connections (research R7): the
        printer may have been connected from the other one. Returns None when
        no status report arrives within ``timeout`` seconds.
        """
        printer_id = config.printer_id
        if self._states.get(printer_id) is None or printer_id not in self._connections:
            if not await self.connect(config):
                return None
        elif config.tenant_id is not None and printer_id in self._configs:
            self._configs[printer_id].tenant_id = config.tenant_id

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            state = self._states.get(printer_id)
            if state is not None and state.is_online and state.print_status is not None:
                return state
            if loop.time() >= deadline:
                return None
            await asyncio.sleep(0.2)

    def get_config(self, printer_id: UUID) -> Optional[BambuConnectionConfig]:
        """Connection settings of a connected printer (holds the access code: never log it)."""
        return self._configs.get(printer_id)

    async def _send_command(self, printer_id: UUID, command: dict[str, Any], qos: int = 0) -> bool:
        """Send a command to the printer."""
        config = self._configs.get(printer_id)
        if not config or printer_id not in self._connections:
            logger.error(f"Cannot send command: printer {printer_id} not connected")
            return False

        client = self._connections[printer_id]
        topic = f"device/{config.serial_number}/request"

        try:
            payload = json.dumps(command)
            result = client.publish(topic, payload, qos=qos)
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.error(f"Failed to send command to printer: {e}")
            return False

    def get_printer_state(self, printer_id: UUID) -> Optional[BambuPrinterState]:
        """Get the current state of a connected printer."""
        return self._states.get(printer_id)

    def get_printer_status(self, printer_id: UUID) -> Optional[BambuPrinterStatus]:
        """Get printer status as a Pydantic model."""
        state = self._states.get(printer_id)
        if not state:
            return None

        return BambuPrinterStatus(
            serial_number=state.serial_number,
            is_online=state.is_online,
            print_status=state.print_status,
            print_percentage=state.print_percentage,
            current_layer=state.current_layer,
            total_layers=state.total_layers,
            remaining_time_minutes=state.remaining_time_seconds // 60
            if state.remaining_time_seconds
            else None,
            current_file=state.current_file,
            nozzle_temp=state.nozzle_temp,
            nozzle_target_temp=state.nozzle_target_temp,
            bed_temp=state.bed_temp,
            bed_target_temp=state.bed_target_temp,
            chamber_temp=state.chamber_temp,
            error_code=state.hms_errors[0].get("code") if state.hms_errors else None,
        )

    def get_ams_status(self, printer_id: UUID) -> list[AMSStatusFromMQTT]:
        """Get AMS status as Pydantic models."""
        state = self._states.get(printer_id)
        if not state or not state.ams_units:
            return []

        result = []
        for ams_unit in state.ams_units:
            trays = []
            for tray_data in ams_unit.get("tray", []):
                tray = AMSTrayStatus(
                    tray_id=int(tray_data.get("id", 0)),
                    tag_uid=tray_data.get("tag_uid"),
                    tray_type=tray_data.get("tray_type"),
                    tray_color=tray_data.get("tray_color"),
                    tray_weight=int(tray_data["tray_weight"])
                    if tray_data.get("tray_weight")
                    else None,
                    tray_diameter=float(tray_data["tray_diameter"])
                    if tray_data.get("tray_diameter")
                    else None,
                    nozzle_temp_min=int(tray_data["nozzle_temp_min"])
                    if tray_data.get("nozzle_temp_min")
                    else None,
                    nozzle_temp_max=int(tray_data["nozzle_temp_max"])
                    if tray_data.get("nozzle_temp_max")
                    else None,
                    bed_temp=int(tray_data["bed_temp"]) if tray_data.get("bed_temp") else None,
                    remain=int(tray_data["remain"])
                    if tray_data.get("remain") is not None
                    else None,
                    tray_info_idx=tray_data.get("tray_info_idx"),
                    tray_sub_brands=tray_data.get("tray_sub_brands"),
                )
                trays.append(tray)

            ams_status = AMSStatusFromMQTT(
                ams_id=int(ams_unit.get("id", 0)),
                humidity=float(ams_unit["humidity"]) if ams_unit.get("humidity") else None,
                temperature=float(ams_unit["temp"]) if ams_unit.get("temp") else None,
                trays=trays,
            )
            result.append(ams_status)

        return result

    def is_connected(self, printer_id: UUID) -> bool:
        """Check if a printer is currently connected."""
        state = self._states.get(printer_id)
        return state.is_online if state else False

    def get_connected_printers(self) -> list[UUID]:
        """Get list of currently connected printer IDs."""
        return [pid for pid, state in self._states.items() if state.is_online]


# Global service instance
_bambu_mqtt_service: Optional[BambuMQTTService] = None


def get_bambu_mqtt_service() -> BambuMQTTService:
    """Get or create the global Bambu MQTT service instance."""
    global _bambu_mqtt_service
    if _bambu_mqtt_service is None:
        _bambu_mqtt_service = BambuMQTTService()
    return _bambu_mqtt_service
