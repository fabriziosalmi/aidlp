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
| `ssl_bump` | `bool` | `true` | Enables HTTPS interception. Requires CA cert installation on clients. |
| `metrics_port` | `int` | `9090` | Port for the Prometheus metrics server. |

## DLP Settings

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `static_terms_file` | `string` | `terms.txt` | Path to the file containing static keywords. Ignored if provider is `vault`. |
| `ml_enabled` | `bool` | `true` | Enables the ML-based PII detection engine (Presidio). |
| `ml_threshold` | `float` | `0.5` | Confidence threshold (0.0-1.0). Higher values reduce false positives but may miss some PII. |
| `nlp_model` | `string` | `en_core_web_lg` | SpaCy model to use. Options: `en_core_web_lg` (accurate), `en_core_web_sm` (fast). |
| `entities` | `list` | `null` | List of entities to detect (e.g., `["PERSON", "EMAIL_ADDRESS"]`). `null` detects all supported types. |
| `replacement_token` | `string` | `[REDACTED]` | The string used to replace sensitive data. |
| `secrets_provider.type` | `string` | `file` | Source of static terms. Options: `file`, `vault`. |
| `secrets_provider.vault.url` | `string` | - | URL of the Vault server (e.g., `http://localhost:8200`). |
| `secrets_provider.vault.path` | `string` | - | Path to the KV secret (e.g., `aidlp/terms`). |
| `secrets_provider.vault.token` | `string` | - | Vault token. **Recommended:** Use `VAULT_TOKEN` env var instead. |

## Upstream Settings

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `default_scheme` | `string` | `https` | Default protocol for upstream requests if not specified. |

## Environment Variables

Sensitive configuration can be overridden via environment variables:

- `VAULT_TOKEN`: Authentication token for HashiCorp Vault.
- `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`: Used in CI/CD for publishing images.

## Full Configuration Example

```yaml
# config.yaml
proxy:
  # The port the proxy listens on for incoming traffic
  port: 8080
  # The port for Prometheus metrics
  metrics_port: 9090
  # Enable SSL interception (required for DLP)
  ssl_bump: true

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
