# Deployment Patterns

Strategies for deploying AI DLP Proxy in production environments.

## Docker Compose

For a complete stack including Prometheus and Grafana (optional), use Docker Compose. The image uses a **multi-stage build** based on `python:3.12-slim` for minimal size and maximum security.

```yaml
version: '3.8'
services:
  aidlp:
    build: .
    # Published to loopback only. Docker publishes to every host interface
    # unless you say otherwise, which would bypass proxy.host entirely.
    ports:
      - "127.0.0.1:8080:8080"
      - "127.0.0.1:9090:9090"
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./terms.txt:/app/terms.txt
      # Persist CA certs to avoid regeneration.
      # The image runs as appuser (useradd -m), and mitmproxy stores its CA
      # under $HOME/.mitmproxy -- so this is /home/appuser/.mitmproxy, NOT
      # /root/.mitmproxy. Mounting the wrong path silently persists nothing:
      # the CA is regenerated on every container recreate, invalidating every
      # client that trusted the previous one.
      - ./certs:/home/appuser/.mitmproxy
    environment:
      - VAULT_TOKEN=${VAULT_TOKEN}
      # Inside the container the proxy must bind every interface for the
      # port publishing above to reach it.
      - AIDLP_PROXY__HOST=0.0.0.0
      - AIDLP_PROXY__METRICS_HOST=0.0.0.0
      # Mandatory on any non-loopback bind: without it the proxy refuses
      # to relay rather than serve as an open proxy.
      - AIDLP_PROXY__AUTH_TOKEN=${AIDLP_PROXY_AUTH_TOKEN:?supply a secret of your own}
```

::: danger The proxy is an open relay without a token
`aidlp` performs no authorisation of its own. Any caller that can open a
connection can make it fetch whatever upstream a request names, and read the
Prometheus endpoint.

Since 3.0.0 it therefore binds `127.0.0.1` by default, and **refuses to start**
when bound to a routable interface with no `proxy.auth_token` set — the refusal
is logged at CRITICAL, which mitmproxy treats as fatal during startup.
Callers then authenticate with:

```
Proxy-Authorization: Bearer <token>
Proxy-Authorization: Basic base64(anyuser:<token>)
```

The credential is stripped before the request is forwarded, so it never reaches
the upstream. `/_health` stays reachable without it, for container health
checks.

Exposing the proxy beyond a single trusted host wants an authenticating reverse
proxy in front of it as well; the shared secret is a floor, not a substitute for
per-caller identity.
:::

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

## Availability

The reference `docker-compose.yml` and the Kubernetes "Centralized Gateway"
pattern below both run a **single** proxy instance, inline on every client
request. If that process dies, clients routed through it lose their path to
the LLM endpoint entirely — the proxy fails *closed* at the network level,
because there is no path around it. Nothing silently bypasses redaction, but
nothing gets through either.

That is the right failure direction for a DLP control, and the wrong one for
availability. For production, run several instances behind a load balancer and
give the orchestrator a restart policy; the proxy keeps no cross-request state,
so instances are interchangeable. The only per-instance state is the mitmproxy
CA, which every replica must share — mount the same CA directory into all of
them, or clients will reject whichever replica they did not trust.

## Terms File Durability

`terms.txt` is the only mutable state the proxy owns. `aidlp add-term` writes it
atomically — snapshot to `terms.txt.bak`, write a temp file, `fsync`, rename —
so a kill mid-write leaves either the old contents or the new, never a half-line
that would be loaded as a keyword on the next start.

**Recovery.** If the live file is damaged:

```bash
cp terms.txt.bak terms.txt      # restore the state before the last add-term
```

A running proxy re-reads the file within `dlp.reload_interval` seconds (default
60), so no restart is required.

The `.bak` is a single-step recovery point, not a history. In containers it
lives inside the container filesystem unless `terms.txt` is on a mounted volume
— mount the file, or keep it in version control, if you need it to survive the
container.

## Vault Integration

Securely manage your static sensitive terms using HashiCorp Vault.

1.  **Enable KV Secrets Engine**:
    ```bash
    vault secrets enable -path=aidlp kv-v2
    ```

2.  **Write Secrets**:
    ```bash
    vault kv put aidlp/terms \
        term1="secret_project_x" \
        term2="api_key_123"
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
