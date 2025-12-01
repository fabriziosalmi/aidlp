# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
