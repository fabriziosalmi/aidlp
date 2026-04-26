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

    try:
        subprocess.run(cmd, env=env)
    except KeyboardInterrupt:
        typer.echo("Stopping proxy...")


@app.command()
def stats():
    """
    Show current stats from Prometheus.
    """
    metrics_port = config.get("proxy.metrics_port", 9090)
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
    config_path = "config.yaml"
    if not os.path.exists(config_path):
        typer.echo(f"Config file '{config_path}' not found.")
        raise typer.Exit(1)

    with open(config_path, "r") as f:
        data = yaml.safe_load(f) or {}

    if "dlp" not in data:
        data["dlp"] = {}
    if "static_terms" not in data["dlp"]:
        data["dlp"]["static_terms"] = []

    if term not in data["dlp"]["static_terms"]:
        data["dlp"]["static_terms"].append(term)
        with open(config_path, "w") as f:
            yaml.dump(data, f)
        typer.echo(f"Added '{term}' to static terms.")
    else:
        typer.echo(f"'{term}' already exists.")


if __name__ == "__main__":
    app()
