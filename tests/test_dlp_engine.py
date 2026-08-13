import asyncio
import time

import pytest
from src.dlp_engine import DLPEngine

import pytest_asyncio


@pytest_asyncio.fixture
async def dlp_engine():
    engine = DLPEngine()
    engine.start_workers()
    yield engine
    engine.shutdown()


@pytest.mark.asyncio
async def test_analyze_text_with_pii(dlp_engine):
    text = "This is a secret password."
    redacted, stats = await dlp_engine.redact(text)
    assert "[REDACTED]" in redacted
    assert "password" not in redacted
    assert stats["static_replacements"] > 0


@pytest.mark.asyncio
async def test_analyze_text_no_pii(dlp_engine):
    text = "Call me at 415-555-0199."
    redacted, stats = await dlp_engine.redact(text)
    assert "[REDACTED]" in redacted
    assert "415-555-0199" not in redacted
    assert stats["ml_replacements"] > 0


@pytest.mark.asyncio
async def test_no_redaction_needed(dlp_engine):
    text = "Hello world."
    redacted, stats = await dlp_engine.redact(text)
    assert redacted == text
    assert stats["static_replacements"] == 0
    assert stats["ml_replacements"] == 0


@pytest.mark.asyncio
async def test_worker_survives_cancelled_caller(dlp_engine):
    """A client disconnecting used to kill the ML worker for good.

    set_result() on the cancelled future raised InvalidStateError, the
    handler called set_exception() which raised it again, and the escaping
    exception ended the worker task. Once all four were gone, every later
    request waited on the queue forever.
    """
    loop = asyncio.get_running_loop()
    # Enough cancellations to hit every worker, not just one of the four.
    for _ in range(len(dlp_engine.workers) * 2):
        fut = loop.create_future()
        await dlp_engine.task_queue.put(("This is a secret password.", fut))
        fut.cancel()
        await asyncio.sleep(0.05)  # let a worker pick it up and try to answer

    assert not any(
        w.done() for w in dlp_engine.workers
    ), "cancelled callers killed the ML workers"

    redacted, _ = await asyncio.wait_for(
        dlp_engine.redact("Call me at 415-555-0199."), timeout=10
    )
    assert "[REDACTED]" in redacted


@pytest.mark.asyncio
async def test_redact_times_out_instead_of_hanging():
    """With no workers running, redact() must fail rather than hang.

    A hang is not an exception, so the proxy's fail-closed path never fires.
    """
    engine = DLPEngine()  # deliberately no start_workers()
    engine.ml_timeout = 0.2

    started = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(engine.redact("Call me at 415-555-0199."), timeout=5)
    elapsed = time.monotonic() - started

    assert elapsed < 2, "redact() hung instead of honouring ml_timeout"
    engine.shutdown()
