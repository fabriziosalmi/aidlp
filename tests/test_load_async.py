import pytest
import asyncio
from unittest.mock import patch
from mitmproxy.test import tflow

from src.proxy_core import DLPAddon


@pytest.fixture
def mock_dlp_engine():
    with patch("src.proxy_core.DLPEngine") as MockEngine:
        engine_instance = MockEngine.return_value

        # Records how many calls are in flight at once, so concurrency can be
        # asserted structurally rather than from a wall-clock threshold.
        state = {"in_flight": 0, "peak": 0}

        async def slow_redact(text, request_id="unknown"):
            state["in_flight"] += 1
            state["peak"] = max(state["peak"], state["in_flight"])
            try:
                await asyncio.sleep(0.05)
                return text, {}
            finally:
                state["in_flight"] -= 1

        engine_instance.redact = slow_redact
        engine_instance.peak_in_flight = state
        engine_instance.health_report = lambda: (True, {})
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

    await asyncio.gather(*[addon.request(flow) for flow in flows])

    # A wall-clock bound made this flaky on a loaded runner and proved
    # nothing about the behaviour: assert the invariant instead. All ten
    # redactions must have overlapped, which is impossible if they ran
    # one after another.
    assert mock_dlp_engine.peak_in_flight["peak"] == len(flows), (
        "requests did not overlap: peak concurrency was "
        f"{mock_dlp_engine.peak_in_flight['peak']} of {len(flows)}"
    )


@pytest.mark.asyncio
async def test_request_buffering_limit(mock_dlp_engine):
    addon = DLPAddon()
    flow = _make_flow(content=b"x" * (10 * 1024 * 1024 + 1))

    await addon.request(flow)

    assert flow.response.status_code == 413
