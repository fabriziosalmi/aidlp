import typer
import subprocess
import os
import sys
import time
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
    ]
    
    if ssl_bump:
        # mitmproxy defaults to ssl bump if not specified otherwise, but we can be explicit or add certs
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
    stats_file = "stats.json"
    if not os.path.exists(stats_file):
        typer.echo("No stats available yet.")
        return
        
    import json
    with open(stats_file, "r") as f:
        data = json.load(f)
        
    typer.echo("DLP Proxy Stats:")
    typer.echo(f"  Total Requests Redacted: {data.get('total_redacted', 0)}")
    typer.echo(f"  Static Replacements: {data.get('static_replacements', 0)}")
    typer.echo(f"  ML Replacements: {data.get('ml_replacements', 0)}")
    
    total_time = data.get('total_time', 0)
    total_reqs = data.get('total_requests', 0)
    if total_reqs > 0:
        avg_time = total_time / total_reqs
        typer.echo(f"  Avg Processing Time: {avg_time:.4f}s")

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
