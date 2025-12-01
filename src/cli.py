import typer
import subprocess
import os
import requests
import re

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
        # mitmproxy defaults to ssl bump if not specified otherwise, but we can
        # be explicit or add certs
        pass

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
    Show current stats.
    """
    """
    Show current stats from Prometheus.
    """
    metrics_url = "http://localhost:9090"
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
    # Load raw config to preserve comments if possible, but for now just append
    # simpler to just append to the list in memory and save
    import yaml

    with open("config.yaml", "r") as f:
        data = yaml.safe_load(f)

    if "dlp" not in data:
        data["dlp"] = {}
    if "static_terms" not in data["dlp"]:
        data["dlp"]["static_terms"] = []

    if term not in data["dlp"]["static_terms"]:
        data["dlp"]["static_terms"].append(term)
        with open("config.yaml", "w") as f:
            yaml.dump(data, f)
        typer.echo(f"Added '{term}' to static terms.")
    else:
        typer.echo(f"'{term}' already exists.")


if __name__ == "__main__":
    app()
