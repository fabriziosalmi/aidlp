import os
import logging
import yaml
from typing import Literal, Optional, List, get_args
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

logger = logging.getLogger("dlp_proxy")


# Reject unknown keys inside every section. A mistyped nested key used to be
# dropped in silence, so the intended override simply never applied.
_STRICT = ConfigDict(extra="forbid")


class VaultConfig(BaseModel):
    model_config = _STRICT

    url: str = "http://localhost:8200"
    # Bounds the HTTP call itself. The circuit breaker counts *failures*, so a
    # Vault that is slow but not yet erroring could stall a fetch without ever
    # incrementing the failure count that would open the breaker.
    timeout: float = Field(10.0, gt=0)
    token: Optional[str] = None
    path: str = "aidlp/terms"


class SecretsProviderConfig(BaseModel):
    model_config = _STRICT

    # A bare string compared with == "vault" meant that "Vault", "VAULT" or a
    # typo silently selected the file provider instead of failing.
    type: Literal["file", "vault"] = "file"
    vault: Optional[VaultConfig] = None

    @model_validator(mode="after")
    def _vault_payload_matches_type(self):
        """Keep the discriminator and its payload consistent.

        `type: vault` with no vault section used to construct happily and
        only fail later, at the first term fetch.
        """
        if self.type == "vault" and self.vault is None:
            raise ValueError(
                "secrets_provider.type is 'vault' but no secrets_provider.vault "
                "section was supplied"
            )
        return self


class DLPConfig(BaseModel):
    model_config = _STRICT

    static_terms_file: str = "terms.txt"
    ml_enabled: bool = True
    # Compared directly against a presidio confidence score, which is in
    # [0, 1]. Anything above 1.0 made every comparison false and silently
    # disabled ML redaction while the proxy kept reporting normal stats.
    ml_threshold: float = Field(0.5, ge=0.0, le=1.0)
    # Upper bound on a single ML analysis, in seconds. Exceeding it raises,
    # which the proxy turns into a fail-closed 500 rather than a hang.
    ml_timeout: float = 30.0
    # How often the background poller re-reads the term source, in seconds.
    # Applies to the file provider as well as Vault, so `aidlp add-term`
    # reaches a running proxy without a restart.
    reload_interval: float = 60.0
    # When only the ML stage times out, forward with static-keyword redaction
    # instead of failing the request closed. OFF by default: partial redaction
    # is a real reduction in coverage, and for a DLP proxy that has to be a
    # deliberate choice rather than a default.
    degrade_to_static_on_ml_timeout: bool = False
    # ML analysis capacity. Previously literals in dlp_engine.py, so the only
    # way to add workers or deepen the queue was to edit the source.
    ml_workers: int = Field(4, ge=1, le=64)
    ml_queue_maxsize: int = Field(1000, ge=1)
    nlp_model: str = "en_core_web_sm"
    entities: Optional[List[str]] = None
    secrets_provider: SecretsProviderConfig = Field(
        default_factory=SecretsProviderConfig
    )
    replacement_token: str = "[REDACTED]"


class ProxyConfig(BaseModel):
    model_config = _STRICT

    port: int = Field(8080, ge=1, le=65535)

    # Loopback by default. The proxy authorises nobody unless auth_token is
    # set, so binding every interface would hand an open relay to any host
    # that can reach this machine. Widening this is an explicit decision.
    host: str = "127.0.0.1"

    metrics_port: int = Field(9090, ge=1, le=65535)

    # The Prometheus endpoint carries no authentication of its own, so it
    # stays off the network unless deliberately opened. Kept separate from
    # `host`: exposing the proxy should not silently expose its metrics.
    metrics_host: str = "127.0.0.1"

    # Shared secret that callers must present in Proxy-Authorization, as
    # either `Bearer <token>` or `Basic base64(user:<token>)`. With no token
    # the proxy serves loopback only; on any other interface it refuses to
    # relay rather than act as an open proxy.
    auth_token: Optional[str] = None

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


def _nested_model(annotation):
    """Return the BaseModel behind a field annotation, unwrapping Optional."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in get_args(annotation) or ():
        if isinstance(arg, type) and issubclass(arg, BaseModel):
            return arg
    return None


def find_unknown_config_keys(raw_config: dict, model=None, path=()) -> list[str]:
    """List config.yaml keys that map to no field on the model.

    AppConfig keeps extra="ignore" so a stray AIDLP_* variable cannot crash
    startup, but that also means a renamed or misspelled top-level section is
    dropped without a word. Name them instead.
    """
    model = model or AppConfig
    fields = model.model_fields
    unknown: list[str] = []

    for key, value in (raw_config or {}).items():
        here = path + (str(key),)
        if key not in fields:
            unknown.append(".".join(here))
            continue
        sub = _nested_model(fields[key].annotation)
        if sub is not None and isinstance(value, dict):
            unknown.extend(find_unknown_config_keys(value, sub, here))

    return sorted(unknown)


def load_config(config_path: str = "config.yaml") -> AppConfig:
    raw_config = _read_yaml(config_path)

    unknown = find_unknown_config_keys(raw_config)
    if unknown:
        logger.warning(
            f"Unrecognised keys in {config_path}, which will not take effect: "
            + ", ".join(unknown)
        )

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
