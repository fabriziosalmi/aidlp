import yaml
import os
import logging
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("dlp_proxy")

# Pydantic Models


class VaultConfig(BaseModel):
    url: str = "http://localhost:8200"
    token: Optional[str] = None
    path: str = "aidlp/terms"


class SecretsProviderConfig(BaseModel):
    type: str = "file"
    vault: Optional[VaultConfig] = None


class DLPConfig(BaseModel):
    static_terms_file: str = "terms.txt"
    ml_enabled: bool = True
    ml_threshold: float = 0.5
    nlp_model: str = "en_core_web_sm"
    entities: Optional[List[str]] = None
    secrets_provider: SecretsProviderConfig = Field(default_factory=SecretsProviderConfig)
    replacement_token: str = "[REDACTED]"


class ProxyConfig(BaseModel):
    port: int = 8080
    host: str = "0.0.0.0"
    ssl_bump: bool = True
    metrics_port: int = 9090


class UpstreamConfig(BaseModel):
    default_scheme: str = "https"


class AppConfig(BaseModel):
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    dlp: DLPConfig = Field(default_factory=DLPConfig)
    upstream: UpstreamConfig = Field(default_factory=UpstreamConfig)


class ConfigLoader:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            logger.warning(f"Config file {self.config_path} not found. Using defaults.")
            return AppConfig().model_dump()

        try:
            with open(self.config_path, 'r') as f:
                raw_config = yaml.safe_load(f) or {}

            # Validate with Pydantic
            app_config = AppConfig(**raw_config)
            return app_config.model_dump()
        except ValidationError as e:
            logger.critical(f"Configuration validation failed: {e}")
            raise  # Fail fast
        except Exception as e:
            logger.critical(f"Failed to load config: {e}")
            raise

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    def reload(self):
        self._config = self._load_config()


# Global instance
try:
    config = ConfigLoader()
except Exception:
    # If validation fails during import (e.g. in tests or initial startup),
    # we might want to handle it, but failing fast is requested.
    # However, for tools that import config but don't run the app, we might want to be careful.
    # But the requirement is "Fail fast if types are wrong".
    # So we let it raise.
    raise
