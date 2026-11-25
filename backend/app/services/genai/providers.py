"""Provider registry: the catalog names a provider, this returns its adapter."""

from app.config import get_settings
from app.services.genai.base import GenAIProvider
from app.services.genai.errors import GenAIError


def get_provider(name: str, token: str) -> GenAIProvider:
    """An adapter for ``name`` authenticated with ``token``."""
    if name == "replicate":
        from app.services.genai.replicate import ReplicateProvider

        return ReplicateProvider(token, get_settings().genai_provider_url)
    raise GenAIError(f"Unknown provider: {name}", code="unknown_provider")


__all__ = ["get_provider"]
