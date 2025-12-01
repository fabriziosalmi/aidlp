import pytest
from unittest.mock import MagicMock
from mitmproxy.test import tflow
from src.proxy_core import DLPAddon


@pytest.mark.asyncio
async def test_dlp_addon_redaction_fail_closed():
    addon = DLPAddon()
    # Mock DLP Engine to fail
    addon.dlp_engine.redact = MagicMock(side_effect=Exception("DLP Crash"))

    f = tflow.tflow()
    f.request.method = "POST"
    f.request.content = b"test"

    await addon.request(f)

    # Verify 500 response (Fail Closed)
    assert f.response is not None
    assert f.response.status_code == 500
    assert b"DLP Engine Error" in f.response.content


@pytest.mark.asyncio
async def test_dlp_addon_redaction_success():
    addon = DLPAddon()
    # Mock DLP Engine to return redacted content
    addon.dlp_engine.redact = MagicMock(return_value=("redacted", {}))

    f = tflow.tflow()
    f.request.method = "POST"
    f.request.content = b"sensitive"

    await addon.request(f)

    assert f.request.text == "redacted"
