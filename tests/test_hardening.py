import asyncio
import logging

import pytest
from unittest.mock import MagicMock, patch
from mitmproxy.test import tflow
from pydantic import ValidationError

from src.config import AppConfig, DLPConfig, SecretsProviderConfig, find_unknown_config_keys
from src.dlp_engine import DLPEngine
from src.proxy_core import FLOWS_SEEN_TOTAL, DLPAddon


# --- configuration is validated, not merely parsed ---------------------------


@pytest.mark.parametrize("value", [1.5, -0.1, 2.0])
def test_ml_threshold_out_of_range_is_rejected(value):
    """Above 1.0 every score comparison is false, silently disabling ML."""
    with pytest.raises(ValidationError):
        DLPConfig(ml_threshold=value)


def test_ml_threshold_boundaries_are_allowed():
    assert DLPConfig(ml_threshold=0.0).ml_threshold == 0.0
    assert DLPConfig(ml_threshold=1.0).ml_threshold == 1.0


@pytest.mark.parametrize("value", ["Vault", "VAULT", "vualt", "files"])
def test_misspelled_provider_type_is_rejected(value):
    """A typo used to fall through to the file provider without a word."""
    with pytest.raises(ValidationError):
        SecretsProviderConfig(type=value)


def test_vault_type_without_vault_section_is_rejected():
    with pytest.raises(ValidationError, match="no secrets_provider.vault"):
        SecretsProviderConfig(type="vault")


def test_unknown_nested_key_is_rejected():
    with pytest.raises(ValidationError):
        DLPConfig(ml_enabl=True)


def test_unknown_top_level_section_is_named():
    assert find_unknown_config_keys({"upstream": {"scheme": "https"}}) == ["upstream"]


def test_capacity_is_configurable():
    """Previously literals 4 and 1000 inside dlp_engine.py."""
    cfg = DLPConfig(ml_workers=8, ml_queue_maxsize=50)
    assert (cfg.ml_workers, cfg.ml_queue_maxsize) == (8, 50)
    assert AppConfig().dlp.ml_workers == 4


# --- engine lifecycle --------------------------------------------------------


def _engine(**overrides):
    cfg = DLPConfig(ml_enabled=False, **overrides)
    return DLPEngine(dlp_config=cfg)


def test_engine_accepts_an_injected_config():
    """Two engines could not hold different settings before."""
    engine = _engine(replacement_token="[X]")
    assert engine.replacement_token == "[X]"


@pytest.mark.asyncio
async def test_shutdown_resets_so_the_engine_can_restart():
    """cancel() alone left workers/poller non-empty, so a later
    start_workers() saw them as live and silently spawned nothing."""
    engine = _engine()
    engine.start_workers()
    assert engine.poller_task is not None

    engine.shutdown()
    assert engine.poller_task is None
    assert engine.workers == []

    engine.start_workers()
    assert engine.poller_task is not None
    await engine.aclose()


@pytest.mark.asyncio
async def test_aclose_waits_for_the_tasks():
    engine = _engine()
    engine.start_workers()
    poller = engine.poller_task

    await engine.aclose()
    assert poller.done()


@pytest.mark.asyncio
async def test_enqueue_is_bounded_when_the_pool_is_saturated():
    """A full queue used to block put() forever, hanging the request instead
    of failing closed."""
    engine = DLPEngine(dlp_config=DLPConfig(ml_enabled=False))
    engine.ml_timeout = 0.1
    engine.task_queue = asyncio.Queue(maxsize=1)
    await engine.task_queue.put(("filler", asyncio.get_running_loop().create_future(), "x"))

    with pytest.raises(asyncio.TimeoutError):
        await engine._analyze_ml("text", [], {"pii_types": {}}, "rid")


# --- health reports the subsystems that fail quietly -------------------------


def test_health_is_unhealthy_when_terms_never_loaded():
    engine = _engine()
    engine._terms_loaded = False
    healthy, details = engine.health_report()
    assert healthy is False
    assert details["terms_loaded"] is False


def test_health_is_ok_on_a_freshly_loaded_engine():
    healthy, details = _engine().health_report()
    assert healthy is True
    assert details["terms_loaded"] is True


# --- redaction output is correct with many spans -----------------------------


@pytest.mark.asyncio
async def test_redact_replaces_every_span_after_the_rewrite():
    """The substitution moved from repeated slice-assignment to one pass."""
    engine = _engine(replacement_token="[R]")
    engine.keyword_processor.add_keyword("alpha", "alpha")
    engine.keyword_processor.add_keyword("bravo", "bravo")

    text = "alpha middle bravo tail alpha"
    redacted, stats = await engine.redact(text)

    assert redacted == "[R] middle [R] tail [R]"
    assert stats["static_replacements"] == 3


# --- proxy contract ----------------------------------------------------------


@pytest.fixture
def addon():
    with patch("src.proxy_core.DLPEngine") as MockEngine:
        engine = MockEngine.return_value

        async def redact(text, request_id="unknown"):
            return text, {}

        engine.redact = redact
        engine.health_report = lambda: (True, {"terms_loaded": True})
        yield DLPAddon()


@pytest.mark.asyncio
async def test_request_too_large_uses_the_json_error_contract(addon):
    """The documented contract is JSON; this path returned plain text."""
    flow = tflow.tflow()
    flow.request.method = "POST"
    flow.request.headers["Content-Type"] = "text/plain"
    flow.request.content = b"x" * (10 * 1024 * 1024 + 1)

    await addon.request(flow)

    assert flow.response.status_code == 413
    assert flow.response.headers["Content-Type"] == "application/json"
    assert b"request_too_large" in flow.response.content


@pytest.mark.asyncio
async def test_health_reports_json_with_a_version(addon):
    flow = tflow.tflow()
    flow.request.method = "GET"
    flow.request.path = "/_health"
    flow.request.content = b""

    await addon.request(flow)

    assert flow.response.headers["Content-Type"] == "application/json"
    assert b'"version"' in flow.response.content


@pytest.mark.asyncio
async def test_uninspectable_requests_are_still_counted(addon):
    """A request with no body and no query used to pass through with no
    metric and no log at all."""
    before = FLOWS_SEEN_TOTAL._value.get()

    flow = tflow.tflow()
    flow.request.method = "GET"
    flow.request.path = "/nothing"
    flow.request.content = b""
    await addon.request(flow)

    assert FLOWS_SEEN_TOTAL._value.get() == before + 1


def test_done_shuts_the_engine_down(addon):
    """done() only logged, so workers and the poller outlived the addon."""
    addon.dlp_engine.shutdown = MagicMock()  # shutdown() is synchronous
    addon.done()
    addon.dlp_engine.shutdown.assert_called_once()


def test_missing_terms_file_is_announced(tmp_path, caplog):
    """Seeding placeholders looked exactly like a successful load."""
    from src.dlp_engine import FileTermProvider

    provider = FileTermProvider(str(tmp_path / "absent.txt"))
    with caplog.at_level(logging.WARNING, logger="dlp_proxy"):
        terms = provider.get_terms()

    assert terms == list(FileTermProvider.DEFAULT_TERMS)
    assert "placeholder terms" in caplog.text
