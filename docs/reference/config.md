# Configuration Reference

The AI DLP Proxy is configured via a `config.yaml` file located in the root directory.

## Structure

```yaml
proxy:
  # ... network settings ...
dlp:
  # ... engine settings ...
upstream:
  # ... forwarding settings ...
```

## Proxy Settings

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `port` | `int` | `8080` | The TCP port where the proxy listens for incoming connections. |
| `host` | `string` | `0.0.0.0` | The interface to bind to. `0.0.0.0` listens on all interfaces. |
| `metrics_port` | `int` | `9090` | Port for the Prometheus metrics server. |
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

## DLP Settings

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `static_terms_file` | `string` | `terms.txt` | Path to the file containing static keywords. Ignored if provider is `vault`. |
| `ml_enabled` | `bool` | `true` | Enables the ML-based PII detection engine (Presidio). |
| `ml_threshold` | `float` | `0.5` | Confidence threshold (0.0-1.0). Higher values reduce false positives but may miss some PII. |
| `nlp_model` | `string` | `en_core_web_sm` | SpaCy model to use. Options: `en_core_web_lg` (accurate), `en_core_web_sm` (fast). |
| `entities` | `list` | `null` | List of entities to detect (e.g., `["PERSON", "EMAIL_ADDRESS"]`). `null` detects all supported types. |
| `replacement_token` | `string` | `[REDACTED]` | The string used to replace sensitive data. |
| `secrets_provider.type` | `string` | `file` | Source of static terms. Options: `file`, `vault`. |
| `secrets_provider.vault.url` | `string` | - | URL of the Vault server (e.g., `http://localhost:8200`). |
| `secrets_provider.vault.path` | `string` | - | Path to the KV secret (e.g., `aidlp/terms`). |
| `secrets_provider.vault.token` | `string` | - | Vault token. **Recommended:** Use `VAULT_TOKEN` env var instead. |

## Environment Variables

Sensitive configuration can be overridden via environment variables:

- `VAULT_TOKEN`: Authentication token for HashiCorp Vault.

## Full Configuration Example

```yaml
# config.yaml
proxy:
  # The port the proxy listens on for incoming traffic
  port: 8080
  # The port for Prometheus metrics
  metrics_port: 9090
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
