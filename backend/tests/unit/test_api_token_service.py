"""ApiTokenService and token helpers (spec 010)."""

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.models.api_token import ApiToken
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.api_token import ApiTokenCreate
from app.services.api_token_service import (
    ApiTokenService,
    generate_token,
    hash_token,
    prefix_of,
    status_of,
)
from tests.api_token_helpers import make_member, make_tenant, make_token

pytestmark = pytest.mark.asyncio

TOKEN_SHAPE = re.compile(r"^bvt_[a-z2-7]{8}_[A-Za-z0-9_-]{43}$")


def _create(name: str = "Agent", scopes=("read",), days: int = 30) -> ApiTokenCreate:
    return ApiTokenCreate(
        name=name,
        scopes=list(scopes),
        expires_at=datetime.now(timezone.utc) + timedelta(days=days),
    )


async def test_generated_token_shape_and_prefix():
    raw = generate_token()
    assert TOKEN_SHAPE.match(raw)
    assert prefix_of(raw) == raw[:12]
    assert hash_token(raw) == hash_token(raw)
    assert len(hash_token(raw)) == 64
    assert generate_token() != raw


async def test_create_stores_only_the_hash(db_session, test_tenant: Tenant, test_user: User):
    token, secret = await ApiTokenService(db_session, test_tenant, test_user).create(
        _create(scopes=["write", "read", "read"])
    )
    await db_session.commit()
    assert TOKEN_SHAPE.match(secret)
    assert token.token_hash == hash_token(secret)
    assert token.token_prefix == secret[:12]
    assert token.scopes == ["read", "write"]
    stored = await db_session.get(ApiToken, token.id)
    assert secret not in (stored.token_hash, stored.token_prefix, stored.name)


async def test_status_of():
    now = datetime.now(timezone.utc)
    token = ApiToken(expires_at=now + timedelta(days=1), revoked_at=None)
    assert status_of(token, now) == "active"
    token.expires_at = now - timedelta(seconds=1)
    assert status_of(token, now) == "expired"
    token.revoked_at = now
    assert status_of(token, now) == "revoked"
    # Naive datetimes (SQLite) are read as UTC.
    token = ApiToken(expires_at=(now + timedelta(hours=1)).replace(tzinfo=None), revoked_at=None)
    assert status_of(token, now) == "active"


async def test_list_is_own_tokens_in_this_tenant_newest_first(
    db_session, test_tenant: Tenant, test_user: User
):
    older, _ = await make_token(db_session, test_tenant, test_user, ["read"], name="Older")
    older.created_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.commit()
    newer, _ = await make_token(db_session, test_tenant, test_user, ["read"], name="Newer")

    colleague = await make_member(db_session, test_tenant)
    await make_token(db_session, test_tenant, colleague, ["read"], name="Colleague")
    other_tenant = await make_tenant(db_session)
    from app.models.user import UserTenant

    db_session.add(UserTenant(user_id=test_user.id, tenant_id=other_tenant.id, role="member"))
    await db_session.commit()
    await make_token(db_session, other_tenant, test_user, ["read"], name="Elsewhere")

    tokens = await ApiTokenService(db_session, test_tenant, test_user).list()
    assert [t.name for t in tokens] == ["Newer", "Older"]


async def test_revoke_is_idempotent_and_never_cleared(
    db_session, test_tenant: Tenant, test_user: User
):
    token, _ = await make_token(db_session, test_tenant, test_user, ["read"])
    service = ApiTokenService(db_session, test_tenant, test_user)
    first = await service.revoke(token.id)
    revoked_at = first.revoked_at
    assert revoked_at is not None
    second = await service.revoke(token.id)
    assert second.revoked_at == revoked_at
    assert status_of(second) == "revoked"


async def test_revoke_another_users_token_is_not_found(
    db_session, test_tenant: Tenant, test_user: User
):
    colleague = await make_member(db_session, test_tenant)
    token, _ = await make_token(db_session, test_tenant, colleague, ["read"])
    with pytest.raises(HTTPException) as exc:
        await ApiTokenService(db_session, test_tenant, test_user).revoke(token.id)
    assert exc.value.status_code == 404
    await db_session.refresh(token)
    assert token.revoked_at is None


async def test_create_never_logs_the_secret(
    db_session, test_tenant: Tenant, test_user: User, caplog
):
    caplog.set_level("DEBUG")
    _, secret = await ApiTokenService(db_session, test_tenant, test_user).create(_create())
    assert secret not in caplog.text
    assert secret[12:] not in caplog.text
