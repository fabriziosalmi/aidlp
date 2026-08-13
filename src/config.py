import os
import logging
import yaml
from typing import Optional, List
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
    # Upper bound on a single ML analysis, in seconds. Exceeding it raises,
    # which the proxy turns into a fail-closed 500 rather than a hang.
    ml_timeout: float = 30.0
    nlp_model: str = "en_core_web_sm"
    entities: Optional[List[str]] = None
    secrets_provider: SecretsProviderConfig = Field(
        default_factory=SecretsProviderConfig
    )
    replacement_token: str = "[REDACTED]"


class ProxyConfig(BaseModel):
    port: int = 8080
    host: str = "0.0.0.0"
    metrics_port: int = 9090

    # Skip verification of the certificate presented by the upstream server.
    # Turning this on means the proxy accepts ANY certificate, so the prompts
    # it forwards can be read and altered in transit by whoever answers.
    # Defaults to off since 2.0.0; before that it was effectively on.
    upstream_insecure: bool = False

    # Deprecated in 2.0.0, kept only so an existing config.yaml is reported
    # rather than silently ignored. The name always promised TLS interception;
    # its one real effect was disabling upstream verification.
    ssl_bump: Optional[bool] = None


class AppConfig(BaseSettings):
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    dlp: DLPConfig = Field(default_factory=DLPConfig)

    model_config = SettingsConfigDict(
        env_nested_delimiter="__", env_prefix="AIDLP_", extra="ignore"
    )


def load_config(config_path: str = "config.yaml") -> AppConfig:
    raw_config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
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
