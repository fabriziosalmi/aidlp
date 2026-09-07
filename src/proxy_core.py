import base64
import errno
import hmac
import ipaddress
import json
import logging
import os
from mitmproxy import ctx, http
from src import __version__ as AIDLP_VERSION
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
FLOWS_SEEN_TOTAL = Counter(
    "dlp_flows_seen_total",
    "Every request the addon saw, whether or not it was inspected",
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


PROXY_AUTH_HEADER = "Proxy-Authorization"
PROXY_AUTHENTICATE_HEADER = "Proxy-Authenticate"
AUTH_REALM = 'Basic realm="aidlp"'

LOOPBACK_NAMES = frozenset({"localhost", "ip6-localhost", "localhost.localdomain"})


def is_loopback_host(host: str) -> bool:
    """True when a listener on `host` can only be reached from this machine.

    An empty string is mitmproxy's "every interface". A name we cannot
    resolve to a literal is treated as routable: guessing in the permissive
    direction here would quietly re-open the relay this check exists to
    close.
    """
    candidate = (host or "").strip()
    if not candidate:
        return False
    if candidate.lower() in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def credential_matches(header_value: str, token: str) -> bool:
    """Constant-time comparison of a Proxy-Authorization value to the token.

    Accepts `Bearer <token>` and `Basic base64(user:<token>)`. Ordinary
    proxy clients -- curl --proxy-user, requests, browsers -- send the
    latter, so supporting only Bearer would make the proxy unusable by the
    tools people actually put in front of it.
    """
    if not token:
        return False

    scheme, _, payload = (header_value or "").partition(" ")
    scheme = scheme.strip().lower()
    payload = payload.strip()
    if not payload:
        return False

    if scheme == "bearer":
        return hmac.compare_digest(payload, token)

    if scheme == "basic":
        try:
            decoded = base64.b64decode(payload, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return False
        _, separator, password = decoded.partition(":")
        if not separator:
            return False
        return hmac.compare_digest(password, token)

    return False


def start_metrics_server() -> None:
    """Start the Prometheus listener.

    Lives outside DLPAddon so constructing the addon has no side effects on
    the network -- wiring and request handling are separate concerns.
    """
    metrics_port = config.proxy.metrics_port
    metrics_host = config.proxy.metrics_host
    try:
        start_http_server(metrics_port, addr=metrics_host)
        logger.info(
            f"Prometheus metrics server started on {metrics_host}:{metrics_port}"
        )
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            logger.error(
                f"Failed to start Prometheus server on port {metrics_port}: "
                "Address already in use. Metrics will not be available."
            )
        else:
            logger.error(f"Failed to start Prometheus server: {e}")
    except Exception as e:
        logger.error(f"Failed to start Prometheus server: {e}")


class DLPAddon:
    def __init__(self, dlp_engine=None):
        self.dlp_engine = dlp_engine if dlp_engine is not None else DLPEngine()

        # Provisional: running() re-resolves this from the address mitmproxy
        # actually bound to, which the CLI can override.
        self.auth_token = config.proxy.auth_token
        self.apply_bind_policy(config.proxy.host)
        logger.info("DLP Engine initialized")

    @staticmethod
    def warn_if_upstream_unverified(options) -> bool:
        """Log a warning when upstream certificate verification is off.

        The CLI warns too, but mitmdump can be driven directly -- the
        deployment guide does exactly that -- so check the option we are
        actually running with rather than trusting the launcher.
        """
        if options is None or not getattr(options, "ssl_insecure", False):
            return False

        logger.warning(
            "Upstream TLS certificate verification is DISABLED "
            "(mitmproxy option ssl_insecure). The proxy will accept any "
            "certificate the upstream presents, so redacted prompts can still "
            "be intercepted and altered in transit. To restore verification: "
            "drop --ssl-insecure if you launch mitmdump directly, or unset "
            "proxy.upstream_insecure if you start via the aidlp CLI."
        )
        return True

    def apply_bind_policy(self, listen_host: str) -> None:
        """Decide whether to demand credentials, or refuse to relay at all.

        The proxy performs no authorisation of its own, so an
        unauthenticated listener on a routable interface is an open relay:
        anything that can reach the port can make the proxy fetch arbitrary
        upstreams on its behalf. Rather than assume the operator intended
        that, refuse the traffic and say why.

        The refusal is logged at CRITICAL, which mitmproxy treats as fatal
        when it happens during startup -- so in practice the process exits
        rather than listening at all. `deny_all` is the belt to that
        braces: if the addon is driven some other way, every request is
        answered 403 instead of relayed.
        """
        self.listen_host = listen_host
        self.auth_required = bool(self.auth_token)
        self.deny_all = False

        if self.auth_token:
            return

        if is_loopback_host(listen_host):
            logger.warning(
                "No proxy.auth_token is set, so callers are not "
                f"authenticated. Tolerated only because the proxy is bound to "
                f"{listen_host!r}, reachable from this machine alone. Set "
                "proxy.auth_token (AIDLP_PROXY__AUTH_TOKEN) before binding "
                "anywhere else."
            )
            return

        self.deny_all = True
        logger.critical(
            f"Refusing to relay: bound to {listen_host or 'every interface'!r} "
            "with no proxy.auth_token set, which would be an open proxy for "
            "anything that can reach this port. Set proxy.auth_token "
            "(AIDLP_PROXY__AUTH_TOKEN), or bind proxy.host to loopback."
        )

    def reject_unauthenticated(self, flow: http.HTTPFlow) -> bool:
        """Answer the flow ourselves if the caller may not use the proxy.

        Returns True when the flow has been answered and must not be
        forwarded.
        """
        if self.deny_all:
            flow.response = http.Response.make(
                403,
                b'{"error": {"message": "Proxy refuses to relay: no '
                b'auth_token configured for a non-loopback listener", '
                b'"code": "proxy_misconfigured"}}',
                {"Content-Type": "application/json"},
            )
            return True

        if not self.auth_required:
            return False

        supplied = flow.request.headers.get(PROXY_AUTH_HEADER, "")
        if credential_matches(supplied, self.auth_token):
            # Never forward our own credential to the upstream.
            if PROXY_AUTH_HEADER in flow.request.headers:
                del flow.request.headers[PROXY_AUTH_HEADER]
            return False

        flow.response = http.Response.make(
            407,
            b'{"error": {"message": "Proxy authentication required", '
            b'"code": "proxy_auth_required"}}',
            {
                "Content-Type": "application/json",
                PROXY_AUTHENTICATE_HEADER: AUTH_REALM,
            },
        )
        return True

    def http_connect(self, flow: http.HTTPFlow):
        """Authorise the CONNECT before the tunnel exists.

        Checking only in request() would let an unauthenticated caller open
        the tunnel first and be refused per-request afterwards.
        """
        self.reject_unauthenticated(flow)

    def running(self):
        try:
            options = ctx.options
        except Exception:
            # Not running under a mitmproxy master (unit tests, imports).
            options = None
        self.warn_if_upstream_unverified(options)
        if options is not None:
            # listen_host is the address actually bound; the CLI can override
            # config.proxy.host, so the runtime value is the authority.
            self.apply_bind_policy(getattr(options, "listen_host", "") or "")
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

        # Health Probe. Reports the subsystems that fail quietly -- term
        # staleness, circuit breaker, worker liveness -- not just whether the
        # analyzer object was built at startup.
        if flow.request.path == "/_health" and flow.request.method == "GET":
            healthy, details = self.dlp_engine.health_report()
            body = json.dumps(
                {
                    "status": "ok" if healthy else "unhealthy",
                    "version": AIDLP_VERSION,
                    "details": details,
                }
            ).encode()
            flow.response = http.Response.make(
                200 if healthy else 503,
                body,
                {"Content-Type": "application/json"},
            )
            return

        # Authorise the caller before doing anything on its behalf. The
        # health probe above is deliberately exempt: it reveals nothing and
        # container health checks run without credentials.
        if self.reject_unauthenticated(flow):
            return

        # Counted before the inspection gate below: a request with neither a
        # body nor a query string used to pass through completely
        # untelemetered, so traffic dashboards silently undercounted.
        FLOWS_SEEN_TOTAL.inc()

        content = flow.request.content

        # Request Buffering Limit
        if content and len(content) > MAX_BODY_BYTES:
            logger.warning(
                "Request too large",
                extra={"request_id": request_id, "size": len(content)},
            )
            flow.response = http.Response.make(
                413,
                b'{"error": {"message": "Request Entity Too Large", '
                b'"code": "request_too_large"}}',
                {"Content-Type": "application/json"},
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

    async def _redact_json_tree(self, obj, stats: dict, request_id: str):
        if isinstance(obj, dict):
            for k, v in obj.items():
                obj[k] = await self._redact_json_tree(v, stats, request_id)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                obj[i] = await self._redact_json_tree(v, stats, request_id)
        elif isinstance(obj, str):
            # Only redact string values, preserving structure and NLP context!
            red_str, s = await self.dlp_engine.redact(obj, request_id)
            _merge_stats(stats, s)
            return red_str
        return obj

    async def _redact_body(
        self, flow: http.HTTPFlow, stats: dict, request_id: str
    ) -> bool:
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
                redacted_content, s = await self.dlp_engine.redact(
                    content_str, request_id
                )
                _merge_stats(stats, s)
            else:
                redacted_content = json.dumps(
                    await self._redact_json_tree(data, stats, request_id),
                    ensure_ascii=False,
                )
        else:
            redacted_content, s = await self.dlp_engine.redact(content_str, request_id)
            _merge_stats(stats, s)

        TOKEN_USAGE_TOTAL.labels(direction="input").inc(len(content_str) / 4)

        if redacted_content == content_str:
            TOKEN_USAGE_TOTAL.labels(direction="output").inc(len(content_str) / 4)
            return False

        flow.request.set_text(redacted_content)
        TOKEN_USAGE_TOTAL.labels(direction="output").inc(len(redacted_content) / 4)
        return True

    async def _redact_query(
        self, flow: http.HTTPFlow, stats: dict, request_id: str
    ) -> bool:
        """Redact query-string values in place. Returns True if any changed."""
        items = list(flow.request.query.items(multi=True))
        if not items:
            return False

        changed = False
        redacted_items = []
        for key, value in items:
            red_value, s = await self.dlp_engine.redact(value, request_id)
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
                    changed |= await self._redact_query(flow, stats, request_id)
                if inspect_body:
                    changed |= await self._redact_body(flow, stats, request_id)

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
        """Stop the engine's background tasks.

        Cannot be async: mitmproxy triggers DoneHook through
        invoke_addon_sync() when an addon is removed or the chain is
        cleared, and that path raises on a coroutine hook. shutdown()
        cancels and resets synchronously; a worker already inside
        asyncio.to_thread cannot be interrupted either way.
        """
        logger.info("Shutting down DLP Proxy...")
        self.dlp_engine.shutdown()


def build_addon() -> DLPAddon:
    """Composition root: build the engine, start metrics, return the addon."""
    start_metrics_server()
    return DLPAddon(DLPEngine())


addons = [build_addon()]
