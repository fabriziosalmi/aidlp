import pytest
from unittest.mock import AsyncMock
from mitmproxy.test import tflow
from src.proxy_core import DLPAddon


def _flow(content=b"test", content_type="text/plain", path=None):
    f = tflow.tflow()
    f.request.method = "POST"
    f.request.headers["Content-Type"] = content_type
    f.request.content = content
    if path is not None:
        f.request.path = path
    return f


def _stub_redact(returns="[REDACTED]"):
    return AsyncMock(
        return_value=(
            returns,
            {"static_replacements": 1, "ml_replacements": 0, "pii_types": {}},
        )
    )


@pytest.mark.asyncio
async def test_dlp_addon_redaction_fail_closed():
    addon = DLPAddon()
    # Mock DLP Engine to fail
    addon.dlp_engine.redact = AsyncMock(side_effect=Exception("DLP Crash"))

    f = _flow()
    await addon.request(f)

    # Verify 500 response (Fail Closed)
    assert f.response is not None
    assert f.response.status_code == 500
    assert b"DLP Policy Violation" in f.response.content
    addon.dlp_engine.shutdown()


@pytest.mark.asyncio
async def test_dlp_addon_redaction_success():
    addon = DLPAddon()
    # Mock DLP Engine to return redacted content
    addon.dlp_engine.redact = AsyncMock(return_value=("redacted", {}))

    f = _flow(content=b"sensitive")
    await addon.request(f)

    assert f.request.text == "redacted"
    addon.dlp_engine.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content_type",
    ["application/octet-stream", "application/x-www-form-urlencoded", ""],
)
async def test_unrecognised_content_type_is_still_inspected(content_type):
    """Regression: the old allow-list skipped anything that was not JSON or
    text/*, so setting Content-Type: application/octet-stream bypassed DLP
    entirely.
    """
    addon = DLPAddon()
    addon.dlp_engine.redact = _stub_redact()

    f = _flow(content=b"my api_key is hunter2", content_type=content_type)
    await addon.request(f)

    addon.dlp_engine.redact.assert_awaited()
    assert f.request.text == "[REDACTED]"
    addon.dlp_engine.shutdown()


@pytest.mark.asyncio
async def test_binary_content_type_is_skipped():
    addon = DLPAddon()
    addon.dlp_engine.redact = _stub_redact()

    f = _flow(content=b"\x89PNG\r\n\x1a\n", content_type="image/png")
    await addon.request(f)

    addon.dlp_engine.redact.assert_not_awaited()
    addon.dlp_engine.shutdown()


@pytest.mark.asyncio
async def test_query_string_is_redacted():
    """Regression: only bodies were scanned, so a secret in the query string
    was forwarded untouched.
    """
    addon = DLPAddon()
    addon.dlp_engine.redact = _stub_redact()

    f = tflow.tflow()
    f.request.method = "GET"
    f.request.content = b""
    f.request.path = "/v1/completions?prompt=my-api_key"

    await addon.request(f)

    assert f.request.query["prompt"] == "[REDACTED]"
    addon.dlp_engine.shutdown()
