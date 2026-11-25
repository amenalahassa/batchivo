"""Pure rules of the generative AI layer (spec 008): no database, no network."""

import logging
import struct
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.config import GENAI_DEFAULT_PROVIDER_URL, Settings
from app.core.encryption import encrypt_value
from app.models.tenant import Tenant
from app.services.genai import catalog, credentials
from app.services.genai.base import ProviderPrediction
from app.services.genai.capabilities import (
    Capability,
    output_count,
    parse_capability,
    validate_inputs,
)
from app.services.genai.costs import GenAICostService, month_start, quantize
from app.services.genai.errors import InputInvalid
from app.services.genai.glb import build_glb, to_stl
from app.services.genai.logging import REDACTED, TokenRedactingFilter, redact
from app.services.genai.runner import poll_delay
from app.services.genai.webhooks import InvalidSignature, sign, verify_webhook
from tests.utils.genai import FAKE_SECRET, FAKE_TOKEN

ASSET = {"type": "asset", "id": str(uuid.uuid4())}


def _settings(**changes) -> Settings:
    return Settings(secret_key="x" * 40, **changes)


# ============================================
# Config levers (refused in production)
# ============================================


def test_platform_token_has_no_default():
    assert Settings.model_fields["replicate_api_token"].default is None


def test_test_levers_work_in_development_and_test():
    s = _settings(
        environment="development",
        genai_provider_base_url="http://localhost:8008/api/v1/genai/e2e-fake/",
        genai_run_inline=True,
    )
    assert s.genai_provider_url == "http://localhost:8008/api/v1/genai/e2e-fake"
    assert s.genai_inline is True


@pytest.mark.parametrize("hooks", [False, True])
def test_test_levers_refused_in_production(hooks):
    s = _settings(
        environment="production",
        e2e_test_hooks_enabled=hooks,
        genai_provider_base_url="http://evil.example/v1",
        genai_run_inline=True,
    )
    assert s.genai_test_levers_allowed is False
    assert s.genai_provider_url == GENAI_DEFAULT_PROVIDER_URL
    assert s.genai_inline is False


def test_test_levers_refused_on_staging_without_hooks():
    s = _settings(environment="staging", genai_run_inline=True)
    assert s.genai_inline is False
    s = _settings(environment="staging", genai_run_inline=True, e2e_test_hooks_enabled=True)
    assert s.genai_inline is True


def test_secret_token_never_in_repr():
    s = _settings(replicate_api_token=FAKE_TOKEN)
    assert FAKE_TOKEN not in repr(s)
    assert FAKE_TOKEN not in str(s.model_dump())


# ============================================
# Capabilities and inputs
# ============================================


def test_parse_capability_rejects_unknown():
    assert parse_capability("upscale") is Capability.UPSCALE
    with pytest.raises(InputInvalid):
        parse_capability("video")


def test_concept_inputs_valid_and_count():
    inputs = validate_inputs(Capability.CONCEPT_IMAGE, {"prompt": "  a clip ", "count": 3})
    assert inputs.prompt == "a clip"
    assert output_count(inputs) == 3


@pytest.mark.parametrize(
    "capability,raw",
    [
        (Capability.CONCEPT_IMAGE, {}),
        (Capability.CONCEPT_IMAGE, {"prompt": "x", "count": 5}),
        (Capability.CONCEPT_IMAGE, {"prompt": "x", "unknown": 1}),
        (Capability.IMAGE_EDIT, {"instruction": "x"}),
        (Capability.IMAGE_EDIT, {"instruction": "x", "input_assets": [ASSET, ASSET]}),
        (Capability.UPSCALE, {"factor": 3, "input_assets": [ASSET]}),
        (Capability.IMAGE_TO_3D, {"input_assets": []}),
        (Capability.CONCEPT_IMAGE, {"prompt": "x", "seed": -1}),
        (Capability.BACKGROUND_REMOVE, {"input_assets": [{"type": "web", "id": ASSET["id"]}]}),
    ],
)
def test_invalid_inputs_raise_readable_error(capability, raw):
    with pytest.raises(InputInvalid) as err:
        validate_inputs(capability, raw)
    assert err.value.message


def test_count_capped_by_model():
    with pytest.raises(InputInvalid, match="at most 1 image"):
        validate_inputs(Capability.CONCEPT_IMAGE, {"prompt": "x", "count": 2}, max_count=1)


# ============================================
# Catalog
# ============================================


def test_defaults_cover_every_capability_with_pins():
    for capability in Capability:
        config = catalog.DEFAULTS[capability]
        assert config.model_version != "latest"
        if config.pinnable:
            assert len(config.model_version) == 64
            assert config.version_spec == f"{config.model_ref}:{config.model_version}"
        else:
            assert config.version_spec == config.model_ref


def test_concept_with_references_uses_reference_model():
    plain = catalog.resolve(Capability.CONCEPT_IMAGE)
    refs = catalog.resolve(Capability.CONCEPT_IMAGE, has_references=True)
    assert plain.model_ref == "black-forest-labs/flux-schnell"
    assert refs.model_ref == "google/nano-banana"
    assert refs.max_inputs >= 1


def test_override_replaces_model_and_price():
    settings = {
        "replicate": {
            "model_overrides": {
                "upscale": {
                    "model_ref": "someone/better-upscaler",
                    "model_version": "c" * 64,
                    "price_unit": "per_run",
                    "price_usd": "0.01",
                }
            }
        }
    }
    config = catalog.resolve(Capability.UPSCALE, settings)
    assert config.overridden is True
    assert config.version_spec == "someone/better-upscaler:" + "c" * 64
    assert config.price.unit == "per_run"
    assert config.price.amount_usd == Decimal("0.01")
    assert config.price.source == "override"
    assert catalog.resolve(Capability.BACKGROUND_REMOVE, settings).overridden is False


def test_concept_override_applies_without_references_only():
    """F16: the override names a no-reference model; references keep the official one."""
    settings = {
        "replicate": {
            "model_overrides": {
                "concept_image": {
                    "model_ref": "someone/my-flux",
                    "model_version": "d" * 64,
                    "price_unit": "per_output",
                    "price_usd": "0.01",
                }
            }
        }
    }
    plain = catalog.resolve(Capability.CONCEPT_IMAGE, settings)
    assert plain.overridden is True
    assert plain.model_ref == "someone/my-flux"
    assert plain.input_mapping == catalog.DEFAULTS[Capability.CONCEPT_IMAGE].input_mapping
    refs = catalog.resolve(Capability.CONCEPT_IMAGE, settings, has_references=True)
    assert refs == catalog.CONCEPT_WITH_REFERENCES
    assert refs.overridden is False
    assert refs.model_ref == "google/nano-banana"
    assert refs.price.source == "catalog"


def test_concept_offers_reference_images():
    """F1: a concept resolves to the no-reference model but offers up to 4 references."""
    config = catalog.resolve(Capability.CONCEPT_IMAGE)
    assert config.max_inputs == 0
    assert catalog.selectable_inputs(config) == catalog.CONCEPT_WITH_REFERENCES.max_inputs == 4
    assert catalog.input_rules(config)["input_assets"]["max"] == 4
    assert catalog.selectable_inputs(catalog.resolve(Capability.IMAGE_TO_3D)) == 4
    assert catalog.selectable_inputs(catalog.resolve(Capability.UPSCALE)) == 1


def test_input_rules_follow_validation():
    """F5: the rules are read from the input models the service validates with."""
    rules = {c.capability: catalog.input_rules(c) for c in catalog.capability_list()}
    concept = rules[Capability.CONCEPT_IMAGE]
    assert concept["prompt"] == {"required": True, "max_length": 2000}
    assert concept["style"] == {"required": False, "max_length": 200}
    assert concept["count"] == {
        "required": False, "min": 1, "max": 4, "default": 1, "max_with_inputs": 1,
    }  # fmt: skip
    assert concept["input_assets"] == {"required": False, "min": 0, "max": 4}
    assert concept["seed"]["max"] == 2**31 - 1
    assert rules[Capability.IMAGE_EDIT]["instruction"]["required"] is True
    assert rules[Capability.PRODUCT_PHOTO_ENHANCE]["instruction"] == {
        "required": False, "max_length": 500,
    }  # fmt: skip
    assert rules[Capability.UPSCALE]["factor"] == {
        "required": False,
        "values": [2, 4],
        "default": 2,
    }
    assert rules[Capability.LIFESTYLE_SCENE]["scene"]["max_length"] == 2000
    assert rules[Capability.LIFESTYLE_SCENE]["count"]["max"] == 1  # model returns one image
    assert rules[Capability.IMAGE_TO_3D]["input_assets"] == {"required": True, "min": 1, "max": 4}
    for capability in (
        Capability.IMAGE_EDIT,
        Capability.PRODUCT_PHOTO_ENHANCE,
        Capability.BACKGROUND_REMOVE,
        Capability.UPSCALE,
        Capability.LIFESTYLE_SCENE,
    ):
        assert rules[capability]["input_assets"] == {"required": True, "min": 1, "max": 1}
    # the published limit is the enforced one
    too_long = {"prompt": "x" * (concept["prompt"]["max_length"] + 1)}
    with pytest.raises(InputInvalid):
        validate_inputs(Capability.CONCEPT_IMAGE, too_long)
    validate_inputs(Capability.CONCEPT_IMAGE, {"prompt": "x" * concept["prompt"]["max_length"]})


def test_build_provider_input_maps_fields_and_template():
    config = catalog.resolve(Capability.PRODUCT_PHOTO_ENHANCE)
    payload = catalog.build_provider_input(
        config, SimpleNamespace(instruction="warmer light"), ["data:image/png;base64,AA"], 42
    )
    text = " ".join(str(v) for v in payload.values())
    assert "warmer light" in text
    assert "data:image/png;base64,AA" in text


def test_build_provider_input_concept_style():
    config = catalog.resolve(Capability.CONCEPT_IMAGE)
    payload = catalog.build_provider_input(
        config, SimpleNamespace(prompt="a clip", style="studio", count=2), [], 1
    )
    assert "a clip. Style: studio" in payload.values()


def test_extract_output_urls_shapes():
    image = catalog.resolve(Capability.CONCEPT_IMAGE)
    mesh = catalog.resolve(Capability.IMAGE_TO_3D)
    assert catalog.extract_output_urls(image, None) == []
    assert catalog.extract_output_urls(image, "https://x/a.png") == ["https://x/a.png"]
    assert catalog.extract_output_urls(image, ["https://x/a", "", 3]) == ["https://x/a"]
    assert catalog.extract_output_urls(
        mesh, {"model_file": "https://x/m.glb", "color_video": "https://x/v.mp4"}
    ) == ["https://x/m.glb"]


# ============================================
# Costs (Decimal, USD)
# ============================================


def _job(snapshot, submitted=True, estimated="0.0100"):
    return SimpleNamespace(
        price_snapshot=snapshot,
        submitted_at=datetime.now(timezone.utc) if submitted else None,
        external_id="p" if submitted else None,
        estimated_cost=Decimal(estimated),
    )


def _pred(status, predict_time=None):
    return ProviderPrediction(
        id="p", status=status, output=None, error=None, version=None,
        predict_time=predict_time, raw={},
    )  # fmt: skip


def test_estimates_by_unit():
    costs = GenAICostService()
    assert costs.estimate_from_snapshot({"unit": "per_output", "amount_usd": "0.003"}, 4) == (
        Decimal("0.0120")
    )
    assert costs.estimate_from_snapshot(
        {"unit": "per_second", "amount_usd": "0.0014", "typical_seconds": 30}, 1
    ) == Decimal("0.0420")
    assert costs.estimate_from_snapshot({"unit": "per_run", "amount_usd": "0.04"}, 3) == Decimal(
        "0.0400"
    )


def test_final_cost_computed_from_provider_report():
    costs = GenAICostService()
    per_second = {"unit": "per_second", "amount_usd": "0.000225", "typical_seconds": 3}
    assert costs.final(_job(per_second), _pred("succeeded", 2.5), 1) == (
        Decimal("0.0006"),
        "computed",
    )
    per_output = {"unit": "per_output", "amount_usd": "0.003"}
    assert costs.final(_job(per_output), _pred("succeeded"), 3) == (Decimal("0.0090"), "computed")
    assert costs.final(_job(per_output), _pred("failed"), 0) == (Decimal("0"), "computed")


def test_final_cost_estimated_when_nothing_reported():
    costs = GenAICostService()
    per_second = {"unit": "per_second", "amount_usd": "0.0014", "typical_seconds": 30}
    assert costs.final(_job(per_second, estimated="0.0420"), None, 0) == (
        Decimal("0.0420"),
        "estimated",
    )


def test_never_submitted_costs_nothing():
    costs = GenAICostService()
    snapshot = {"unit": "per_run", "amount_usd": "0.04"}
    assert costs.final(_job(snapshot, submitted=False), None, 0) == (Decimal("0"), "computed")


def test_quantize_and_month_start():
    assert quantize(Decimal("0.00005")) == Decimal("0.0001")
    assert month_start(datetime(2026, 11, 24, 13, 5, tzinfo=timezone.utc)) == datetime(
        2026, 11, 1, tzinfo=timezone.utc
    )


def test_poll_delay_backs_off_and_caps():
    assert poll_delay(0) == 2.0
    assert poll_delay(1) == 3.0
    assert poll_delay(50) == 30.0


# ============================================
# Credentials
# ============================================


def _tenant(replicate=None):
    return Tenant(id=uuid.uuid4(), name="T", slug="t", settings={"replicate": replicate or {}})


def test_resolve_prefers_tenant_token():
    tenant = _tenant({"api_token_encrypted": encrypt_value(FAKE_TOKEN)})
    resolved = credentials.resolve(tenant, _settings(replicate_api_token="r8_platform"))
    assert resolved.token == FAKE_TOKEN
    assert resolved.source == credentials.SOURCE_TENANT
    assert FAKE_TOKEN not in repr(resolved)


def test_platform_token_only_when_authorised():
    settings = _settings(replicate_api_token="r8_platform")
    assert credentials.resolve(_tenant(), settings).token is None
    allowed = _tenant({"platform_token_allowed": True})
    assert credentials.resolve(allowed, settings).source == credentials.SOURCE_PLATFORM
    everyone = _settings(replicate_api_token="r8_platform", genai_platform_token_all_tenants=True)
    assert credentials.resolve(_tenant(), everyone).token == "r8_platform"


def test_no_token_anywhere():
    resolved = credentials.resolve(_tenant({"platform_token_allowed": True}), _settings())
    assert resolved.token is None
    assert resolved.source == credentials.SOURCE_NONE


# ============================================
# Token redaction
# ============================================


def test_redact_removes_tokens_and_bearer():
    text = f"call with {FAKE_TOKEN} and Authorization: Bearer abc.def-123"
    cleaned = redact(text)
    assert FAKE_TOKEN not in cleaned
    assert "abc.def-123" not in cleaned
    assert REDACTED in cleaned


def test_filter_rewrites_record_args():
    record = logging.LogRecord("httpx", logging.INFO, __file__, 1, "token=%s", (FAKE_TOKEN,), None)
    assert TokenRedactingFilter().filter(record) is True
    assert FAKE_TOKEN not in record.getMessage()


@pytest.mark.parametrize(
    "name",
    [
        "app.services.genai.runner",
        "app.services.genai.replicate",
        "app.api.v1.genai",
        "app.api.v1.genai_settings",
        "app.tasks.genai",
        "httpx",
        "httpcore.http11",
        "httpcore.connection",
    ],
)
def test_child_logger_records_are_redacted(name):
    """F3: a record of a child logger is redacted too, whatever handler formats it."""
    import io

    from app.services.genai import logging as genai_logging

    genai_logging.install()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(handler)
    child = logging.getLogger(name)
    previous = child.level
    child.setLevel(logging.INFO)
    try:
        child.info("calling with %s", FAKE_TOKEN)
        child.warning(f"header Authorization: Bearer {FAKE_TOKEN}")
    finally:
        root.removeHandler(handler)
        child.setLevel(previous)
    output = stream.getvalue()
    assert FAKE_TOKEN not in output
    assert output.count(REDACTED) == 2


def test_other_loggers_are_left_alone():
    from app.services.genai.logging import covers

    assert covers("app.services.genai.runner")
    assert covers("app.api.v1.genai_platform")
    assert not covers("app.services.genai_other_thing")
    assert not covers("app.services.costing")
    assert not covers("httpxyz")


# ============================================
# Webhook signatures
# ============================================


def _headers(body: bytes, ts: int, secret: str = FAKE_SECRET):
    return {
        "webhook-id": "msg_1",
        "webhook-timestamp": str(ts),
        "webhook-signature": sign(secret, "msg_1", str(ts), body),
    }


def test_verify_accepts_valid_signature():
    body = b'{"id":"p"}'
    now = int(time.time())
    verify_webhook(FAKE_SECRET, _headers(body, now), body, now=now)


def test_verify_accepts_one_of_several_signatures():
    body = b"{}"
    now = int(time.time())
    headers = _headers(body, now)
    headers["webhook-signature"] = "v1,bogus " + headers["webhook-signature"]
    verify_webhook(FAKE_SECRET, headers, body, now=now)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda h, b: ({**h, "webhook-signature": "v1,AAAA"}, b),
        lambda h, b: (h, b + b" "),
        lambda h, b: ({k: v for k, v in h.items() if k != "webhook-id"}, b),
        lambda h, b: ({**h, "webhook-timestamp": "nope"}, b),
    ],
)
def test_verify_rejects_tampering(mutate):
    body = b'{"id":"p"}'
    now = int(time.time())
    headers, sent = mutate(_headers(body, now), body)
    with pytest.raises(InvalidSignature):
        verify_webhook(FAKE_SECRET, headers, sent, now=now)


def test_verify_rejects_old_or_future_timestamp():
    body = b"{}"
    now = int(time.time())
    with pytest.raises(InvalidSignature):
        verify_webhook(FAKE_SECRET, _headers(body, now - 301), body, now=now)
    with pytest.raises(InvalidSignature):
        verify_webhook(FAKE_SECRET, _headers(body, now + 301), body, now=now)


def test_verify_rejects_other_secret():
    body = b"{}"
    now = int(time.time())
    other = "whsec_" + "b3RoZXItc2VjcmV0"
    with pytest.raises(InvalidSignature):
        verify_webhook(FAKE_SECRET, _headers(body, now, other), body, now=now)


# ============================================
# GLB → STL
# ============================================


def _stl_bounds(stl: bytes):
    (count,) = struct.unpack_from("<I", stl, 80)
    points = []
    for i in range(count):
        values = struct.unpack_from("<12f", stl, 84 + i * 50)
        points += [values[3:6], values[6:9], values[9:12]]
    return count, [max(p[a] for p in points) - min(p[a] for p in points) for a in range(3)]


def test_glb_to_stl_triangles_and_size():
    glb = build_glb([(0, 0, 0), (40, 0, 0), (0, 30, 0), (0, 0, 20)], [0, 1, 2, 0, 1, 3])
    count, size = _stl_bounds(to_stl(glb))
    assert count == 2
    assert [round(s) for s in size] == [40, 30, 20]


def test_glb_node_matrix_applied():
    scale = [2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 1]
    glb = build_glb([(0, 0, 0), (10, 0, 0), (0, 20, 0)], [0, 1, 2], matrix=scale)
    _, size = _stl_bounds(to_stl(glb))
    assert [round(s) for s in size[:2]] == [20, 40]


def test_glb_rejects_garbage():
    with pytest.raises(InputInvalid, match="Not a GLB file"):
        to_stl(b"not a glb at all")


# ============================================
# Sentry events carry no token (T068, FR-021, SC-006)
# ============================================


def test_sentry_event_loses_the_token():
    from app.observability.sentry import before_send

    token = "r8_SentryLeakCheck0000000000000000000"
    event = {
        "request": {"data": {"api_token": token, "monthly_budget": "25.00"}},
        "exception": {
            "values": [
                {
                    "value": f"failed with Bearer {token}",
                    "stacktrace": {"frames": [{"vars": {"own": token, "shared": [token], "n": 3}}]},
                }
            ]
        },
        "extra": {"api_token_encrypted": "gAAAA-ciphertext", "webhook_secret_encrypted": "x"},
    }
    sent = before_send(event, {})
    assert token not in repr(sent)
    assert "gAAAA-ciphertext" not in repr(sent)
    assert sent["request"]["data"] == {"api_token": REDACTED, "monthly_budget": "25.00"}
    frame = sent["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
    assert frame == {"own": REDACTED, "shared": [REDACTED], "n": 3}
    assert sent["tags"]["app.name"]


# ============================================
# A per-second override always has a run time (T076, FR-024, SC-002)
# ============================================


def _per_second_override(capability: str, **extra) -> dict:
    item = {"model_ref": "someone/editor", "model_version": "official"}
    item.update(price_unit="per_second", price_usd="0.0014", **extra)
    return {"replicate": {"model_overrides": {capability: item}}}


def test_per_second_override_uses_the_operators_run_time():
    config = catalog.resolve(
        Capability.IMAGE_EDIT, _per_second_override("image_edit", typical_seconds=20)
    )
    assert (config.price.typical_seconds, config.price.assumed) == (20, False)
    assert GenAICostService().estimate(config, 1) == quantize(Decimal("0.0014") * 20)


def test_per_second_override_falls_back_to_the_default_run_time():
    config = catalog.resolve(Capability.UPSCALE, _per_second_override("upscale"))
    assert (
        config.price.typical_seconds == catalog.DEFAULTS[Capability.UPSCALE].price.typical_seconds
    )
    assert config.price.typical_seconds > 0


def test_per_second_override_without_any_run_time_assumes_the_time_limit():
    config = catalog.resolve(Capability.IMAGE_EDIT, _per_second_override("image_edit"))
    assert config.price.typical_seconds == config.time_limit_s
    assert config.price.assumed is True
    assert GenAICostService().estimate(config, 1) > Decimal("0")
