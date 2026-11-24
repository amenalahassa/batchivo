"""Implicit FTPS client for Bambu printers (spec 011, T019). ftplib is always mocked."""

import ftplib
import logging
import socket
from unittest.mock import MagicMock, patch

import pytest

from app.services import bambu_ftps
from app.services.bambu_ftps import BambuFileTransferError

pytestmark = pytest.mark.asyncio

SECRET = "87654321"


def _fake_ftp() -> MagicMock:
    return MagicMock(spec=bambu_ftps.ImplicitFTPS)


async def test_upload_stores_file_under_remote_name():
    ftp = _fake_ftp()
    with patch.object(bambu_ftps, "ImplicitFTPS", return_value=ftp):
        await bambu_ftps.upload("192.168.1.50", SECRET, "batchivo-1.gcode.3mf", b"data")

    ftp.connect.assert_called_once_with(host="192.168.1.50", port=990)
    ftp.login.assert_called_once_with(user="bblp", passwd=SECRET)
    ftp.prot_p.assert_called_once()
    command, stream = ftp.storbinary.call_args.args
    assert command == "STOR batchivo-1.gcode.3mf"
    assert stream.read() == b"data"
    ftp.quit.assert_called_once()


async def test_login_refused_raises_safe_error(caplog):
    ftp = _fake_ftp()
    ftp.login.side_effect = ftplib.error_perm("530 Login incorrect.")
    caplog.set_level(logging.DEBUG)
    with patch.object(bambu_ftps, "ImplicitFTPS", return_value=ftp):
        with pytest.raises(BambuFileTransferError) as excinfo:
            await bambu_ftps.upload("192.168.1.50", SECRET, "a.gcode.3mf", b"x")

    assert "access code" in str(excinfo.value)
    assert SECRET not in str(excinfo.value)
    assert SECRET not in caplog.text


async def test_timeout_raises_error():
    ftp = _fake_ftp()
    ftp.storbinary.side_effect = socket.timeout()
    with patch.object(bambu_ftps, "ImplicitFTPS", return_value=ftp):
        with pytest.raises(BambuFileTransferError, match="did not answer"):
            await bambu_ftps.upload("h", SECRET, "a.gcode.3mf", b"x")


async def test_unreachable_raises_error():
    ftp = _fake_ftp()
    ftp.connect.side_effect = OSError("no route")
    with patch.object(bambu_ftps, "ImplicitFTPS", return_value=ftp):
        with pytest.raises(BambuFileTransferError, match="could not be reached"):
            await bambu_ftps.upload("h", SECRET, "a.gcode.3mf", b"x")


async def test_delete_is_best_effort():
    ftp = _fake_ftp()
    ftp.delete.side_effect = ftplib.error_perm("550 No such file")
    with patch.object(bambu_ftps, "ImplicitFTPS", return_value=ftp):
        assert await bambu_ftps.delete("h", SECRET, "a.gcode.3mf") is False

    ok_ftp = _fake_ftp()
    with patch.object(bambu_ftps, "ImplicitFTPS", return_value=ok_ftp):
        assert await bambu_ftps.delete("h", SECRET, "a.gcode.3mf") is True
    ok_ftp.delete.assert_called_once_with("a.gcode.3mf")


async def test_check_login_lists_without_writing():
    ftp = _fake_ftp()
    with patch.object(bambu_ftps, "ImplicitFTPS", return_value=ftp):
        ok, message = await bambu_ftps.check_login("h", SECRET)

    assert ok is True and "accepted" in message
    ftp.nlst.assert_called_once()
    ftp.storbinary.assert_not_called()
    ftp.delete.assert_not_called()


async def test_check_login_reports_failure():
    ftp = _fake_ftp()
    ftp.connect.side_effect = ConnectionRefusedError()
    with patch.object(bambu_ftps, "ImplicitFTPS", return_value=ftp):
        ok, message = await bambu_ftps.check_login("h", SECRET)

    assert ok is False
    assert "Developer Mode" in message
