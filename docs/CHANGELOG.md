# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
