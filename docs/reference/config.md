# Configuration Reference

The AI DLP Proxy is configured via a `config.yaml` file located in the root directory.

## Structure

```yaml
proxy:
  # ... network and access settings ...
dlp:
  # ... engine settings ...
```

## Proxy Settings

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `port` | `int` | `8080` | The TCP port where the proxy listens for incoming connections. |
| `host` | `string` | `127.0.0.1` | Interface to bind. Loopback by default; see the warning below before widening it. |
| `metrics_port` | `int` | `9090` | Port for the Prometheus metrics server. |
| `metrics_host` | `string` | `127.0.0.1` | Interface for the metrics server. Separate from `host` so exposing the proxy does not silently expose its metrics. |
| `auth_token` | `string` | `null` | Shared secret callers present in `Proxy-Authorization`. Required to bind anything but loopback. |
| `upstream_insecure` | `bool` | `false` | Skip verification of the upstream server's TLS certificate. **Leave this off.** See the warning below. |
| `ssl_bump` | `bool` | — | **Deprecated in 2.0.0 and inert.** Setting it only prints a warning. |

::: danger upstream_insecure disables a security control
Turning `upstream_insecure` on makes the proxy accept **any** certificate the
upstream presents, so the prompts it forwards can be intercepted and altered in
transit. Redaction does not protect against that.

Only use it against a known upstream with a private CA, never on the open
internet. The proxy logs a warning on every startup while it is on.
:::

::: warning Renamed from `ssl_bump` in 2.0.0
`ssl_bump` never enabled TLS interception, despite the name and despite what
this page previously claimed. Its one real effect was disabling upstream
certificate verification — and it defaulted to `true`, so every stock
deployment accepted any upstream certificate.

Verification is now on by default. If you relied on the old behaviour, set
`upstream_insecure: true` explicitly. HTTPS interception itself is unaffected
and still requires the CA certificate on clients; that was always handled by
mitmproxy, not by this setting.
:::

::: danger The proxy authorises nobody without `auth_token`
`aidlp` does not identify its callers. Anything that can reach the port can use
it to relay requests to whatever upstream they name, and can read the
unauthenticated Prometheus endpoint.

Because of that, since **3.0.0**:

- `host` and `metrics_host` default to `127.0.0.1` rather than `0.0.0.0`.
- Binding a routable interface with no `auth_token` set is **refused**: the
  refusal is logged at CRITICAL, which mitmproxy treats as fatal during
  startup, so the process exits rather than listen. Should the addon run
  anyway, every request is answered `403` instead of relayed.
- With a token set, callers send `Proxy-Authorization: Bearer <token>` or
  `Basic base64(anyuser:<token>)`. The header is stripped before the request is
  forwarded, so the secret never reaches the upstream.
- `/_health` remains reachable without credentials, for container health checks.

Generate a token with `openssl rand -hex 32` and supply it via
`AIDLP_PROXY__AUTH_TOKEN` rather than committing it to `config.yaml`.
:::

## DLP Settings

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `static_terms_file` | `string` | `terms.txt` | Path to the file containing static keywords. Ignored if provider is `vault`. |
| `ml_enabled` | `bool` | `true` | Enables the ML-based PII detection engine (Presidio). |
| `reload_interval` | `float` | `60.0` | How often the background poller re-reads the term source, in seconds. Applies to the file provider as well as Vault. |
| `ml_threshold` | `float` | `0.5` | Confidence threshold (0.0-1.0). Higher values reduce false positives but may miss some PII. |
| `nlp_model` | `string` | `en_core_web_sm` | SpaCy model to use. Options: `en_core_web_lg` (accurate), `en_core_web_sm` (fast). |
| `entities` | `list` | `null` | List of entities to detect (e.g., `["PERSON", "EMAIL_ADDRESS"]`). `null` detects all supported types. |
| `replacement_token` | `string` | `[REDACTED]` | The string used to replace sensitive data. |
| `secrets_provider.type` | `string` | `file` | Source of static terms. Options: `file`, `vault`. |
| `secrets_provider.vault.url` | `string` | - | URL of the Vault server (e.g., `http://localhost:8200`). |
| `secrets_provider.vault.path` | `string` | - | Path to the KV secret (e.g., `aidlp/terms`). |
| `secrets_provider.vault.token` | `string` | - | Vault token. **Recommended:** Use `VAULT_TOKEN` env var instead. |

### The terms file

`terms.txt` is rewritten atomically. `aidlp add-term` copies the current file to
`terms.txt.bak`, writes the full new contents to a temporary file in the same
directory, `fsync`s it, and renames it into place. An interrupted run therefore
leaves either the old file or the new one, never a truncated trailing line.

**To restore** the previous known-good state:

```bash
cp terms.txt.bak terms.txt
```

A running proxy picks that up within `reload_interval` seconds; no restart is
needed. `terms.txt.bak` holds only the state from immediately before the last
`add-term`, so it is a recovery point, not a history — put `terms.txt` under
version control or your normal backup schedule if you need more than that.

Entries are validated when loaded: blank lines are ignored, and entries longer
than 512 characters or containing control characters are skipped with a warning
naming the position and reason (never the term itself, since these are secrets).
A `terms.txt` that is not valid UTF-8 is treated as a failed fetch, so the proxy
keeps its last known-good keywords rather than redacting from a mangled file.

## Environment Variables

Any setting can be supplied through an `AIDLP_`-prefixed variable, using `__`
to descend into nested keys — `AIDLP_DLP__SECRETS_PROVIDER__TYPE` maps to
`dlp.secrets_provider.type`.

### Precedence

Highest first:

1. Environment variables (`AIDLP_*`)
2. `config.yaml`
3. Built-in defaults

Sources are merged key by key, so setting one variable does not discard the rest
of a `config.yaml` section.

::: warning Reversed in 2.1.0
Before 2.1.0 `config.yaml` was loaded as constructor arguments, which outrank
every other source in `pydantic-settings`. The file therefore **beat** the
environment — the opposite of what this page and the README described, and the
opposite of what `docker-compose.yml` assumed.

The practical consequences were quiet and unpleasant: an
`AIDLP_PROXY__UPSTREAM_INSECURE=false` meant to harden a deployment could be
undone by a stale `upstream_insecure: true` in a file, and an
`AIDLP_DLP__ML_ENABLED=true` could be silenced into disabling ML redaction
altogether.

Since 2.1.0 the order above holds, and startup logs a warning naming every
`config.yaml` key that an environment variable overrides.
:::

Other variables:

- `VAULT_TOKEN`: Authentication token for HashiCorp Vault.

## Full Configuration Example

```yaml
# config.yaml
proxy:
  # The port the proxy listens on for incoming traffic
  port: 8080
  # Interface to bind. Loopback unless you have set an auth_token.
  host: 127.0.0.1
  # The port for Prometheus metrics
  metrics_port: 9090
  # The metrics endpoint is unauthenticated; keep it off the network.
  metrics_host: 127.0.0.1
  # Shared secret for Proxy-Authorization. Prefer AIDLP_PROXY__AUTH_TOKEN.
  # auth_token: null
  # Skip verification of the upstream certificate. Leave this false.
  upstream_insecure: false

dlp:
  # Path to file containing static sensitive terms (one per line)
  static_terms_file: "terms.txt"

  # Enable Machine Learning based detection
  ml_enabled: true

  # Confidence threshold (0.0 - 1.0)
  # Higher = fewer false positives, potentially more missed PII
  ml_threshold: 0.8

  # NLP Model to use
  # "en_core_web_lg" (Accurate, Slower)
  # "en_core_web_sm" (Fast, Less Accurate)
  nlp_model: "en_core_web_sm"

  # Specific entities to detect. If null, detects all.
  # See Presidio docs for full list.
  entities:
    - "PERSON"
    - "PHONE_NUMBER"
    - "EMAIL_ADDRESS"
    - "CREDIT_CARD"

  # String to replace sensitive data with
  replacement_token: "[REDACTED]"

  # Secrets Provider Configuration
  secrets_provider:
    # "file" or "vault"
    type: "vault"
    vault:
      url: "http://localhost:8200"
      path: "aidlp/terms"
      # Token can also be set via VAULT_TOKEN env var
      # token: "hvs.xxx"
```
