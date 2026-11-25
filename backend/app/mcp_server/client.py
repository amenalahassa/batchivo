"""The MCP server's only way to Batchivo: its REST API, with the token (spec 010, FR-013)."""

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx

API_PREFIX = "/api/v1"


class BatchivoApiError(Exception):
    """The API answered with an error status; the message is what the agent sees."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{status_code}: {detail}")


class BatchivoUnreachable(Exception):
    """The API could not be reached at all."""

    def __init__(self, url: str):
        self.url = url
        super().__init__(f"Batchivo could not be reached at {url}")


@dataclass(frozen=True)
class BinaryResponse:
    """A non-JSON body, such as an idea image."""

    content: bytes
    content_type: str


def _detail(response: httpx.Response) -> str:
    """The API's own message; a 422 becomes one `field: message` line per error."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip() or response.reason_phrase
    detail = body.get("detail", body) if isinstance(body, dict) else body
    if isinstance(detail, list):
        lines = []
        for error in detail:
            if isinstance(error, dict):
                loc = [str(p) for p in error.get("loc", []) if p not in ("body", "query", "path")]
                field = ".".join(loc) or "request"
                lines.append(f"{field}: {error.get('msg', error)}")
            else:
                lines.append(str(error))
        return "\n".join(lines)
    return str(detail)


def _clean(params: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if params is None:
        return None
    return {k: v for k, v in params.items() if v is not None and v != []}


class BatchivoClient:
    """A thin async client: bearer token on every call, errors made readable."""

    def __init__(
        self,
        api_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.api_url = api_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=f"{self.api_url}{API_PREFIX}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._http.request(method, path, **kwargs)
        except (httpx.TransportError, httpx.TimeoutException):
            raise BatchivoUnreachable(self.api_url) from None
        if response.status_code >= 400:
            raise BatchivoApiError(response.status_code, _detail(response))
        return response

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        return self._json(await self._send("GET", path, params=_clean(params)))

    async def post(
        self, path: str, json: Any = None, params: Optional[dict[str, Any]] = None
    ) -> Any:
        return self._json(await self._send("POST", path, json=json, params=_clean(params)))

    async def patch(self, path: str, json: Any = None) -> Any:
        return self._json(await self._send("PATCH", path, json=json))

    async def upload(
        self,
        path: str,
        file_field: str,
        file_path: str,
        data: Optional[dict[str, Any]] = None,
    ) -> Any:
        """POST multipart with a local file read from `file_path`."""
        local = Path(file_path).expanduser()
        if not local.is_file():
            raise FileNotFoundError(f"No file at {file_path}")
        mime = mimetypes.guess_type(local.name)[0] or "application/octet-stream"
        form = {k: str(v) for k, v in (data or {}).items() if v is not None}
        with local.open("rb") as handle:
            files = {file_field: (local.name, handle.read(), mime)}
        return self._json(await self._send("POST", path, data=form, files=files))

    async def post_form(self, path: str, data: dict[str, Any]) -> Any:
        """POST form fields without a file (URL-encoded; FastAPI `Form` reads both encodings)."""
        form = {k: str(v) for k, v in data.items() if v is not None}
        return self._json(await self._send("POST", path, data=form))

    async def get_bytes(self, path: str) -> BinaryResponse:
        response = await self._send("GET", path)
        content_type = response.headers.get("content-type", "application/octet-stream")
        return BinaryResponse(content=response.content, content_type=content_type.split(";")[0])
