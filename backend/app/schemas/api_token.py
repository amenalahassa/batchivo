"""Schemas for personal API tokens (spec 010, contracts/api-tokens-api.md)."""

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ApiTokenScope = Literal["read", "write", "genai", "print"]
ApiTokenStatus = Literal["active", "expired", "revoked"]

#: The longest a token may live (clarification 2026-11-24: mandatory, at most one year).
MAX_TOKEN_LIFETIME = timedelta(days=365)


class ApiTokenCreate(BaseModel):
    """What the operator chooses when creating a token."""

    name: str = Field(..., description="A label, 1-100 characters; duplicates allowed")
    scopes: list[ApiTokenScope] = Field(..., min_length=1, description="At least one scope")
    expires_at: datetime = Field(..., description="Mandatory, at most one year ahead")

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def _name_length(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 100:
            raise ValueError("Name must be 1 to 100 characters")
        return value

    @field_validator("scopes")
    @classmethod
    def _scopes_sorted(cls, value: list[str]) -> list[str]:
        return sorted(set(value))

    @field_validator("expires_at")
    @classmethod
    def _expiry_bounds(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Expiry must include a time zone")
        now = datetime.now(timezone.utc)
        if value <= now:
            raise ValueError("Expiry must be in the future")
        if value > now + MAX_TOKEN_LIFETIME:
            raise ValueError("Expiry must be at most one year ahead")
        return value


class ApiTokenResponse(BaseModel):
    """A token as listed: never the secret."""

    id: UUID
    name: str
    token_prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    status: ApiTokenStatus


class ApiTokenCreated(ApiTokenResponse):
    """The creation response: the only place the secret ever appears."""

    token: str = Field(..., description="The full token. Shown once; store it now.")


class ApiTokenListResponse(BaseModel):
    """The caller's tokens in the current tenant, newest first."""

    items: list[ApiTokenResponse]
    total: int


class ApiTokenCurrent(BaseModel):
    """What a token learns about itself (used by the MCP server at startup)."""

    id: UUID
    name: str
    token_prefix: str
    scopes: list[str]
    expires_at: datetime
    tenant_id: UUID
    tenant_name: str
