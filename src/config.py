import os
import logging
import yaml
from typing import Optional, List
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

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


class _MappingSource(PydanticBaseSettingsSource):
    """Feed an already-parsed mapping in as an ordinary settings source.

    The YAML file used to be passed as init keyword arguments, and in
    pydantic-settings those outrank every other source. So config.yaml
    silently beat the AIDLP_* environment variables that the README
    promised would win -- quietly undoing, among other things, an
    AIDLP_PROXY__UPSTREAM_INSECURE=false meant to harden a deployment.
    """

    def __init__(self, settings_cls, data: dict):
        super().__init__(settings_cls)
        self._data = data

    def get_field_value(self, field, field_name):
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict:
        return self._data


def _read_yaml(config_path: str) -> dict:
    if not os.path.exists(config_path):
        logger.warning(f"Config file {config_path} not found. Using defaults/env vars.")
        return {}

    try:
        with open(config_path, "r") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        logger.critical(f"Failed to load yaml config: {e}")
        raise

    if data is None:  # empty file
        return {}

    if not isinstance(data, dict):
        # A top-level list or scalar would otherwise reach the settings
        # source and fail somewhere far less informative.
        message = (
            f"Config file {config_path} must contain a mapping at the top "
            f"level, got {type(data).__name__}."
        )
        logger.critical(message)
        raise TypeError(message)

    return data


def find_env_shadowed_keys(raw_config: dict, environ=None) -> list[str]:
    """List config.yaml keys that an AIDLP_* variable takes precedence over.

    Silently winning is how this went unnoticed for so long, in both
    directions. Name the conflicts instead.
    """
    environ = os.environ if environ is None else environ
    shadowed: list[str] = []

    def walk(node, path):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            here = path + [str(key)]
            if isinstance(value, dict):
                walk(value, here)
                continue
            var = "AIDLP_" + "__".join(p.upper() for p in here)
            if var in environ:
                shadowed.append(f"{'.'.join(here)} (overridden by {var})")

    walk(raw_config, [])
    return sorted(shadowed)


def load_config(config_path: str = "config.yaml") -> AppConfig:
    raw_config = _read_yaml(config_path)

    shadowed = find_env_shadowed_keys(raw_config)
    if shadowed:
        logger.warning(
            "Environment variables override these config.yaml keys: "
            + "; ".join(shadowed)
        )

    class _AppConfig(AppConfig):
        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls,
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        ):
            # First source wins. Environment beats the YAML file, which
            # beats the field defaults -- the order the README always
            # documented and docker-compose.yml always assumed.
            #
            # init_settings is deliberately absent: load_config passes no
            # keyword arguments, and leaving it in would keep a silent tier
            # above the environment. That extra tier is exactly what caused
            # this bug in the first place.
            return (
                env_settings,
                dotenv_settings,
                _MappingSource(settings_cls, raw_config),
                file_secret_settings,
            )

    try:
        return _AppConfig()
    except ValidationError as e:
        logger.critical(f"Configuration validation failed: {e}")
        raise


# Global instance
config = load_config()
