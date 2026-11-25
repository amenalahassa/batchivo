"""Rate limiting configuration using SlowAPI."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import Settings

# Create limiter instance with IP-based rate limiting
limiter = Limiter(key_func=get_remote_address)


def rate_limiting_enabled(settings: Settings) -> bool:
    """Whether the limiter enforces its limits for this process.

    Always on, except for a local Playwright run that registers many throwaway
    users from one IP: E2E_TEST_HOOKS_ENABLED switches it off there. Production
    keeps it on even when that flag is set.
    """
    return settings.is_production or not settings.e2e_test_hooks_enabled


# Rate limit configurations for different endpoint types
AUTH_RATE_LIMIT = "5/minute"  # Login, register, password reset attempts
FORGOT_PASSWORD_RATE_LIMIT = "3/minute"  # More restrictive for password reset requests
API_RATE_LIMIT = "100/minute"  # General API endpoints
