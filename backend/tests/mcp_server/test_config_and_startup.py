"""Startup, configuration, scope-filtered registration and secrecy of the MCP server."""

import logging
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app.mcp_server.client import BatchivoClient
from app.mcp_server.config import (
    API_TOKEN_ENV,
    API_URL_ENV,
    SecretMaskingFilter,
    StartupError,
    load_config,
    mask_secrets,
)
from app.mcp_server.server import create_server, main, tools_for_scopes
from tests.mcp_server.conftest import API, API_URL, TOKEN

BACKEND = Path(__file__).resolve().parents[2]


# ============================================
# Configuration
# ============================================


@pytest.mark.parametrize(
    "env,named",
    [
        ({}, API_URL_ENV),
        ({API_URL_ENV: "  "}, API_URL_ENV),
        ({API_URL_ENV: "http://x"}, API_TOKEN_ENV),
        ({API_URL_ENV: "http://x", API_TOKEN_ENV: ""}, API_TOKEN_ENV),
        ({API_URL_ENV: "ftp://x", API_TOKEN_ENV: TOKEN}, API_URL_ENV),
    ],
)
def test_missing_configuration_names_the_variable(env, named):
    with pytest.raises(StartupError) as exc:
        load_config(env)
    assert named in str(exc.value)
    assert TOKEN not in str(exc.value)


def test_config_trims_and_never_shows_token():
    config = load_config({API_URL_ENV: "http://api.test/ ", API_TOKEN_ENV: f" {TOKEN} "})
    assert config.api_url == "http://api.test"
    assert config.token == TOKEN
    assert TOKEN not in repr(config)


@pytest.mark.parametrize("env", [{}, {API_URL_ENV: "http://x"}])
def test_main_exits_2_on_missing_configuration(monkeypatch, capsys, env):
    # Keep pytest's own log capture: the real handler is exercised in the subprocess tests.
    monkeypatch.setattr("app.mcp_server.server.configure_logging", lambda: None)
    monkeypatch.delenv(API_URL_ENV, raising=False)
    monkeypatch.delenv(API_TOKEN_ENV, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert main([]) == 2
    err = capsys.readouterr().err
    assert (API_TOKEN_ENV if env else API_URL_ENV) in err


# ============================================
# Startup against the API
# ============================================


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_refused_token_stops_startup():
    config = load_config({API_URL_ENV: API_URL, API_TOKEN_ENV: TOKEN})
    transport = _transport(lambda request: httpx.Response(401, json={"detail": "Invalid"}))
    with pytest.raises(StartupError) as exc:
        await create_server(config, transport=transport)
    assert "refused the API token" in str(exc.value)
    assert TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_unreachable_api_stops_startup():
    config = load_config({API_URL_ENV: API_URL, API_TOKEN_ENV: TOKEN})

    def fail(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(StartupError) as exc:
        await create_server(config, transport=_transport(fail))
    assert "could not be reached" in str(exc.value)


@pytest.mark.asyncio
async def test_startup_registers_only_tools_within_scopes():
    config = load_config({API_URL_ENV: API_URL, API_TOKEN_ENV: TOKEN})
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"scopes": ["read"]})

    server, client = await create_server(config, transport=_transport(handler))
    try:
        names = {tool.name for tool in await server.list_tools()}
    finally:
        await client.aclose()
    assert str(seen[0].url) == f"{API}/api-tokens/current"
    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert {"list_ideas", "get_model", "list_spools", "get_token_info"} <= names
    assert not names & {"create_idea", "add_file_note", "prepare_print", "confirm_print"}


def test_scope_filter_by_group():
    client = BatchivoClient(API_URL, TOKEN)
    read = {s.name for s in tools_for_scopes(client, ["read"])}
    write = {s.name for s in tools_for_scopes(client, ["write"])}
    printing = {s.name for s in tools_for_scopes(client, ["print"])}
    assert "list_ideas" in read and "create_idea" not in read
    assert "create_idea" in write and "list_ideas" not in write
    assert printing == {"prepare_print", "confirm_print", "get_token_info"}


# ============================================
# Secrets
# ============================================


def test_mask_secrets():
    assert mask_secrets(f"Bearer {TOKEN} failed") == "Bearer bvt_**** failed"


def test_masking_filter_rewrites_records():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "token %s used", (TOKEN,), None)
    SecretMaskingFilter().filter(record)
    assert TOKEN not in record.getMessage()
    assert "bvt_****" in record.getMessage()


# ============================================
# Process isolation (FR-013): a real `python -m app.mcp_server`
# ============================================


def _run(code: str, env_extra: dict[str, str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in (API_URL_ENV, API_TOKEN_ENV)}
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_server_imports_no_backend_module():
    code = (
        "import sys, app.mcp_server.server\n"
        "bad = [m for m in sys.modules if m.startswith(('app.database', 'app.models', "
        "'app.config', 'app.services', 'app.api', 'app.auth', 'app.main'))]\n"
        "print('BAD' if bad else 'CLEAN', bad)\n"
    )
    result = _run(code, {})
    assert "CLEAN" in result.stdout, result.stdout + result.stderr


def test_module_exits_2_with_masked_message_when_token_refused():
    # An address nothing listens on: startup fails on reachability, never printing the token.
    result = subprocess.run(
        [sys.executable, "-m", "app.mcp_server"],
        cwd=BACKEND,
        env={
            **{k: v for k, v in os.environ.items() if k not in (API_URL_ENV, API_TOKEN_ENV)},
            API_URL_ENV: "http://127.0.0.1:9",
            API_TOKEN_ENV: TOKEN,
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "could not be reached" in result.stderr
    assert TOKEN not in result.stderr + result.stdout
