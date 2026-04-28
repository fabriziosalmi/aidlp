import errno
import logging
import os
from mitmproxy import http
from src.dlp_engine import DLPEngine
from src.config import config
from prometheus_client import start_http_server, Counter, Histogram, Gauge
from pythonjsonlogger import jsonlogger

# Configure JSON logging
logger = logging.getLogger("dlp_proxy")
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(message)s")
logHandler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

# Silence Presidio warnings
logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)

# Prometheus Metrics
REQUESTS_TOTAL = Counter("dlp_requests_total", "Total number of DLP requests processed")
REDACTED_TOTAL = Counter("dlp_redacted_total", "Total number of requests redacted")
PII_DETECTED_TOTAL = Counter(
    "dlp_pii_detected_total", "Total number of PII entities detected", ["type"]
)
TOKEN_USAGE_TOTAL = Counter(
    "dlp_token_usage_total", "Estimated token usage", ["direction"]
)
LATENCY = Histogram(
    "dlp_latency_seconds",
    "Time spent processing DLP requests",
    buckets=[
        0.005,
        0.01,
        0.025,
        0.05,
        0.075,
        0.1,
        0.25,
        0.5,
        0.75,
        1.0,
        2.5,
        5.0,
        7.5,
        10.0,
    ],
)
ACTIVE_CONNECTIONS = Gauge(
    "dlp_active_connections", "Number of currently active connections"
)


class DLPAddon:
    def __init__(self):
        self.dlp_engine = DLPEngine()

        # Start Prometheus metrics server
        metrics_port = config.proxy.metrics_port
        try:
            start_http_server(metrics_port)
            logger.info(f"Prometheus metrics server started on port {metrics_port}")
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                logger.error(
                    f"Failed to start Prometheus server on port "
                    f"{metrics_port}: "
                    "Address already in use. Metrics will not be available."
                )
            else:
                logger.error(f"Failed to start Prometheus server: {e}")
        except Exception as e:
            logger.error(f"Failed to start Prometheus server: {e}")
        logger.info("DLP Engine initialized")

    def running(self):
        self.dlp_engine.start_workers()

    async def request(self, flow: http.HTTPFlow):
        # We can inspect request content here if we want to redact outgoing
        # data
        # (which is the use case: "proxy dlp in uscita")
        # "uscita verso gli endpoint llm" -> Client sends request to Proxy
        # -> Proxy sends to LLM.
        # So we need to redact the REQUEST body.

        # Correlation ID
        request_id = flow.request.headers.get("X-Request-ID")
        if not request_id:
            request_id = os.urandom(16).hex()
            flow.request.headers["X-Request-ID"] = request_id

        # Health Probe
        if flow.request.path == "/_health" and flow.request.method == "GET":
            is_healthy = True
            # Check Vault (if used) - simplified check if engine is initialized
            # In a real scenario, we might ping Vault here.
            # Check Model
            if not self.dlp_engine.analyzer:
                is_healthy = False

            if is_healthy:
                flow.response = http.Response.make(
                    200, b"OK", {"Content-Type": "text/plain"}
                )
            else:
                flow.response = http.Response.make(
                    503, b"Service Unavailable", {"Content-Type": "text/plain"}
                )
            return

        if flow.request.method in ["POST", "PUT", "PATCH"] and flow.request.content:
            content_type = flow.request.headers.get("Content-Type", "")
            if "application/json" not in content_type and "text/" not in content_type:
                return  # Skip binary or unsupported data

            # Request Buffering Limit
            if len(flow.request.content) > 10 * 1024 * 1024:  # 10MB
                logger.warning(
                    "Request too large",
                    extra={"request_id": request_id, "size": len(flow.request.content)},
                )
                flow.response = http.Response.make(
                    413, b"Request Entity Too Large", {"Content-Type": "text/plain"}
                )
                return

            # Await the process_request to ensure redaction happens BEFORE forwarding.
            # This makes the proxy blocking for the duration of the analysis.
            await self.process_request(flow)

    async def process_request(self, flow: http.HTTPFlow):  # noqa: C901
        request_id = flow.request.headers.get("X-Request-ID", "unknown")

        ACTIVE_CONNECTIONS.inc()
        REQUESTS_TOTAL.inc()
        try:
            content_str = flow.request.get_text()
            if not content_str:
                return

            content_type = flow.request.headers.get("Content-Type", "")

            with LATENCY.time():
                if "application/json" in content_type:
                    import json

                    try:
                        data = json.loads(content_str)
                        merged_stats = {
                            "static_replacements": 0,
                            "ml_replacements": 0,
                            "pii_types": {},
                        }

                        async def traverse_and_redact(obj):
                            if isinstance(obj, dict):
                                for k, v in obj.items():
                                    obj[k] = await traverse_and_redact(v)
                            elif isinstance(obj, list):
                                for i, v in enumerate(obj):
                                    obj[i] = await traverse_and_redact(v)
                            elif isinstance(obj, str):
                                # Only redact string values, preserving structure and NLP context!
                                red_str, s = await self.dlp_engine.redact(obj)
                                merged_stats["static_replacements"] += s[
                                    "static_replacements"
                                ]
                                merged_stats["ml_replacements"] += s["ml_replacements"]
                                for pii, count in s["pii_types"].items():
                                    merged_stats["pii_types"][pii] = (
                                        merged_stats["pii_types"].get(pii, 0) + count
                                    )
                                return red_str
                            return obj

                        redacted_data = await traverse_and_redact(data)
                        redacted_content = json.dumps(redacted_data, ensure_ascii=False)
                        stats = merged_stats
                    except json.JSONDecodeError:
                        # Fallback for malformed JSON
                        redacted_content, stats = await self.dlp_engine.redact(
                            content_str
                        )
                else:
                    redacted_content, stats = await self.dlp_engine.redact(content_str)

                # Token Usage Estimation (Input)
                input_tokens = len(content_str) / 4
                TOKEN_USAGE_TOTAL.labels(direction="input").inc(input_tokens)

                if redacted_content != content_str:
                    flow.request.set_text(redacted_content)
                    REDACTED_TOTAL.inc()

                    # Token Usage Estimation (Output - if changed)
                    output_tokens = len(redacted_content) / 4
                    TOKEN_USAGE_TOTAL.labels(direction="output").inc(output_tokens)

                    # PII Metrics
                    if "pii_types" in stats:
                        for pii_type, count in stats["pii_types"].items():
                            PII_DETECTED_TOTAL.labels(type=pii_type).inc(count)

                    logger.info(
                        "Redacted request",
                        extra={
                            "url": flow.request.pretty_url,
                            "stats": stats,
                            "request_id": request_id,
                        },
                    )

                else:
                    # No redaction, output tokens = input tokens
                    TOKEN_USAGE_TOTAL.labels(direction="output").inc(input_tokens)
        except Exception as e:
            logger.error(
                "Error redacting request",
                extra={"error": str(e), "request_id": request_id},
            )

            # Fail Closed: Block the request if DLP fails
            flow.response = http.Response.make(
                500,
                b'{"error": {"message": "DLP Policy Violation", "code": "dlp_blocked"}}',
                {"Content-Type": "application/json"},
            )
        finally:

            ACTIVE_CONNECTIONS.dec()

    def response(self, flow: http.HTTPFlow):
        pass

    def done(self):
        logger.info("Shutting down DLP Proxy...")


addons = [DLPAddon()]
