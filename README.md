# AI DLP Proxy

![CI](https://github.com/fabriziosalmi/aidlp/actions/workflows/ci.yml/badge.svg)
![Docker](https://github.com/fabriziosalmi/aidlp/actions/workflows/docker.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)

A high-performance, enterprise-grade HTTP/HTTPS Data Loss Prevention (DLP) proxy designed to sanitize sensitive information before it reaches external LLM endpoints.

### Demo
[![asciicast](https://asciinema.org/a/VKFol51SRDzleQKY7c2ZmgUKz.svg)](https://asciinema.org/a/VKFol51SRDzleQKY7c2ZmgUKz)

> 📘 **Documentation**
>
> Full documentation is available at [https://fabriziosalmi.github.io/aidlp/](https://fabriziosalmi.github.io/aidlp/) (or locally via `npm run docs:dev`).

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
- **Strict Pydantic Validation**: Configuration is deeply validated via `pydantic-settings`, with full support for `AIDLP_` prefixed environment variables.
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
docker-compose up --build -d
curl -x http://localhost:8080 http://httpbin.org/ip
```

## Configuration

The proxy uses `pydantic-settings` and can be configured via `config.yaml` or Environment Variables (prefix: `AIDLP_`). Environment variables take precedence.

### `config.yaml`
```yaml
proxy:
  port: 8080
  metrics_port: 9090
  ssl_bump: true

dlp:
  static_terms_file: "terms.txt"
  ml_enabled: true
  nlp_model: "en_core_web_sm"
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

Prometheus metrics are available at `http://localhost:9090`.
- `dlp_requests_total`: Total requests processed.
- `dlp_redacted_total`: Requests containing sensitive data.
- `dlp_pii_detected_total`: Count of PII entities by type (e.g., `PERSON`).
- `dlp_active_connections`: Current active connections.

Logs are printed in structured JSON format to stdout.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
