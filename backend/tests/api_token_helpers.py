"""Helpers shared by the personal API token tests (spec 010)."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tests.passwords import hashed_test_password
from app.core.security import create_access_token
from app.models.api_token import ApiToken
from app.models.tenant import Tenant
from app.models.user import User, UserRole, UserTenant
from app.services.api_token_service import generate_token, hash_token, prefix_of


def jwt_headers(user: User, tenant: Tenant) -> dict[str, str]:
    """A real access JWT for this user and tenant."""
    token = create_access_token(
        {
            "user_id": str(user.id),
            "email": user.email,
            "tenant_id": str(tenant.id),
            "is_platform_admin": user.is_platform_admin,
        }
    )
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": str(tenant.id)}


def bearer(secret: str) -> dict[str, str]:
    """Authorization header for an API token."""
    return {"Authorization": f"Bearer {secret}"}


async def make_tenant(db: AsyncSession, name: str = "Other Tenant") -> Tenant:
    tenant = Tenant(id=uuid4(), name=name, slug=f"t-{uuid4().hex[:8]}", settings={})
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def make_member(db: AsyncSession, tenant: Tenant, role: UserRole = UserRole.MEMBER) -> User:
    user = User(
        id=uuid4(),
        email=f"{role.value}-{uuid4().hex[:8]}@example.com",
        full_name=f"Token {role.value}",
        hashed_password=hashed_test_password("tokenpassword123"),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserTenant(user_id=user.id, tenant_id=tenant.id, role=role))
    await db.commit()
    await db.refresh(user)
    return user


async def make_token(
    db: AsyncSession,
    tenant: Tenant,
    user: User,
    scopes: list[str],
    *,
    name: str = "Agent",
    expires_in: timedelta = timedelta(days=30),
    revoked: bool = False,
    last_used_at: Optional[datetime] = None,
) -> tuple[ApiToken, str]:
    """A token row and its secret, written directly (bypassing the API)."""
    secret = generate_token()
    now = datetime.now(timezone.utc)
    token = ApiToken(
        tenant_id=tenant.id,
        user_id=user.id,
        name=name,
        token_prefix=prefix_of(secret),
        token_hash=hash_token(secret),
        scopes=sorted(scopes),
        expires_at=now + expires_in,
        revoked_at=now if revoked else None,
        last_used_at=last_used_at,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return token, secret
