import logging
from typing import List, Tuple, Dict
from flashtext import KeywordProcessor
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from .config import config

logger = logging.getLogger(__name__)

class DLPEngine:
    def __init__(self):
        self.keyword_processor = KeywordProcessor()
        self.analyzer = AnalyzerEngine()
        self.anonymizer = AnonymizerEngine()
        self.reload_config()

    def reload_config(self):
        # Reload static terms
        self.keyword_processor = KeywordProcessor()
        static_terms = config.get("dlp.static_terms", [])
        for term in static_terms:
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
