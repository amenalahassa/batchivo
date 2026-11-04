"""`/consumables` and `/designers` are reachable (bug consumables-module-never-enabled).

Packaging is set up on the consumables page. The `consumables` and `designers`
modules had navigation in `MODULE_NAVIGATION` but were missing from
`ALL_MODULES` and the 3D-print defaults, so they were never enabled: the nav had
no entry, `ModuleGuard` refused the URL, and the module settings could not turn
them on.
"""

import pytest
from httpx import AsyncClient

from app.api.v1.modules import MODULE_NAVIGATION
from app.services.tenant_module_service import ALL_MODULES


async def _routes(client: AsyncClient) -> list[dict]:
    response = await client.get("/api/v1/modules")
    assert response.status_code == 200
    return [route for module in response.json()["modules"] for route in module["routes"]]


@pytest.mark.asyncio
class TestConsumablesAndDesignersAreReachable:
    async def test_consumables_is_in_the_nav_of_a_3d_print_tenant(
        self, client: AsyncClient
    ) -> None:
        paths = {route["path"] for route in await _routes(client)}

        assert "/consumables" in paths

    async def test_designers_is_in_the_nav_of_a_3d_print_tenant(self, client: AsyncClient) -> None:
        paths = {route["path"] for route in await _routes(client)}

        assert "/designers" in paths

    async def test_consumables_carries_a_label_and_icon(self, client: AsyncClient) -> None:
        entry = next(route for route in await _routes(client) if route["path"] == "/consumables")

        assert entry["label"] == "Consumables"
        assert entry["icon"] == "wrench"


def test_every_module_with_navigation_can_be_enabled() -> None:
    """A module with nav that is not in ALL_MODULES is silently never enabled."""
    missing = sorted(set(MODULE_NAVIGATION) - set(ALL_MODULES))

    assert missing == []
