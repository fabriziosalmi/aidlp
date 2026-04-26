# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.9.9] - 2026-04-26
### Fixed
- CI: switched SpaCy model download from `en_core_web_lg` to `en_core_web_sm` to match default config
- CI: upgraded actions (`actions/checkout@v3` → `v4`, `setup-python@v4` → `v5`, `cache@v3` → `v4`)
- CI: added `pytest-cov` with `--cov-fail-under=60` coverage gate

### Changed
- Version bump to 1.9.9

## [1.9.8] - 2026-04-26
### Fixed
- Fixed `typer` version pin (upgraded from `0.9.0` to `^0.12.0`) to resolve `TypeError` on boolean flag with Click 8.3.x
- Fixed `errno.EADDRINUSE` usage (replaced macOS-specific magic number 48 with portable constant)
- Fixed race condition: removed `self.request_id` instance variable assignment in async request handler
- Moved `NlpEngineProvider` import from inside `__init__` to module-level
- Replaced deprecated `typing.Tuple`/`typing.Dict` with native `tuple`/`dict` generics (Python 3.12+)

### Changed
- `cli.py` `stats` command now reads `metrics_port` from config instead of hardcoding `9090`
- `cli.py` `start` command now correctly passes `--ssl-insecure` to mitmdump when `ssl_bump=True`
- `cli.py` `add_term` command now handles missing `config.yaml` gracefully with exit code 1
- Added `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` and `testpaths = ["tests"]`

### Tests
- Added `tests/test_cli.py` with 11 tests covering all CLI commands
- Overall test coverage raised from 68% to 87%

## [1.9.6] - 2025-12-01
### Security
- **CRITICAL**: Updated `h11` to 0.16.0 (fixed malformed Chunked-Encoding vulnerability)
- **HIGH**: Updated `brotli` to 1.2.0 (fixed DoS vulnerability)
- **HIGH**: Updated `mitmproxy` to 12.2.1 (fixed API authentication bypass)
- **MEDIUM**: Updated `cryptography` to 46.0.3 (fixed vulnerable OpenSSL)
- **MEDIUM**: Updated `esbuild` via npm (fixed request bypass)

### Fixed
- Fixed VitePress documentation build configuration
- Fixed GitHub Pages deployment path
- Fixed flake8 configuration to exclude `.venv` directory
- Fixed Poetry installation and dependency resolution

### Changed
- Migrated CI/CD to Poetry for dependency management
- Updated all outdated dependencies to latest secure versions
- Added `poetry-plugin-export` to Dockerfile for builds

### Documentation
- Updated README with Poetry installation instructions
- Updated getting started guide
- Fixed documentation deployment workflow

## [1.6.0] - 2025-12-01
### Added
- **Documentation**: Comprehensive overhaul:
    - New **Core Concepts** section (Redaction Engine, Secrets Management).
    - Detailed **Configuration Reference**.
    - Enhanced **Getting Started** guide for local usage.

## [1.5.0] - 2025-12-01
### Added
- **Metrics**: Enhanced Prometheus metrics:
    - `dlp_pii_detected_total`: Count of PII entities by type.
    - `dlp_token_usage_total`: Estimated token usage (input/output).
    - `dlp_latency_seconds`: Improved histogram buckets for p95 calculation.

## [1.4.0] - 2025-12-01
### Fixed
- **Docker Build**: Switched base image to `python:3.9` to resolve missing build dependencies.
- **Docs**: Fixed dead links and base URL configuration for GitHub Pages.

## [1.2.1] - 2025-12-01
### Added
- **CI/CD**: Added Docker release workflow (`docker-publish.yml`).

## [1.2.0] - 2025-12-01
### Added
- **Vault Integration**: Added support for HashiCorp Vault as a secrets provider.

## [1.1.0] - 2025-12-01
### Added
- **Documentation**: Initial setup of VitePress documentation.

## [1.0.0] - 2025-12-01
### Added
- Initial stable release.

## [0.1.0] - 2025-12-01

### Added
- **Core Proxy**: HTTP/HTTPS interception with SSL bumping using `mitmproxy`.
- **DLP Engine**:
    - Static redaction using `flashtext` (configurable via `terms.txt`).
    - ML-based redaction using `presidio-analyzer` (PII/Secrets).
    - Asynchronous processing for high performance.
- **Observability**:
    - Prometheus metrics endpoint (default port 9090).
    - Structured JSON logging.
    - Real-time CLI stats (`active_connections`, `upstream_hosts`).
- **Deployment**:
    - `Dockerfile` and `docker-compose.yml`.
    - GitHub Actions for CI (tests/lint) and Docker build/push.
- **Testing**:
    - Unit tests (`pytest`).
    - Load testing script (`load_test.py`) verifying <100ms latency at 1000 concurrent clients.
- **Documentation**:
    - Comprehensive `README.md` with demo and usage instructions.
    - `load_testing_report.md`.
