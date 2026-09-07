# Changelog

All notable changes to this project will be documented in this file.

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

### Changed: environment variables now take precedence over `config.yaml`

They always should have. Both the README and `docs/reference/config.md` stated
it plainly. But `config.yaml` was loaded via `AppConfig(**raw_config)`, and in
`pydantic-settings` constructor arguments outrank every other source — so the
file quietly beat the environment.

The consequences were exactly the kind that go unnoticed:

- `AIDLP_PROXY__UPSTREAM_INSECURE=false`, set to harden a deployment, could be
  undone by a stale `upstream_insecure: true` in a file — re-disabling the
  upstream certificate verification that 2.0.0 had just made the default.
- `AIDLP_DLP__ML_ENABLED=true` could be overridden into disabling ML redaction
  entirely, leaving static term matching as the only protection, with nothing
  announcing the downgrade.
- `docker-compose.yml` ships `AIDLP_*` variables and assumes they win. They only
  did because the image happens not to contain a `config.yaml`.

Precedence is now, highest first: **environment → `config.yaml` → defaults**.
Sources merge key by key, so setting one variable no longer discards the rest of
a section.

### Added
- Startup logs a warning naming every `config.yaml` key an environment variable
  overrides, so the conflict is stated rather than silent.

### Migration
If you run with both a `config.yaml` and `AIDLP_*` variables covering the same
keys, your effective configuration changes with this release. The new startup
warning names precisely which keys are affected; confirm the resulting values
are the ones you want, especially `proxy.upstream_insecure` and `dlp.ml_enabled`.

## [2.0.0] - 2026-08-13

### ⚠️ BREAKING: upstream TLS certificates are now verified

Through 1.x, `proxy.ssl_bump` defaulted to `true`, and its only effect was to
pass `--ssl-insecure` to mitmproxy — **disabling verification of the upstream
server's certificate**. The name promised TLS interception and the documentation
described it as "Enables HTTPS interception", but neither was true. The practical
result: every stock deployment accepted any certificate the upstream presented,
so the prompts this proxy exists to protect could be intercepted and altered in
transit by anything that could answer for the endpoint.

**Verification is now on by default.**

- Added `proxy.upstream_insecure` (default `false`), and the matching
  `--upstream-insecure` flag, as the explicit and only way to skip verification.
- Enabling it logs a warning on every startup, from both the CLI and the
  mitmproxy addon, so the state is visible even when `mitmdump` is driven
  directly.
- `proxy.ssl_bump` and `--ssl-bump` are **deprecated and inert**. Setting either
  prints a deprecation notice and changes nothing.

**Migration.** If you talk to an upstream with a private CA or a self-signed
certificate and change nothing, connections will now fail with a certificate
error. That is intended. Either trust the CA on the host, or opt back in with:

```yaml
proxy:
  upstream_insecure: true   # accepts ANY upstream certificate
```

HTTPS interception towards *clients* is unaffected — that was always mitmproxy's
own behaviour and never depended on this setting.

### Fixed
- `aidlp start` could not start at all: it passed `--ssl-version-client` and
  `--ssl-version-server`, removed from mitmproxy years ago, and mitmdump exited
  with "unrecognized arguments".
- DLP was fail-open in three ways despite the fail-closed claim: a Vault outage
  silently emptied the static term list; `Content-Type: application/octet-stream`
  (or no header) bypassed body inspection entirely; query strings were never
  inspected.
- A disconnecting client could kill the ML workers permanently, after which every
  request hung forever rather than failing closed.
- The Docker image could not build (it copied a `poetry.lock` that was never
  committed) and CI resolved dependencies that contradicted `pyproject.toml`.

### Changed
- Removed `upstream.default_scheme`, which no code ever read.
- `proxy.port` and `proxy.host` are now actually honoured by `start`.
- The image is built on every pull request, not only on tags.

## [1.9.7] - 2025-12-04

### Added
- **Local Docker Setup**: Added `docker-compose.yml` configuration for running the DLP Proxy, Prometheus, and Grafana locally.
- **Observability**: Added `prometheus.yml` and configured Grafana for real-time metrics visualization.
- **Verification Script**: Added `test_local_setup.py` to verify the proxy and DLP functionality with LM Studio.
- **Documentation**: Updated `docs/guide/architecture.md` with a new Observability section and updated sequence diagram.

### Fixed
- **Docker Build**: Resolved `apt-get` hash mismatch errors in the Dockerfile by cleaning apt lists.
- **Linting**: Fixed flake8 errors in `test_local_setup.py`.
