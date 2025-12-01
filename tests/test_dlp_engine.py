import pytest
from src.dlp_engine import DLPEngine


@pytest.fixture
def dlp_engine():
    return DLPEngine()


def test_analyze_text_with_pii(dlp_engine):
    text = "This is a secret password."
    redacted, stats = dlp_engine.redact(text)
    assert "[REDACTED]" in redacted
    assert "password" not in redacted
    assert stats["static_replacements"] > 0


def test_analyze_text_no_pii(dlp_engine):
    text = "Call me at 415-555-0199."
    redacted, stats = dlp_engine.redact(text)
    assert "[REDACTED]" in redacted
    assert "415-555-0199" not in redacted
    assert stats["ml_replacements"] > 0


def test_no_redaction_needed(dlp_engine):
    text = "Hello world."
    redacted, stats = dlp_engine.redact(text)
    assert redacted == text
    assert stats["static_replacements"] == 0
    assert stats["ml_replacements"] == 0
