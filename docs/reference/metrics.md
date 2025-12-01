# Metrics Reference

The AI DLP Proxy exposes Prometheus metrics at `/metrics` (default port 9090).

## Core Metrics

| Metric Name | Type | Labels | Description |
| :--- | :--- | :--- | :--- |
| `dlp_requests_total` | Counter | None | Total number of HTTP requests processed by the DLP engine. |
| `dlp_redacted_total` | Counter | None | Total number of requests where sensitive data was found and redacted. |
| `dlp_pii_detected_total` | Counter | `type` | Count of detected PII entities, broken down by type (e.g., `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`). |
| `dlp_token_usage_total` | Counter | `direction` | Estimated token usage (characters / 4). Labels: `input` (original), `output` (redacted). |
| `dlp_active_connections` | Gauge | None | Number of currently active connections being processed. |

## Latency

### `dlp_latency_seconds`
A Histogram tracking the time spent in the DLP analysis phase (excluding network overhead).

**Buckets (seconds)**:
- `.005` (5ms)
- `.01` (10ms)
- `.025` (25ms)
- `.05` (50ms)
- `.1` (100ms)
- `.25` (250ms)
- `.5` (500ms)
- `1.0`+

**Usage**:
Use `histogram_quantile(0.95, rate(dlp_latency_seconds_bucket[5m]))` to calculate the P95 latency.

## Alerts

Recommended alert rules:

- **High Latency**: P95 latency > 200ms for 5 minutes.
- **High Error Rate**: `dlp_redacted_total` rate drops to 0 (if traffic exists) or spikes unexpectedly.
- **Security Incident**: `dlp_pii_detected_total{type="API_KEY"}` > 0 (if you have custom logic for keys).
