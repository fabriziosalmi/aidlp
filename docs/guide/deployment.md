# Deployment Patterns

Strategies for deploying AI DLP Proxy in production environments.

## Docker Compose

For a complete stack including Prometheus and Grafana (optional), use Docker Compose.

```yaml
version: '3.8'
services:
  aidlp:
    build: .
    ports:
      - "8080:8080"
      - "9090:9090"
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./terms.txt:/app/terms.txt
      # Persist CA certs to avoid regeneration
      - ./certs:/root/.mitmproxy
    environment:
      - VAULT_TOKEN=${VAULT_TOKEN}
```

## Kubernetes (K8s)

### Sidecar Pattern
Deploy the proxy as a sidecar container in the same Pod as your application.
- **Pros**: Low latency (localhost), secure communication.
- **Cons**: Resource duplication if multiple apps need it.

### Centralized Gateway
Deploy as a standalone Service/Deployment.
- **Pros**: Centralized management, scaling independent of apps.
- **Cons**: Extra network hop.

**Recommended**: Centralized Gateway for initial rollout to simplify certificate management.

## Vault Integration

Securely manage your static sensitive terms using HashiCorp Vault.

1.  **Enable KV Secrets Engine**:
    ```bash
    vault secrets enable -path=aidlp kv-v2
    ```

2.  **Write Secrets**:
    ```bash
    vault kv put aidlp/terms data='["secret_project_x", "api_key_123"]'
    ```

3.  **Configure Policy**:
    Create a policy `aidlp-policy.hcl`:
    ```hcl
    path "aidlp/data/terms" {
      capabilities = ["read"]
    }
    ```

4.  **Update Config**:
    In `config.yaml`:
    ```yaml
    dlp:
      secrets_provider:
        type: "vault"
        vault:
          url: "http://vault:8200"
          path: "aidlp/terms"
    ```
