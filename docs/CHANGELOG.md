# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] - 2026-09-07

### ⚠️ BREAKING: the proxy no longer relays for anonymous callers

`DLPAddon.request` forwarded every request once DLP redaction had run, with
nothing establishing who the caller was. Combined with a default bind of
`0.0.0.0`, any host that could reach the port could use the proxy to fetch
whatever upstream a request named, and could read the unauthenticated
Prometheus endpoint. An open relay is a poor thing for a data-loss-prevention
appliance to be.

- Added `proxy.auth_token`. When set, callers must present
  `Proxy-Authorization: Bearer <token>` or `Basic base64(anyuser:<token>)`;
  anything else gets `407` with a `Proxy-Authenticate` challenge. The
  comparison is constant-time, and the header is **stripped before the request
  is forwarded** so the secret never reaches the upstream.
- `CONNECT` is authorised in `http_connect`, before the tunnel exists —
  checking only in `request()` would let an unauthenticated caller open it
  first.
- `proxy.host` now defaults to **`127.0.0.1`** instead of `0.0.0.0`.
- Binding a routable interface with no `auth_token` is **refused**. The refusal
  is logged at CRITICAL, which mitmproxy treats as fatal during startup, so the
  process exits rather than listening at all; verified end to end. If the addon
  is driven some other way, every request is answered `403` instead of relayed.
  On loopback without a token it runs normally, with a warning.
- Added `proxy.metrics_host` (default `127.0.0.1`). The Prometheus listener had
  no `addr` at all, so it bound every interface; it is deliberately a separate
  knob, so exposing the proxy does not silently expose its metrics.
- `/_health` remains reachable without credentials, for container health checks.

`docker-compose.yml` published `8080:8080`, `9090:9090`, `9091:9090` and
`3000:3000` to every host interface, which bypassed `proxy.host` entirely.
All four are now bound to `127.0.0.1`. Inside the container the proxy still
binds `0.0.0.0` — it has to, both for port publishing and for Prometheus to
scrape `dlp-proxy:9090` — which is why the loopback publishing is what actually
contains it.

The bundled Grafana shipped `GF_SECURITY_ADMIN_PASSWORD=admin`. That default is
gone; both it and `AIDLP_PROXY_AUTH_TOKEN` are now declared with `:?` so compose
refuses to start rather than fall back to a credential committed in the repo.
See the new `.env.example`.

### Migration
- Running on loopback for local development: nothing to do, beyond a warning.
- Exposing the proxy to anything else: set `proxy.auth_token`
  (`AIDLP_PROXY__AUTH_TOKEN`, e.g. `openssl rand -hex 32`) and have callers send
  the `Proxy-Authorization` header. Without it the proxy will refuse to relay.
- Using `docker compose`: copy `.env.example` to `.env` and fill in both
  secrets. `docker compose up` now fails fast if either is missing.
- A shared secret is a floor, not per-caller identity. Beyond a single trusted
  host, put an authenticating reverse proxy in front.

## [2.1.0] - 2026-08-13

### Changed (behavioural)
- **Environment variables now take precedence over `config.yaml`.** They always
  should have — the README and this reference both said so — but the file was
  loaded as constructor arguments, and those outrank every other source in
  `pydantic-settings`. The file silently won.

  This was quiet and it mattered. An `AIDLP_PROXY__UPSTREAM_INSECURE=false` set
  to harden a deployment could be undone by a leftover `upstream_insecure: true`
  in a file, re-disabling the certificate verification that 2.0.0 had just made
  the default. An `AIDLP_DLP__ML_ENABLED=true` could likewise be overridden into
  turning ML redaction off entirely, leaving static term matching as the only
  protection with nothing reporting the downgrade.

  Precedence is now, highest first: environment → `config.yaml` → defaults.
  Sources merge key by key, so one variable no longer discards the rest of a
  section.

### Added
- Startup logs a warning naming every `config.yaml` key that an environment
  variable overrides, so the conflict is visible instead of silent.

### Migration
If you run with both a `config.yaml` and `AIDLP_*` variables setting the same
keys, the effective configuration changes with this release. Check the startup
warning to see exactly which keys are affected, and confirm the values are the
ones you intend — particularly `proxy.upstream_insecure` and `dlp.ml_enabled`.

## [2.0.0] - 2026-08-13

### Removed (BREAKING)
- `proxy.ssl_bump` and `--ssl-bump` are deprecated and inert. Through 1.x this
  setting defaulted to `true` and its only effect was disabling verification of
  the **upstream** server's TLS certificate — despite the name, and despite the
  documentation describing it as "Enables HTTPS interception". Every stock
  deployment therefore accepted any certificate the upstream presented, so
  forwarded prompts could be intercepted and altered in transit.
- `upstream.default_scheme`, which no code ever read.

### Added
- `proxy.upstream_insecure` (default `false`) and `--upstream-insecure`: the
  explicit, and now only, way to skip upstream certificate verification. While
  enabled, both the CLI and the mitmproxy addon warn on every startup.
- Query-string values are redacted, on every HTTP method.
- The Docker image is built on every pull request, not only on release tags.

### Fixed
- `aidlp start` could not start: it passed `--ssl-version-client` and
  `--ssl-version-server`, removed from mitmproxy years ago.
- A Vault outage silently emptied the static term list, forwarding secrets in
  the clear; the term provider now keeps the last known good list.
- `Content-Type: application/octet-stream`, or no header at all, bypassed body
  inspection entirely.
- A disconnecting client could permanently kill the ML workers, after which
  every request hung instead of failing closed.
- The Docker image could not build, and CI installed a dependency set that
  contradicted `pyproject.toml`.

### Migration
If you reach an upstream through a private CA or a self-signed certificate and
change nothing, connections will now fail with a certificate error. Either trust
the CA on the host, or opt back in explicitly:

```yaml
proxy:
  upstream_insecure: true   # accepts ANY upstream certificate
```

HTTPS interception towards *clients* is unaffected.

## [1.0.0] - 2026-04-28
### Added
- Enterprise-grade AI DLP proxy architecture.
- Asynchronous ML worker queue for non-blocking HTTP processing.
- Parallel text redaction combining Presidio and FlashText.
- JSON-aware recursive redaction to preserve API payload structures.
- Multi-architecture Docker builds (`linux/amd64` and `linux/arm64`).
- Pinned GitHub Actions SHAs for supply chain security.
- Comprehensive `pydantic-settings` based configuration system.
- Hot-reloading of Vault/local terms via background tasks.
- Improved CI pipeline with strict `flake8` linting and `pytest-cov` gating.
- Automated dependency management via Dependabot.
