import errno
import json
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


MAX_BODY_BYTES = 10 * 1024 * 1024

# Media types that genuinely cannot carry inspectable text.
BINARY_CONTENT_PREFIXES = ("image/", "audio/", "video/", "font/")
BINARY_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "application/zip",
        "application/gzip",
        "application/x-tar",
        "application/x-7z-compressed",
    }
)


def _is_binary_content_type(content_type: str) -> bool:
    """Decide whether a body can be skipped without inspecting it.

    Deliberately a deny-list. The previous allow-list only scanned
    "application/json" and "text/*", so any client could bypass DLP
    completely by sending Content-Type: application/octet-stream -- or by
    omitting the header altogether.
    """
    ct = content_type.split(";")[0].strip().lower()
    return ct.startswith(BINARY_CONTENT_PREFIXES) or ct in BINARY_CONTENT_TYPES


def _merge_stats(target: dict, source: dict) -> None:
    target["static_replacements"] += source.get("static_replacements", 0)
    target["ml_replacements"] += source.get("ml_replacements", 0)
    for pii, count in source.get("pii_types", {}).items():
        target["pii_types"][pii] = target["pii_types"].get(pii, 0) + count


def _new_stats() -> dict:
    return {"static_replacements": 0, "ml_replacements": 0, "pii_types": {}}


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

        content = flow.request.content

        # Request Buffering Limit
        if content and len(content) > MAX_BODY_BYTES:
            logger.warning(
                "Request too large",
                extra={"request_id": request_id, "size": len(content)},
            )
            flow.response = http.Response.make(
                413, b"Request Entity Too Large", {"Content-Type": "text/plain"}
            )
            return

        content_type = flow.request.headers.get("Content-Type", "")
        inspect_body = bool(content) and not _is_binary_content_type(content_type)
        # The query string is scanned on every method: a plain
        # GET /v1/completions?prompt=<secret> used to sail straight through.
        inspect_query = bool(flow.request.query)

        if inspect_body or inspect_query:
            # Await the redaction so it happens BEFORE forwarding. This makes
            # the proxy blocking for the duration of the analysis.
            await self.process_request(
                flow, inspect_body=inspect_body, inspect_query=inspect_query
            )

    async def _redact_json_tree(self, obj, stats: dict):
        if isinstance(obj, dict):
            for k, v in obj.items():
                obj[k] = await self._redact_json_tree(v, stats)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                obj[i] = await self._redact_json_tree(v, stats)
        elif isinstance(obj, str):
            # Only redact string values, preserving structure and NLP context!
            red_str, s = await self.dlp_engine.redact(obj)
            _merge_stats(stats, s)
            return red_str
        return obj

    async def _redact_body(self, flow: http.HTTPFlow, stats: dict) -> bool:
        """Redact the request body in place. Returns True if it changed."""
        # strict=False so an undecodable byte does not fail the whole request
        # closed. The body is only written back when something was redacted.
        content_str = flow.request.get_text(strict=False)
        if not content_str:
            return False

        content_type = flow.request.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                data = json.loads(content_str)
            except json.JSONDecodeError:
                # Fallback for malformed JSON
                redacted_content, s = await self.dlp_engine.redact(content_str)
                _merge_stats(stats, s)
            else:
                redacted_content = json.dumps(
                    await self._redact_json_tree(data, stats), ensure_ascii=False
                )
        else:
            redacted_content, s = await self.dlp_engine.redact(content_str)
            _merge_stats(stats, s)

        TOKEN_USAGE_TOTAL.labels(direction="input").inc(len(content_str) / 4)

        if redacted_content == content_str:
            TOKEN_USAGE_TOTAL.labels(direction="output").inc(len(content_str) / 4)
            return False

        flow.request.set_text(redacted_content)
        TOKEN_USAGE_TOTAL.labels(direction="output").inc(len(redacted_content) / 4)
        return True

    async def _redact_query(self, flow: http.HTTPFlow, stats: dict) -> bool:
        """Redact query-string values in place. Returns True if any changed."""
        items = list(flow.request.query.items(multi=True))
        if not items:
            return False

        changed = False
        redacted_items = []
        for key, value in items:
            red_value, s = await self.dlp_engine.redact(value)
            _merge_stats(stats, s)
            changed = changed or red_value != value
            redacted_items.append((key, red_value))

        # Query values are sent upstream just like the body, so they count
        # towards the token estimate too -- otherwise a prompt passed as a
        # query parameter is redacted but never measured.
        TOKEN_USAGE_TOTAL.labels(direction="input").inc(
            sum(len(v) for _, v in items) / 4
        )
        TOKEN_USAGE_TOTAL.labels(direction="output").inc(
            sum(len(v) for _, v in redacted_items) / 4
        )

        if changed:
            flow.request.query = redacted_items
        return changed

    async def process_request(
        self,
        flow: http.HTTPFlow,
        inspect_body: bool = True,
        inspect_query: bool = False,
    ):
        request_id = flow.request.headers.get("X-Request-ID", "unknown")

        ACTIVE_CONNECTIONS.inc()
        REQUESTS_TOTAL.inc()
        try:
            stats = _new_stats()
            changed = False

            with LATENCY.time():
                if inspect_query:
                    changed |= await self._redact_query(flow, stats)
                if inspect_body:
                    changed |= await self._redact_body(flow, stats)

            if changed:
                REDACTED_TOTAL.inc()
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
