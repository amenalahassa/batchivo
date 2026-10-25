"""The application, run as `app_user` with row-level security switched on.

Every other suite connects as the database owner, which RLS does not filter,
so none of them could see that switching `RLS_ENABLED` on would have broken
login, every role guard, the platform admin and a hundred routes (bug
rls-unscoped-routes). This suite builds a database from the migrations alone
-- the policies only exist there -- connects the application as `app_user`, and
drives the flows that must keep working, and the isolation that must hold.

Setup and assertions about rows run on the owner connection, synchronously, as
the other migration suites do; the application itself runs as `app_user`.
"""

import os
import uuid

import pytest
from alembic import command
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.integration.migration_support import alembic_against, database_named, sync_url

pytestmark = [
    pytest.mark.skipif(
        "postgres" not in os.environ.get("DATABASE_URL", ""),
        reason="row-level security needs PostgreSQL; set DATABASE_URL to run it",
    ),
    pytest.mark.asyncio,
]

API = "/api/v1"
PASSWORD = "rls-enforced-pw-123"
APP_USER_PASSWORD = "rls-suite-app-user"


def _id() -> str:
    return str(uuid.uuid4())


# ============================================
# The database: migrated, seeded with two tenants
# ============================================


@pytest.fixture(scope="module")
def database():
    """A scratch database at head, two tenants in it, and both connection URLs."""
    from app.auth.password import get_password_hash

    base_url = os.environ["DATABASE_URL"]
    scratch = f"rls_enforced_{uuid.uuid4().hex[:10]}"
    admin = create_engine(
        sync_url(database_named(base_url, "postgres")), isolation_level="AUTOCOMMIT"
    )
    owner_url = database_named(base_url, scratch)
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{scratch}"'))
    owner = create_engine(sync_url(owner_url), isolation_level="AUTOCOMMIT")
    try:
        with owner.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        with alembic_against(owner_url) as config:
            command.upgrade(config, "head")
        with owner.connect() as conn:
            # Drift, not RLS: the initial migration made tenants.settings `json`
            # while the model and the shop resolver use `jsonb`, so a database
            # built from migrations alone cannot resolve a shop by hostname
            # (side finding recorded in rls-unscoped-routes/fix.md).
            conn.execute(
                text("ALTER TABLE tenants ALTER COLUMN settings TYPE jsonb USING settings::jsonb")
            )
            # The role is cluster-wide; give it a password this suite knows.
            conn.execute(text(f"ALTER ROLE app_user WITH LOGIN PASSWORD '{APP_USER_PASSWORD}'"))

        ids = {
            "tenant_a": _id(),
            "tenant_b": _id(),
            "user_a": _id(),
            "user_b": _id(),
            "admin": _id(),
            "slug_a": f"shop-a-{uuid.uuid4().hex[:6]}",
        }
        hashed = get_password_hash(PASSWORD)
        with owner.connect() as conn:
            for tenant, slug in (("tenant_a", ids["slug_a"]), ("tenant_b", f"shop-b-{_id()[:6]}")):
                conn.execute(
                    text(
                        "INSERT INTO tenants (id, name, slug, is_active, settings, tenant_type, "
                        "currency_code, currency_symbol, created_at, updated_at) VALUES "
                        "(:id, :name, :slug, true, '{}', 'three_d_print', 'GBP', '£', now(), now())"
                    ),
                    {"id": ids[tenant], "name": tenant, "slug": slug},
                )
            for user, email, admin_flag in (
                ("user_a", f"a-{_id()[:8]}@example.com", False),
                ("user_b", f"b-{_id()[:8]}@example.com", False),
                ("admin", f"admin-{_id()[:8]}@example.com", True),
            ):
                ids[f"{user}_email"] = email
                conn.execute(
                    text(
                        "INSERT INTO users (id, email, full_name, hashed_password, is_active, "
                        "is_platform_admin, created_at, updated_at) VALUES "
                        "(:id, :email, :name, :pw, true, :admin, now(), now())"
                    ),
                    {
                        "id": ids[user],
                        "email": email,
                        "name": user,
                        "pw": hashed,
                        "admin": admin_flag,
                    },
                )
            for user, tenant in (
                ("user_a", "tenant_a"),
                ("user_b", "tenant_b"),
                ("admin", "tenant_a"),
            ):
                conn.execute(
                    text(
                        "INSERT INTO user_tenants (id, user_id, tenant_id, role, created_at, updated_at) "
                        "VALUES (:id, :user, :tenant, 'owner', now(), now())"
                    ),
                    {"id": _id(), "user": ids[user], "tenant": ids[tenant]},
                )
            for tenant, name in (("tenant_a", "Alpha dragons"), ("tenant_b", "Beta wyrms")):
                conn.execute(
                    text(
                        "INSERT INTO categories (id, tenant_id, name, slug, display_order, is_active, "
                        "created_at, updated_at) VALUES (:id, :tenant, :name, :slug, 0, true, now(), now())"
                    ),
                    {
                        "id": _id(),
                        "tenant": ids[tenant],
                        "name": name,
                        "slug": name.lower().replace(" ", "-"),
                    },
                )

        app_url = make_url(owner_url).set(username="app_user", password=APP_USER_PASSWORD)
        yield {
            "owner": owner,
            "owner_url": owner_url,
            "app_url": app_url.render_as_string(hide_password=False),
            **ids,
        }
    finally:
        owner.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
async def rls_app(database, monkeypatch):
    """The application, connected as `app_user`, with RLS on."""
    import app.auth.customer_dependencies as customer_dependencies
    import app.auth.dependencies as dependencies
    import app.core.rls as rls
    import app.database as database_module
    from app.main import app

    app_engine = create_async_engine(database["app_url"], pool_pre_ping=True)
    owner_engine = create_async_engine(database["owner_url"], pool_pre_ping=True)
    app_maker = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    owner_maker = async_sessionmaker(owner_engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(rls, "_enabled", lambda: True)
    monkeypatch.setattr(database_module, "async_session_maker", app_maker)
    monkeypatch.setattr(dependencies, "async_session_maker", app_maker)
    monkeypatch.setattr(customer_dependencies, "async_session_maker", app_maker)
    monkeypatch.setattr(dependencies, "privileged_session_maker", lambda: owner_maker)
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    was_limited = app.state.limiter.enabled
    app.state.limiter.enabled = False

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield {"client": client, "app_maker": app_maker, **database}

    app.state.limiter.enabled = was_limited
    app.dependency_overrides.update(previous_overrides)
    await app_engine.dispose()
    await owner_engine.dispose()


async def _login(client: AsyncClient, email: str) -> dict:
    response = await client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# ============================================
# The policies are really enforced on this connection
# ============================================


class TestTheConnectionIsReallyFiltered:
    """Without these, every test below could pass on a connection RLS ignores."""

    async def test_an_unscoped_app_user_session_sees_no_tenant_rows(self, rls_app) -> None:
        async with rls_app["app_maker"]() as session:
            count = (await session.execute(text("SELECT count(*) FROM categories"))).scalar_one()
        assert count == 0

    async def test_the_owner_sees_both_tenants(self, database) -> None:
        with database["owner"].connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM categories")).scalar_one() == 2

    async def test_the_scope_survives_a_commit_and_a_rollback(self, rls_app) -> None:
        from app.core.rls import set_rls_context

        async with rls_app["app_maker"]() as session:
            await set_rls_context(session, tenant_id=uuid.UUID(rls_app["tenant_a"]))
            await session.commit()
            await session.rollback()
            names = (await session.execute(text("SELECT name FROM categories"))).scalars().all()
        assert names == ["Alpha dragons"]


class TestMemberships:
    """Option (a): a user reads their own memberships before a tenant is chosen."""

    async def test_a_user_sees_their_own_memberships_and_nobody_elses(self, rls_app) -> None:
        from app.core.rls import set_rls_context

        async with rls_app["app_maker"]() as session:
            await set_rls_context(session, user_id=uuid.UUID(rls_app["user_a"]))
            users = (
                (await session.execute(text("SELECT user_id FROM user_tenants"))).scalars().all()
            )
        assert [str(u) for u in users] == [rls_app["user_a"]]

    async def test_a_user_cannot_write_themselves_into_another_tenant(self, rls_app) -> None:
        from sqlalchemy.exc import ProgrammingError

        from app.core.rls import set_rls_context

        async with rls_app["app_maker"]() as session:
            await set_rls_context(
                session,
                tenant_id=uuid.UUID(rls_app["tenant_a"]),
                user_id=uuid.UUID(rls_app["user_a"]),
            )
            with pytest.raises(ProgrammingError, match="row-level security"):
                await session.execute(
                    text(
                        "INSERT INTO user_tenants (id, user_id, tenant_id, role, created_at, updated_at) "
                        "VALUES (gen_random_uuid(), :user, :tenant, 'owner', now(), now())"
                    ),
                    {"user": rls_app["user_a"], "tenant": rls_app["tenant_b"]},
                )


# ============================================
# The flows that must keep working
# ============================================


class TestTheConsoleWorksUnderRls:
    async def test_login_and_who_am_i(self, rls_app) -> None:
        headers = await _login(rls_app["client"], rls_app["user_a_email"])

        response = await rls_app["client"].get(f"{API}/users/me", headers=headers)

        assert response.status_code == 200, response.text

    async def test_a_get_db_route_shows_only_its_own_tenant(self, rls_app) -> None:
        headers = await _login(rls_app["client"], rls_app["user_a_email"])

        response = await rls_app["client"].get(f"{API}/categories", headers=headers)

        assert response.status_code == 200, response.text
        body = response.json()
        names = [c["name"] for c in (body["categories"] if isinstance(body, dict) else body)]
        assert "Alpha dragons" in names
        assert "Beta wyrms" not in names

    async def test_a_role_guarded_write_lands_in_the_right_tenant(self, rls_app) -> None:
        headers = await _login(rls_app["client"], rls_app["user_a_email"])

        response = await rls_app["client"].post(
            f"{API}/categories", headers=headers, json={"name": f"Gamma {_id()[:6]}"}
        )

        assert response.status_code == 201, response.text
        with rls_app["owner"].connect() as conn:
            tenant = conn.execute(
                text("SELECT tenant_id FROM categories WHERE id = :id"),
                {"id": response.json()["id"]},
            ).scalar_one()
        assert str(tenant) == rls_app["tenant_a"]

    async def test_a_tenant_db_route_works(self, rls_app) -> None:
        headers = await _login(rls_app["client"], rls_app["user_a_email"])

        response = await rls_app["client"].get(f"{API}/settings/pricing-policy", headers=headers)

        assert response.status_code == 200, response.text

    async def test_another_tenant_cannot_be_named_in_the_header(self, rls_app) -> None:
        headers = await _login(rls_app["client"], rls_app["user_a_email"])
        headers["X-Tenant-ID"] = rls_app["tenant_b"]

        response = await rls_app["client"].get(f"{API}/settings/pricing-policy", headers=headers)

        assert response.status_code == 403

    async def test_email_verification_creates_a_workspace(self, rls_app) -> None:
        """The live signup path (`/auth/register` is disabled in code)."""
        import json

        from sqlalchemy.orm import Session

        from app.models.email_verification import EmailVerificationToken

        slug = f"verified-{_id()[:8]}"
        token = EmailVerificationToken.create_email_verification(
            email=f"{slug}@example.com",
            registration_data=json.dumps(
                {
                    "email": f"{slug}@example.com",
                    "password_hash": "$2b$12$notarealhashbutstoredasgiven",
                    "full_name": "Verified Owner",
                    "business_name": "Verified Shop",
                    "tenant_type": "three_d_print",
                    "slug": slug,
                }
            ),
        )
        with Session(rls_app["owner"]) as session:
            session.add(token)
            session.commit()
            value = token.token

        response = await rls_app["client"].post(
            f"{API}/onboarding/verify-email", json={"token": value}
        )

        assert response.status_code == 200, response.text
        with rls_app["owner"].connect() as conn:
            memberships = conn.execute(
                text(
                    "SELECT count(*) FROM user_tenants JOIN tenants ON tenants.id = "
                    "user_tenants.tenant_id WHERE tenants.slug = :slug"
                ),
                {"slug": slug},
            ).scalar_one()
        assert memberships == 1


class TestCrossTenantWorkUsesTheRealBypass:
    async def test_the_platform_admin_sees_every_tenant(self, rls_app) -> None:
        headers = await _login(rls_app["client"], rls_app["admin_email"])

        response = await rls_app["client"].get(f"{API}/platform/tenants", headers=headers)

        assert response.status_code == 200, response.text
        ids = {t["id"] for t in response.json()["items"]}
        assert {rls_app["tenant_a"], rls_app["tenant_b"]} <= ids


class TestTheStorefrontIsIsolated:
    async def test_a_shop_lists_only_its_own_categories(self, rls_app) -> None:
        # The handler has no tenant filter of its own: RLS is the whole belt.
        response = await rls_app["client"].get(
            f"{API}/shop/categories",
            headers={"X-Shop-Hostname": f"{rls_app['slug_a']}.batchivo.shop"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        names = [c["name"] for c in body["data"]]
        assert "Alpha dragons" in names
        assert "Beta wyrms" not in names


def test_only_the_admin_session_and_the_power_task_use_the_privileged_connection() -> None:
    """The one deliberate hole stays where it was put."""
    import pathlib

    app_root = pathlib.Path(__file__).resolve().parents[2] / "app"
    users = sorted(
        str(path.relative_to(app_root)).replace("\\", "/")
        for path in app_root.rglob("*.py")
        if "privileged_session_maker" in path.read_text(encoding="utf-8")
    )
    assert users == ["auth/dependencies.py", "database.py", "tasks/power.py"]
