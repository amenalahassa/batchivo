"""BambuMQTTService additions for spec 011: thread-safe callbacks, start command, connect-and-wait.

paho is mocked throughout; no test talks to a printer.
"""

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import paho.mqtt.client as mqtt
import pytest

from app.services.bambu_mqtt import (
    BambuConnectionConfig,
    BambuMQTTService,
    BambuPrinterState,
)

pytestmark = pytest.mark.asyncio


def _config(**overrides) -> BambuConnectionConfig:
    values = dict(
        printer_id=uuid4(),
        serial_number="01S00C123456789",
        ip_address="192.168.1.50",
        access_code="12345678",
    )
    values.update(overrides)
    return BambuConnectionConfig(**values)


def _connected(service: BambuMQTTService, config: BambuConnectionConfig) -> MagicMock:
    client = MagicMock()
    client.publish.return_value = SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS)
    service._connections[config.printer_id] = client
    service._configs[config.printer_id] = config
    service._states[config.printer_id] = BambuPrinterState(
        serial_number=config.serial_number, is_online=True, print_status="IDLE"
    )
    return client


# ============================================
# Regression: callbacks from paho's thread (R6)
# ============================================


async def test_message_from_paho_thread_updates_state():
    """paho calls on_message from its own thread; the state must still be updated."""
    service = BambuMQTTService()
    config = _config()
    fake_client = MagicMock()
    with patch("app.services.bambu_mqtt.mqtt.Client", return_value=fake_client):
        assert await service.connect(config)

    on_message = fake_client.on_message
    message = SimpleNamespace(
        payload=json.dumps({"print": {"gcode_state": "RUNNING", "print_error": 0}}).encode()
    )
    thread = threading.Thread(target=on_message, args=(fake_client, None, message))
    thread.start()
    thread.join()

    for _ in range(50):
        if service.get_printer_state(config.printer_id).print_status == "RUNNING":
            break
        await asyncio.sleep(0.02)
    assert service.get_printer_state(config.printer_id).print_status == "RUNNING"


async def test_print_error_is_parsed():
    service = BambuMQTTService()
    state = BambuPrinterState(serial_number="x")
    await service._update_print_status(state, {"gcode_state": "FAILED", "print_error": 50348044})
    assert state.print_error == 50348044
    await service._update_print_status(state, {"print_error": "garbage"})
    assert state.print_error == 0


# ============================================
# Start command (R2)
# ============================================


async def test_start_project_print_payload():
    service = BambuMQTTService()
    config = _config()
    client = _connected(service, config)

    ok = await service.start_project_print(
        config.printer_id,
        remote_file_name="batchivo-abcdef12.gcode.3mf",
        plate_index=2,
        ams_mapping=[2, -1, 254],
        md5="d41d8cd98f00b204e9800998ecf8427e",
    )

    assert ok is True
    topic, payload = client.publish.call_args.args[:2]
    assert topic == f"device/{config.serial_number}/request"
    assert client.publish.call_args.kwargs["qos"] == 1
    command = json.loads(payload)["print"]
    assert command["command"] == "project_file"
    assert command["param"] == "Metadata/plate_2.gcode"
    assert command["url"] == "ftp:///batchivo-abcdef12.gcode.3mf"
    assert command["subtask_name"] == "batchivo-abcdef12"
    assert command["ams_mapping"] == [2, -1, 254]
    assert command["use_ams"] is True
    assert command["md5"] == "d41d8cd98f00b204e9800998ecf8427e"
    assert command["timelapse"] is False
    assert command["bed_levelling"] is True


async def test_external_spool_only_does_not_use_ams():
    service = BambuMQTTService()
    config = _config()
    client = _connected(service, config)

    await service.start_project_print(
        config.printer_id,
        remote_file_name="batchivo-x.gcode.3mf",
        plate_index=1,
        ams_mapping=[254],
        md5="0" * 32,
    )

    command = json.loads(client.publish.call_args.args[1])["print"]
    assert command["use_ams"] is False


async def test_start_refused_when_not_connected():
    service = BambuMQTTService()
    ok = await service.start_project_print(
        uuid4(), remote_file_name="a.gcode.3mf", plate_index=1, ams_mapping=[0], md5="0" * 32
    )
    assert ok is False


# ============================================
# ensure_connected (R7)
# ============================================


async def test_ensure_connected_reuses_live_state_and_records_tenant():
    service = BambuMQTTService()
    config = _config()
    _connected(service, config)
    tenant_id = uuid4()

    state = await service.ensure_connected(
        _config(printer_id=config.printer_id, tenant_id=tenant_id)
    )

    assert state is not None and state.print_status == "IDLE"
    assert service.get_config(config.printer_id).tenant_id == tenant_id


async def test_ensure_connected_times_out_without_report():
    service = BambuMQTTService()
    with patch("app.services.bambu_mqtt.mqtt.Client", return_value=MagicMock()):
        state = await service.ensure_connected(_config(), timeout=0.3)
    assert state is None


async def test_ensure_connected_returns_none_when_connect_fails():
    service = BambuMQTTService()
    with patch("app.services.bambu_mqtt.mqtt.Client", side_effect=OSError("boom")):
        assert await service.ensure_connected(_config(), timeout=0.1) is None
