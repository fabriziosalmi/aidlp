import logging
import json
import time
import os
import asyncio
from mitmproxy import http
from src.dlp_engine import DLPEngine
from src.config import config
from prometheus_client import start_http_server, Counter, Histogram, Gauge
from pythonjsonlogger import jsonlogger

# Configure JSON logging
logger = logging.getLogger("dlp_proxy")
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(message)s')
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

# Silence Presidio warnings
logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)

# Prometheus Metrics
REQUESTS_TOTAL = Counter('dlp_requests_total', 'Total number of DLP requests processed')
REDACTED_TOTAL = Counter('dlp_redacted_total', 'Total number of requests redacted')
LATENCY = Histogram('dlp_latency_seconds', 'Time spent processing DLP requests')
ACTIVE_CONNECTIONS = Gauge('dlp_active_connections', 'Number of currently active connections')


class StatsManager:
    def __init__(self, stats_file="stats.json", flush_interval=1):
        self.stats_file = stats_file
        self.flush_interval = flush_interval
        self.current_stats = {
            "total_requests": 0,
            "total_redacted": 0,
            "static_replacements": 0,
            "ml_replacements": 0,
            "total_time": 0,
            "active_connections": 0,
            "upstream_hosts": {}
        }
        self.last_flush = time.time()
        self._load_stats()

    def _load_stats(self):
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, "r") as f:
                    saved_stats = json.load(f)
                    for k, v in saved_stats.items():
                        self.current_stats[k] = v
            except Exception as e:
                logger.error(f"Failed to load stats: {e}")

    def update(self, request_stats: dict, duration: float, upstream_host: str = None):
        self.current_stats["total_requests"] += 1
        self.current_stats["total_redacted"] += 1
        self.current_stats["static_replacements"] += request_stats.get("static_replacements", 0)
        self.current_stats["ml_replacements"] += request_stats.get("ml_replacements", 0)
        self.current_stats["total_time"] += duration
        
        if upstream_host:
            if upstream_host not in self.current_stats["upstream_hosts"]:
                self.current_stats["upstream_hosts"][upstream_host] = 0
            self.current_stats["upstream_hosts"][upstream_host] += 1
        
        if time.time() - self.last_flush > self.flush_interval:
            self.flush()

    def increment_active(self):
        self.current_stats["active_connections"] += 1
        # Optional: flush on change if we want real-time "active" view, but interval is fine

    def decrement_active(self):
        if self.current_stats["active_connections"] > 0:
            self.current_stats["active_connections"] -= 1

    def flush(self):
        try:
            with open(self.stats_file, "w") as f:
                json.dump(self.current_stats, f)
            self.last_flush = time.time()
        except Exception as e:
            logger.error(f"Failed to flush stats: {e}")

class DLPAddon:
    def __init__(self):
        self.dlp_engine = DLPEngine()
        self.stats_manager = StatsManager()
        
        # Start Prometheus metrics server on port 9090
        try:
            start_http_server(9090)
            logger.info("Prometheus metrics server started on port 9090")
        except Exception as e:
            logger.error(f"Failed to start Prometheus server: {e}")
            
        logger.info("DLP Engine initialized")

    def request(self, flow: http.HTTPFlow):
        # We can inspect request content here if we want to redact outgoing data (which is the use case: "proxy dlp in uscita")
        # "uscita verso gli endpoint llm" -> Client sends request to Proxy -> Proxy sends to LLM.
        # So we need to redact the REQUEST body.
        
        if flow.request.method in ["POST", "PUT", "PATCH"] and flow.request.content:
            # We need to schedule the async task. 
            # mitmproxy supports async event handlers if we define them as async def.
            # But the current structure is sync. Let's make it async.
            asyncio.create_task(self.process_request(flow))

    async def process_request(self, flow: http.HTTPFlow):
        self.stats_manager.increment_active()
        ACTIVE_CONNECTIONS.inc()
        REQUESTS_TOTAL.inc()
        try:
            content_str = flow.request.get_text()
            if content_str:
                start_time = time.time()
                
                # Offload blocking ML call to thread
                with LATENCY.time():
                    redacted_content, stats = await asyncio.to_thread(self.dlp_engine.redact, content_str)
                
                duration = time.time() - start_time
                
                if redacted_content != content_str:
                    flow.request.set_text(redacted_content)
                    REDACTED_TOTAL.inc()
                    logger.info(f"Redacted request", extra={"url": flow.request.pretty_url, "stats": stats})
                    self.stats_manager.update(stats, duration, upstream_host=flow.request.host)
        except Exception as e:
            logger.error(f"Error redacting request", extra={"error": str(e)})
        finally:
            self.stats_manager.decrement_active()
            ACTIVE_CONNECTIONS.dec()

    def response(self, flow: http.HTTPFlow):
        pass

addons = [
    DLPAddon()
]
