"""File transfer to Bambu Lab printers over implicit FTPS (spec 011, research R1).

Printers in LAN mode with Developer Mode accept files on port 990: TLS from the
first byte (implicit FTPS), user ``bblp``, the LAN access code as password, a
self-signed certificate, and a protected data channel that must reuse the
control channel's TLS session (X1-series firmware refuses otherwise).

``ftplib`` is blocking, so every call runs in a worker thread. Errors are
raised as :class:`BambuFileTransferError` with a message that never contains
the access code.
"""

import asyncio
import ftplib
import io
import logging
import socket
import ssl
from typing import Any, Optional

logger = logging.getLogger(__name__)

FTPS_PORT = 990
FTPS_USER = "bblp"
TIMEOUT_SECONDS = 30.0


class BambuFileTransferError(Exception):
    """A file transfer to or from the printer failed (message safe to show)."""


class ImplicitFTPS(ftplib.FTP_TLS):
    """``FTP_TLS`` speaking implicit TLS, reusing the TLS session on data connections."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._sock: Optional[ssl.SSLSocket] = None

    @property
    def sock(self) -> Any:  # type: ignore[override]
        return self._sock

    @sock.setter
    def sock(self, value: Any) -> None:
        # Wrap the control socket in TLS as soon as it is opened (implicit FTPS).
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value, server_hostname=self.host)
        self._sock = value

    def ntransfercmd(self, cmd: str, rest: Any = None) -> tuple[socket.socket, Optional[int]]:
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(
                conn, server_hostname=self.host, session=self.sock.session
            )
        return conn, size


def _context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    # Bambu printers present a self-signed certificate (same as the MQTT connection).
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _open(host: str, access_code: str) -> ImplicitFTPS:
    ftp = ImplicitFTPS(context=_context(), timeout=TIMEOUT_SECONDS)
    ftp.connect(host=host, port=FTPS_PORT)
    ftp.login(user=FTPS_USER, passwd=access_code)
    ftp.prot_p()
    return ftp


def _describe(error: BaseException) -> str:
    """A message for the operator, free of any secret."""
    if isinstance(error, ftplib.error_perm) and str(error).startswith("530"):
        return "Login refused: check the access code and that Developer Mode is on"
    if isinstance(error, (socket.timeout, TimeoutError)):
        return "The printer did not answer in time"
    if isinstance(error, ConnectionRefusedError):
        return "The printer refused the file connection (is Developer Mode on?)"
    if isinstance(error, OSError):
        return "The printer could not be reached on the network"
    return "The file transfer failed"


def _quit(ftp: Optional[ImplicitFTPS]) -> None:
    if ftp is None:
        return
    try:
        ftp.quit()
    except Exception:
        ftp.close()


def _upload_sync(host: str, access_code: str, remote_name: str, data: bytes) -> None:
    ftp = None
    try:
        ftp = _open(host, access_code)
        ftp.storbinary(f"STOR {remote_name}", io.BytesIO(data))
    except Exception as e:
        raise BambuFileTransferError(_describe(e)) from None
    finally:
        _quit(ftp)


def _delete_sync(host: str, access_code: str, remote_name: str) -> None:
    ftp = None
    try:
        ftp = _open(host, access_code)
        ftp.delete(remote_name)
    finally:
        _quit(ftp)


def _check_sync(host: str, access_code: str) -> tuple[bool, str]:
    ftp = None
    try:
        ftp = _open(host, access_code)
        ftp.nlst()
        return True, "The printer accepted the file connection"
    except Exception as e:
        return False, _describe(e)
    finally:
        _quit(ftp)


async def upload(host: str, access_code: str, remote_name: str, data: bytes) -> None:
    """Store ``data`` as ``remote_name`` at the root of the printer's storage."""
    await asyncio.to_thread(_upload_sync, host, access_code, remote_name, data)
    logger.info(f"Uploaded {remote_name} ({len(data)} bytes) to printer at {host}")


async def delete(host: str, access_code: str, remote_name: str) -> bool:
    """Remove ``remote_name`` from the printer. Best effort: never raises."""
    try:
        await asyncio.to_thread(_delete_sync, host, access_code, remote_name)
        return True
    except Exception as e:
        logger.warning(f"Could not delete {remote_name} from printer at {host}: {_describe(e)}")
        return False


async def check_login(host: str, access_code: str) -> tuple[bool, str]:
    """Log in and list the root without writing anything (FR-012a)."""
    return await asyncio.to_thread(_check_sync, host, access_code)
