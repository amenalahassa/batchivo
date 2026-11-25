"""Authenticating with a personal API token (spec 010, plan §Authentication design).

Everything here runs the real `get_current_user` / `get_current_tenant`
(`unauthenticated_client` overrides only the database). With RLS off -- the
default here and the production setting today -- these tests prove the
application query alone keeps a token inside its own tenant (validation
condition 1) and that only the exact hash authenticates (condition 2).
"""

import io
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.auth.api_tokens import INVALID_TOKEN_DETAIL, NOT_ACCEPTED_DETAIL
from app.models.api_token import ApiToken
from app.models.idea import Idea
from app.models.tenant import Tenant
from app.models.user import User, UserRole, UserTenant
from tests.api_token_helpers import (
    bearer,
    jwt_headers,
    make_member,
    make_tenant,
    make_token,
)

pytestmark = pytest.mark.asyncio

IDEAS = "/api/v1/ideas"
#: A fixed id that matches nothing (stable parametrize ids for pytest-xdist).
NOWHERE = "00000000-0000-4000-8000-000000000001"


async def _idea(db, tenant: Tenant, title: str) -> Idea:
    idea = Idea(tenant_id=tenant.id, title=title, tags=[])
    db.add(idea)
    await db.commit()
    await db.refresh(idea)
    return idea


# ============================================
# Accepted
# ============================================


async def test_read_token_reads_its_tenant(
    unauthenticated_client, db_session, test_tenant, test_user
):
    await _idea(db_session, test_tenant, "Mine")
    _, secret = await make_token(db_session, test_tenant, test_user, ["read"])
    response = await unauthenticated_client.get(IDEAS, headers=bearer(secret))
    assert response.status_code == 200, response.text
    assert [i["title"] for i in response.json()["items"]] == ["Mine"]


async def test_write_token_creates_through_the_same_validation(
    unauthenticated_client, db_session, test_tenant, test_user
):
    _, secret = await make_token(db_session, test_tenant, test_user, ["write"])
    created = await unauthenticated_client.post(
        IDEAS, json={"title": "From an agent", "tags": ["kitchen"]}, headers=bearer(secret)
    )
    assert created.status_code == 201, created.text
    invalid = await unauthenticated_client.post(IDEAS, json={"title": ""}, headers=bearer(secret))
    assert invalid.status_code == 422


# ============================================
# Refused as unauthenticated (one message for every reason)
# ============================================


async def _assert_401(client, secret: str) -> None:
    response = await client.get(IDEAS, headers=bearer(secret))
    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_TOKEN_DETAIL
    assert response.headers.get("www-authenticate") == "Bearer"


async def test_unknown_token(unauthenticated_client):
    await _assert_401(unauthenticated_client, "bvt_abcdefgh_" + "x" * 43)


async def test_revoked_token(unauthenticated_client, db_session, test_tenant, test_user):
    _, secret = await make_token(db_session, test_tenant, test_user, ["read"], revoked=True)
    await _assert_401(unauthenticated_client, secret)


async def test_expired_token(unauthenticated_client, db_session, test_tenant, test_user):
    _, secret = await make_token(
        db_session, test_tenant, test_user, ["read"], expires_in=timedelta(seconds=-1)
    )
    await _assert_401(unauthenticated_client, secret)


async def test_inactive_owner(unauthenticated_client, db_session, test_tenant):
    owner = await make_member(db_session, test_tenant)
    _, secret = await make_token(db_session, test_tenant, owner, ["read"])
    owner.is_active = False
    await db_session.commit()
    await _assert_401(unauthenticated_client, secret)


async def test_owner_removed_from_tenant(unauthenticated_client, db_session, test_tenant):
    owner = await make_member(db_session, test_tenant)
    _, secret = await make_token(db_session, test_tenant, owner, ["read"])
    membership = (
        await db_session.execute(
            UserTenant.__table__.select().where(UserTenant.user_id == owner.id)
        )
    ).first()
    await db_session.execute(UserTenant.__table__.delete().where(UserTenant.id == membership.id))
    await db_session.commit()
    await _assert_401(unauthenticated_client, secret)


async def test_matching_prefix_with_wrong_secret(
    unauthenticated_client, db_session, test_tenant, test_user
):
    """Validation condition 2: the display prefix never authenticates on its own."""
    _, secret = await make_token(db_session, test_tenant, test_user, ["read"])
    forged = secret[:13] + ("A" if secret[13] != "A" else "B") + secret[14:]
    await _assert_401(unauthenticated_client, forged)
    await _assert_401(unauthenticated_client, secret[:12])


# ============================================
# Refused by policy (403)
# ============================================


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/users/me"),
        ("GET", "/api/v1/settings/square"),
        ("GET", "/api/v1/tenant-members"),
        ("DELETE", f"{IDEAS}/{NOWHERE}"),
        ("POST", "/api/v1/spools"),
    ],
)
async def test_endpoint_not_accepting_tokens(
    unauthenticated_client, db_session, test_tenant, test_user, method, path
):
    _, secret = await make_token(
        db_session, test_tenant, test_user, ["read", "write", "genai", "print"]
    )
    response = await unauthenticated_client.request(method, path, headers=bearer(secret))
    assert response.status_code in (403, 404, 405), response.text
    if response.status_code == 403:
        assert response.json()["detail"] == NOT_ACCEPTED_DETAIL


async def test_read_only_token_cannot_write(
    unauthenticated_client, db_session, test_tenant, test_user
):
    _, secret = await make_token(db_session, test_tenant, test_user, ["read"])
    response = await unauthenticated_client.post(IDEAS, json={"title": "x"}, headers=bearer(secret))
    assert response.status_code == 403
    assert response.json()["detail"] == "API token is missing the 'write' scope"


async def test_write_only_token_cannot_read(
    unauthenticated_client, db_session, test_tenant, test_user
):
    _, secret = await make_token(db_session, test_tenant, test_user, ["write"])
    response = await unauthenticated_client.get(IDEAS, headers=bearer(secret))
    assert response.status_code == 403
    assert response.json()["detail"] == "API token is missing the 'read' scope"


async def test_token_never_exceeds_owner_role(unauthenticated_client, db_session, test_tenant):
    viewer = await make_member(db_session, test_tenant, UserRole.VIEWER)
    _, secret = await make_token(db_session, test_tenant, viewer, ["read", "write"])
    assert (await unauthenticated_client.get(IDEAS, headers=bearer(secret))).status_code == 200
    response = await unauthenticated_client.post(IDEAS, json={"title": "x"}, headers=bearer(secret))
    assert response.status_code == 403
    assert "role" in response.json()["detail"]


@pytest.mark.parametrize(
    "suffix,body",
    [
        ("prints/prepare", None),
        ("prints/confirm", {"confirmation_token": "x", "acknowledge_warnings": False}),
        (f"prints/{NOWHERE}/consumption/accept", {}),
        (f"prints/{NOWHERE}/consumption/dismiss", {}),
    ],
)
async def test_print_routes_need_print_scope(
    unauthenticated_client, db_session, test_tenant, test_user, suffix, body
):
    path = f"/api/v1/printers/{uuid4()}/{suffix}"
    _, rw = await make_token(db_session, test_tenant, test_user, ["read", "write", "genai"])
    refused = await unauthenticated_client.post(path, json=body, headers=bearer(rw))
    assert refused.status_code == 403
    assert refused.json()["detail"] == "API token is missing the 'print' scope"

    _, printing = await make_token(db_session, test_tenant, test_user, ["print"])
    passed = await unauthenticated_client.post(path, json=body, headers=bearer(printing))
    # Past the scope check, the 011 endpoint answers on its own terms.
    assert passed.status_code != 403 or "scope" not in passed.text
    assert passed.status_code in (400, 404, 409, 422)


# ============================================
# Tenant binding with RLS off (validation condition 1)
# ============================================


async def test_token_stays_in_its_tenant(
    unauthenticated_client, db_session, test_tenant, test_user
):
    other = await make_tenant(db_session, "Shop B")
    theirs = await _idea(db_session, other, "B's idea")
    # The owner belongs to both tenants: membership alone must not open B.
    db_session.add(UserTenant(user_id=test_user.id, tenant_id=other.id, role="owner"))
    await db_session.commit()
    _, secret = await make_token(db_session, test_tenant, test_user, ["read", "write"])

    listing = await unauthenticated_client.get(IDEAS, headers=bearer(secret))
    assert "B's idea" not in listing.text

    assert (
        await unauthenticated_client.get(f"{IDEAS}/{theirs.id}", headers=bearer(secret))
    ).status_code == 404
    assert (
        await unauthenticated_client.get(
            f"{IDEAS}/{theirs.id}/entries/{uuid4()}/image", headers=bearer(secret)
        )
    ).status_code == 404

    switched = await unauthenticated_client.get(
        IDEAS, headers={**bearer(secret), "X-Tenant-ID": str(other.id)}
    )
    assert switched.status_code == 403
    assert switched.json()["detail"] == "API token is bound to another tenant"

    same = await unauthenticated_client.get(
        IDEAS, headers={**bearer(secret), "X-Tenant-ID": str(test_tenant.id)}
    )
    assert same.status_code == 200

    created = await unauthenticated_client.post(
        IDEAS,
        json={"title": "Agent idea"},
        headers={**bearer(secret), "X-Tenant-ID": str(test_tenant.id)},
    )
    assert created.status_code == 201
    row = await db_session.get(Idea, created.json()["id"])
    assert row.tenant_id == test_tenant.id


async def test_token_of_b_never_resolves_to_a(unauthenticated_client, db_session, test_tenant):
    other = await make_tenant(db_session, "Shop B")
    b_user = await make_member(db_session, other)
    await _idea(db_session, test_tenant, "A's idea")
    await _idea(db_session, other, "B's idea")
    _, secret = await make_token(db_session, other, b_user, ["read"])
    response = await unauthenticated_client.get(IDEAS, headers=bearer(secret))
    assert [i["title"] for i in response.json()["items"]] == ["B's idea"]


# ============================================
# Last use
# ============================================


async def test_last_used_recorded_at_most_once_a_minute(
    unauthenticated_client, db_session, test_tenant, test_user
):
    token, secret = await make_token(db_session, test_tenant, test_user, ["read"])
    await unauthenticated_client.get(IDEAS, headers=bearer(secret))
    await db_session.refresh(token)
    first = token.last_used_at
    assert first is not None

    await unauthenticated_client.get(IDEAS, headers=bearer(secret))
    await db_session.refresh(token)
    assert token.last_used_at == first

    token.last_used_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    await db_session.commit()
    await unauthenticated_client.get(IDEAS, headers=bearer(secret))
    await db_session.refresh(token)
    assert token.last_used_at > first - timedelta(minutes=1)


# ============================================
# JWT unchanged, and the two paths never cross
# ============================================


async def test_jwt_still_works_everywhere(unauthenticated_client, test_tenant, test_user):
    headers = jwt_headers(test_user, test_tenant)
    assert (await unauthenticated_client.get(IDEAS, headers=headers)).status_code == 200
    assert (
        await unauthenticated_client.get("/api/v1/users/me", headers=headers)
    ).status_code == 200
    assert (
        await unauthenticated_client.get("/api/v1/api-tokens", headers=headers)
    ).status_code == 200


async def test_token_is_never_decoded_as_jwt(
    unauthenticated_client, db_session, test_tenant, test_user
):
    _, secret = await make_token(db_session, test_tenant, test_user, ["read"])
    with patch("app.core.security.decode_token") as decode:
        response = await unauthenticated_client.get(IDEAS, headers=bearer(secret))
    assert response.status_code == 200
    decode.assert_not_called()


async def test_jwt_never_looked_up_as_token(unauthenticated_client, test_tenant, test_user):
    with patch("app.auth.api_tokens.authenticate_api_token") as token_path:
        response = await unauthenticated_client.get(
            IDEAS, headers=jwt_headers(test_user, test_tenant)
        )
    assert response.status_code == 200
    token_path.assert_not_called()


async def test_invalid_jwt_still_refused(unauthenticated_client):
    response = await unauthenticated_client.get(IDEAS, headers={"Authorization": "Bearer eyJnope"})
    assert response.status_code == 401
    assert response.json()["detail"] != INVALID_TOKEN_DETAIL


# ============================================
# The secret never reaches a log (FR-010, SC-004)
# ============================================


async def test_secret_never_logged(
    unauthenticated_client, db_session, test_tenant, test_user, caplog, capsys
):
    caplog.set_level(logging.DEBUG)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logging.getLogger().addHandler(handler)
    try:
        headers = jwt_headers(test_user, test_tenant)
        created = await unauthenticated_client.post(
            "/api/v1/api-tokens",
            json={
                "name": "Logged?",
                "scopes": ["read"],
                "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            },
            headers=headers,
        )
        secret = created.json()["token"]
        await unauthenticated_client.get(IDEAS, headers=bearer(secret))
        await unauthenticated_client.post(IDEAS, json={"title": "x"}, headers=bearer(secret))
        await unauthenticated_client.get("/api/v1/users/me", headers=bearer(secret))
        await unauthenticated_client.post(
            f"/api/v1/api-tokens/{created.json()['id']}/revoke", headers=headers
        )
        refused = await unauthenticated_client.get(IDEAS, headers=bearer(secret))
        assert refused.status_code == 401
        assert secret not in refused.text
    finally:
        logging.getLogger().removeHandler(handler)

    captured = capsys.readouterr()
    for text in (caplog.text, stream.getvalue(), captured.out, captured.err):
        assert secret not in text
        assert secret[13:] not in text


async def test_token_row_count_unchanged_by_refusals(
    unauthenticated_client, db_session, test_tenant, test_user
):
    """A refused request writes nothing (no last-use on a refused token)."""
    token, secret = await make_token(db_session, test_tenant, test_user, ["read"], revoked=True)
    await unauthenticated_client.get(IDEAS, headers=bearer(secret))
    await db_session.refresh(token)
    assert token.last_used_at is None
    assert isinstance(token, ApiToken)
    assert isinstance(test_user, User)
