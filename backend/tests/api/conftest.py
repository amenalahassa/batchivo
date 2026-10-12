"""Role fixtures shared by the API suites (task T034).

Both Tier 1 endpoint suites need the same thing: to act as a member or a
viewer, so a write can be refused and the stored figure checked afterwards.
The `client` fixture in `tests/conftest.py` is an admin — the role that is
*allowed* to write — so it cannot show a refusal.

`as_role` is an async context manager rather than a second client fixture
because `app.dependency_overrides` is one dictionary: two clients authenticated
as different users cannot coexist. Entering the context swaps who the current
user is and restores the previous overrides on exit, which lets one test write
as an admin and then be refused as a member.

They live in the API conftest rather than the global one because only the HTTP
suites need a differently-roled client; nothing below `tests/unit` does.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, AsyncIterator, Callable
from uuid import uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.tenant import Tenant
from app.models.user import User, UserRole, UserTenant


async def make_user_with_role(
    db_session: AsyncSession,
    tenant: Tenant,
    role: UserRole,
) -> User:
    """A user holding exactly ``role`` in ``tenant``."""
    from app.auth.password import get_password_hash

    unique_id = str(uuid4())[:8]
    user = User(
        id=uuid4(),
        email=f"{role.value}-pricing-{unique_id}@example.com",
        full_name=f"Pricing {role.value}",
        hashed_password=get_password_hash("pricingpassword123"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(UserTenant(user_id=user.id, tenant_id=tenant.id, role=role))
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def as_role(
    db_session: AsyncSession, seed_material_types, test_tenant: Tenant
) -> AsyncGenerator[Callable[[UserRole], AsyncIterator[AsyncClient]], None]:
    """Act as a user holding a given role, then put the overrides back.

    The role check reads `UserTenant` from the database, so the role comes
    from the row rather than from the override — which is the point: this
    exercises the real authorisation path, not a stubbed one.
    """
    from app.auth.dependencies import get_current_tenant, get_current_user, get_tenant_db
    from app.database import get_db

    @asynccontextmanager
    async def _acting_as(role: UserRole) -> AsyncIterator[AsyncClient]:
        user = await make_user_with_role(db_session, test_tenant, role)
        previous = dict(app.dependency_overrides)
        was_enabled = app.state.limiter.enabled

        async def override_get_db():
            yield db_session

        async def override_get_current_user():
            return user

        async def override_get_current_tenant():
            return test_tenant

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_tenant_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_tenant] = override_get_current_tenant
        app.state.limiter.enabled = False
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                yield ac
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous)
            app.state.limiter.enabled = was_enabled

    yield _acting_as
