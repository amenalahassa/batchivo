"""Configuration and logging of the MCP server (spec 010, research R10-R11).

The token comes from the environment and is never printed: every log record
and every message on stderr passes through `SecretMaskingFilter`.
"""

import logging
import os
import re
import sys
from dataclasses import dataclass

API_URL_ENV = "BATCHIVO_API_URL"
API_TOKEN_ENV = "BATCHIVO_API_TOKEN"

#: Exit code for a startup failure (configuration, refused token, API unreachable).
EXIT_STARTUP_FAILURE = 2

_SECRET = re.compile(r"bvt_[A-Za-z0-9_\-]+")


def mask_secrets(text: str) -> str:
    """Replace every personal API token in `text` by `bvt_****`."""
    return _SECRET.sub("bvt_****", text)


class SecretMaskingFilter(logging.Filter):
    """Rewrites log records so no token survives into a log line."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        masked = mask_secrets(message)
        if masked != message:
            record.msg = masked
            record.args = None
        return True


class StartupError(Exception):
    """A failure that stops the server before it serves (exit code 2)."""


@dataclass(frozen=True)
class McpConfig:
    """Where Batchivo is and which token to present."""

    api_url: str
    token: str

    def __repr__(self) -> str:  # never show the token, even in a traceback
        return f"McpConfig(api_url={self.api_url!r}, token='bvt_****')"


def load_config(environ: dict[str, str] | None = None) -> McpConfig:
    """Read and check the environment; raise `StartupError` naming what is missing."""
    env = os.environ if environ is None else environ
    api_url = (env.get(API_URL_ENV) or "").strip().rstrip("/")
    token = (env.get(API_TOKEN_ENV) or "").strip()
    if not api_url:
        raise StartupError(
            f"{API_URL_ENV} is not set: give the Batchivo address, e.g. http://localhost:8000"
        )
    if not api_url.startswith(("http://", "https://")):
        raise StartupError(f"{API_URL_ENV} must start with http:// or https://")
    if not token:
        raise StartupError(
            f"{API_TOKEN_ENV} is not set: create a token in Batchivo, Settings > API tokens"
        )
    return McpConfig(api_url=api_url, token=token)


def configure_logging(level: int = logging.INFO) -> None:
    """Log to stderr (stdout carries the MCP protocol), with secrets masked."""
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(SecretMaskingFilter())
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "httpx2", "httpcore2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
