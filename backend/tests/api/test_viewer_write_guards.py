"""A viewer is refused every write outside pricing (bug viewer-write-guards).

Coverage of *every* non-pricing write route is derived in
`tests/unit/test_write_route_role_guards.py`; this is the behavioural sample,
one or more routes per router that was unguarded, called through the real
authorisation path. Each is called by a random id: the role is refused before
the record is looked up, so no fixture can mask a missing guard.
"""

import pytest

from app.models.user import UserRole

pytestmark = pytest.mark.asyncio

API = "/api/v1"
ANY = "00000000-0000-0000-0000-000000000001"

#: One sample per router, refused to a viewer.
VIEWER_REFUSED: list[tuple[str, str]] = [
    ("POST", "/print-queue"),
    ("POST", "/print-queue/auto-assign"),
    ("POST", f"/print-queue/{ANY}/cancel"),
    ("PATCH", f"/products/{ANY}/images/{ANY}"),
    ("DELETE", f"/products/{ANY}/images/{ANY}"),
    ("POST", "/filament-types"),
    ("POST", "/categories"),
    ("POST", f"/categories/{ANY}/products/{ANY}"),
    ("POST", "/designers"),
    ("POST", f"/models/{ANY}/files"),
    ("POST", f"/printers/{ANY}/connection/connect"),
]

#: Configuration, credentials, moderation and top-level deletes: refused to a
#: member as well as a viewer.
ADMIN_ONLY: list[tuple[str, str]] = [
    ("DELETE", f"/categories/{ANY}"),
    ("DELETE", f"/designers/{ANY}"),
    ("DELETE", f"/filament-types/{ANY}"),
    ("POST", f"/reviews/{ANY}/approve"),
    ("POST", "/webhooks/subscriptions"),
    ("POST", f"/printers/{ANY}/connection"),
    ("POST", "/models/validate-local-path"),
    ("POST", "/pages"),
    ("POST", "/spoolmandb/sync"),
]


async def _call(client, method: str, path: str):
    url = f"{API}{path}"
    if method == "DELETE":
        return await client.delete(url)
    return await client.request(method, url, json={})


class TestAViewerIsRefused:
    @pytest.mark.parametrize(("method", "path"), VIEWER_REFUSED + ADMIN_ONLY)
    async def test_refused(self, as_role, method: str, path: str) -> None:
        async with as_role(UserRole.VIEWER) as viewer:
            response = await _call(viewer, method, path)

        assert response.status_code == 403, (
            f"{method} {path} accepted a viewer ({response.status_code}); FR-007c makes "
            f"the viewer a reader"
        )


class TestAMemberIsRefusedAdministration:
    @pytest.mark.parametrize(("method", "path"), ADMIN_ONLY)
    async def test_refused(self, as_role, method: str, path: str) -> None:
        async with as_role(UserRole.MEMBER) as member:
            response = await _call(member, method, path)

        assert response.status_code == 403, f"{method} {path} accepted a member"


class TestEverySampleIsARoute:
    @pytest.mark.parametrize(("method", "path"), VIEWER_REFUSED + ADMIN_ONLY)
    async def test_exists(self, client, method: str, path: str) -> None:
        # A typo would be refused as surely as a real route, by a 404 or 405
        # rather than a 403; the administrator's call proves the route is there.
        response = await _call(client, method, path)

        assert response.status_code != 405, f"{method} {path} is not a route"
        assert not (response.status_code == 404 and response.json().get("detail") == "Not Found"), (
            f"{method} {path} is not a route"
        )


class TestAMemberStillWrites:
    async def test_a_member_creates_a_category(self, as_role) -> None:
        async with as_role(UserRole.MEMBER) as member:
            response = await member.post(f"{API}/categories", json={"name": "Dragons"})

        assert response.status_code == 201, response.text
