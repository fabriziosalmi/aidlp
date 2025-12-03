# Changelog

All notable changes to this project will be documented in this file.

## [1.9.7] - 2025-12-04

### Added
- **Local Docker Setup**: Added `docker-compose.yml` configuration for running the DLP Proxy, Prometheus, and Grafana locally.
- **Observability**: Added `prometheus.yml` and configured Grafana for real-time metrics visualization.
- **Verification Script**: Added `test_local_setup.py` to verify the proxy and DLP functionality with LM Studio.
- **Documentation**: Updated `docs/guide/architecture.md` with a new Observability section and updated sequence diagram.

### Fixed
- **Docker Build**: Resolved `apt-get` hash mismatch errors in the Dockerfile by cleaning apt lists.
- **Linting**: Fixed flake8 errors in `test_local_setup.py`.
