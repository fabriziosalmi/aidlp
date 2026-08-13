import pytest
import asyncio
import time
from unittest.mock import patch
from mitmproxy.test import tflow

from src.proxy_core import DLPAddon


@pytest.fixture
def mock_dlp_engine():
    with patch("src.proxy_core.DLPEngine") as MockEngine:
        engine_instance = MockEngine.return_value

        # Simulate a slow async operation
        async def slow_redact(text):
            await asyncio.sleep(0.1)  # Async sleep
            return text, {}

        engine_instance.redact = slow_redact
        yield engine_instance


def _make_flow(content=b"test content", content_type="text/plain"):
    flow = tflow.tflow()
    flow.request.method = "POST"
    flow.request.headers["Content-Type"] = content_type
    flow.request.content = content
    return flow


@pytest.mark.asyncio
async def test_async_concurrency(mock_dlp_engine):
    """
    Verify that multiple requests are processed concurrently,
    so the total time is much less than the sum of individual processing times.
    """
    addon = DLPAddon()
    flows = [_make_flow() for _ in range(10)]

    start_time = time.time()
    await asyncio.gather(*[addon.request(flow) for flow in flows])
    total_time = time.time() - start_time

    # If serial: 10 * 0.1 = 1.0s. If concurrent: ~0.1s (plus overhead).
    assert (
        total_time < 0.5
    ), f"Requests took too long ({total_time}s), likely running serially"
    assert (
        total_time >= 0.1
    ), "Requests took too little time, sleep might not have happened"


@pytest.mark.asyncio
async def test_request_buffering_limit(mock_dlp_engine):
    addon = DLPAddon()
    flow = _make_flow(content=b"x" * (10 * 1024 * 1024 + 1))

    await addon.request(flow)

    assert flow.response.status_code == 413
