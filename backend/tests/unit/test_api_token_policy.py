"""The token route policy table stays honest (spec 010, research R5)."""

import pytest

from app.auth.api_token_policy import TOKEN_ROUTE_SCOPES, endpoint_key, iter_routes
from app.main import app

ALLOWED_SCOPES = {"read", "write", "genai", "print", "any"}

#: Route families a token must never reach (FR-008), by path prefix.
FORBIDDEN_PREFIXES = (
    "/api/v1/auth",
    "/api/v1/users",
    "/api/v1/tenant-members",
    "/api/v1/settings",
    "/api/v1/payments",
    "/api/v1/platform",
    "/api/v1/shop",
    "/api/v1/onboarding",
    "/api/v1/test",
)


def _live_routes() -> dict[tuple[str, str], str]:
    return {(method, endpoint_key(ep)): path for method, path, ep in iter_routes(app.routes)}


def test_every_entry_is_a_live_route():
    live = _live_routes()
    missing = [key for key in TOKEN_ROUTE_SCOPES if key not in live]
    assert missing == [], f"policy rows without a route (renamed handler?): {missing}"


def test_scopes_are_known():
    assert set(TOKEN_ROUTE_SCOPES.values()) <= ALLOWED_SCOPES


def test_no_forbidden_family_and_no_delete():
    live = _live_routes()
    for (method, key), _scope in TOKEN_ROUTE_SCOPES.items():
        path = live[(method, key)]
        assert method != "DELETE", key
        assert not path.startswith(FORBIDDEN_PREFIXES), path
        if path.startswith("/api/v1/api-tokens"):
            assert path == "/api/v1/api-tokens/current", path


@pytest.mark.parametrize(
    "method,path,scope",
    [
        ("GET", "/api/v1/ideas", "read"),
        ("POST", "/api/v1/ideas", "write"),
        ("POST", "/api/v1/printers/{printer_id}/prints/confirm", "print"),
        ("GET", "/api/v1/printers/{printer_id}/prints", "read"),
        ("GET", "/api/v1/api-tokens/current", "any"),
    ],
)
def test_key_routes_have_expected_scope(method, path, scope):
    by_path = {(m, p): k for (m, k), p in _live_routes().items()}
    assert TOKEN_ROUTE_SCOPES[(method, by_path[(method, path)])] == scope
