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


class TermProvider:
    def get_terms(self) -> list[str]:
        pass


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
            return self._cached_terms
        except Exception as e:
            logger.error(f"Failed to fetch terms from Vault: {e}")
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
        self.entities = config.dlp.entities
        self.replacement_token = config.dlp.replacement_token

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
                future.set_result(filtered)
            except Exception as e:
                future.set_exception(e)
            finally:
                self.task_queue.task_done()

    def reload_config(self):
        new_kp = KeywordProcessor()
        provider_type = config.dlp.secrets_provider.type
        terms = []

        if provider_type == "vault":
            url = config.dlp.secrets_provider.vault.url
            token = config.dlp.secrets_provider.vault.token or os.getenv("VAULT_TOKEN")
            path = config.dlp.secrets_provider.vault.path
            if url and token and path:
                provider = VaultTermProvider(url, token, path)
                terms = provider.get_terms()
                logger.info(f"Loaded {len(terms)} terms from Vault")
            else:
                logger.error("Vault configuration missing")
        else:
            file_path = config.dlp.static_terms_file
            provider = FileTermProvider(file_path)
            terms = provider.get_terms()
            logger.info(f"Loaded {len(terms)} terms from file: {file_path}")

        for term in terms:
            new_kp.add_keyword(term, term)

        self.keyword_processor = new_kp

    async def redact(self, text: str) -> tuple[str, dict]:
        stats = {"static_replacements": 0, "ml_replacements": 0, "pii_types": {}}
        spans = []

        static_hits = self.keyword_processor.extract_keywords(text, span_info=True)
        for keyword, start, end in static_hits:
            spans.append((start, end, "STATIC_TERM"))
            stats["static_replacements"] += 1

        if self.ml_enabled and self.analyzer:
            future = asyncio.get_running_loop().create_future()
            await self.task_queue.put((text, future))
            ml_results = await future

            stats["ml_replacements"] = len(ml_results)
            for r in ml_results:
                spans.append((r.start, r.end, r.entity_type))
                stats["pii_types"][r.entity_type] = (
                    stats["pii_types"].get(r.entity_type, 0) + 1
                )

        if not spans:
            return text, stats

        spans.sort(key=lambda x: x[0])
        merged_spans = []
        current_start, current_end = -1, -1

        for start, end, etype in spans:
            if current_start == -1:
                current_start, current_end = start, end
            elif start <= current_end:
                current_end = max(current_end, end)
            else:
                merged_spans.append((current_start, current_end))
                current_start, current_end = start, end
        if current_start != -1:
            merged_spans.append((current_start, current_end))

        res = list(text)
        for start, end in reversed(merged_spans):
            res[start:end] = list(self.replacement_token)

        return "".join(res), stats
