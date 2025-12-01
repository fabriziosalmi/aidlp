# AI DLP Proxy

![CI](https://github.com/yourusername/aidlp/actions/workflows/ci.yml/badge.svg)
![Docker](https://github.com/yourusername/aidlp/actions/workflows/docker.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)

A high-performance, enterprise-grade HTTP/HTTPS Data Loss Prevention (DLP) proxy designed to sanitize sensitive information before it reaches external LLM endpoints.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [Local Setup](#local-setup)
  - [Docker Deployment](#docker-deployment)
- [Configuration](#configuration)
- [Usage](#usage)
- [Observability](#observability)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## Overview

In the era of Generative AI, preventing data leakage is paramount. Developers often inadvertently paste secrets, PII, or internal database connection strings into LLM prompts. The **AI DLP Proxy** acts as a secure gateway, intercepting traffic to LLM providers (like OpenAI, Anthropic) and redacting sensitive data in real-time using a hybrid approach of static rules and Machine Learning models.

## Features

- **Hybrid Redaction Engine**: Combines the speed of static keyword matching (FlashText) with the intelligence of NLP models (Presidio/SpaCy) to detect PII, secrets, and custom terms.
- **SSL/TLS Interception**: Full support for HTTPS traffic inspection via `mitmproxy` core.
- **High Performance**: Asynchronous ML processing ensures minimal latency impact (<30ms overhead at P95).
- **Enterprise Observability**: Native Prometheus metrics (`/metrics`) and structured JSON logging for integration with Grafana/Loki.
- **Scalable**: Dockerized and load-tested to handle 1000+ concurrent connections.

## Architecture

The system is built on top of `mitmproxy`'s robust core, extended with a custom Python addon (`DLPAddon`).

1.  **Interception**: The proxy intercepts HTTP/HTTPS `POST` requests.
2.  **Analysis**: The request body is passed to the `DLPEngine`.
    - **Static Analysis**: Checks against `terms.txt` for known secrets.
    - **ML Analysis**: Runs Named Entity Recognition (NER) to find PII (Names, Phones, etc.).
3.  **Redaction**: Sensitive tokens are replaced with `[REDACTED]`.
4.  **Forwarding**: The sanitized request is sent to the upstream server.
5.  **Telemetry**: Metrics and logs are emitted asynchronously.

## Prerequisites

- **Python**: 3.9 or higher.
- **Docker**: 20.10+ (for containerized deployment).
- **Memory**: Minimum 2GB RAM recommended for ML models.

## Installation

### Local Setup

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/yourusername/aidlp.git
    cd aidlp
    ```

2.  **Create a virtual environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    python -m spacy download en_core_web_lg
    ```

4.  **Start the proxy**:
    ```bash
    export PYTHONPATH=$PYTHONPATH:$(pwd)
    python src/cli.py start --port 8080
    ```

### Docker Deployment

1.  **Build and Run**:
    ```bash
    docker-compose up --build -d
    ```

2.  **Verify**:
    ```bash
    curl -x http://localhost:8080 http://httpbin.org/ip
    ```

## Configuration

The proxy is configured via `config.yaml` and `terms.txt`.

### `config.yaml`
```yaml
proxy:
  port: 8080
  metrics_port: 9090
  ssl_bump: true

dlp:
  static_terms_file: "terms.txt"
  ml_enabled: true
  ml_threshold: 0.5
```

### `terms.txt`
Add one sensitive term per line. The proxy reloads this file automatically on restart (dynamic reload planned).
```text
super_secret_token
internal_db_password
```

## Usage

Configure your HTTP client or environment to use the proxy.

**Example (cURL)**:
```bash
curl -x http://localhost:8080 \
     -X POST http://httpbin.org/post \
     -d "My password is super_secret_token"
```

**Output**:
```json
{
  "data": "My password is [REDACTED]"
}
```

### Demo
[![asciicast](https://asciinema.org/a/VKFol51SRDzleQKY7c2ZmgUKz.svg)](https://asciinema.org/a/VKFol51SRDzleQKY7c2ZmgUKz)

## Observability

### Metrics
Prometheus metrics are available at `http://localhost:9090/metrics`.
- `dlp_requests_total`: Total requests processed.
- `dlp_redacted_total`: Requests containing sensitive data.
- `dlp_latency_seconds`: Histogram of processing time.
- `dlp_active_connections`: Current active connections.

### Logs
Logs are output in structured JSON format to stdout, suitable for ingestion by Fluentd/Logstash.

## Troubleshooting

### "Address already in use"
- **Cause**: Port 8080 or 9090 is occupied.
- **Fix**: Change `port` or `metrics_port` in `config.yaml`.

### "Certificate Verify Failed"
- **Cause**: The client does not trust the `mitmproxy` CA.
- **Fix**: Install `~/.mitmproxy/mitmproxy-ca-cert.pem` into your system or browser trust store. For `curl`, use `-k` (insecure) for testing.

### High Latency
- **Cause**: ML model processing on CPU.
- **Fix**: Ensure you are running on a machine with AVX support. For production, consider GPU acceleration (future support).

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to get started.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
