"""`/users/me` reports the caller's role in their tenant (task T127).

The console has to decide what to *offer*, not what to allow. FR-007c says a
viewer sees every cost and margin; the edge case beneath it says every editable
control is "unavailable rather than hidden", so the figures stay explainable.
A screen cannot grey out a control it has no role to grey it out for, which is
why the role travels on the profile.

What it is **not**: authorisation. That stays on the endpoint, where
`require_role` refuses the write regardless of what the client believed
(FR-007d). These tests therefore assert the role is *reported*, and the
pricing-policy tests assert the refusal still happens.
"""

import pytest
from httpx import AsyncClient

from app.models.user import UserRole

pytestmark = pytest.mark.asyncio

ENDPOINT = "/api/v1/users/me"


class TestTheProfileCarriesTheRole:
    async def test_an_admin_sees_their_role(self, client: AsyncClient) -> None:
        """The default fixture user is an admin, so the policy screen may edit."""
        response = await client.get(ENDPOINT)

        assert response.status_code == 200
        assert response.json()["role"] == "admin"

    @pytest.mark.parametrize(
        "role",
        [UserRole.OWNER, UserRole.ADMIN, UserRole.MEMBER, UserRole.VIEWER],
    )
    async def test_every_role_is_reported_by_its_own_name(self, as_role, role: UserRole) -> None:
        """Each of the four roles round-trips as the string the console checks.

        The column is a `String(50)` holding a `UserRole` value, so the member
        could reach the wire as `"UserRole.VIEWER"` instead of `"viewer"`. A
        console comparing against `"viewer"` would then quietly treat a viewer
        as privileged, which is the failure this asserts away.
        """
        async with as_role(role) as ac:
            response = await ac.get(ENDPOINT)

        assert response.status_code == 200
        assert response.json()["role"] == role.value

    async def test_unauthenticated_is_refused(self, unauthenticated_client: AsyncClient) -> None:
        response = await unauthenticated_client.get(ENDPOINT)
        assert response.status_code == 401
