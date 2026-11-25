"""`/ideas` is reachable for 3D-print shops, new and existing (spec 007, FR-001).

`ModuleGuard` admits a path only if an enabled module declares it, so the
navigation entry, ALL_MODULES and the defaults must all carry `ideas`.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.modules import MODULE_NAVIGATION, MODULE_ORDER
from app.models.tenant import Tenant
from app.models.tenant_module import TenantModule
from app.services.tenant_module_service import (
    ALL_MODULES,
    DEFAULT_MODULES_BY_TYPE,
    TenantModuleService,
)

pytestmark = pytest.mark.asyncio


async def _ideas_route(client: AsyncClient) -> dict | None:
    response = await client.get("/api/v1/modules")
    assert response.status_code == 200
    for module in response.json()["modules"]:
        for route in module["routes"]:
            if route["path"] == "/ideas":
                return {**route, "module": module["name"], "icon_module": module["icon"]}
    return None


class TestIdeasModuleRegistration:
    async def test_new_3d_print_shop_sees_ideas(self, client: AsyncClient) -> None:
        route = await _ideas_route(client)
        assert route is not None
        assert route["module"] == "ideas"
        assert route["label"] == "Ideas"
        # `lightbulb` must exist in AppLayout's ICON_COMPONENTS.
        assert route["icon"] == "lightbulb"
        assert route["icon_module"] == "lightbulb"

    async def test_existing_shop_with_module_rows_gets_ideas(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        """A shop configured before 007 has rows for other modules, none for ideas."""
        for name in ("models", "products"):
            db_session.add(
                TenantModule(
                    id=uuid.uuid4(), tenant_id=test_tenant.id, module_name=name, enabled=True
                )
            )
        await db_session.commit()

        assert await _ideas_route(client) is not None

    async def test_disabling_ideas_hides_the_route(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        await TenantModuleService(db_session).set_module_enabled(test_tenant.id, "ideas", False)
        await db_session.commit()

        assert await _ideas_route(client) is None

    async def test_knitting_shop_does_not_get_it_by_default_but_can_enable_it(
        self, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        test_tenant.tenant_type = "hand_knitting"
        await db_session.commit()
        service = TenantModuleService(db_session)

        assert "ideas" not in await service.get_enabled_modules(test_tenant.id)
        await service.set_module_enabled(test_tenant.id, "ideas", True)
        await db_session.commit()
        assert "ideas" in await service.get_enabled_modules(test_tenant.id)


def test_every_navigation_module_is_known() -> None:
    assert set(MODULE_NAVIGATION) <= set(ALL_MODULES)
    assert "ideas" in DEFAULT_MODULES_BY_TYPE["three_d_print"]
    assert MODULE_ORDER["ideas"] == 11
