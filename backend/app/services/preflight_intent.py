"""Validation of a Preflight intent document (spec 009, research R3).

The Preflight skill writes a part's intended use as ``intent.yaml``
(``templates/intent.yaml``, schema version 1) and checks it with
``pf.py validate``. Batchivo stores that document exactly as written and checks
the same things here, once, for the API, the MCP tools and the screens alike:

* ``schema_version`` must be 1;
* enumerated values (load duration and unit, interface fit, value status, sales
  channel) must be one of Preflight's, or the placeholder ``[À PRÉCISER]``;
* everything else -- extra keys included -- is kept untouched.

The report has the shape of ``pf.py validate``: the placeholders still to
clarify, the values still only inferred (``déduit``) or estimated
(``estimée``), and the required keys not there yet. Missing keys are reported,
not refused, so a half-filled intent from the ``intent`` step can be saved.
"""

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Any, Iterator

import yaml

PLACEHOLDER = "[À PRÉCISER]"
SCHEMA_VERSION = 1
MAX_DOCUMENT_BYTES = 256 * 1024

ENUMS: dict[str, frozenset[str]] = {
    "duration": frozenset({"permanent", "cyclic", "shock", "short"}),
    "unit": frozenset({"kg", "N"}),
    "fit": frozenset({"slide", "press", "snap", "screw", "insert", "print-in-place", "none"}),
    "status": frozenset({"déduit", "estimée", "validé", "mesurée"}),
    "sales_channel": frozenset({"etsy", "makerworld", "shop", "none"}),
}
REQUIRED_KEYS = (
    "schema_version",
    "function",
    "loads",
    "environment",
    "interfaces",
    "success_criteria",
)
UNCONFIRMED_STATUSES = ("déduit", "estimée")

Loc = tuple[str | int, ...]


class IntentInvalid(ValueError):
    """The document breaks Preflight's schema; ``errors`` lists (location, message)."""

    def __init__(self, errors: list[tuple[Loc, str]]):
        self.errors = errors
        super().__init__("; ".join(f"{_dotted(loc)}: {msg}" for loc, msg in errors))


@dataclass
class IntentReport:
    """What ``pf.py validate`` reports besides errors."""

    to_clarify: list[str] = field(default_factory=list)
    unconfirmed: list[dict[str, str]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "to_clarify": self.to_clarify,
            "unconfirmed": self.unconfirmed,
            "missing": self.missing,
        }


def _dotted(loc: Loc) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def is_unknown(value: Any) -> bool:
    return value is None or (isinstance(value, str) and PLACEHOLDER in value)


def _jsonable(node: Any) -> Any:
    """YAML gives dates and datetimes; the stored document is plain JSON."""
    if isinstance(node, dict):
        return {str(k): _jsonable(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_jsonable(v) for v in node]
    if isinstance(node, (dt.date, dt.datetime)):
        return node.isoformat()
    return node


def parse_yaml_mapping(text: str, what: str = "document") -> dict[str, Any]:
    """A YAML (or JSON) text as a JSON-safe mapping; anything else is refused."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        raise IntentInvalid([((what,), f"is not valid YAML or JSON{where}")]) from None
    if not isinstance(data, dict):
        raise IntentInvalid([((what,), "must be a mapping of fields")])
    return _jsonable(data)


def check_size(document: Any, what: str) -> None:
    size = len(json.dumps(document, ensure_ascii=False, default=str).encode())
    if size > MAX_DOCUMENT_BYTES:
        raise IntentInvalid([((what,), f"is larger than {MAX_DOCUMENT_BYTES // 1024} KB")])


def _walk(node: Any, loc: Loc = ()) -> Iterator[tuple[Loc, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, (*loc, key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, (*loc, index))
    else:
        yield loc, node


def _enum_error(enum: str, value: Any) -> str:
    allowed = ", ".join(sorted(ENUMS[enum]))
    return f"must be one of {allowed} or {PLACEHOLDER} (got {value!r})"


def validate_intent(document: dict[str, Any]) -> IntentReport:
    """Check ``document`` like ``pf.py validate``; raise :class:`IntentInvalid` on errors."""
    if not isinstance(document, dict):
        raise IntentInvalid([(("intent",), "must be a mapping of fields")])
    check_size(document, "intent")
    errors: list[tuple[Loc, str]] = []
    report = IntentReport()

    version = document.get("schema_version")
    if version != SCHEMA_VERSION:
        errors.append((("schema_version",), f"must be {SCHEMA_VERSION} (got {version!r})"))

    loads = document.get("loads")
    for index, load in enumerate(loads if isinstance(loads, list) else []):
        if not isinstance(load, dict):
            continue
        duration = load.get("duration")
        if not is_unknown(duration) and duration not in ENUMS["duration"]:
            errors.append((("loads", index, "duration"), _enum_error("duration", duration)))
        unit = load.get("unit")
        if unit is not None and not is_unknown(unit) and unit not in ENUMS["unit"]:
            errors.append((("loads", index, "unit"), _enum_error("unit", unit)))

    interfaces = document.get("interfaces")
    for index, interface in enumerate(interfaces if isinstance(interfaces, list) else []):
        if not isinstance(interface, dict):
            continue
        fit = interface.get("fit")
        if not is_unknown(fit) and fit not in ENUMS["fit"]:
            errors.append((("interfaces", index, "fit"), _enum_error("fit", fit)))

    channel = document.get("sales_channel")
    if channel is not None and not is_unknown(channel) and channel not in ENUMS["sales_channel"]:
        errors.append((("sales_channel",), _enum_error("sales_channel", channel)))

    for key in REQUIRED_KEYS:
        if key not in document:
            report.missing.append(key)

    for loc, value in _walk(document):
        if isinstance(value, str) and PLACEHOLDER in value:
            report.to_clarify.append(_dotted(loc))
        if len(loc) > 1 and loc[-1] == "status":  # pf.py: paths ending in ".status"
            if value not in ENUMS["status"]:
                errors.append((loc, _enum_error("status", value)))
            elif value in UNCONFIRMED_STATUSES:
                report.unconfirmed.append({"field": _dotted(loc[:-1]), "status": value})

    if errors:
        raise IntentInvalid(errors)
    return report


def report_for(document: dict[str, Any] | None) -> IntentReport:
    """The report of a stored document (already valid); empty when there is none."""
    if not document:
        return IntentReport()
    try:
        return validate_intent(document)
    except IntentInvalid:
        # Stored documents were validated on save; a later rule change must not hide them.
        return IntentReport()
