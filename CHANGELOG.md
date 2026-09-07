# Changelog

All notable changes to this project will be documented in this file.

## [4.0.0] - 2026-09-07

Sweep of the remaining audit findings. Two changes alter an existing contract,
hence the major.

### ⚠️ BREAKING
- **Unknown keys inside a config section are now rejected.** `ProxyConfig`,
  `DLPConfig`, `SecretsProviderConfig` and `VaultConfig` set `extra="forbid"`,
  so a misspelled nested key fails at startup instead of being dropped while
  the default silently applied. Unknown *top-level* sections are still ignored
  (a stray `AIDLP_*` variable must not stop the proxy) but are now named in a
  startup warning.
- **`GET /_health` returns JSON, not plain text.** The body is
  `{"status", "version", "details"}`. A probe matching on the literal `OK`
  needs updating; one checking the status code does not.

### Fixed
- `secrets_provider.type` is a `Literal["file","vault"]`, and `type: vault`
  without a `vault:` section is rejected. `"Vault"`, `"VAULT"` or a typo used
  to fall through to the file provider silently.
- `ml_threshold` is constrained to `[0, 1]`. Above 1.0 every score comparison
  was false, so ML redaction stopped flagging anything while stats looked
  normal.
- `DLPAddon.done()` now shuts the engine down; it previously only logged, so
  the worker tasks and the poller outlived the addon.
- `shutdown()` resets `workers`/`poller_task`, so a later `start_workers()`
  actually respawns. It used to see the cancelled-but-non-empty lists as live
  and spawn nothing, leaving an engine with no workers at all. `aclose()` is
  the awaiting variant; `done()` cannot be async because mitmproxy triggers
  DoneHook through `invoke_addon_sync`, which rejects coroutine hooks.
- Enqueueing for ML analysis is bounded by `ml_timeout`. With a full queue the
  `put()` blocked forever, hanging the request instead of failing closed.
- A stuck ML worker is recycled by a watchdog. `asyncio.to_thread` cannot be
  cancelled, so one pathological input used to occupy a worker indefinitely
  and drain a fixed pool to zero capacity.
- A missing terms file is announced. Seeding three placeholder words looked
  exactly like a successful load.
- The 413 response uses the documented `{"error": {...}}` JSON shape.
- Every flow is counted before the inspection gate; requests with neither body
  nor query string passed through completely untelemetered.
- Redaction substitutes in one pass instead of repeated slice-assignment, so
  cost no longer grows with spans x text length.
- `docker-compose.yml` mounts `terms.txt` and `config.yaml`, and the CA volume
  points at `/home/appuser/.mitmproxy` — the image runs as `appuser`, so the
  documented `/root/.mitmproxy` persisted nothing and the CA was regenerated
  on every recreate.
- Both Dockerfile stages are pinned by digest, and the build backend is
  constrained, so the same commit rebuilds to the same artefact.
- CLI failures exit with distinct codes (3 mitmdump missing, 4 empty term,
  5 Vault-managed terms) instead of all returning 1.

### Added
- `--version` and a `version` command; the running version also appears in the
  `/_health` body. A test asserts it never drifts from `pyproject.toml`.
- `dlp.ml_workers` and `dlp.ml_queue_maxsize`: the pool size and queue depth
  were literals in the source.
- Metrics for the quiet failures: `dlp_term_reload_failures_total`,
  `dlp_terms_last_reload_success_timestamp_seconds`, `dlp_term_poller_alive`,
  `dlp_ml_workers_alive`, `dlp_ml_worker_restarts_total`, `dlp_flows_seen_total`.
- `/_health` consults real state: terms loaded and fresh, circuit breaker,
  worker liveness, poller liveness.
- The request correlation id reaches the engine, so an ML failure names the
  request that caused it.
- `DLPEngine(dlp_config=...)` takes its configuration by parameter instead of
  reading the global singleton, and metrics startup moved out of the addon
  constructor into `build_addon()`.

### Documentation
- `architecture.md` no longer claims the two extraction passes run in
  parallel; they are sequential within a request, and it says why that does
  not cost accuracy.
- The published image bundles only `en_core_web_sm`; the config reference now
  says so next to the `nlp_model` options.
- `/_health` is documented, and the availability consequences of the
  single-instance reference deployment are stated.

## [3.1.0] - 2026-09-07

### Fixed
- **`terms.txt` is now written atomically.** `aidlp add-term` appended in place,
  so a kill between `open()` and the buffered write reaching disk could leave
  anything from no change at all to a truncated trailing line — which the next
  start loaded as a redaction keyword. The CLI now snapshots the current file to
  `terms.txt.bak`, writes the full contents to a temp file in the same
  directory, `fsync`s it, and renames it into place, `fsync`ing the directory so
  the rename itself is durable. It also no longer writes a leading blank line.
- **The file provider is polled too.** `start_workers()` created the reload task
  only when the secrets provider was `vault`, so after `aidlp add-term` a
  running proxy kept redacting from its original in-memory keyword set
  indefinitely — while the CLI told the operator to "wait for hot-reload". Every
  provider now gets a poller. The file provider is checked by mtime and size, so
  an untouched file costs a `stat` rather than a rebuilt keyword set.
- **Loaded terms are validated.** Every non-blank line became a keyword
  verbatim, so a corrupted entry surfaced later as wrong redaction behaviour
  instead of a load-time error. Entries over 512 characters, or containing
  control characters, are now skipped with a warning naming the position and
  reason — never the term itself, since these are secrets. A `terms.txt` that is
  not valid UTF-8 is treated as a failed fetch, so the engine keeps its last
  known-good keywords.

### Added
- `terms.txt.bak`, written before every mutating write, with the restore
  procedure documented in the configuration reference and the deployment guide
  and covered by a test. There was previously no way, coded or documented, to
  recover a damaged terms file.
- `dlp.reload_interval` (default `60.0`): how often the poller re-reads the term
  source. Previously hardcoded to 60 seconds inside the Vault-only poller.
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
