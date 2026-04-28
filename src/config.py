import yaml
import os
import logging
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("dlp_proxy")

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

class AppConfig(BaseSettings):
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    dlp: DLPConfig = Field(default_factory=DLPConfig)
    upstream: UpstreamConfig = Field(default_factory=UpstreamConfig)

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_prefix="AIDLP_",
        extra="ignore"
    )

def load_config(config_path: str = "config.yaml") -> AppConfig:
    raw_config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                raw_config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.critical(f"Failed to load yaml config: {e}")
            raise
    else:
        logger.warning(f"Config file {config_path} not found. Using defaults/env vars.")

    try:
        return AppConfig(**raw_config)
    except ValidationError as e:
        logger.critical(f"Configuration validation failed: {e}")
        raise

# Global instance
config = load_config()
