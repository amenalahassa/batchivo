"""Personal API token lifecycle (spec 010): create, list, revoke, status.

The secret is generated here, hashed here and returned once to the creator;
only `token_prefix` and the id are ever logged.
"""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_token import ApiToken
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.api_token import ApiTokenCreate, ApiTokenResponse, ApiTokenStatus

logger = logging.getLogger(__name__)

TOKEN_MARKER = "bvt_"
_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"


def generate_token() -> str:
    """A new secret: `bvt_<id8>_<43 url-safe chars>` (256 bits after the id)."""
    public_id = "".join(secrets.choice(_ID_ALPHABET) for _ in range(8))
    return f"{TOKEN_MARKER}{public_id}_{secrets.token_urlsafe(32)}"


def hash_token(raw: str) -> str:
    """The stored form: SHA-256 hex of the full token (research R2)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def prefix_of(raw: str) -> str:
    """The display prefix `bvt_<id8>` (never used to authenticate)."""
    return raw[: len(TOKEN_MARKER) + 8]


def _aware(value: datetime) -> datetime:
    # SQLite hands back naive datetimes; every stored value is UTC.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def status_of(token: ApiToken, now: Optional[datetime] = None) -> ApiTokenStatus:
    """Derived on read (Constitution V): revoked, else expired, else active."""
    now = now or datetime.now(timezone.utc)
    if token.revoked_at is not None:
        return "revoked"
    if _aware(token.expires_at) <= now:
        return "expired"
    return "active"


def to_response(token: ApiToken) -> ApiTokenResponse:
    """The listed form of a token, with its derived status."""
    return ApiTokenResponse(
        id=token.id,
        name=token.name,
        token_prefix=token.token_prefix,
        scopes=list(token.scopes),
        created_at=token.created_at,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        revoked_at=token.revoked_at,
        status=status_of(token),
    )


class ApiTokenService:
    """Creates, lists and revokes the current user's tokens in the current tenant."""

    def __init__(self, db: AsyncSession, tenant: Tenant, user: User):
        self.db = db
        self.tenant = tenant
        self.user = user

    async def create(self, data: ApiTokenCreate) -> tuple[ApiToken, str]:
        """Create a token; returns the row and the secret (to be shown once)."""
        raw = generate_token()
        token = ApiToken(
            tenant_id=self.tenant.id,
            user_id=self.user.id,
            name=data.name,
            token_prefix=prefix_of(raw),
            token_hash=hash_token(raw),
            scopes=list(data.scopes),
            expires_at=data.expires_at,
        )
        self.db.add(token)
        await self.db.flush()
        await self.db.refresh(token)
        logger.info(
            f"Created API token {token.id} ({token.token_prefix}) for user {self.user.id} "
            f"in tenant {self.tenant.id}"
        )
        return token, raw

    async def list(self) -> list[ApiToken]:
        """The caller's own tokens in this tenant, newest first."""
        result = await self.db.execute(
            select(ApiToken)
            .where(ApiToken.tenant_id == self.tenant.id, ApiToken.user_id == self.user.id)
            .order_by(ApiToken.created_at.desc())
        )
        return list(result.scalars().unique().all())

    async def get_own(self, token_id: uuid.UUID) -> ApiToken:
        """One of the caller's tokens, or 404 (another user's token is not found)."""
        result = await self.db.execute(
            select(ApiToken).where(
                ApiToken.id == token_id,
                ApiToken.tenant_id == self.tenant.id,
                ApiToken.user_id == self.user.id,
            )
        )
        token = result.scalars().unique().one_or_none()
        if token is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API token not found")
        return token

    async def revoke(self, token_id: uuid.UUID) -> ApiToken:
        """Revoke once; revoking again changes nothing (idempotent)."""
        token = await self.get_own(token_id)
        if token.revoked_at is None:
            token.revoked_at = datetime.now(timezone.utc)
            await self.db.flush()
            await self.db.refresh(token)
            logger.info(f"Revoked API token {token.id} ({token.token_prefix})")
        return token
