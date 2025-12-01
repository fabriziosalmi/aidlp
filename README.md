# DLP Proxy

An HTTP/HTTPS DLP proxy that redacts sensitive information using static lists and ML models.

## Features
- **Static Redaction**: Fast replacement of known terms (e.g., "password", "api_key").
- **ML Redaction**: Intelligent detection of PII (Person, Phone, etc.) using Presidio.
- **SSL Interception**: Inspects HTTPS traffic (requires CA trust).
- **Dockerized**: Easy deployment.

## Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   python -m spacy download en_core_web_lg
   ```

2. Start the proxy:
   ```bash
   python src/cli.py start --port 8080
   ```

## Usage

Configure your client to use `http://localhost:8080` as the proxy.
For HTTPS, you must install the `mitmproxy` CA certificate on the client.
- The cert is usually found at `~/.mitmproxy/mitmproxy-ca-cert.pem` after the first run.

## Demo

You can record a demo using `asciinema` and the provided scenario script:

```bash
asciinema rec -c "bash demo_scenario.sh" demo.cast
```

## Configuration

Edit `config.yaml` to add static terms or adjust ML settings.

## Docker

```bash
docker-compose up --build
```
