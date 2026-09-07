import logging
import os
import re
import time
import asyncio
import hvac
import pybreaker

from prometheus_client import Counter, Gauge

from flashtext import KeywordProcessor
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

from .config import config

logger = logging.getLogger("dlp_proxy")

# Term-source health. Failures were previously only ever logged, so
# "redaction terms have not refreshed in N hours" was undetectable short of
# reading logs by hand.
TERM_RELOAD_FAILURES = Counter(
    "dlp_term_reload_failures_total",
    "Failed attempts to refresh the redaction term list",
    ["source"],
)
TERMS_LAST_RELOAD = Gauge(
    "dlp_terms_last_reload_success_timestamp_seconds",
    "Unix time of the last successful term-list load",
)
TERM_POLLER_ALIVE = Gauge(
    "dlp_term_poller_alive",
    "1 while the background term-refresh poller is running, 0 if it stopped",
)

# ML pool health.
ML_WORKERS_ALIVE = Gauge("dlp_ml_workers_alive", "Live ML worker tasks")
ML_DEGRADED_TOTAL = Counter(
    "dlp_ml_degraded_total",
    "Requests forwarded with static-only redaction after an ML timeout",
)
ML_WORKER_RESTARTS = Counter(
    "dlp_ml_worker_restarts_total",
    "ML workers replaced after exceeding the hard analysis ceiling",
)


def _merge_spans(spans: list) -> list:
    """Collapse overlapping (start, end, type) spans into disjoint ranges.

    Returned in ascending order, so callers must apply them in reverse to
    keep earlier offsets valid while substituting.
    """
    merged = []
    current_start, current_end = -1, -1

    for start, end, _etype in sorted(spans, key=lambda s: s[0]):
        if current_start == -1:
            current_start, current_end = start, end
        elif start <= current_end:
            current_end = max(current_end, end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end

    if current_start != -1:
        merged.append((current_start, current_end))

    return merged


MAX_TERM_LENGTH = 512

# C0 and C1 control characters. A redaction keyword holding a NUL or a stray
# \x08 is corruption, not a term someone meant to write.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def validate_terms(raw_terms, source: str) -> list[str]:
    """Keep only entries that can meaningfully act as redaction keywords.

    Every non-blank line used to become a keyword verbatim, so a half-written
    line from an interrupted append surfaced later as wrong redaction
    behaviour instead of as something an operator could act on at load time.

    Rejected entries are logged by reason and position only -- never by
    content, because these are secrets.
    """
    valid: list[str] = []

    for index, raw in enumerate(raw_terms, start=1):
        term = raw.strip()
        if not term:
            continue  # blank padding, not corruption

        if len(term) > MAX_TERM_LENGTH:
            logger.warning(
                f"Skipping term {index} from {source}: {len(term)} characters "
                f"exceeds the {MAX_TERM_LENGTH} limit"
            )
            continue

        if _CONTROL_CHARACTERS.search(term):
            logger.warning(
                f"Skipping term {index} from {source}: contains control characters"
            )
            continue

        valid.append(term)

    return valid


class TermFetchError(Exception):
    """Raised when a provider cannot supply a usable term list.

    Callers must treat this as "keep the previous terms", never as
    "there are no terms" -- the latter silently disables redaction.
    """


class TermProvider:
    def get_terms(self) -> list[str]:
        raise NotImplementedError

    def fingerprint(self):
        """Cheap change signal for the poller; None means "always reload"."""
        return None


class FileTermProvider(TermProvider):
    DEFAULT_TERMS = ("password", "secret", "api_key")

    def __init__(self, file_path: str):
        self.file_path = file_path

    def get_terms(self) -> list[str]:
        """Return the raw lines of the terms file.

        Validation lives in validate_terms(), which the engine applies to
        every provider: a corrupt entry is corrupt whether it arrived from
        disk or from Vault.
        """
        if not os.path.exists(self.file_path):
            # Seeding three generic defaults looked like a successful load,
            # so an operator whose large blocklist never mounted got no
            # signal at all -- just "Loaded 3 terms".
            logger.warning(
                f"Terms file {self.file_path} does not exist. Creating it with "
                f"{len(self.DEFAULT_TERMS)} placeholder terms "
                f"({', '.join(self.DEFAULT_TERMS)}). If you expected your own "
                "term list here, redaction is running on placeholders."
            )
            with open(self.file_path, "w", encoding="utf-8") as f:
                f.write("".join(f"{term}\n" for term in self.DEFAULT_TERMS))
            return list(self.DEFAULT_TERMS)

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return f.read().splitlines()
        except UnicodeDecodeError as e:
            # Treated as a fetch failure so the engine keeps the last known
            # good terms rather than redacting from a mangled file.
            raise TermFetchError(
                f"{self.file_path} is not valid UTF-8 ({e})"
            ) from e

    def fingerprint(self):
        try:
            stat = os.stat(self.file_path)
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)


class VaultTermProvider(TermProvider):
    def __init__(
        self,
        url: str,
        token: str,
        path: str,
        mount_point: str = "secret",
        timeout: float = 10.0,
    ):
        self.client = hvac.Client(url=url, token=token, timeout=timeout)
        self.path = path
        self.mount_point = mount_point
        self.breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=60)
        self._cached_terms = []

    def get_terms(self) -> list[str]:
        try:
            return self.breaker.call(self._fetch_from_vault)
        except pybreaker.CircuitBreakerError as e:
            logger.error("Vault Circuit Breaker open. Using cached terms.")
            return self._cached_or_raise(f"circuit breaker open: {e}")
        except Exception as e:
            logger.error(f"Failed to fetch terms from Vault: {e}")
            return self._cached_or_raise(str(e))

    def _cached_or_raise(self, reason: str) -> list[str]:
        # An empty cache means we never had a good fetch. Returning [] here
        # would install an empty keyword set and silently stop redacting.
        # Carry the underlying cause: "unreachable", "not authenticated" and
        # "breaker open" send an operator to three different places.
        if not self._cached_terms:
            raise TermFetchError(f"Vault fetch failed ({reason}); no cached terms")
        return self._cached_terms

    def _fetch_from_vault(self) -> list[str]:
        if not self.client.is_authenticated():
            raise Exception("Vault client not authenticated")

        read_response = self.client.secrets.kv.v2.read_secret_version(
            path=self.path, mount_point=self.mount_point
        )
        data = read_response["data"]["data"]
        terms = []
        for key, value in data.items():
            if isinstance(value, list):
                terms.extend([str(v) for v in value])
            else:
                terms.append(str(value))

        self._cached_terms = terms
        return terms


class DLPEngine:
    def __init__(self, dlp_config=None):
        """Build an engine.

        `dlp_config` defaults to the process-wide `config.dlp` so existing
        callers are unaffected, but passing it explicitly lets two engines
        hold different settings -- previously impossible, since the engine
        read the global singleton directly.
        """
        self.config = dlp_config if dlp_config is not None else config.dlp

        self.keyword_processor = KeywordProcessor()
        self.ml_enabled = self.config.ml_enabled
        self.ml_threshold = self.config.ml_threshold
        self.ml_timeout = self.config.ml_timeout
        self.entities = self.config.entities
        self.replacement_token = self.config.replacement_token

        self._term_provider = None
        self._terms_loaded = False
        self._terms_fingerprint = None
        self.reload_interval = self.config.reload_interval

        self.analyzer = None
        if self.ml_enabled:
            model_name = self.config.nlp_model
            logger.info(f"Loading NLP model: {model_name}")
            nlp_configuration = {
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": model_name}],
            }
            provider = NlpEngineProvider(nlp_configuration=nlp_configuration)
            nlp_engine = provider.create_engine()
            self.analyzer = AnalyzerEngine(nlp_engine=nlp_engine)

        self.reload_config()
        self.task_queue = asyncio.Queue(maxsize=self.config.ml_queue_maxsize)
        self.workers = []
        self.poller_task = None
        self.watchdog_task = None
        # worker task -> monotonic time it began its current analysis.
        self._worker_started_at = {}

    def start_workers(self):
        if self.ml_enabled and not self.workers:
            for _ in range(self.config.ml_workers):
                self.workers.append(asyncio.create_task(self._ml_worker()))
            ML_WORKERS_ALIVE.set(len(self.workers))

        if self.ml_enabled and not self.watchdog_task:
            self.watchdog_task = asyncio.create_task(self._worker_watchdog())

        if not self.poller_task:
            # Every provider gets a poller, not only Vault. The file provider
            # had none, so `aidlp add-term` changed terms.txt while a running
            # proxy kept redacting from its original in-memory set -- exactly
            # what the CLI told the operator would not happen.
            self.poller_task = asyncio.create_task(self._term_poller())

    def health_report(self) -> tuple[bool, dict]:
        """Report the state of the subsystems most likely to fail quietly.

        The health probe used to check only that the analyzer object exists,
        which is decided once at startup. A Vault outage, an open circuit
        breaker or a dead worker pool all left it answering 200 OK.
        """
        details: dict = {}
        healthy = True

        if self.ml_enabled:
            details["analyzer_loaded"] = self.analyzer is not None
            alive = sum(1 for w in self.workers if not w.done())
            details["ml_workers_alive"] = alive
            details["ml_workers_expected"] = self.config.ml_workers
            details["ml_queue_depth"] = self.task_queue.qsize()
            if not self.analyzer or (self.workers and alive == 0):
                healthy = False

        details["terms_loaded"] = self._terms_loaded
        if not self._terms_loaded:
            healthy = False

        # Terms going stale is the quiet failure a Vault outage produces.
        last = TERMS_LAST_RELOAD._value.get()
        if last:
            age = time.time() - last
            details["terms_age_seconds"] = round(age, 1)
            if age > max(self.reload_interval * 10, 600):
                details["terms_stale"] = True
                healthy = False

        provider = self._term_provider
        breaker = getattr(provider, "breaker", None)
        if breaker is not None:
            details["vault_breaker_state"] = str(breaker.current_state)
            if breaker.current_state == "open":
                healthy = False

        if self.poller_task is not None:
            details["term_poller_alive"] = not self.poller_task.done()
            if self.poller_task.done():
                healthy = False

        return healthy, details

    def _pending_tasks(self):
        tasks = list(self.workers)
        if self.poller_task:
            tasks.append(self.poller_task)
        if self.watchdog_task:
            tasks.append(self.watchdog_task)
        return tasks

    def shutdown(self):
        """Cancel every background task and reset so the engine can restart.

        Resetting matters as much as cancelling: `workers` stayed non-empty
        and `poller_task` non-None after cancellation, so a later
        start_workers() saw `not self.workers` as False and silently spawned
        nothing, leaving an engine with no workers and no poller.

        This does not wait for the tasks to finish -- use aclose() for that.
        A worker blocked in asyncio.to_thread cannot be interrupted anyway.
        """
        tasks = self._pending_tasks()
        for task in tasks:
            task.cancel()

        self.workers = []
        self.poller_task = None
        self.watchdog_task = None
        self._worker_started_at.clear()
        ML_WORKERS_ALIVE.set(0)
        TERM_POLLER_ALIVE.set(0)
        return tasks

    async def aclose(self):
        """shutdown(), then wait for the cancelled tasks to actually stop."""
        tasks = self.shutdown()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _term_poller(self):
        TERM_POLLER_ALIVE.set(1)
        while True:
            await asyncio.sleep(self.reload_interval)
            try:
                self.reload_config()
            except Exception as e:
                # A poller that dies takes every future reload with it, in
                # silence. CancelledError is a BaseException, so shutdown
                # still stops this loop.
                TERM_RELOAD_FAILURES.labels(
                    source=self.config.secrets_provider.type
                ).inc()
                logger.error(f"Scheduled term reload failed: {e}")

    async def _worker_watchdog(self):
        """Replace workers stuck past a hard ceiling.

        ml_timeout only releases the caller; asyncio.to_thread cannot be
        cancelled, so one pathological input occupies its worker for as long
        as analyze() keeps running. With a fixed pool that is a slow drain to
        zero capacity. Replacing the task restores the slot -- the stuck
        thread is left to finish on its own, because Python cannot kill it.
        """
        ceiling = max(self.ml_timeout * 4, self.ml_timeout + 30)
        interval = max(self.ml_timeout, 1.0)

        while True:
            await asyncio.sleep(interval)
            now = time.monotonic()
            for worker in list(self.workers):
                started = self._worker_started_at.get(worker)
                if started is None or (now - started) < ceiling:
                    continue

                logger.error(
                    f"ML worker stuck for {now - started:.0f}s (ceiling "
                    f"{ceiling:.0f}s); replacing it to restore pool capacity"
                )
                worker.cancel()
                self._worker_started_at.pop(worker, None)
                self.workers.remove(worker)
                self.workers.append(asyncio.create_task(self._ml_worker()))
                ML_WORKER_RESTARTS.inc()
                ML_WORKERS_ALIVE.set(len(self.workers))

    async def _ml_worker(self):
        while True:
            text, future, request_id = await self.task_queue.get()
            task = asyncio.current_task()
            self._worker_started_at[task] = time.monotonic()
            try:
                results = await asyncio.to_thread(
                    self.analyzer.analyze,
                    text=text,
                    language="en",
                    entities=self.entities,
                )
                filtered = [r for r in results if r.score >= self.ml_threshold]
                # The caller may have timed out or disconnected, which cancels
                # the future. Setting a result on it raises InvalidStateError,
                # and that used to escape and kill the worker for good.
                if not future.done():
                    future.set_result(filtered)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    "ML worker failed to analyze text",
                    extra={"error": str(e), "request_id": request_id},
                )
                if not future.done():
                    future.set_exception(e)
            finally:
                self._worker_started_at.pop(task, None)
                self.task_queue.task_done()

    def _get_provider(self) -> TermProvider:
        """Build the configured term provider once and reuse it.

        VaultTermProvider holds the last-known-good terms and the circuit
        breaker state on the instance, so rebuilding it on every reload would
        reset both and defeat the whole point of having them.
        """
        if self._term_provider is not None:
            return self._term_provider

        if self.config.secrets_provider.type == "vault":
            vault_cfg = self.config.secrets_provider.vault
            if vault_cfg is None:
                raise TermFetchError(
                    "secrets_provider.type is 'vault' but no vault section configured"
                )
            token = vault_cfg.token or os.getenv("VAULT_TOKEN")
            if not (vault_cfg.url and token and vault_cfg.path):
                raise TermFetchError("Vault configuration incomplete (url/token/path)")
            self._term_provider = VaultTermProvider(
                vault_cfg.url, token, vault_cfg.path, timeout=vault_cfg.timeout
            )
        else:
            self._term_provider = FileTermProvider(self.config.static_terms_file)

        return self._term_provider

    def reload_config(self, force: bool = False):
        source = self.config.secrets_provider.type

        try:
            provider = self._get_provider()
            fingerprint = provider.fingerprint()

            # The poller runs on every provider now, so skip the rebuild when
            # the source demonstrably has not changed. A provider that cannot
            # answer cheaply returns None and is always reloaded.
            if (
                not force
                and self._terms_loaded
                and fingerprint is not None
                and fingerprint == self._terms_fingerprint
            ):
                return

            raw_terms = provider.get_terms()
        except TermFetchError as e:
            if not self._terms_loaded:
                # Nothing to fall back on. Starting up with an empty keyword
                # set would forward secrets in the clear, so refuse to run.
                raise
            TERM_RELOAD_FAILURES.labels(source=source).inc()
            logger.error(f"Term reload failed ({e}); keeping previously loaded terms")
            return

        terms = validate_terms(raw_terms, source)

        new_kp = KeywordProcessor()
        for term in terms:
            new_kp.add_keyword(term, term)

        self.keyword_processor = new_kp
        self._terms_loaded = True
        self._terms_fingerprint = fingerprint
        TERMS_LAST_RELOAD.set(time.time())
        logger.info(f"Loaded {len(terms)} terms from {source}")

    async def _analyze_ml(
        self, text: str, spans: list, stats: dict, request_id: str = "unknown"
    ) -> None:
        future = asyncio.get_running_loop().create_future()

        # The enqueue needs the same bound as the wait below. With a full
        # queue this put() blocked forever, so a saturated pool hung the
        # request instead of failing closed -- the opposite of what the
        # comment underneath promised.
        try:
            await asyncio.wait_for(
                self.task_queue.put((text, future, request_id)),
                timeout=self.ml_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Timed out enqueueing for ML analysis; the worker pool is "
                f"saturated (queue holds {self.task_queue.qsize()})",
                extra={"request_id": request_id},
            )
            future.cancel()
            raise

        # Never wait forever: if every worker is gone the queue would
        # otherwise hang the request, and a hang is not an exception, so
        # the proxy's fail-closed path would never fire.
        try:
            ml_results = await asyncio.wait_for(future, timeout=self.ml_timeout)
        except asyncio.TimeoutError:
            logger.error(
                f"ML analysis timed out after {self.ml_timeout}s",
                extra={"request_id": request_id},
            )
            raise

        stats["ml_replacements"] = len(ml_results)
        for r in ml_results:
            spans.append((r.start, r.end, r.entity_type))
            stats["pii_types"][r.entity_type] = (
                stats["pii_types"].get(r.entity_type, 0) + 1
            )

    async def redact(
        self, text: str, request_id: str = "unknown"
    ) -> tuple[str, dict]:
        stats = {"static_replacements": 0, "ml_replacements": 0, "pii_types": {}}
        spans = []

        static_hits = self.keyword_processor.extract_keywords(text, span_info=True)
        for _keyword, start, end in static_hits:
            spans.append((start, end, "STATIC_TERM"))
            stats["static_replacements"] += 1

        if self.ml_enabled and self.analyzer:
            try:
                await self._analyze_ml(text, spans, stats, request_id)
            except asyncio.TimeoutError:
                if not self.config.degrade_to_static_on_ml_timeout:
                    raise
                # Explicitly enabled: forward with reduced coverage rather
                # than block. Recorded in the stats and the metrics so the
                # degradation is never invisible.
                stats["ml_degraded"] = True
                ML_DEGRADED_TOTAL.inc()
                logger.warning(
                    "ML analysis timed out; forwarding with static-keyword "
                    "redaction only (degrade_to_static_on_ml_timeout is on). "
                    "Detection coverage is reduced for this request.",
                    extra={"request_id": request_id},
                )

        if not spans:
            return text, stats

        # Slice-assigning into one character list shifted every trailing
        # element per span, so cost grew with spans x text length. Copy the
        # gaps between spans instead and join once.
        chunks = []
        cursor = 0
        for start, end in _merge_spans(spans):
            chunks.append(text[cursor:start])
            chunks.append(self.replacement_token)
            cursor = end
        chunks.append(text[cursor:])

        return "".join(chunks), stats
