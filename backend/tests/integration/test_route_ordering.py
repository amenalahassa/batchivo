"""Regression tests for static-vs-dynamic route ordering under /api/v1/models.

These specifically run against a real TCP server (uvicorn.Server), not the
in-process ASGITransport the other integration tests use. The in-process
ASGITransport test client (used by the `client`/`async_client` fixtures)
does NOT reproduce the bug below - only a real HTTP request through
Starlette's actual routing stack does - which is how it went uncaught by
the existing test suite:

- GET /api/v1/models/export was being swallowed by GET /{model_id} (confirmed
  with a real server, both before and after this fix), because the static
  /export route was defined after the dynamic /{model_id} route in the same
  router (models.py). "export" was coerced into the model_id UUID path
  param and failed validation (422) instead of reaching the real handler.

The POST /api/v1/models/files/parse-3mf case is also covered here as a
defensive check for the same static-vs-dynamic hazard across the
model_files.router / models.router split (both included at the "/models"
prefix) - that specific 404 was reproduced against a long-running --reload
dev server, but not against a freshly-started one, so it looks like a
--reload staleness artifact rather than a routing defect; no code change
was needed for it. Kept here anyway as regression coverage.
"""

import asyncio
import io
import socket
import zipfile

import httpx
import pytest
import uvicorn

from app.auth.dependencies import get_current_tenant, get_current_user, get_tenant_db
from app.database import get_db
from app.main import app
from app.models.tenant import Tenant
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def real_server_base_url(db_session: AsyncSession, test_user: User, test_tenant: Tenant):
    """Run the real app on a real TCP socket, reusing the test DB session."""

    async def override_get_db():
        yield db_session

    async def override_get_current_user():
        return test_user

    async def override_get_current_tenant():
        return test_tenant

    app.dependency_overrides[get_db] = override_get_db
    # `TenantDB` endpoints resolve through `get_tenant_db`, which otherwise
    # opens its own session against the real engine (task T155).
    app.dependency_overrides[get_tenant_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_current_tenant] = override_get_current_tenant
    app.state.limiter.enabled = False

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())

    try:
        base_url = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as probe:
            for _ in range(50):
                try:
                    await probe.get("/health")
                    break
                except httpx.TransportError:
                    await asyncio.sleep(0.05)
        yield base_url
    finally:
        server.should_exit = True
        await task
        app.state.limiter.enabled = True
        app.dependency_overrides.clear()


class TestStaticRoutesNotSwallowedByDynamicRoutes:
    """Static routes must win over same-shaped dynamic routes, over a real HTTP connection."""

    @pytest.mark.asyncio
    async def test_export_route_not_swallowed_by_model_id_route(self, real_server_base_url):
        async with httpx.AsyncClient(base_url=real_server_base_url, timeout=5.0) as client:
            response = await client.get("/api/v1/models/export")

        # A 422 here means "export" was coerced into the {model_id} UUID
        # path parameter instead of reaching the real /export handler.
        assert response.status_code != 422, response.text
        assert response.status_code == 200, response.text
        assert "ID,Name,SKU" in response.text

    @pytest.mark.asyncio
    async def test_parse_3mf_route_not_swallowed_by_other_router(self, real_server_base_url):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("dummy.txt", "not slicer metadata")
        zip_buffer.seek(0)

        async with httpx.AsyncClient(base_url=real_server_base_url, timeout=5.0) as client:
            response = await client.post(
                "/api/v1/models/files/parse-3mf",
                files={"file": ("test.3mf", zip_buffer, "application/octet-stream")},
            )

        # A 404 here means model_files.router's static route was never
        # reached because models.router (included first) claimed the
        # (POST, 2-path-segments) slot with a dynamic route instead.
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["thumbnail_available"] is False
