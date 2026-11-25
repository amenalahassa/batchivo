"""Keep provider tokens out of the logs (spec 008 FR-021, SC-006, research R9).

Every record from a genai or HTTP-client logger, children included
(``app.services.genai.runner``, ``app.api.v1.genai_settings``, ``httpcore.http11``…),
has any Replicate token (``r8_…``) or bearer value in its message and arguments
rewritten when it is created. A filter on a parent logger would not do: Python
applies a logger's filters only to records logged through that very logger, not to
those propagated from its children. It is defence in depth: the code never logs a
token on purpose.
"""

import logging
import re

_PATTERNS = (
    re.compile(r"r8_[A-Za-z0-9]+"),
    # A personal API token already masked by spec 010 (`bvt_****`) stays as it is.
    re.compile(r"(?i)(bearer\s+)(?!bvt_\*{4})[A-Za-z0-9._\-]+"),
)
REDACTED = "[redacted]"

LOGGER_NAMES = (
    "app.services.genai",
    "app.tasks.genai",
    "app.api.v1.genai",
    "httpx",
    "httpcore",
)
#: ``app.api.v1.genai`` also covers its sibling modules ``genai_settings``, ``genai_platform``…
_PREFIX_ONLY = ("app.api.v1.genai",)


def covers(name: str) -> bool:
    """Whether records of the logger ``name`` are redacted."""
    for root in LOGGER_NAMES:
        if name == root or name.startswith(root + "."):
            return True
    return any(name.startswith(prefix) for prefix in _PREFIX_ONLY)


def redact(text: str) -> str:
    """The text with every token-looking value replaced."""
    text = _PATTERNS[0].sub(REDACTED, text)
    return _PATTERNS[1].sub(lambda m: m.group(1) + REDACTED, text)


#: Field names whose value is a Replicate secret, whatever it looks like.
SECRET_KEYS = frozenset({"api_token", "api_token_encrypted", "webhook_secret_encrypted"})


def scrub(value):
    """A copy of ``value`` (an error-report event, a request body…) with no token.

    Values under a ``SECRET_KEYS`` key are blanked; every string is redacted.
    Used by the Sentry ``before_send`` hook, whose default scrubber matches only
    a few exact key names and leaves a JSON request body as it is.
    """
    if isinstance(value, dict):
        return {
            k: REDACTED if isinstance(k, str) and k in SECRET_KEYS else scrub(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, tuple):
        return tuple(scrub(v) for v in value)
    if isinstance(value, str):
        return redact(value)
    return value


class TokenRedactingFilter(logging.Filter):
    """Rewrites a record so that it carries no token."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - logging API
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a broken record must still be logged
            return True
        cleaned = redact(message)
        if cleaned != message or record.args:
            record.msg = cleaned
            record.args = None
        return True


_FILTER = TokenRedactingFilter()


def _redacting_factory(previous):
    def factory(*args, **kwargs) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        if covers(record.name):
            _FILTER.filter(record)
        return record

    factory._genai_redacting = True  # type: ignore[attr-defined]
    return factory


def install() -> None:
    """Redact every record of the genai and HTTP-client loggers and their children.

    Idempotent. The record factory catches records of child loggers, which a filter
    on the parent never sees; the filter on each named logger stays for records
    built by a factory installed later by someone else.
    """
    current = logging.getLogRecordFactory()
    if not getattr(current, "_genai_redacting", False):
        logging.setLogRecordFactory(_redacting_factory(current))
    for name in LOGGER_NAMES:
        logger = logging.getLogger(name)
        if _FILTER not in logger.filters:
            logger.addFilter(_FILTER)


install()

__all__ = [
    "REDACTED",
    "SECRET_KEYS",
    "TokenRedactingFilter",
    "covers",
    "install",
    "redact",
    "scrub",
]
