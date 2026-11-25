"""`/scenarios` is a route the console is allowed to reach (task T132).

The frontend's `ModuleGuard` does not keep its own list of permitted paths: it
asks `GET /api/v1/modules` and admits a path only if some enabled module
declares it. A page added to the router but not to `MODULE_NAVIGATION` is
therefore rendered as "not available for your plan", which is how FR-044's
catalogue shock would stay unreachable even with a route pointing at it.

This test is the one that fails if the navigation entry is ever dropped while
the route stays.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _routes(client: AsyncClient) -> list[dict]:
    response = await client.get("/api/v1/modules")
    assert response.status_code == 200
    return [route for module in response.json()["modules"] for route in module["routes"]]


class TestTheScenariosRouteIsReachable:
    async def test_some_enabled_module_declares_it(self, client: AsyncClient) -> None:
        paths = {route["path"] for route in await _routes(client)}

        assert "/scenarios" in paths, (
            "ModuleGuard admits a path only if an enabled module declares it, so "
            "dropping this entry hides the scenarios page the router still serves"
        )

    async def test_it_carries_a_label_and_an_icon_the_sidebar_can_render(
        self, client: AsyncClient
    ) -> None:
        """A nav item with no icon name falls back to a blank in the sidebar."""
        entry = next(route for route in await _routes(client) if route["path"] == "/scenarios")

        assert entry["label"] == "Scenarios"
        # `trending-up` has to exist in AppLayout's ICON_COMPONENTS map; a name
        # that is not there renders nothing and the row looks broken.
        assert entry["icon"] == "trending-up"

    async def test_it_sits_with_the_catalogue_it_sweeps(self, client: AsyncClient) -> None:
        """A shock prices every product, so it belongs to the products module.

        Were it declared by a module a 3D-print tenant does not have, the page
        would vanish for exactly the operators it is for.
        """
        response = await client.get("/api/v1/modules")
        owning = [
            module["name"]
            for module in response.json()["modules"]
            if any(route["path"] == "/scenarios" for route in module["routes"])
        ]

        assert owning == ["products"]
