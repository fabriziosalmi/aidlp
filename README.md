# AI DLP Proxy

![CI](https://github.com/fabriziosalmi/aidlp/actions/workflows/ci.yml/badge.svg)
![Docker](https://github.com/fabriziosalmi/aidlp/actions/workflows/docker-publish.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)

A high-performance, enterprise-grade HTTP/HTTPS Data Loss Prevention (DLP) proxy designed to sanitize sensitive information before it reaches external LLM endpoints.

> 📘 **Documentation**
>
> Full documentation is available at [https://fabriziosalmi.github.io/aidlp/](https://fabriziosalmi.github.io/aidlp/) (or locally via `npm run docs:dev`).

> ⚠️ **Breaking change in 3.0.0 — the proxy no longer relays for anonymous callers**
>
> `aidlp` performs no authorisation of its own: any caller able to open a
> connection could make it fetch whatever upstream a request named, and read its
> unauthenticated Prometheus endpoint. The default bind was `0.0.0.0`, so that
> was reachable from the whole network.
>
> From 3.0.0 `proxy.host` and `proxy.metrics_host` default to `127.0.0.1`, and
> binding a routable interface **without** `proxy.auth_token` makes the process
> refuse to start rather than serve as an open proxy. With a token set, callers send
> `Proxy-Authorization: Bearer <token>` (or `Basic base64(anyuser:<token>)`); the
> header is stripped before forwarding, so the secret never reaches the upstream.
> `/_health` stays open for container health checks.
>
> `docker-compose.yml` now publishes to loopback only and requires
> `AIDLP_PROXY_AUTH_TOKEN` and `GF_SECURITY_ADMIN_PASSWORD` — see `.env.example`.
> The Grafana `admin` default password is gone.

> ⚠️ **Breaking change in 2.0.0 — upstream TLS certificates are now verified**
>
> Up to and including 1.x, `proxy.ssl_bump` defaulted to `true` and its only
> effect was passing `--ssl-insecure` to mitmproxy, which **disabled
> verification of the upstream server's certificate**. The name promised TLS
> interception; it delivered the opposite of what it sounded like. Every stock
> deployment accepted any certificate the upstream presented, so the prompts
> this proxy exists to protect could be intercepted in transit.
>
> **From 2.0.0 verification is on by default.** `ssl_bump` is deprecated and
> inert; setting it only prints a warning. If you deliberately need to reach an
> upstream with an untrusted certificate — a private CA, a test endpoint — opt
> in explicitly with `proxy.upstream_insecure: true` or `--upstream-insecure`,
> and the proxy will warn on every startup while it is on.
>
> **If you use a private CA upstream and do nothing, connections will now fail**
> with a certificate error. That is the intended behaviour. See
> [#47](https://github.com/fabriziosalmi/aidlp/issues/47) for the migration
> notes. HTTPS interception towards *clients* is unaffected.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Observability](#observability)
- [License](#license)

## Overview

The **AI DLP Proxy** acts as a secure gateway, intercepting traffic to LLM providers (like OpenAI, Anthropic) and redacting sensitive data in real-time. It uses an advanced parallel processing engine that combines static rules and NLP models for 100% contextual accuracy without blocking the asynchronous proxy loop.

## Features

- **Parallel Redaction Engine**: Runs Static analysis (FlashText) and ML analysis (Presidio/SpaCy) concurrently on the original text, merging offsets before applying redactions to preserve the NLP context window.
- **Asynchronous Worker Queue**: Heavy ML inferences are offloaded to a bounded `asyncio.Queue` with dedicated persistent workers, preventing OOM and thread-thrashing under high concurrency.
- **Atomic Hot-Reload**: Automatically polls HashiCorp Vault (or files) every 60 seconds and swaps redaction terms atomically, guaranteeing zero-downtime secret rotation.
- **Validated Configuration**: Deeply validated via `pydantic-settings`, with full support for `AIDLP_` prefixed environment variables. Unknown keys *inside* a section are rejected outright; unknown top-level sections are ignored (so a stray `AIDLP_*` variable cannot stop startup) but are named in a startup warning rather than dropped in silence.
- **Smart Body Routing & JSON Parsing**: Safely ignores binary files. For `application/json`, it recursively traverses the AST to redact only string values, preserving the exact JSON structure and NLP context.
- **Enterprise Observability**: Native Prometheus metrics (`/metrics`) and structured JSON logging.
- **Fail Closed Security**: Hardened safety loop returns a clean JSON 500 error `{"error": {"message": "DLP Policy Violation"}}` on failure, preventing downstream parser crashes.

## Architecture

The proxy intercepts requests using `mitmproxy` and offloads text analysis to the `DLPEngine`.
Instead of sequential replacement (which corrupts ML context) or flattening payloads (which breaks JSON), the engine performs:
1. **Recursive Traversal**: Parses JSON safely and targets strings without corrupting keys.
2. **Parallel Extraction**: Static terms and ML entities are extracted simultaneously.
3. **Overlap Resolution**: Offsets are merged and deduplicated in `O(N log N)`.
4. **Atomic Replacement**: `[REDACTED]` tokens are applied from end-to-start to preserve index offsets.

## Installation

### Local Setup
```bash
git clone https://github.com/fabriziosalmi/aidlp.git
cd aidlp
python3 -m venv venv && source venv/bin/activate
pip install poetry
poetry install
poetry run python -m spacy download en_core_web_sm
poetry run python src/cli.py start --port 8080
```

### Docker Deployment
```bash
cp .env.example .env          # then fill in both secrets
docker-compose up --build -d
curl -x http://localhost:8080 \
     --proxy-header "Proxy-Authorization: Bearer $AIDLP_PROXY_AUTH_TOKEN" \
     http://httpbin.org/ip
```
Compose publishes to `127.0.0.1` only and refuses to start until
`AIDLP_PROXY_AUTH_TOKEN` and `GF_SECURITY_ADMIN_PASSWORD` are set — neither has
a fallback, so nothing ships with a credential everybody already knows.

## Configuration

The proxy uses `pydantic-settings` and can be configured via `config.yaml` or Environment Variables (prefix: `AIDLP_`).

**Precedence, highest first:** environment variables → `config.yaml` → built-in defaults.

> ⚠️ Before **2.1.0** this was the other way round: `config.yaml` silently beat the environment, despite this page having always claimed otherwise. If you have both, check which values actually apply after upgrading — the proxy now logs a warning naming every `config.yaml` key an environment variable overrides.

### `config.yaml`
```yaml
proxy:
  port: 8080
  # Loopback by default; widening it requires an auth_token (see below).
  host: 127.0.0.1
  metrics_port: 9090
  metrics_host: 127.0.0.1
  # Shared secret for Proxy-Authorization. Prefer AIDLP_PROXY__AUTH_TOKEN.
  # auth_token: null
  # Skip upstream certificate verification. Leave false; see the note below.
  upstream_insecure: false

dlp:
  static_terms_file: "terms.txt"
  ml_enabled: true
  nlp_model: "en_core_web_sm"
  # Forward with static-only redaction when the ML stage times out, instead of
  # failing the request closed. Off by default: partial redaction is a real
  # reduction in coverage, so it has to be a deliberate choice.
  degrade_to_static_on_ml_timeout: false
  secrets_provider:
    type: "vault"
    vault:
      url: "http://localhost:8200"
      path: "aidlp/terms"
```

### Environment Variables
You can override any nested config. Example:
```bash
export AIDLP_PROXY__PORT=8080
export AIDLP_DLP__SECRETS_PROVIDER__TYPE="vault"
export AIDLP_DLP__SECRETS_PROVIDER__VAULT__TOKEN="hvs.your_token"
```

## Usage

**Example (cURL)**:
```bash
curl -x http://localhost:8080 \
     -H "Content-Type: application/json" \
     -X POST http://httpbin.org/post \
     -d '{"prompt": "My password is super_secret_token and my name is John Doe"}'
```

**Output**:
```json
{
  "data": "{\"prompt\": \"My password is [REDACTED] and my name is [REDACTED]\"}"
}
```

## Observability

Prometheus metrics are available at `http://localhost:9090` (loopback by default; see `proxy.metrics_host`).

### Health endpoint

`GET /_health` through the proxy returns JSON and is exempt from
`Proxy-Authorization`, so container health checks work without credentials:

```json
{"status": "ok", "version": "4.0.1", "details": {"terms_loaded": true, "ml_workers_alive": 4}}
```

`200` when healthy, `503` when a subsystem is degraded — terms failed to load or
have gone stale, the Vault circuit breaker is open, the ML worker pool is dead,
or the term poller stopped. It is covered by the same compatibility policy as
the CLI flags.

### Metrics

Traffic:

- `dlp_flows_seen_total`: Every request the proxy saw, inspected or not.
- `dlp_requests_total`: Requests that reached DLP processing.
- `dlp_redacted_total`: Requests in which something was redacted.
- `dlp_pii_detected_total{type}`: PII entities found, by type (e.g. `PERSON`).
- `dlp_active_connections`: Requests currently in flight.
- `dlp_latency_seconds`: Histogram of time spent in DLP processing.
- `dlp_token_usage_total{direction}`: Estimated tokens in and out.

Term-source health — these are what an alert on "redaction terms have gone
stale" should be built from:

- `dlp_term_reload_failures_total{source}`: Failed term refreshes.
- `dlp_terms_last_reload_success_timestamp_seconds`: Unix time of the last
  successful load. Alert on its age.
- `dlp_term_poller_alive`: `1` while the refresh poller is running.

ML pool health:

- `dlp_ml_workers_alive`: Live ML worker tasks.
- `dlp_ml_worker_restarts_total`: Workers replaced after exceeding the hard
  analysis ceiling.
- `dlp_ml_degraded_total`: Requests forwarded with static-only redaction after
  an ML timeout. Non-zero only if `dlp.degrade_to_static_on_ml_timeout` is on.

`aidlp stats` surfaces a subset of these (requests, redactions, PII entities,
active connections); the full set is on the metrics port.

Logs are printed in structured JSON format to stdout, and carry the
`X-Request-ID` correlation identifier, which is also threaded into the DLP
engine so an ML failure names the request that caused it.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
