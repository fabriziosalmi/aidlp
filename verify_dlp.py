import sys
import os
import asyncio

# Add current directory to path
sys.path.append(os.getcwd())

from src.dlp_engine import DLPEngine  # noqa: E402


async def test_dlp():
    print("Initializing DLP Engine...")
    engine = DLPEngine()
    engine.start_workers()

    test_text = "My password is secret and my name is John Doe. Contact me at 555-0199."
    print(f"Original: {test_text}")

    redacted, stats = await engine.redact(test_text)
    print(f"Redacted: {redacted}")
    print(f"Stats: {stats}")

    # Assertions
    assert "[REDACTED]" in redacted
    assert "secret" not in redacted
    # John Doe might be redacted by ML

    print("Test Passed!")


if __name__ == "__main__":
    asyncio.run(test_dlp())
