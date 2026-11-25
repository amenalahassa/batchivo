"""Personal API tokens under row-level security (spec 010, research R4).

The application runs as `app_user` with RLS on, on a database built from the
migrations alone (fixtures shared with `test_rls_enforced`). A token must be
found by its hash before any tenant is set, without a privileged session, and
must never expose another tenant's tokens or data.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from tests.integration import test_rls_enforced as _rls

# The scratch database and the app-as-app_user client of the RLS suite.
API = _rls.API
_login = _rls._login
database = _rls.database
rls_app = _rls.rls_app

pytestmark = [
    pytest.mark.skipif(
        "postgres" not in __import__("os").environ.get("DATABASE_URL", ""),
        reason="row-level security needs PostgreSQL; set DATABASE_URL to run it",
    ),
    pytest.mark.asyncio,
]


def _insert_token(owner, tenant_id: str, user_id: str, scopes: list[str]) -> str:
    """Write a token row as the owner (RLS-free) and return its secret."""
    secret = f"bvt_{uuid.uuid4().hex[:8]}_{uuid.uuid4().hex}{uuid.uuid4().hex[:11]}"
    with owner.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO api_tokens (id, tenant_id, user_id, name, token_prefix, token_hash, "
                "scopes, expires_at, created_at, updated_at) VALUES (:id, :tenant, :user, "
                "'RLS', :prefix, :hash, CAST(:scopes AS json), :expires, now(), now())"
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant": tenant_id,
                "user": user_id,
                "prefix": secret[:12],
                "hash": hashlib.sha256(secret.encode()).hexdigest(),
                "scopes": __import__("json").dumps(scopes),
                "expires": datetime.now(timezone.utc) + timedelta(days=30),
            },
        )
    return secret


async def test_token_authenticates_under_rls_and_stays_in_its_tenant(rls_app):
    client = rls_app["client"]
    secret = _insert_token(rls_app["owner"], rls_app["tenant_a"], rls_app["user_a"], ["read"])

    response = await client.get(f"{API}/ideas", headers={"Authorization": f"Bearer {secret}"})
    assert response.status_code == 200, response.text

    current = await client.get(
        f"{API}/api-tokens/current", headers={"Authorization": f"Bearer {secret}"}
    )
    assert current.status_code == 200, current.text
    assert current.json()["tenant_id"] == rls_app["tenant_a"]

    with rls_app["owner"].connect() as conn:
        used = conn.execute(
            text("SELECT last_used_at FROM api_tokens WHERE token_prefix = :p"),
            {"p": secret[:12]},
        ).scalar_one()
    assert used is not None


async def test_other_tenants_tokens_are_invisible(rls_app):
    client = rls_app["client"]
    theirs = _insert_token(rls_app["owner"], rls_app["tenant_b"], rls_app["user_b"], ["read"])
    mine = _insert_token(rls_app["owner"], rls_app["tenant_a"], rls_app["user_a"], ["read"])

    headers = await _login(client, rls_app["user_a_email"])
    listing = await client.get(f"{API}/api-tokens", headers=headers)
    assert listing.status_code == 200, listing.text
    prefixes = {t["token_prefix"] for t in listing.json()["items"]}
    assert mine[:12] in prefixes
    assert theirs[:12] not in prefixes

    async with rls_app["app_maker"]() as session:
        # No tenant, no hash: app_user sees no token row at all.
        count = (await session.execute(text("SELECT count(*) FROM api_tokens"))).scalar_one()
        assert count == 0
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": rls_app["tenant_a"]},
        )
        tenants = (
            (await session.execute(text("SELECT DISTINCT tenant_id::text FROM api_tokens")))
            .scalars()
            .all()
        )
        assert tenants == [rls_app["tenant_a"]]


async def test_wrong_secret_finds_nothing_under_rls(rls_app):
    client = rls_app["client"]
    secret = _insert_token(rls_app["owner"], rls_app["tenant_a"], rls_app["user_a"], ["read"])
    forged = secret[:-1] + ("a" if secret[-1] != "a" else "b")
    response = await client.get(f"{API}/ideas", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401
