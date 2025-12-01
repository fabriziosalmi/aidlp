import logging
import os
from typing import Tuple, Dict
from abc import ABC, abstractmethod
import hvac
from flashtext import KeywordProcessor
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from .config import config

logger = logging.getLogger("dlp_proxy")


class TermProvider(ABC):
    @abstractmethod
    def get_terms(self) -> list[str]:
        pass


class FileTermProvider(TermProvider):
    def __init__(self, file_path: str):
        self.file_path = file_path

    def get_terms(self) -> list[str]:
        if not os.path.exists(self.file_path):
            # Create default if missing
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

    def get_terms(self) -> list[str]:
        try:
            if not self.client.is_authenticated():
                logger.error("Vault client is not authenticated")
                return []

            # Read secret from Vault (KV v2)
            read_response = self.client.secrets.kv.v2.read_secret_version(
                path=self.path,
                mount_point=self.mount_point
            )

            # Assuming terms are stored as keys or a specific list in the secret
            # Strategy: Take all values from the secret dictionary
            data = read_response['data']['data']
            terms = []
            for key, value in data.items():
                if isinstance(value, list):
                    terms.extend([str(v) for v in value])
                else:
                    terms.append(str(value))
            return terms
        except Exception as e:
            logger.error(f"Failed to fetch terms from Vault: {e}")
            return []


class DLPEngine:
    def __init__(self):
        self.keyword_processor = KeywordProcessor()
        self.analyzer = AnalyzerEngine()
        self.anonymizer = AnonymizerEngine()
        self.reload_config()

    def reload_config(self):
        # Reload static terms
        self.keyword_processor = KeywordProcessor()

        # Determine provider
        provider_type = config.get("dlp.secrets_provider.type", "file")

        terms = []
        if provider_type == "vault":
            url = config.get("dlp.secrets_provider.vault.url")
            token = config.get("dlp.secrets_provider.vault.token") or os.getenv("VAULT_TOKEN")
            path = config.get("dlp.secrets_provider.vault.path")
            if url and token and path:
                provider = VaultTermProvider(url, token, path)
                terms = provider.get_terms()
                logger.info(f"Loaded {len(terms)} terms from Vault")
            else:
                logger.error("Vault configuration missing")
        else:
            # Default to file
            file_path = config.get("dlp.static_terms_file", "terms.txt")
            provider = FileTermProvider(file_path)
            terms = provider.get_terms()
            logger.info(f"Loaded {len(terms)} terms from file: {file_path}")

        for term in terms:
            self.keyword_processor.add_keyword(term, config.get("dlp.replacement_token", "[REDACTED]"))

        self.ml_enabled = config.get("dlp.ml_enabled", True)
        self.ml_threshold = config.get("dlp.ml_threshold", 0.5)
        self.replacement_token = config.get("dlp.replacement_token", "[REDACTED]")

    def redact(self, text: str) -> Tuple[str, Dict[str, int]]:
        stats = {"static_replacements": 0, "ml_replacements": 0}

        # 1. Static Redaction (Fastest)
        # Flashtext replaces in-place or returns new string.
        # To get stats, we might need to extract keywords first or just trust the replacement count if flashtext supported it easily.
        # For now, let's just do replacement.
        # To count, we can extract keywords first.
        keywords_found = self.keyword_processor.extract_keywords(text)
        stats["static_replacements"] = len(keywords_found)

        text_after_static = self.keyword_processor.replace_keywords(text)

        if not self.ml_enabled:
            return text_after_static, stats

        # 2. ML Redaction
        results = self.analyzer.analyze(text=text_after_static, language='en')

        # Filter by threshold
        results = [r for r in results if r.score >= self.ml_threshold]
        stats["ml_replacements"] = len(results)

        # Define anonymizer operators
        operators = {
            "DEFAULT": OperatorConfig("replace", {"new_value": self.replacement_token}),
        }

        anonymized_result = self.anonymizer.anonymize(
            text=text_after_static,
            analyzer_results=results,
            operators=operators
        )

        return anonymized_result.text, stats
