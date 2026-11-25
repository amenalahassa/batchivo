"""Which provider token a tenant uses, and the webhook signing secret (research R8, R9).

Order (FR-023, clarification Q2):

1. the tenant's own token (``Tenant.settings["replicate"]["api_token_encrypted"]``);
2. else the platform token from configuration, only if a platform admin
   authorised this tenant (``platform_token_allowed``) or the install serves
   all its tenants with it (``genai_platform_token_all_tenants``, single-shop VPS);
3. else none: the tenant is not connected.

Tokens are decrypted here and handed only to a provider adapter; nothing here
logs or returns them to a caller that could put them in a response.
"""

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

from app.config import Settings, get_settings
from app.core.encryption import encrypt_value, safe_decrypt
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

SOURCE_TENANT = "tenant"
SOURCE_PLATFORM = "platform"
SOURCE_NONE = "none"

_platform_secret_cache: dict[str, str] = {}


@dataclass(frozen=True)
class ResolvedToken:
    """A token and where it came from. ``repr`` never shows the token."""

    token: Optional[str]
    source: str

    def __repr__(self) -> str:
        return f"ResolvedToken(source={self.source!r})"

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.token or "")


def fingerprint(token: str) -> str:
    """A short, non-reversible identifier of a token, to key caches."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def replicate_config(tenant: Tenant) -> dict:
    """The tenant's ``replicate`` settings block (never None)."""
    return dict((tenant.settings or {}).get("replicate") or {})


def platform_token(settings: Optional[Settings] = None) -> Optional[str]:
    settings = settings or get_settings()
    secret = settings.replicate_api_token
    value = secret.get_secret_value() if secret is not None else ""
    return value or None


def platform_allowed(tenant: Tenant, settings: Optional[Settings] = None) -> bool:
    """Whether this tenant may use the platform token."""
    settings = settings or get_settings()
    if settings.genai_platform_token_all_tenants:
        return True
    return bool(replicate_config(tenant).get("platform_token_allowed"))


def resolve(tenant: Tenant, settings: Optional[Settings] = None) -> ResolvedToken:
    """The token a job of this tenant runs with."""
    settings = settings or get_settings()
    own = safe_decrypt(replicate_config(tenant).get("api_token_encrypted", ""))
    if own:
        return ResolvedToken(own, SOURCE_TENANT)
    shared = platform_token(settings)
    if shared and platform_allowed(tenant, settings):
        return ResolvedToken(shared, SOURCE_PLATFORM)
    return ResolvedToken(None, SOURCE_NONE)


async def webhook_secret(tenant: Tenant, resolved: ResolvedToken, provider) -> Optional[str]:
    """The provider's webhook signing secret for this token, cached.

    A tenant's secret is cached encrypted in its settings, keyed by the token's
    fingerprint (a new token fetches a new secret); the caller commits. The
    platform token's secret is cached in process memory.
    """
    if not resolved.token:
        return None
    key = resolved.fingerprint
    if resolved.source == SOURCE_PLATFORM:
        if key not in _platform_secret_cache:
            _platform_secret_cache[key] = await provider.webhook_secret()
        return _platform_secret_cache[key]
    config = replicate_config(tenant)
    if config.get("webhook_secret_token_fingerprint") == key:
        cached = safe_decrypt(config.get("webhook_secret_encrypted", ""))
        if cached:
            return cached
    secret = await provider.webhook_secret()
    config["webhook_secret_encrypted"] = encrypt_value(secret)
    config["webhook_secret_token_fingerprint"] = key
    settings = dict(tenant.settings or {})
    settings["replicate"] = config
    tenant.settings = settings
    return secret


def clear_platform_cache() -> None:
    """Forget cached platform secrets (tests, token rotation)."""
    _platform_secret_cache.clear()


__all__ = [
    "ResolvedToken",
    "SOURCE_NONE",
    "SOURCE_PLATFORM",
    "SOURCE_TENANT",
    "clear_platform_cache",
    "fingerprint",
    "platform_allowed",
    "platform_token",
    "replicate_config",
    "resolve",
    "webhook_secret",
]
