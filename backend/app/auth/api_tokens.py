"""Authenticating a request made with a personal API token (spec 010, plan §Authentication design).

`get_current_user` sends a bearer value here only when it starts with `bvt_`;
JWTs never reach this module and a token is never decoded as a JWT.

Order of checks, each refusal final:
1. find the row whose `token_hash` equals SHA-256 of the presented value
   (exact match on the indexed column; the display prefix never authenticates);
2. 401 when unknown, revoked, expired, the owner is inactive or no longer a
   member of the token's tenant -- one message for all, so a caller learns nothing;
3. 403 when the endpoint does not accept tokens, or the token lacks its scope;
4. record the use (at most once a minute) and the token context on the request.

The secret is never logged: only the token id and its display prefix.
"""

import hmac
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy import or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_token_policy import ANY_SCOPE, required_scope
from app.core.rls import set_rls_context
from app.models.api_token import ApiToken
from app.models.user import User, UserTenant
from app.services.api_token_service import hash_token

logger = logging.getLogger(__name__)

TOKEN_MARKER = "bvt_"
INVALID_TOKEN_DETAIL = "Invalid or expired API token"
NOT_ACCEPTED_DETAIL = "This endpoint does not accept API tokens"
#: Name of the setting the `api_tokens` RLS policies compare with `token_hash`.
TOKEN_HASH_SETTING = "app.current_api_token_hash"
#: `last_used_at` is written at most this often per token (FR-009: minute precision).
LAST_USED_GRANULARITY = timedelta(seconds=60)


@dataclass(frozen=True)
class ApiTokenContext:
    """The authenticated token of a request. Never holds the secret."""

    id: UUID
    tenant_id: UUID
    user_id: UUID
    scopes: frozenset[str]
    prefix: str


def is_api_token(value: str) -> bool:
    """Whether a bearer value is a personal API token (as opposed to a JWT)."""
    return value.startswith(TOKEN_MARKER)


def token_context(request: Request) -> ApiTokenContext | None:
    """The token context `authenticate_api_token` put on this request, if any."""
    return getattr(request.state, "api_token", None)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=INVALID_TOKEN_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _admit_hash_under_rls(db: AsyncSession, digest: str) -> None:
    """Let the `api_tokens` policies show the one row with this hash (research R4).

    Harmless while row-level security is off (a setting no policy reads); the
    query below filters by the exact hash in any case, so RLS is a second belt,
    not the only one. PostgreSQL only: SQLite has no settings.
    """
    if db.bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": TOKEN_HASH_SETTING, "value": digest},
        )


async def authenticate_api_token(request: Request, db: AsyncSession, raw: str) -> User:
    """Authenticate `raw` for this request and return the token's owner."""
    digest = hash_token(raw)
    await _admit_hash_under_rls(db, digest)

    result = await db.execute(select(ApiToken).where(ApiToken.token_hash == digest))
    token = result.scalars().unique().one_or_none()
    if token is None or not hmac.compare_digest(token.token_hash, digest):
        logger.info("Refused an unknown API token")
        raise _unauthorized()

    now = datetime.now(timezone.utc)
    if token.revoked_at is not None or _aware(token.expires_at) <= now:
        logger.info(f"Refused revoked or expired API token {token.id} ({token.token_prefix})")
        raise _unauthorized()

    user = token.user
    if user is None or not user.is_active:
        logger.info(f"Refused API token {token.id}: owner missing or inactive")
        raise _unauthorized()

    # The owner's memberships become readable under RLS, exactly as for a JWT.
    await set_rls_context(db, user_id=user.id)
    membership = await db.execute(
        select(UserTenant.id).where(
            UserTenant.user_id == user.id, UserTenant.tenant_id == token.tenant_id
        )
    )
    if membership.first() is None:
        logger.info(f"Refused API token {token.id}: owner no longer in tenant {token.tenant_id}")
        raise _unauthorized()

    scope = required_scope(request.method, request.scope.get("endpoint"))
    if scope is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NOT_ACCEPTED_DETAIL)
    if scope != ANY_SCOPE and scope not in token.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API token is missing the '{scope}' scope",
        )

    await db.execute(
        update(ApiToken)
        .where(
            ApiToken.id == token.id,
            or_(
                ApiToken.last_used_at.is_(None),
                ApiToken.last_used_at < now - LAST_USED_GRANULARITY,
            ),
        )
        .values(last_used_at=now)
        .execution_options(synchronize_session=False)
    )

    request.state.api_token = ApiTokenContext(
        id=token.id,
        tenant_id=token.tenant_id,
        user_id=user.id,
        scopes=frozenset(token.scopes),
        prefix=token.token_prefix,
    )
    return user
