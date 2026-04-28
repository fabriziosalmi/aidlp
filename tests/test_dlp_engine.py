import pytest
from src.dlp_engine import DLPEngine


@pytest.fixture
def dlp_engine():
    engine = DLPEngine()
    # Mock or start workers - for tests, we need an event loop running,
    # but fixtures are sync unless decorated. We will start them inside the async tests.
    return engine


@pytest.mark.asyncio
async def test_analyze_text_with_pii(dlp_engine):
    dlp_engine.start_workers()
    text = "This is a secret password."
    redacted, stats = await dlp_engine.redact(text)
    assert "[REDACTED]" in redacted
    assert "password" not in redacted
    assert stats["static_replacements"] > 0


@pytest.mark.asyncio
async def test_analyze_text_no_pii(dlp_engine):
    dlp_engine.start_workers()
    text = "Call me at 415-555-0199."
    redacted, stats = await dlp_engine.redact(text)
    assert "[REDACTED]" in redacted
    assert "415-555-0199" not in redacted
    assert stats["ml_replacements"] > 0


@pytest.mark.asyncio
async def test_no_redaction_needed(dlp_engine):
    dlp_engine.start_workers()
    text = "Hello world."
    redacted, stats = await dlp_engine.redact(text)
    assert redacted == text
    assert stats["static_replacements"] == 0
    assert stats["ml_replacements"] == 0
