"""The Replicate adapter against a respx-mocked API (never the real one)."""

import json
import logging

import httpx
import pytest

from app.services.genai.base import (
    CANCELED,
    FAILED,
    RUNNING,
    SUCCEEDED,
    ProviderAuthError,
    ProviderRateLimited,
    ProviderRejected,
    ProviderTooLarge,
    ProviderTransient,
)
from app.services.genai.replicate import DATA_URI_MAX_BYTES, ReplicateProvider, parse_prediction
from tests.utils.genai import DELIVERY, FAKE_SECRET, FAKE_TOKEN, png_bytes, prediction, provider_url


@pytest.fixture
async def provider():
    p = ReplicateProvider(FAKE_TOKEN, provider_url())
    yield p
    await p.aclose()


def test_parse_prediction_statuses():
    assert parse_prediction(prediction(status="starting")).status == RUNNING
    assert parse_prediction(prediction(status="succeeded", predict_time=1.5)).predict_time == 1.5
    assert parse_prediction(prediction(status="succeeded")).status == SUCCEEDED
    assert parse_prediction(prediction(status="canceled")).status == CANCELED
    aborted = parse_prediction(prediction(status="aborted"))
    assert aborted.status == FAILED
    assert aborted.error


async def test_submit_sends_version_input_and_webhook(provider, replicate_mock):
    route = replicate_mock.post(f"{provider_url()}/predictions").mock(
        return_value=httpx.Response(201, json=prediction(status="starting"))
    )
    result = await provider.submit(
        "owner/model:" + "a" * 64, {"prompt": "x"}, "https://api.test/hook"
    )
    assert result.id == "pred-1"
    request = route.calls.last.request
    assert request.headers["authorization"] == f"Bearer {FAKE_TOKEN}"
    body = json.loads(request.content)
    assert body == {
        "version": "owner/model:" + "a" * 64,
        "input": {"prompt": "x"},
        "webhook": "https://api.test/hook",
        "webhook_events_filter": ["completed"],
    }


async def test_submit_without_webhook(provider, replicate_mock):
    route = replicate_mock.post(f"{provider_url()}/predictions").mock(
        return_value=httpx.Response(201, json=prediction())
    )
    await provider.submit("owner/model", {}, None)
    assert "webhook" not in json.loads(route.calls.last.request.content)


@pytest.mark.parametrize(
    "code,error",
    [
        (401, ProviderAuthError),
        (403, ProviderAuthError),
        (429, ProviderRateLimited),
        (413, ProviderTooLarge),
        (422, ProviderRejected),
        (502, ProviderTransient),
    ],
)
async def test_errors_are_classified(provider, replicate_mock, code, error):
    replicate_mock.post(f"{provider_url()}/predictions").mock(
        return_value=httpx.Response(code, json={"detail": "nope"})
    )
    with pytest.raises(error) as err:
        await provider.submit("owner/model", {}, None)
    assert FAKE_TOKEN not in str(err.value)


async def test_transient_flags(provider, replicate_mock):
    replicate_mock.post(f"{provider_url()}/predictions").mock(
        side_effect=httpx.ConnectError("boom")
    )
    with pytest.raises(ProviderTransient) as err:
        await provider.submit("owner/model", {}, None)
    assert err.value.transient is True
    assert ProviderRateLimited("x").transient is True
    assert ProviderAuthError("x").transient is False


async def test_get_and_cancel(provider, replicate_mock):
    replicate_mock.get(f"{provider_url()}/predictions/pred-1").mock(
        return_value=httpx.Response(200, json=prediction(status="succeeded", output=["u"]))
    )
    cancel = replicate_mock.post(f"{provider_url()}/predictions/pred-1/cancel").mock(
        return_value=httpx.Response(200, json=prediction(status="canceled"))
    )
    assert (await provider.get("pred-1")).output == ["u"]
    await provider.cancel("pred-1")
    assert cancel.called


async def test_small_input_is_a_data_uri(provider, replicate_mock):
    url = await provider.upload_input(png_bytes(), "image/png", "a.png")
    assert url.startswith("data:image/png;base64,")
    assert not any("/files" in str(c.request.url) for c in replicate_mock.calls)


async def test_large_input_goes_to_files_api(provider, replicate_mock):
    content = b"\0" * (DATA_URI_MAX_BYTES + 1)
    url = await provider.upload_input(content, "image/png", "big.png")
    assert url == f"{provider_url()}/files/file1"
    await provider.delete_input(url)
    await provider.delete_input("data:image/png;base64,AA")


async def test_download_sends_token_only_to_replicate(provider, replicate_mock):
    content, ctype = await provider.download(f"{DELIVERY}/a.png", 10_000_000)
    assert ctype == "image/png"
    assert content.startswith(b"\x89PNG")
    delivery_call = replicate_mock.calls.last.request
    assert delivery_call.headers.get("authorization") == f"Bearer {FAKE_TOKEN}"


@pytest.mark.parametrize(
    "url",
    [
        "https://evilreplicate.delivery/x.png",  # a lookalike host
        "https://replicate.delivery.evil.com/x.png",
        "http://replicate.delivery/x.png",  # not https
        "https://cdn.example.com/out.png",
        "http://169.254.169.254/latest/meta-data",  # an internal address
    ],
)
async def test_download_refuses_hosts_other_than_the_provider(provider, replicate_mock, url):
    """G1/T079: an output URL comes from the model; nothing else gets the token or a fetch."""
    sent = replicate_mock.route(url__startswith=url.split("/x.png")[0]).mock(
        return_value=httpx.Response(200, content=png_bytes())
    )
    with pytest.raises(ProviderRejected):
        await provider.download(url, 10_000_000)
    assert not sent.called


async def test_download_accepts_delivery_subdomains(provider, replicate_mock):
    route = replicate_mock.get("https://pbxt.replicate.delivery/a.png").mock(
        return_value=httpx.Response(200, content=png_bytes(), headers={"content-type": "image/png"})
    )
    await provider.download("https://pbxt.replicate.delivery/a.png", 10_000_000)
    assert route.calls.last.request.headers.get("authorization") == f"Bearer {FAKE_TOKEN}"


async def test_download_refuses_oversized(provider, replicate_mock):
    with pytest.raises(ProviderTooLarge):
        await provider.download(f"{DELIVERY}/a.png", 10)


async def test_account_and_webhook_secret(provider, replicate_mock):
    account = await provider.account()
    assert account.username == "shop-owner"
    assert await provider.webhook_secret() == FAKE_SECRET


async def test_token_never_logged(provider, replicate_mock, caplog):
    caplog.set_level(logging.DEBUG)
    replicate_mock.post(f"{provider_url()}/predictions").mock(
        return_value=httpx.Response(401, json={"detail": "bad token"})
    )
    with pytest.raises(ProviderAuthError):
        await provider.submit("owner/model", {}, None)
    await provider.account()
    assert FAKE_TOKEN not in caplog.text


async def test_download_error_status_is_classified(provider, replicate_mock):
    replicate_mock.get("https://gone.replicate.delivery/gone.png").mock(
        return_value=httpx.Response(404, json={"detail": "gone"})
    )
    with pytest.raises(ProviderRejected):
        await provider.download("https://gone.replicate.delivery/gone.png", 1000)


async def test_unreadable_answer_is_transient(provider, replicate_mock):
    replicate_mock.get(f"{provider_url()}/predictions/pred-1").mock(
        return_value=httpx.Response(200, content=b"<html>")
    )
    with pytest.raises(ProviderTransient):
        await provider.get("pred-1")
