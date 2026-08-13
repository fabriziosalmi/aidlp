import pytest

from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

from src.cli import app
from src.config import config

runner = CliRunner()


@patch("src.cli.os.execvpe")
def test_start_default(mock_run):
    result = runner.invoke(app, ["start"])
    assert result.exit_code == 0
    assert "Starting DLP Proxy on 0.0.0.0:8080" in result.output
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][1]
    assert "mitmdump" in cmd
    assert "-p" in cmd
    assert "8080" in cmd


@patch("src.cli.os.execvpe")
def test_start_verifies_upstream_by_default(mock_run):
    """The default must not disable upstream certificate verification.

    Until 2.0.0 `ssl_bump` defaulted to true and mapped straight to
    --ssl-insecure, so every stock deployment accepted any upstream
    certificate.
    """
    runner.invoke(app, ["start"])
    assert "--ssl-insecure" not in mock_run.call_args[0][1]


@patch("src.cli.os.execvpe")
def test_start_custom_port(mock_run):
    result = runner.invoke(app, ["start", "--port", "9000"])
    assert result.exit_code == 0
    assert "Starting DLP Proxy on 0.0.0.0:9000" in result.output
    cmd = mock_run.call_args[0][1]
    assert "9000" in cmd


@patch("src.cli.os.execvpe")
def test_start_upstream_insecure_is_opt_in(mock_run):
    result = runner.invoke(app, ["start", "--upstream-insecure"])
    assert result.exit_code == 0
    assert "--ssl-insecure" in mock_run.call_args[0][1]
    # Turning verification off must never be quiet.
    assert "verification is DISABLED" in result.output


@patch("src.cli.os.execvpe")
def test_start_upstream_insecure_from_config(mock_run):
    with patch.object(config.proxy, "upstream_insecure", True):
        result = runner.invoke(app, ["start"])
    assert result.exit_code == 0
    assert "--ssl-insecure" in mock_run.call_args[0][1]


@patch("src.cli.os.execvpe")
def test_deprecated_ssl_bump_warns_and_does_not_disable_verification(mock_run):
    """`--ssl-bump` used to disable verification. It must now be inert."""
    result = runner.invoke(app, ["start", "--ssl-bump"])
    assert result.exit_code == 0
    assert "ssl_bump is deprecated" in result.output
    assert "--ssl-insecure" not in mock_run.call_args[0][1]


@patch("src.cli.os.execvpe")
def test_deprecated_ssl_bump_in_config_warns(mock_run):
    with patch.object(config.proxy, "ssl_bump", True):
        result = runner.invoke(app, ["start"])
    assert result.exit_code == 0
    assert "ssl_bump is deprecated" in result.output
    assert "--ssl-insecure" not in mock_run.call_args[0][1]


@patch("src.cli.os.execvpe")
def test_start_uses_no_removed_ssl_flags(mock_run):
    """--ssl-version-client/-server were removed from mitmproxy long ago."""
    runner.invoke(app, ["start"])
    cmd = mock_run.call_args[0][1]
    assert "--ssl-version-client" not in cmd
    assert "--ssl-version-server" not in cmd


@pytest.mark.asyncio
@patch("src.cli.os.execvpe")
async def test_start_command_is_accepted_by_mitmdump(mock_run):
    """The regression guard: the previous command line made mitmdump exit
    with 'unrecognized arguments', and mocking execvpe hid it completely.

    Parse the real command with mitmproxy's own parser instead.
    """
    from mitmproxy import options
    from mitmproxy.tools import cmdline
    from mitmproxy.tools.dump import DumpMaster

    runner.invoke(app, ["start"])
    cmd = mock_run.call_args[0][1]

    opts = options.Options()
    DumpMaster(opts, with_termlog=False, with_dumper=False)  # registers addon options
    parser = cmdline.mitmdump(opts)

    parser.parse_args(cmd[1:])  # raises SystemExit if any flag is unknown

    # --set keys are not validated by argparse, so check them explicitly.
    valid = opts.keys()
    for flag, value in zip(cmd, cmd[1:]):
        if flag == "--set":
            key = value.split("=", 1)[0]
            assert key in valid, f"{key} is not a mitmproxy option"


@patch("src.cli.os.execvpe", side_effect=KeyboardInterrupt)
def test_start_keyboard_interrupt(mock_run):
    result = runner.invoke(app, ["start"])
    assert result.exit_code != 0


@patch("src.cli.requests.get")
def test_stats_success(mock_get):
    mock_response = MagicMock()
    mock_response.text = (
        "# HELP dlp_requests_total Total\n"
        "dlp_requests_total 42\n"
        "dlp_redacted_total 7\n"
        "dlp_active_connections 3\n"
    )
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "Total Requests: 42" in result.output
    assert "Redacted Requests: 7" in result.output
    assert "Active Connections: 3" in result.output


@patch("src.cli.requests.get", side_effect=Exception("connection refused"))
def test_stats_connection_error(mock_get):
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "Failed to fetch metrics" in result.output
    assert "Ensure the proxy is running." in result.output


@patch("src.cli.requests.get")
def test_stats_metrics_missing(mock_get):
    mock_response = MagicMock()
    mock_response.text = "# no metrics here\n"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "Total Requests: 0" in result.output


# CliRunner.isolated_filesystem() is gone in typer >= 0.13 (its CliRunner no
# longer subclasses click's), so drive the working directory directly.
def test_add_term_no_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["add-term", "mysecret"])
    assert result.exit_code == 0


def test_add_term_new_term(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["add-term", "mynewterm"])
    assert result.exit_code == 0
    assert "Added 'mynewterm'" in result.output

    assert "mynewterm" in (tmp_path / "terms.txt").read_text()


def test_add_term_already_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "terms.txt").write_text("existing\n")

    result = runner.invoke(app, ["add-term", "existing"])
    assert result.exit_code == 0
    assert "Added" not in result.output
