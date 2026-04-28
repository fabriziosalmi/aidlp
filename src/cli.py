import typer
import subprocess
import os
import requests
import re
import yaml

from src.config import config

app = typer.Typer()


@app.command()
def start(port: int = 8080, ssl_bump: bool = True):
    """
    Start the DLP Proxy.
    """
    typer.echo(f"Starting DLP Proxy on port {port}...")

    # Construct mitmdump command
    cmd = [
        "mitmdump",
        "-s", "src/proxy_core.py",
        "-p", str(port),
        "--ssl-version-client", "TLS1_2",
        "--ssl-version-server", "TLS1_2",
    ]

    if ssl_bump:
        cmd.extend(["--ssl-insecure"])

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
    provider_type = config.dlp.secrets_provider.type
    if provider_type == "vault":
        typer.echo("Error: Configured to use Vault. Please add secrets directly to Vault.")
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
        typer.echo("Note: If the proxy is running, Vault poller will pick this up automatically if configured, otherwise restart proxy or wait for hot-reload.")
    else:
        typer.echo(f"'{term}' already exists in {terms_file}.")


if __name__ == "__main__":
    app()
