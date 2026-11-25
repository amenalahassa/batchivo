"""Validation of a Preflight intent (spec 009, research R3): `pf.py validate`'s rules."""

import datetime as dt

import pytest
import yaml

from app.services.preflight_intent import (
    PLACEHOLDER,
    IntentInvalid,
    check_size,
    parse_yaml_mapping,
    report_for,
    validate_intent,
)
from tests.fixtures.preflight import FILLED_INTENT, INTENT_TEMPLATE


def _locs(exc: IntentInvalid) -> list[tuple]:
    return [loc for loc, _ in exc.errors]


def test_template_is_valid_and_reports_what_is_left():
    report = validate_intent(yaml.safe_load(INTENT_TEMPLATE))
    assert report.missing == []
    assert "slug" in report.to_clarify
    assert "loads[0].value" in report.to_clarify
    assert "environment.max_temp_c" in report.to_clarify
    assert "success_criteria[0]" in report.to_clarify
    assert {"field": "environment", "status": "déduit"} in report.unconfirmed
    assert {"field": "interfaces[0]", "status": "estimée"} in report.unconfirmed


def test_filled_intent_has_nothing_left():
    report = validate_intent(FILLED_INTENT)
    assert report.as_dict() == {"to_clarify": [], "unconfirmed": [], "missing": []}


def test_half_filled_intent_reports_missing_keys():
    report = validate_intent({"schema_version": 1, "function": "Tient un sac"})
    assert report.missing == ["loads", "environment", "interfaces", "success_criteria"]


@pytest.mark.parametrize(
    "change,loc",
    [
        ({"schema_version": 2}, ("schema_version",)),
        ({"schema_version": None}, ("schema_version",)),
        ({"loads": [{"duration": "forever"}]}, ("loads", 0, "duration")),
        ({"loads": [{"unit": "lb"}]}, ("loads", 0, "unit")),
        ({"interfaces": [{"fit": "glued"}]}, ("interfaces", 0, "fit")),
        ({"sales_channel": "ebay"}, ("sales_channel",)),
        ({"environment": {"status": "supposé"}}, ("environment", "status")),
    ],
)
def test_enum_errors_name_their_place(change, loc):
    with pytest.raises(IntentInvalid) as raised:
        validate_intent({**FILLED_INTENT, **change})
    assert loc in _locs(raised.value)


def test_placeholders_pass_every_enum():
    document = {
        **FILLED_INTENT,
        "loads": [{"duration": PLACEHOLDER, "unit": PLACEHOLDER}],
        "interfaces": [{"fit": PLACEHOLDER}],
        "sales_channel": PLACEHOLDER,
    }
    report = validate_intent(document)
    assert "loads[0].duration" in report.to_clarify
    assert "sales_channel" in report.to_clarify


def test_a_top_level_status_key_is_not_a_value_status():
    """pf.py only checks paths ending in `.status`; a top-level `status` is free text."""
    validate_intent({**FILLED_INTENT, "status": "brouillon"})


def test_all_errors_come_at_once():
    with pytest.raises(IntentInvalid) as raised:
        validate_intent({**FILLED_INTENT, "schema_version": 3, "sales_channel": "ebay"})
    assert len(raised.value.errors) == 2
    assert "schema_version" in str(raised.value)


def test_extra_keys_are_kept_and_not_checked():
    document = {**FILLED_INTENT, "x_shop": {"anything": [1, 2, {"deep": True}]}}
    assert validate_intent(document).missing == []


def test_not_a_mapping_is_refused():
    with pytest.raises(IntentInvalid):
        validate_intent(["schema_version", 1])  # type: ignore[arg-type]


def test_parse_yaml_mapping():
    assert parse_yaml_mapping("schema_version: 1\nslug: a\n") == {"schema_version": 1, "slug": "a"}
    assert parse_yaml_mapping('{"a": 1}') == {"a": 1}
    dated = parse_yaml_mapping("when: 2026-11-25\nat: 2026-11-25 10:00:00\n")
    assert dated["when"] == dt.date(2026, 11, 25).isoformat()
    assert dated["at"].startswith("2026-11-25T10:00:00")
    for bad in ("- a\n- b\n", "just text", "a: [unclosed\n", ""):
        with pytest.raises(IntentInvalid) as raised:
            parse_yaml_mapping(bad, "intent_yaml")
        assert raised.value.errors[0][0] == ("intent_yaml",)


def test_yaml_tags_are_refused():
    """safe_load: a YAML document can never build Python objects."""
    with pytest.raises(IntentInvalid):
        parse_yaml_mapping("a: !!python/object/apply:os.system ['echo hi']\n")


def test_size_limit():
    check_size({"a": "x" * 1000}, "params")
    with pytest.raises(IntentInvalid) as raised:
        check_size({"a": "x" * (256 * 1024)}, "params")
    assert raised.value.errors[0][0] == ("params",)


def test_report_for_stored_documents():
    assert report_for(None).as_dict() == {"to_clarify": [], "unconfirmed": [], "missing": []}
    assert report_for({"schema_version": 99}).as_dict()["missing"] == []  # never raises
    assert report_for(yaml.safe_load(INTENT_TEMPLATE)).to_clarify
