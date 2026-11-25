"""Personal API token endpoints (spec 010, contracts/api-tokens-api.md).

Real authentication: these tests use `unauthenticated_client` (only the
database is overridden) with real JWTs and real tokens.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.api_token import ApiToken
from app.models.tenant import Tenant
from app.models.user import User
from app.services.api_token_service import hash_token
from tests.api_token_helpers import bearer, jwt_headers, make_member, make_token

pytestmark = pytest.mark.asyncio

API = "/api/v1/api-tokens"


def _body(**overrides):
    body = {
        "name": "Claude Code",
        "scopes": ["read", "write"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=90)).isoformat(),
    }
    body.update(overrides)
    return body


# ============================================
# Create
# ============================================


async def test_create_returns_secret_once(
    unauthenticated_client, db_session, test_tenant: Tenant, test_user: User
):
    headers = jwt_headers(test_user, test_tenant)
    response = await unauthenticated_client.post(API, json=_body(), headers=headers)
    assert response.status_code == 201, response.text
    created = response.json()
    secret = created["token"]
    assert secret.startswith("bvt_")
    assert created["token_prefix"] == secret[:12]
    assert created["scopes"] == ["read", "write"]
    assert created["status"] == "active"
    assert created["last_used_at"] is None

    listed = await unauthenticated_client.get(API, headers=headers)
    assert listed.status_code == 200
    assert secret not in listed.text
    assert listed.json()["total"] == 1
    assert "token" not in listed.json()["items"][0]

    row = await db_session.get(ApiToken, created["id"])
    assert row.token_hash == hash_token(secret)


async def test_same_name_twice_is_allowed(
    unauthenticated_client, test_tenant: Tenant, test_user: User
):
    headers = jwt_headers(test_user, test_tenant)
    for _ in range(2):
        response = await unauthenticated_client.post(API, json=_body(name="Same"), headers=headers)
        assert response.status_code == 201
    listed = await unauthenticated_client.get(API, headers=headers)
    assert [t["name"] for t in listed.json()["items"]] == ["Same", "Same"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 101},
        {"scopes": []},
        {"scopes": ["admin"]},
        {"expires_at": None},
        {"expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()},
        {"expires_at": (datetime.now(timezone.utc) + timedelta(days=366)).isoformat()},
        {"expires_at": (datetime.now() + timedelta(days=10)).isoformat()},  # no time zone
    ],
)
async def test_create_validation(
    unauthenticated_client, test_tenant: Tenant, test_user: User, overrides
):
    body = _body(**overrides)
    if body["expires_at"] is None:
        del body["expires_at"]
    response = await unauthenticated_client.post(
        API, json=body, headers=jwt_headers(test_user, test_tenant)
    )
    assert response.status_code == 422


async def test_create_print_scope_and_one_year_expiry(
    unauthenticated_client, test_tenant: Tenant, test_user: User
):
    body = _body(
        scopes=["print"],
        expires_at=(
            datetime.now(timezone.utc) + timedelta(days=365) - timedelta(minutes=1)
        ).isoformat(),
    )
    response = await unauthenticated_client.post(
        API, json=body, headers=jwt_headers(test_user, test_tenant)
    )
    assert response.status_code == 201
    assert response.json()["scopes"] == ["print"]


# ============================================
# List
# ============================================


async def test_list_shows_only_own_tokens(
    unauthenticated_client, db_session, test_tenant: Tenant, test_user: User
):
    colleague = await make_member(db_session, test_tenant)
    await make_token(db_session, test_tenant, colleague, ["read"], name="Theirs")
    await make_token(db_session, test_tenant, test_user, ["read"], name="Mine")

    response = await unauthenticated_client.get(API, headers=jwt_headers(test_user, test_tenant))
    assert response.status_code == 200
    assert [t["name"] for t in response.json()["items"]] == ["Mine"]

    response = await unauthenticated_client.get(API, headers=jwt_headers(colleague, test_tenant))
    assert [t["name"] for t in response.json()["items"]] == ["Theirs"]


async def test_list_statuses(unauthenticated_client, db_session, test_tenant, test_user):
    await make_token(db_session, test_tenant, test_user, ["read"], name="Live")
    await make_token(db_session, test_tenant, test_user, ["read"], name="Gone", revoked=True)
    await make_token(
        db_session, test_tenant, test_user, ["read"], name="Old", expires_in=timedelta(seconds=-5)
    )
    response = await unauthenticated_client.get(API, headers=jwt_headers(test_user, test_tenant))
    statuses = {t["name"]: t["status"] for t in response.json()["items"]}
    assert statuses == {"Live": "active", "Gone": "revoked", "Old": "expired"}


# ============================================
# Revoke
# ============================================


async def test_revoke_then_token_refused(
    unauthenticated_client, db_session, test_tenant: Tenant, test_user: User
):
    token, secret = await make_token(db_session, test_tenant, test_user, ["read"])
    assert (
        await unauthenticated_client.get("/api/v1/ideas", headers=bearer(secret))
    ).status_code == 200

    headers = jwt_headers(test_user, test_tenant)
    response = await unauthenticated_client.post(f"{API}/{token.id}/revoke", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"
    revoked_at = response.json()["revoked_at"]

    again = await unauthenticated_client.post(f"{API}/{token.id}/revoke", headers=headers)
    assert again.status_code == 200
    assert again.json()["revoked_at"] == revoked_at

    refused = await unauthenticated_client.get("/api/v1/ideas", headers=bearer(secret))
    assert refused.status_code == 401


async def test_revoke_not_found(unauthenticated_client, db_session, test_tenant, test_user):
    headers = jwt_headers(test_user, test_tenant)
    response = await unauthenticated_client.post(f"{API}/{uuid4()}/revoke", headers=headers)
    assert response.status_code == 404

    colleague = await make_member(db_session, test_tenant)
    theirs, _ = await make_token(db_session, test_tenant, colleague, ["read"])
    response = await unauthenticated_client.post(f"{API}/{theirs.id}/revoke", headers=headers)
    assert response.status_code == 404


async def test_revoke_bad_uuid(unauthenticated_client, test_tenant, test_user):
    response = await unauthenticated_client.post(
        f"{API}/not-a-uuid/revoke", headers=jwt_headers(test_user, test_tenant)
    )
    assert response.status_code == 422


# ============================================
# Auth on the management routes
# ============================================


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", API),
        ("POST", API),
        ("POST", f"{API}/00000000-0000-4000-8000-000000000001/revoke"),
        ("GET", f"{API}/current"),
    ],
)
async def test_management_requires_auth(unauthenticated_client, method, path):
    response = await unauthenticated_client.request(method, path, json=_body())
    assert response.status_code == 401


async def test_management_refuses_tokens(
    unauthenticated_client, db_session, test_tenant: Tenant, test_user: User
):
    token, secret = await make_token(
        db_session, test_tenant, test_user, ["read", "write", "genai", "print"]
    )
    headers = bearer(secret)
    assert (await unauthenticated_client.get(API, headers=headers)).status_code == 403
    assert (
        await unauthenticated_client.post(API, json=_body(), headers=headers)
    ).status_code == 403
    assert (
        await unauthenticated_client.post(f"{API}/{token.id}/revoke", headers=headers)
    ).status_code == 403


# ============================================
# Current
# ============================================


async def test_current_with_token(unauthenticated_client, db_session, test_tenant, test_user):
    token, secret = await make_token(db_session, test_tenant, test_user, ["print"], name="Me")
    response = await unauthenticated_client.get(f"{API}/current", headers=bearer(secret))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(token.id)
    assert body["name"] == "Me"
    assert body["scopes"] == ["print"]
    assert body["tenant_id"] == str(test_tenant.id)
    assert body["tenant_name"] == test_tenant.name
    assert secret not in response.text


async def test_current_with_jwt_is_refused(unauthenticated_client, test_tenant, test_user):
    response = await unauthenticated_client.get(
        f"{API}/current", headers=jwt_headers(test_user, test_tenant)
    )
    assert response.status_code == 403
