import yaml
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

from src.cli import app

runner = CliRunner()


@patch("src.cli.os.execvpe")
def test_start_default(mock_run):
    result = runner.invoke(app, ["start"])
    assert result.exit_code == 0
    assert "Starting DLP Proxy on port 8080" in result.output
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "mitmdump" in cmd
    assert "-p" in cmd
    assert "8080" in cmd
    assert "--ssl-insecure" in cmd


@patch("src.cli.os.execvpe")
def test_start_custom_port(mock_run):
    result = runner.invoke(app, ["start", "--port", "9000"])
    assert result.exit_code == 0
    assert "Starting DLP Proxy on port 9000" in result.output
    cmd = mock_run.call_args[0][0]
    assert "9000" in cmd


@patch("src.cli.os.execvpe")
def test_start_no_ssl_bump(mock_run):
    result = runner.invoke(app, ["start", "--no-ssl-bump"])
    assert result.exit_code == 0
    cmd = mock_run.call_args[0][0]
    assert "--ssl-insecure" not in cmd


@patch("src.cli.os.execvpe", side_effect=KeyboardInterrupt)
def test_start_keyboard_interrupt(mock_run):
    result = runner.invoke(app, ["start"])
    assert "Stopping proxy..." in result.output


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


def test_add_term_no_config():
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["add-term", "mysecret"])
        assert result.exit_code == 1
        assert "not found" in result.output


def test_add_term_new_term():
    with runner.isolated_filesystem():
        with open("config.yaml", "w") as f:
            yaml.dump({"proxy": {"port": 8080}}, f)

        result = runner.invoke(app, ["add-term", "mynewterm"])
        assert result.exit_code == 0
        assert "Added 'mynewterm'" in result.output

        with open("config.yaml") as f:
            data = yaml.safe_load(f)
        assert "mynewterm" in data["dlp"]["static_terms"]


def test_add_term_already_exists():
    with runner.isolated_filesystem():
        with open("config.yaml", "w") as f:
            yaml.dump({"dlp": {"static_terms": ["existing"]}}, f)

        result = runner.invoke(app, ["add-term", "existing"])
        assert result.exit_code == 0
        assert "already exists" in result.output


def test_add_term_empty_config():
    with runner.isolated_filesystem():
        with open("config.yaml", "w") as f:
            f.write("")  # empty file -> yaml.safe_load returns None

        result = runner.invoke(app, ["add-term", "term1"])
        assert result.exit_code == 0
        assert "Added 'term1'" in result.output
