import asyncio
import glob
import logging
import os

import pytest
from unittest.mock import patch
from typer.testing import CliRunner

from src.cli import TERMS_BACKUP_SUFFIX, app, write_terms_atomically
from src.config import config
from src.dlp_engine import (
    MAX_TERM_LENGTH,
    DLPEngine,
    FileTermProvider,
    TermFetchError,
    validate_terms,
)

runner = CliRunner()


def _use_terms_file(path, **overrides):
    """Point the engine/CLI at `path` with the ML model switched off."""
    patches = [
        patch.object(config.dlp, "static_terms_file", str(path)),
        patch.object(config.dlp, "ml_enabled", False),
        patch.object(config.dlp.secrets_provider, "type", "file"),
    ]
    for key, value in overrides.items():
        patches.append(patch.object(config.dlp, key, value))
    return patches


class _Ctx:
    def __init__(self, patches):
        self._patches = patches

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


# --- AIDLP-DATA-04: terms are validated before becoming keywords -----------


def test_validate_terms_keeps_ordinary_entries():
    assert validate_terms(["password", " api_key ", "", "  "], "file") == [
        "password",
        "api_key",
    ]


def test_validate_terms_rejects_control_characters():
    """A half-written line is corruption, not a keyword."""
    assert validate_terms(["good", "bad\x00term", "worse\x08"], "file") == ["good"]


def test_validate_terms_rejects_overlong_entries():
    assert validate_terms(["x" * (MAX_TERM_LENGTH + 1), "ok"], "file") == ["ok"]
    assert validate_terms(["x" * MAX_TERM_LENGTH], "file") == ["x" * MAX_TERM_LENGTH]


def test_validate_terms_logs_without_leaking_the_term(caplog):
    with caplog.at_level(logging.WARNING, logger="dlp_proxy"):
        validate_terms(["s3cr3t\x00value"], "file")
    assert "control characters" in caplog.text
    assert "s3cr3t" not in caplog.text  # terms are secrets


def test_corrupt_line_is_skipped_at_load_time(tmp_path, caplog):
    terms = tmp_path / "terms.txt"
    terms.write_text("alpha\nbra\x00vo\ncharlie\n", encoding="utf-8")

    with _Ctx(_use_terms_file(terms)):
        with caplog.at_level(logging.WARNING, logger="dlp_proxy"):
            engine = DLPEngine()

    assert "alpha" in engine.keyword_processor
    assert "charlie" in engine.keyword_processor
    assert "bra\x00vo" not in engine.keyword_processor
    assert "control characters" in caplog.text


def test_non_utf8_terms_file_is_a_fetch_failure(tmp_path):
    """Better a load-time error than redacting from a mangled file."""
    terms = tmp_path / "terms.txt"
    terms.write_bytes(b"alpha\n\xff\xfe\n")

    with pytest.raises(TermFetchError, match="not valid UTF-8"):
        FileTermProvider(str(terms)).get_terms()


# --- AIDLP-DATA-03: the write is atomic ------------------------------------


def test_write_is_all_or_nothing(tmp_path):
    terms = tmp_path / "terms.txt"
    terms.write_text("alpha\nbravo\n", encoding="utf-8")

    # Simulate a failure at the moment of the rename.
    with patch("src.cli.os.replace", side_effect=OSError("boom")):
        with pytest.raises(OSError):
            write_terms_atomically(str(terms), ["alpha", "bravo", "charlie"])

    # The original is untouched, and nothing half-written is left behind.
    assert terms.read_text(encoding="utf-8") == "alpha\nbravo\n"
    assert glob.glob(str(tmp_path / ".terms-*.tmp")) == []


def test_write_normalises_and_leaves_no_temp_files(tmp_path):
    terms = tmp_path / "terms.txt"
    write_terms_atomically(str(terms), ["alpha", "bravo"])

    assert terms.read_text(encoding="utf-8") == "alpha\nbravo\n"
    assert glob.glob(str(tmp_path / ".terms-*.tmp")) == []


def test_add_term_writes_atomically(tmp_path, monkeypatch):
    terms = tmp_path / "terms.txt"
    terms.write_text("alpha\n", encoding="utf-8")

    with _Ctx(_use_terms_file(terms)):
        result = runner.invoke(app, ["add-term", "bravo"])

    assert result.exit_code == 0
    # No leading blank line: the old append wrote "\n{term}".
    assert terms.read_text(encoding="utf-8") == "alpha\nbravo\n"


# --- AIDLP-DATA-01: there is something to restore from ---------------------


def test_add_term_keeps_the_previous_contents_as_a_backup(tmp_path):
    terms = tmp_path / "terms.txt"
    terms.write_text("alpha\n", encoding="utf-8")

    with _Ctx(_use_terms_file(terms)):
        result = runner.invoke(app, ["add-term", "bravo"])

    backup = tmp_path / ("terms.txt" + TERMS_BACKUP_SUFFIX)
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "alpha\n"
    assert str(backup) in result.output


def test_backup_restores_the_previous_known_good_state(tmp_path):
    """The documented recovery path, exercised."""
    terms = tmp_path / "terms.txt"
    terms.write_text("alpha\n", encoding="utf-8")

    with _Ctx(_use_terms_file(terms)):
        runner.invoke(app, ["add-term", "bravo"])

        # Something truncates the live file.
        terms.write_text("alp", encoding="utf-8")

        backup = tmp_path / ("terms.txt" + TERMS_BACKUP_SUFFIX)
        os.replace(backup, terms)

        engine = DLPEngine()

    assert terms.read_text(encoding="utf-8") == "alpha\n"
    assert "alpha" in engine.keyword_processor


def test_first_write_has_no_backup_to_make(tmp_path):
    terms = tmp_path / "terms.txt"
    with _Ctx(_use_terms_file(terms)):
        result = runner.invoke(app, ["add-term", "alpha"])

    assert result.exit_code == 0
    assert not (tmp_path / ("terms.txt" + TERMS_BACKUP_SUFFIX)).exists()


# --- AIDLP-DATA-02: the file provider is polled too ------------------------


@pytest.mark.asyncio
async def test_file_provider_gets_a_poller(tmp_path):
    """start_workers() only ever created one for Vault."""
    terms = tmp_path / "terms.txt"
    terms.write_text("alpha\n", encoding="utf-8")

    with _Ctx(_use_terms_file(terms, reload_interval=0.05)):
        engine = DLPEngine()
        engine.start_workers()
        try:
            assert engine.poller_task is not None
        finally:
            engine.shutdown()


@pytest.mark.asyncio
async def test_added_term_reaches_a_running_proxy_without_restart(tmp_path):
    terms = tmp_path / "terms.txt"
    terms.write_text("alpha\n", encoding="utf-8")

    with _Ctx(_use_terms_file(terms, reload_interval=0.05)):
        engine = DLPEngine()
        engine.start_workers()
        try:
            assert "bravo" not in engine.keyword_processor
            terms.write_text("alpha\nbravo\n", encoding="utf-8")

            for _ in range(100):
                await asyncio.sleep(0.05)
                if "bravo" in engine.keyword_processor:
                    break
        finally:
            engine.shutdown()

    assert "bravo" in engine.keyword_processor


def test_unchanged_file_is_not_rebuilt(tmp_path):
    """The poller runs on every provider now, so skip untouched sources."""
    terms = tmp_path / "terms.txt"
    terms.write_text("alpha\n", encoding="utf-8")

    with _Ctx(_use_terms_file(terms)):
        engine = DLPEngine()
        first = engine.keyword_processor
        engine.reload_config()
        assert engine.keyword_processor is first  # same object: no rebuild

        terms.write_text("alpha\nbravo\n", encoding="utf-8")
        engine.reload_config()
        assert engine.keyword_processor is not first
        assert "bravo" in engine.keyword_processor
