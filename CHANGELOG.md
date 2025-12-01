# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
