import logging
import os
import asyncio
import hvac
import pybreaker

from flashtext import KeywordProcessor
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

from .config import config

logger = logging.getLogger("dlp_proxy")


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


class TermFetchError(Exception):
    """Raised when a provider cannot supply a usable term list.

    Callers must treat this as "keep the previous terms", never as
    "there are no terms" -- the latter silently disables redaction.
    """


class TermProvider:
    def get_terms(self) -> list[str]:
        raise NotImplementedError


class FileTermProvider(TermProvider):
    def __init__(self, file_path: str):
        self.file_path = file_path

    def get_terms(self) -> list[str]:
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w") as f:
                f.write("password\nsecret\napi_key\n")
            return ["password", "secret", "api_key"]

        with open(self.file_path, "r") as f:
            return [line.strip() for line in f if line.strip()]


class VaultTermProvider(TermProvider):
    def __init__(self, url: str, token: str, path: str, mount_point: str = "secret"):
        self.client = hvac.Client(url=url, token=token)
        self.path = path
        self.mount_point = mount_point
        self.breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=60)
        self._cached_terms = []

    def get_terms(self) -> list[str]:
        try:
            return self.breaker.call(self._fetch_from_vault)
        except pybreaker.CircuitBreakerError:
            logger.error("Vault Circuit Breaker open. Using cached terms.")
            return self._cached_or_raise()
        except Exception as e:
            logger.error(f"Failed to fetch terms from Vault: {e}")
            return self._cached_or_raise()

    def _cached_or_raise(self) -> list[str]:
        # An empty cache means we never had a good fetch. Returning [] here
        # would install an empty keyword set and silently stop redacting.
        if not self._cached_terms:
            raise TermFetchError("Vault unreachable and no cached terms available")
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
    def __init__(self):
        self.keyword_processor = KeywordProcessor()
        self.ml_enabled = config.dlp.ml_enabled
        self.ml_threshold = config.dlp.ml_threshold
        self.ml_timeout = config.dlp.ml_timeout
        self.entities = config.dlp.entities
        self.replacement_token = config.dlp.replacement_token

        self._term_provider = None
        self._terms_loaded = False

        self.analyzer = None
        if self.ml_enabled:
            model_name = config.dlp.nlp_model
            logger.info(f"Loading NLP model: {model_name}")
            nlp_configuration = {
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": model_name}],
            }
            provider = NlpEngineProvider(nlp_configuration=nlp_configuration)
            nlp_engine = provider.create_engine()
            self.analyzer = AnalyzerEngine(nlp_engine=nlp_engine)

        self.reload_config()
        self.task_queue = asyncio.Queue(maxsize=1000)
        self.workers = []
        self.poller_task = None

    def start_workers(self):
        if self.ml_enabled and not self.workers:
            for _ in range(4):
                self.workers.append(asyncio.create_task(self._ml_worker()))

        if config.dlp.secrets_provider.type == "vault" and not self.poller_task:
            self.poller_task = asyncio.create_task(self._vault_poller())

    def shutdown(self):
        for worker in self.workers:
            worker.cancel()
        if self.poller_task:
            self.poller_task.cancel()

    async def _vault_poller(self):
        while True:
            await asyncio.sleep(60)
            logger.info("Polling Vault for new terms...")
            self.reload_config()

    async def _ml_worker(self):
        while True:
            text, future = await self.task_queue.get()
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
                logger.error(f"ML worker failed to analyze text: {e}")
                if not future.done():
                    future.set_exception(e)
            finally:
                self.task_queue.task_done()

    def _get_provider(self) -> TermProvider:
        """Build the configured term provider once and reuse it.

        VaultTermProvider holds the last-known-good terms and the circuit
        breaker state on the instance, so rebuilding it on every reload would
        reset both and defeat the whole point of having them.
        """
        if self._term_provider is not None:
            return self._term_provider

        if config.dlp.secrets_provider.type == "vault":
            vault_cfg = config.dlp.secrets_provider.vault
            if vault_cfg is None:
                raise TermFetchError(
                    "secrets_provider.type is 'vault' but no vault section configured"
                )
            token = vault_cfg.token or os.getenv("VAULT_TOKEN")
            if not (vault_cfg.url and token and vault_cfg.path):
                raise TermFetchError("Vault configuration incomplete (url/token/path)")
            self._term_provider = VaultTermProvider(
                vault_cfg.url, token, vault_cfg.path
            )
        else:
            self._term_provider = FileTermProvider(config.dlp.static_terms_file)

        return self._term_provider

    def reload_config(self):
        try:
            terms = self._get_provider().get_terms()
        except TermFetchError as e:
            if not self._terms_loaded:
                # Nothing to fall back on. Starting up with an empty keyword
                # set would forward secrets in the clear, so refuse to run.
                raise
            logger.error(f"Term reload failed ({e}); keeping previously loaded terms")
            return

        new_kp = KeywordProcessor()
        for term in terms:
            new_kp.add_keyword(term, term)

        self.keyword_processor = new_kp
        self._terms_loaded = True
        logger.info(f"Loaded {len(terms)} terms from {config.dlp.secrets_provider.type}")

    async def _analyze_ml(self, text: str, spans: list, stats: dict) -> None:
        future = asyncio.get_running_loop().create_future()
        await self.task_queue.put((text, future))
        # Never wait forever: if every worker is gone the queue would
        # otherwise hang the request, and a hang is not an exception, so
        # the proxy's fail-closed path would never fire.
        try:
            ml_results = await asyncio.wait_for(future, timeout=self.ml_timeout)
        except asyncio.TimeoutError:
            logger.error(f"ML analysis timed out after {self.ml_timeout}s")
            raise

        stats["ml_replacements"] = len(ml_results)
        for r in ml_results:
            spans.append((r.start, r.end, r.entity_type))
            stats["pii_types"][r.entity_type] = (
                stats["pii_types"].get(r.entity_type, 0) + 1
            )

    async def redact(self, text: str) -> tuple[str, dict]:
        stats = {"static_replacements": 0, "ml_replacements": 0, "pii_types": {}}
        spans = []

        static_hits = self.keyword_processor.extract_keywords(text, span_info=True)
        for _keyword, start, end in static_hits:
            spans.append((start, end, "STATIC_TERM"))
            stats["static_replacements"] += 1

        if self.ml_enabled and self.analyzer:
            await self._analyze_ml(text, spans, stats)

        if not spans:
            return text, stats

        res = list(text)
        for start, end in reversed(_merge_spans(spans)):
            res[start:end] = list(self.replacement_token)

        return "".join(res), stats
