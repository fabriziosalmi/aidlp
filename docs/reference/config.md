# Configuration Reference

The AI DLP Proxy is configured via a `config.yaml` file. Below is the reference for all available configuration options.

## Proxy Settings

Configuration for the proxy server listener.

```yaml
proxy:
  port: 8080          # Port to listen on
  host: 0.0.0.0       # Interface to bind to
  ssl_bump: true      # Enable SSL interception (requires CA certificate)
  metrics_port: 9090  # Port for Prometheus metrics
```

## DLP Settings

Configuration for the Data Loss Prevention engine.

```yaml
dlp:
  # Path to file containing static terms to redact (one per line)
  static_terms_file: "terms.txt"

  # Enable Machine Learning based redaction (Presidio)
  ml_enabled: true

  # Confidence threshold for ML entities (0.0 to 1.0)
  ml_threshold: 0.5

  # Replacement string for redacted content
  replacement_token: "[REDACTED]"

  # Secrets Provider Configuration
  secrets_provider:
    # Type of provider: "file" or "vault"
    type: "file"

    # Vault Configuration (only used if type is "vault")
    vault:
      url: "http://localhost:8200"
      token: "" # Can also be set via VAULT_TOKEN env var
      path: "aidlp/terms"
```

## Upstream Settings

Configuration for upstream forwarding.

```yaml
upstream:
  # Default scheme to use when forwarding requests
  default_scheme: "https"
```
