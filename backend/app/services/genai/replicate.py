"""Replicate adapter (research R3, R7, R8, R10).

Every call goes through one ``httpx.AsyncClient`` on ``settings.genai_provider_url``
(the real API, or the local fake in development and e2e). Tests mock this host
with respx; nothing in the test suite reaches api.replicate.com.

The token is sent only in the Authorization header and never appears in an
exception message or a log line.
"""

import base64
import logging
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from app.services.genai.base import (
    CANCELED,
    FAILED,
    RUNNING,
    SUCCEEDED,
    ProviderAccount,
    ProviderAuthError,
    ProviderError,
    ProviderPrediction,
    ProviderRateLimited,
    ProviderRejected,
    ProviderTooLarge,
    ProviderTransient,
)

logger = logging.getLogger(__name__)

#: Where Replicate serves prediction outputs.
DELIVERY_HOST = "replicate.delivery"

DATA_URI_MAX_BYTES = 256 * 1024
_STATUS = {
    "starting": RUNNING,
    "processing": RUNNING,
    "succeeded": SUCCEEDED,
    "failed": FAILED,
    "canceled": CANCELED,
    "aborted": FAILED,
}


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("title") or f"HTTP {response.status_code}")
    return f"HTTP {response.status_code}"


def _raise_for(response: httpx.Response) -> None:
    code = response.status_code
    if code < 400:
        return
    detail = _detail(response)[:300]
    if code in (401, 403):
        raise ProviderAuthError(f"Replicate refused the token ({detail})")
    if code == 429:
        raise ProviderRateLimited(f"Replicate rate limit reached ({detail})")
    if code == 413:
        raise ProviderTooLarge(f"File too large for Replicate ({detail})")
    if code >= 500:
        raise ProviderTransient(f"Replicate is unavailable (HTTP {code})")
    raise ProviderRejected(f"Replicate rejected the request: {detail}")


def _json(response: httpx.Response) -> dict:
    """The response body as an object; a body that is not one is a transient fault."""
    try:
        body = response.json()
    except ValueError as exc:
        raise ProviderTransient(
            f"Replicate sent an unreadable answer (HTTP {response.status_code})"
        ) from exc
    if not isinstance(body, dict):
        raise ProviderTransient("Replicate sent an unexpected answer")
    return body


def parse_prediction(body: dict) -> ProviderPrediction:
    """A Replicate prediction object, normalised."""
    metrics = body.get("metrics") or {}
    predict_time = metrics.get("predict_time")
    error = body.get("error")
    if body.get("status") == "aborted" and not error:
        error = "The prediction was aborted before it started"
    return ProviderPrediction(
        id=str(body.get("id", "")),
        status=_STATUS.get(str(body.get("status")), RUNNING),
        output=body.get("output"),
        error=str(error) if error else None,
        version=body.get("version"),
        predict_time=float(predict_time) if predict_time is not None else None,
        raw=body,
    )


class ReplicateProvider:
    """``GenAIProvider`` over Replicate's HTTP API."""

    name = "replicate"

    def __init__(
        self,
        token: str,
        base_url: str,
        *,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._token = token
        self._base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True
        )

    def _headers(self, extra: Optional[dict] = None) -> dict:
        headers = {"Authorization": f"Bearer {self._token}"}
        if extra:
            headers.update(extra)
        return headers

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = path if path.startswith("http") else f"{self._base}{path}"
        try:
            response = await self._client.request(
                method, url, headers=self._headers(kwargs.pop("headers", None)), **kwargs
            )
        except httpx.TimeoutException as exc:
            raise ProviderTransient("Replicate did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise ProviderTransient(f"Could not reach Replicate ({type(exc).__name__})") from exc
        _raise_for(response)
        return response

    async def submit(
        self, version: str, payload: dict, webhook_url: Optional[str] = None
    ) -> ProviderPrediction:
        body: dict[str, Any] = {"version": version, "input": payload}
        if webhook_url:
            body["webhook"] = webhook_url
            body["webhook_events_filter"] = ["completed"]
        response = await self._request("POST", "/predictions", json=body)
        return parse_prediction(_json(response))

    async def get(self, prediction_id: str) -> ProviderPrediction:
        response = await self._request("GET", f"/predictions/{prediction_id}")
        return parse_prediction(_json(response))

    async def cancel(self, prediction_id: str) -> None:
        await self._request("POST", f"/predictions/{prediction_id}/cancel")

    async def upload_input(self, content: bytes, content_type: str, filename: str) -> str:
        """A URL the provider can read: a data URI when small, else a Files API upload."""
        if len(content) <= DATA_URI_MAX_BYTES:
            encoded = base64.b64encode(content).decode()
            return f"data:{content_type};base64,{encoded}"
        response = await self._request(
            "POST",
            "/files",
            files={"content": (filename, content, content_type)},
            data={"filename": filename, "type": content_type},
        )
        url = (_json(response).get("urls") or {}).get("get")
        if not url:
            raise ProviderRejected("Replicate did not return a URL for the uploaded file")
        return str(url)

    async def delete_input(self, url: str) -> None:
        """Delete an uploaded input file (data URIs are not stored by the provider)."""
        if url.startswith("data:"):
            return
        try:
            await self._request("DELETE", url)
        except ProviderError as exc:
            logger.info(f"Could not delete a Replicate input file: {exc}")

    def _is_provider_url(self, url: str) -> bool:
        """The configured API itself, or https on ``replicate.delivery`` and its subdomains."""
        if url == self._base or url.startswith(self._base + "/"):
            return True
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        delivery = host == DELIVERY_HOST or host.endswith("." + DELIVERY_HOST)
        return parsed.scheme == "https" and delivery

    async def download(self, url: str, max_bytes: int) -> tuple[bytes, str]:
        """Fetch an output file, refusing anything over ``max_bytes``.

        Only the provider's own hosts are fetched, with the token (FR-021, R7):
        an output URL comes from the model, and a community model can return any
        string. A lookalike host must never receive the token, and the backend
        must not be made to fetch an arbitrary or internal address.
        """
        if not self._is_provider_url(url):
            raise ProviderRejected("The provider returned an output outside its own file hosts")
        headers = self._headers()
        try:
            async with self._client.stream("GET", url, headers=headers) as response:
                if response.status_code >= 400:
                    await response.aread()
                _raise_for(response)
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ProviderTooLarge(f"Output larger than {max_bytes} bytes")
                    chunks.append(chunk)
                content_type = response.headers.get("content-type", "application/octet-stream")
        except httpx.TimeoutException as exc:
            raise ProviderTransient("Downloading the output timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderTransient(
                f"Could not download the output ({type(exc).__name__})"
            ) from exc
        return b"".join(chunks), content_type.split(";")[0].strip()

    async def account(self) -> ProviderAccount:
        body = _json(await self._request("GET", "/account"))
        return ProviderAccount(
            username=str(body.get("username", "")), name=body.get("name"), type=body.get("type")
        )

    async def webhook_secret(self) -> str:
        body = _json(await self._request("GET", "/webhooks/default/secret"))
        key = body.get("key")
        if not key:
            raise ProviderRejected("Replicate returned no webhook signing secret")
        return str(key)

    async def aclose(self) -> None:
        await self._client.aclose()


__all__ = ["DATA_URI_MAX_BYTES", "ReplicateProvider", "parse_prediction"]
