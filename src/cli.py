import typer
import os
import requests
import re
import shutil
import tempfile
from typing import Optional

from src import __version__
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

# Distinct exit codes so a wrapper script can tell these apart; every failure
# used to exit 1, which is indistinguishable from any other error.
EXIT_MITMDUMP_MISSING = 3
EXIT_EMPTY_TERM = 4
EXIT_VAULT_MANAGED_TERMS = 5

UPSTREAM_INSECURE_WARNING = (
    "WARNING: upstream TLS certificate verification is DISABLED.\n"
    "  The proxy will accept any certificate the upstream presents, so the\n"
    "  prompts it forwards can be intercepted and altered in transit.\n"
    "  Redaction does not protect you from that. Use this only against a\n"
    "  known upstream with a private CA, never on the open internet."
)


def _version_callback(value: bool):
    if value:
        typer.echo(f"aidlp {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
):
    """AI DLP Proxy."""


@app.command()
def version():
    """Print the running version."""
    typer.echo(f"aidlp {__version__}")


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
        raise typer.Exit(EXIT_MITMDUMP_MISSING)


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
        match = re.search(f"^{re.escape(name)} ([\\d\\.eE+-]+)", metrics, re.MULTILINE)
        return float(match.group(1)) if match else 0

    def sum_labelled_metric(name):
        """Sum a labelled counter across its label values.

        dlp_pii_detected_total is emitted per type, as
        `dlp_pii_detected_total{type="PERSON"} 3.0`, so the unlabelled
        pattern above never matches it -- which is why it was missing from
        this command despite README listing it.
        """
        pattern = rf"^{re.escape(name)}\{{[^}}]*\}} ([\d\.eE+-]+)"
        return sum(float(v) for v in re.findall(pattern, metrics, re.MULTILINE))

    total_requests = get_metric("dlp_requests_total")
    redacted_requests = get_metric("dlp_redacted_total")
    active_connections = get_metric("dlp_active_connections")
    pii_detected = sum_labelled_metric("dlp_pii_detected_total")

    typer.echo("DLP Proxy Stats (Prometheus):")
    typer.echo(f"  Total Requests: {int(total_requests)}")
    typer.echo(f"  Redacted Requests: {int(redacted_requests)}")
    typer.echo(f"  PII Entities Detected: {int(pii_detected)}")
    typer.echo(f"  Active Connections: {int(active_connections)}")


TERMS_BACKUP_SUFFIX = ".bak"


def write_terms_atomically(terms_file: str, terms: list) -> str:
    """Replace `terms_file` with `terms`, keeping the previous copy alongside.

    The old in-place append could be interrupted between open() and the
    buffered write reaching disk, leaving anything from no change at all to a
    truncated trailing line -- which the next start would load as a keyword.
    Writing to a temp file and renaming makes the update all-or-nothing.

    The `.bak` written first is the known-good state to restore from if the
    file is later damaged; there was previously nothing to recover from.

    Returns the backup path (which may not exist on a first write).
    """
    directory = os.path.dirname(os.path.abspath(terms_file)) or "."
    backup_path = terms_file + TERMS_BACKUP_SUFFIX

    if os.path.exists(terms_file):
        shutil.copy2(terms_file, backup_path)

    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".terms-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("".join(f"{term}\n" for term in terms))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, terms_file)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    # Without fsync on the directory the rename itself can still be lost.
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return backup_path  # platform without directory fds; the rename stands
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

    return backup_path


@app.command()
def add_term(term: str):
    """
    Add a static term to the blacklist.
    """
    if not term or term.strip() == "":
        typer.echo("Error: Term cannot be empty or whitespace-only.")
        raise typer.Exit(EXIT_EMPTY_TERM)

    provider_type = config.dlp.secrets_provider.type
    if provider_type == "vault":
        typer.echo(
            "Error: Configured to use Vault. Please add secrets directly to Vault."
        )
        raise typer.Exit(EXIT_VAULT_MANAGED_TERMS)

    terms_file = config.dlp.static_terms_file

    existing = []
    if os.path.exists(terms_file):
        with open(terms_file, "r", encoding="utf-8") as f:
            existing = [line.strip() for line in f if line.strip()]

    if term in existing:
        typer.echo(f"'{term}' already exists in {terms_file}.")
        return

    backup_path = write_terms_atomically(terms_file, existing + [term])
    typer.echo(f"Added '{term}' to {terms_file}.")

    if os.path.exists(backup_path):
        typer.echo(f"Previous contents saved to {backup_path}.")

    typer.echo(
        f"A running proxy re-reads {terms_file} within "
        f"{int(config.dlp.reload_interval)}s. No restart needed."
    )


if __name__ == "__main__":
    app()
