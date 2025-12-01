import pytest
import asyncio
import time
from unittest.mock import MagicMock, patch
from src.proxy_core import DLPAddon


# Mock config to avoid loading real models
@pytest.fixture
def mock_config():
    with patch("src.proxy_core.config") as mock:
        mock.get.return_value = 9090  # metrics port
        yield mock


@pytest.fixture
def mock_dlp_engine():
    with patch("src.proxy_core.DLPEngine") as MockEngine:
        engine_instance = MockEngine.return_value

        # Simulate a slow blocking operation
        def slow_redact(text):
            time.sleep(0.1)  # Blocking sleep
            return text, {}

        engine_instance.redact = slow_redact
        yield engine_instance


@pytest.mark.asyncio
async def test_async_concurrency(mock_config, mock_dlp_engine):
    """
    Verify that multiple requests are processed concurrently using threads,
    so the total time is much less than the sum of individual processing times.
    """
    addon = DLPAddon()

    # Create a flow with content
    def create_flow():
        flow = MagicMock()
        flow.request.method = "POST"
        flow.request.content = b"test content"
        flow.request.get_text.return_value = "test content"
        flow.request.headers = {}
        flow.request.pretty_url = "http://example.com"
        flow.request.host = "example.com"
        return flow

    # Run 10 requests concurrently
    flows = [create_flow() for _ in range(10)]

    start_time = time.time()

    # We need to call process_request directly or via request
    # addon.request is async
    tasks = [addon.request(flow) for flow in flows]
    await asyncio.gather(*tasks)

    total_time = time.time() - start_time

    # If serial: 10 * 0.1 = 1.0s
    # If concurrent: ~0.1s (plus overhead)
    # We assert it's significantly faster than serial
    print(f"Total time for 10 requests: {total_time:.4f}s")  # noqa: E231
    assert total_time < 0.5, f"Requests took too long ({total_time}s), likely running serially"
    assert total_time >= 0.1, "Requests took too little time, sleep might not have happened"


@pytest.mark.asyncio
async def test_request_buffering_limit(mock_config, mock_dlp_engine):
    addon = DLPAddon()

    flow = MagicMock()
    flow.request.method = "POST"
    # Create content > 10MB
    flow.request.content = b"x" * (10 * 1024 * 1024 + 1)
    flow.request.headers = {}

    await addon.request(flow)

    # Verify response is 413
    assert flow.response.status_code == 413
