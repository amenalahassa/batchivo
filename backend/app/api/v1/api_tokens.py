"""Personal API token endpoints (spec 010, contracts/api-tokens-api.md).

List, create and revoke are for the signed-in web user only: they are absent
from the token policy table, so a token is refused there (FR-008). `current`
is the reverse: only a token may call it, to learn its own scopes.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from app.auth.api_tokens import token_context
from app.auth.dependencies import CurrentTenant, CurrentUser, TenantDB
from app.models.api_token import ApiToken
from app.schemas.api_token import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenCurrent,
    ApiTokenListResponse,
    ApiTokenResponse,
)
from app.services.api_token_service import ApiTokenService, to_response

router = APIRouter()


@router.get("", response_model=ApiTokenListResponse)
async def list_api_tokens(
    user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> ApiTokenListResponse:
    """The caller's own tokens in the current tenant, newest first. Never the secrets."""
    tokens = await ApiTokenService(db, tenant, user).list()
    return ApiTokenListResponse(items=[to_response(t) for t in tokens], total=len(tokens))


@router.post("", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_api_token(
    data: ApiTokenCreate, user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> ApiTokenCreated:
    """Create a token. The response carries the secret, once."""
    token, secret = await ApiTokenService(db, tenant, user).create(data)
    return ApiTokenCreated(**to_response(token).model_dump(), token=secret)


@router.get("/current", response_model=ApiTokenCurrent)
async def get_current_token(
    request: Request, user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> ApiTokenCurrent:
    """The calling token's own description. Only available to API tokens."""
    context = token_context(request)
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only available to API tokens",
        )
    token = await db.get(ApiToken, context.id)
    if token is None:  # revoked and deleted between the auth check and here
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
    return ApiTokenCurrent(
        id=token.id,
        name=token.name,
        token_prefix=token.token_prefix,
        scopes=list(token.scopes),
        expires_at=token.expires_at,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
    )


@router.post("/{token_id}/revoke", response_model=ApiTokenResponse)
async def revoke_api_token(
    token_id: UUID, user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> ApiTokenResponse:
    """Revoke one of the caller's tokens; revoking twice changes nothing."""
    token = await ApiTokenService(db, tenant, user).revoke(token_id)
    return to_response(token)
