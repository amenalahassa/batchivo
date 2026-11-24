"""Tests for the e2e-only verification-token hook (bug e2e-register-verification).

The hook lets the Playwright helper finish the real email-verification flow
without an email provider. These tests pin down that it is inert unless
explicitly enabled, refused in production, and never published.
"""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.main import app
from app.models.email_verification import EmailVerificationToken

HOOK_URL = "/api/v1/onboarding/test/verification-token"
REPO_ROOT = Path(__file__).resolve().parents[3]


def _override_settings(**changes) -> None:
    """Serve a copy of the real settings with the given fields changed."""
    patched = get_settings().model_copy(update=changes)
    app.dependency_overrides[get_settings] = lambda: patched


async def _pending_token(db: AsyncSession, email: str) -> EmailVerificationToken:
    token = EmailVerificationToken.create_email_verification(
        email=email, registration_data='{"business_name": "E2E Shop"}'
    )
    db.add(token)
    await db.flush()
    return token


# ============================================
# Off by default
# ============================================


def test_setting_is_off_by_default():
    """The flag defaults to False: nothing is exposed unless someone sets it."""
    assert Settings.model_fields["e2e_test_hooks_enabled"].default is False


@pytest.mark.asyncio
async def test_hook_returns_404_by_default(
    unauthenticated_client: AsyncClient, db_session: AsyncSession
):
    """With default settings the route answers 404 even for a pending registration."""
    await _pending_token(db_session, "default-off@example.com")
    _override_settings(e2e_test_hooks_enabled=False, environment="development")

    response = await unauthenticated_client.get(
        HOOK_URL, params={"email": "default-off@example.com"}
    )

    assert response.status_code == 404
    assert "token" not in response.json()


@pytest.mark.asyncio
async def test_hook_refused_in_production_even_when_enabled(
    unauthenticated_client: AsyncClient, db_session: AsyncSession
):
    """A flag set by mistake in production still exposes nothing."""
    await _pending_token(db_session, "prod@example.com")
    _override_settings(e2e_test_hooks_enabled=True, environment="production")

    response = await unauthenticated_client.get(HOOK_URL, params={"email": "prod@example.com"})

    assert response.status_code == 404
    assert "token" not in response.json()


# ============================================
# Enabled (local e2e backend)
# ============================================


@pytest.mark.asyncio
async def test_hook_returns_pending_token_when_enabled(
    unauthenticated_client: AsyncClient, db_session: AsyncSession
):
    token = await _pending_token(db_session, "e2e-user@example.com")
    _override_settings(e2e_test_hooks_enabled=True, environment="development")

    # Case-insensitive, like registration itself
    response = await unauthenticated_client.get(HOOK_URL, params={"email": "E2E-User@example.com"})

    assert response.status_code == 200
    assert response.json() == {"token": token.token}


@pytest.mark.asyncio
async def test_hook_returns_404_for_unknown_email(unauthenticated_client: AsyncClient):
    _override_settings(e2e_test_hooks_enabled=True, environment="development")

    response = await unauthenticated_client.get(HOOK_URL, params={"email": "nobody@example.com"})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_hook_returns_404_for_used_token(
    unauthenticated_client: AsyncClient, db_session: AsyncSession
):
    token = await _pending_token(db_session, "used@example.com")
    token.mark_as_used()
    await db_session.flush()
    _override_settings(e2e_test_hooks_enabled=True, environment="development")

    response = await unauthenticated_client.get(HOOK_URL, params={"email": "used@example.com"})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_hook_requires_email(unauthenticated_client: AsyncClient):
    _override_settings(e2e_test_hooks_enabled=True, environment="development")

    response = await unauthenticated_client.get(HOOK_URL)

    assert response.status_code == 422


# ============================================
# Never published
# ============================================


def test_hook_not_in_openapi_schema():
    """The route is never listed in the API docs, whatever the settings."""
    assert HOOK_URL not in app.openapi()["paths"]


def test_flag_absent_from_deployment_config():
    """No deployment manifest or instance config may switch the hook on."""
    candidates = [REPO_ROOT / "infrastructure"]
    candidates += list(REPO_ROOT.glob("docker-compose*.yml"))
    candidates += [REPO_ROOT / "deploy.sh"]
    existing = [p for p in candidates if p.exists()]
    if not existing:
        pytest.skip("deployment config not present in this checkout")

    offenders = []
    for root in existing:
        files = [root] if root.is_file() else [f for f in root.rglob("*") if f.is_file()]
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "E2E_TEST_HOOKS_ENABLED" in text.upper():
                offenders.append(str(f.relative_to(REPO_ROOT)))

    assert offenders == []


# ============================================
# Rate limiting stays on unless a local e2e run turns it off
# ============================================


def _settings(**changes) -> Settings:
    return get_settings().model_copy(update=changes)


def test_rate_limiting_on_by_default():
    from app.core.rate_limit import rate_limiting_enabled

    assert rate_limiting_enabled(Settings(secret_key="x" * 32, _env_file=None)) is True


def test_rate_limiting_on_in_test_and_dev_without_the_flag():
    from app.core.rate_limit import rate_limiting_enabled

    for environment in ("development", "test", "staging"):
        assert rate_limiting_enabled(_settings(environment=environment)) is True


def test_rate_limiting_stays_on_in_production_even_with_the_flag():
    from app.core.rate_limit import rate_limiting_enabled

    settings = _settings(environment="production", e2e_test_hooks_enabled=True)
    assert rate_limiting_enabled(settings) is True


def test_rate_limiting_off_for_a_local_e2e_run():
    from app.core.rate_limit import rate_limiting_enabled

    settings = _settings(environment="development", e2e_test_hooks_enabled=True)
    assert rate_limiting_enabled(settings) is False


def test_app_limiter_is_enforcing_by_default():
    """The process under test was started without the flag: limits apply."""
    from app.core.rate_limit import limiter

    assert get_settings().e2e_test_hooks_enabled is False
    assert limiter.enabled is True
