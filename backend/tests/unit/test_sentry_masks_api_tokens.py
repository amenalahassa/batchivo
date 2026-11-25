"""No personal API token reaches Sentry (spec 010, FR-010)."""

import json

from app.observability.sentry import API_TOKEN_MASK, before_send, mask_api_tokens

SECRET = "bvt_abcd2345_" + "Zz9-_" * 8


def _event() -> dict:
    return {
        "request": {
            "headers": {"Authorization": f"Bearer {SECRET}", "Accept": "application/json"},
            "url": "http://api.test/api/v1/ideas",
        },
        "breadcrumbs": {"values": [{"message": f"retry with {SECRET}", "level": "info"}]},
        "extra": {"args": (SECRET, 3), "nested": [{"token": SECRET}]},
        "message": f"failed for {SECRET}",
        "level": "error",
    }


def test_before_send_masks_the_token_everywhere():
    event = before_send(_event(), {})
    dumped = json.dumps(event)
    assert SECRET not in dumped
    assert "bvt_abcd2345" not in dumped
    assert event["request"]["headers"]["Authorization"] == f"Bearer {API_TOKEN_MASK}"
    assert event["breadcrumbs"]["values"][0]["message"] == f"retry with {API_TOKEN_MASK}"
    assert event["extra"]["nested"][0]["token"] == API_TOKEN_MASK
    assert event["extra"]["args"] == (API_TOKEN_MASK, 3)


def test_everything_else_is_unchanged():
    event = before_send(_event(), {})
    assert event["request"]["headers"]["Accept"] == "application/json"
    assert event["request"]["url"] == "http://api.test/api/v1/ideas"
    assert event["level"] == "error"
    assert "app.name" in event["tags"]


def test_jwt_and_plain_values_are_untouched():
    value = {"Authorization": "Bearer eyJhbGciOi.payload.sig", "count": 2, "none": None}
    assert mask_api_tokens(value) == value


def test_filtered_exceptions_are_still_dropped():
    from fastapi import HTTPException

    error = HTTPException(status_code=401)
    assert before_send(_event(), {"exc_info": (HTTPException, error, None)}) is None


def test_a_replicate_token_is_removed_and_the_api_token_mask_kept():
    """Spec 008's scrub runs after the spec 010 mask and leaves `bvt_****` readable."""
    replicate = "r8_" + "Abc123" * 6
    event = _event()
    event["extra"]["replicate"] = f"Bearer {replicate}"
    event["request"]["data"] = {"api_token": replicate}
    sent = before_send(event, {})
    dumped = json.dumps(sent)
    assert replicate not in dumped and SECRET not in dumped
    assert sent["request"]["headers"]["Authorization"] == f"Bearer {API_TOKEN_MASK}"
    assert sent["extra"]["replicate"] == "Bearer [redacted]"
    assert sent["request"]["data"]["api_token"] == "[redacted]"
