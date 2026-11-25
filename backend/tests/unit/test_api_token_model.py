"""ApiToken model: CRUD, constraints and relationships (spec 010, data-model.md)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.models.api_token import ApiToken
from app.models.tenant import Tenant
from app.models.user import User
from app.services.api_token_service import hash_token
from tests.api_token_helpers import make_member, make_tenant, make_token

pytestmark = pytest.mark.asyncio


async def test_create_read_update(db_session, test_tenant: Tenant, test_user: User):
    token, secret = await make_token(db_session, test_tenant, test_user, ["read", "write"])

    loaded = await db_session.get(ApiToken, token.id)
    assert loaded.token_hash == hash_token(secret)
    assert loaded.scopes == ["read", "write"]
    assert loaded.user.id == test_user.id
    assert loaded.tenant.id == test_tenant.id

    now = datetime.now(timezone.utc)
    loaded.last_used_at = now
    loaded.revoked_at = now
    await db_session.commit()
    await db_session.refresh(loaded)
    assert loaded.last_used_at is not None
    assert loaded.revoked_at is not None


async def test_token_hash_is_unique(db_session, test_tenant: Tenant, test_user: User):
    token, _ = await make_token(db_session, test_tenant, test_user, ["read"])
    db_session.add(
        ApiToken(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            name="Copy",
            token_prefix=token.token_prefix,
            token_hash=token.token_hash,
            scopes=["read"],
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_blank_name_violates_check(db_session, test_tenant: Tenant, test_user: User):
    db_session.add(
        ApiToken(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            name="   ",
            token_prefix="bvt_abcdefgh",
            token_hash="0" * 64,
            scopes=["read"],
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_deleting_user_cascades(db_session):
    tenant = await make_tenant(db_session)
    user = await make_member(db_session, tenant)
    token, _ = await make_token(db_session, tenant, user, ["read"])
    token_id, user_id = token.id, user.id

    await db_session.execute(delete(User).where(User.id == user_id))
    await db_session.commit()
    remaining = await db_session.execute(select(ApiToken.id).where(ApiToken.id == token_id))
    assert remaining.first() is None


async def test_deleting_tenant_cascades(db_session):
    tenant = await make_tenant(db_session)
    user = await make_member(db_session, tenant)
    token, _ = await make_token(db_session, tenant, user, ["read"])
    token_id, tenant_id = token.id, tenant.id

    await db_session.execute(delete(Tenant).where(Tenant.id == tenant_id))
    await db_session.commit()
    remaining = await db_session.execute(select(ApiToken.id).where(ApiToken.id == token_id))
    assert remaining.first() is None
