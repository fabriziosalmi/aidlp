import typer
import os
import requests
import re
from typing import Optional

from src.config import config

app = typer.Typer()


SSL_BUMP_DEPRECATED = (
    "WARNING: ssl_bump is deprecated and no longer has any effect.\n"
    "  It never enabled TLS interception, whatever the name suggested: its\n"
    "  only effect was to disable verification of the upstream server's\n"
    "  certificate, and it was on by default.\n"
    "  Verification is now ON. If you genuinely need to talk to an upstream\n"
    "  with an untrusted certificate, ask for it explicitly with\n"
    "  --upstream-insecure (or proxy.upstream_insecure in config.yaml)."
)

UPSTREAM_INSECURE_WARNING = (
    "WARNING: upstream TLS certificate verification is DISABLED.\n"
    "  The proxy will accept any certificate the upstream presents, so the\n"
    "  prompts it forwards can be intercepted and altered in transit.\n"
    "  Redaction does not protect you from that. Use this only against a\n"
    "  known upstream with a private CA, never on the open internet."
)


@app.command()
def start(
    port: Optional[int] = None,
    host: Optional[str] = None,
    upstream_insecure: Optional[bool] = None,
    ssl_bump: Optional[bool] = None,
):
    """
    Start the DLP Proxy.
    """
    # Fall back to config.yaml / AIDLP_* env vars when not given on the CLI.
    port = port if port is not None else config.proxy.port
    host = host if host is not None else config.proxy.host

    if ssl_bump is not None or config.proxy.ssl_bump is not None:
        typer.secho(SSL_BUMP_DEPRECATED, fg=typer.colors.YELLOW, err=True)

    if upstream_insecure is None:
        upstream_insecure = config.proxy.upstream_insecure

    typer.echo(f"Starting DLP Proxy on {host}:{port}...")

    # Construct mitmdump command.
    # NOTE: --ssl-version-client/--ssl-version-server were removed in
    # mitmproxy; the current spelling is --set tls_version_*_min.
    cmd = [
        "mitmdump",
        "-s",
        "src/proxy_core.py",
        "-p",
        str(port),
        "--listen-host",
        str(host),
        "--set",
        "tls_version_client_min=TLS1_2",
        "--set",
        "tls_version_server_min=TLS1_2",
    ]

    if upstream_insecure:
        cmd.extend(["--ssl-insecure"])
        typer.secho(UPSTREAM_INSECURE_WARNING, fg=typer.colors.RED, err=True)

    # Set PYTHONPATH so mitmproxy can find src modules
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()

    # Use exec to replace the CLI process with mitmdump
    try:
        os.execvpe("mitmdump", cmd, env)
    except FileNotFoundError:
        typer.echo("Error: mitmdump not found. Are you in the poetry shell?")
        raise typer.Exit(1)


@app.command()
def stats():
    """
    Show current stats from Prometheus.
    """
    metrics_port = config.proxy.metrics_port
    metrics_url = f"http://localhost:{metrics_port}"
    try:
        response = requests.get(metrics_url)
        response.raise_for_status()
        metrics = response.text
    except Exception as e:
        typer.echo(f"Failed to fetch metrics from {metrics_url}: {e}")
        typer.echo("Ensure the proxy is running.")
        return

    # Parse simple metrics using regex
    def get_metric(name):
        match = re.search(f"^{name} ([\\d\\.]+)", metrics, re.MULTILINE)
        return float(match.group(1)) if match else 0

    total_requests = get_metric("dlp_requests_total")
    redacted_requests = get_metric("dlp_redacted_total")
    active_connections = get_metric("dlp_active_connections")

    typer.echo("DLP Proxy Stats (Prometheus):")
    typer.echo(f"  Total Requests: {int(total_requests)}")
    typer.echo(f"  Redacted Requests: {int(redacted_requests)}")
    typer.echo(f"  Active Connections: {int(active_connections)}")


@app.command()
def add_term(term: str):
    """
    Add a static term to the blacklist.
    """
    if not term or term.strip() == "":
        typer.echo("Error: Term cannot be empty or whitespace-only.")
        raise typer.Exit(1)

    provider_type = config.dlp.secrets_provider.type
    if provider_type == "vault":
        typer.echo(
            "Error: Configured to use Vault. Please add secrets directly to Vault."
        )
        raise typer.Exit(1)

    terms_file = config.dlp.static_terms_file

    if os.path.exists(terms_file):
        with open(terms_file, "r") as f:
            existing = set(line.strip() for line in f)
    else:
        existing = set()

    if term not in existing:
        with open(terms_file, "a") as f:
            f.write(f"\n{term}")
        typer.echo(f"Added '{term}' to {terms_file}.")
        typer.echo(
            "Note: If the proxy is running, Vault poller will pick this up automatically if configured, otherwise restart proxy or wait for hot-reload."
        )
    else:
        typer.echo(f"'{term}' already exists in {terms_file}.")


if __name__ == "__main__":
    app()
