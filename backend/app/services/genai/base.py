"""The provider contract every generative AI adapter satisfies (research R1, R2).

Screens and the service only see capabilities; a provider adapter turns a
request into the provider's prediction and back. Adding a provider means a new
adapter and catalog entries, never a screen change (FR-004).
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

#: Provider statuses normalised to ours.
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELED = "canceled"
TERMINAL = (SUCCEEDED, FAILED, CANCELED)


@dataclass
class ProviderPrediction:
    """One prediction as the provider reports it, normalised."""

    id: str
    status: str  # running | succeeded | failed | canceled
    output: Any = None
    error: Optional[str] = None
    version: Optional[str] = None
    predict_time: Optional[float] = None
    raw: dict = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL


@dataclass
class ProviderAccount:
    """Who the token belongs to, for the connection test."""

    username: str
    name: Optional[str] = None
    type: Optional[str] = None


class ProviderError(Exception):
    """A provider call failed. The message never contains the token."""

    code = "provider_error"
    transient = False


class ProviderAuthError(ProviderError):
    code = "auth"


class ProviderRateLimited(ProviderError):
    code = "rate_limited"
    transient = True


class ProviderTransient(ProviderError):
    code = "provider_unavailable"
    transient = True


class ProviderRejected(ProviderError):
    code = "provider_rejected"


class ProviderTooLarge(ProviderError):
    code = "too_large"


@runtime_checkable
class GenAIProvider(Protocol):
    """What the runner needs from a provider."""

    name: str

    async def submit(
        self, version: str, payload: dict, webhook_url: Optional[str] = None
    ) -> ProviderPrediction: ...

    async def get(self, prediction_id: str) -> ProviderPrediction: ...

    async def cancel(self, prediction_id: str) -> None: ...

    async def upload_input(self, content: bytes, content_type: str, filename: str) -> str: ...

    async def delete_input(self, url: str) -> None: ...

    async def download(self, url: str, max_bytes: int) -> tuple[bytes, str]: ...

    async def account(self) -> ProviderAccount: ...

    async def webhook_secret(self) -> str: ...

    async def aclose(self) -> None: ...


__all__ = [
    "CANCELED",
    "FAILED",
    "GenAIProvider",
    "ProviderAccount",
    "ProviderAuthError",
    "ProviderError",
    "ProviderPrediction",
    "ProviderRateLimited",
    "ProviderRejected",
    "ProviderTooLarge",
    "ProviderTransient",
    "RUNNING",
    "SUCCEEDED",
    "TERMINAL",
]
