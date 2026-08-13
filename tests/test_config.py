import pytest
import yaml

from src.config import find_env_shadowed_keys, load_config


def _write(tmp_path, data):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return str(path)


def test_environment_beats_yaml(tmp_path, monkeypatch):
    """The precedence the README always documented, and never had.

    Until 2.1.0 the YAML was passed as init kwargs, which outrank every
    other source in pydantic-settings, so config.yaml silently won.
    """
    path = _write(tmp_path, {"dlp": {"replacement_token": "[YAML]"}})
    monkeypatch.setenv("AIDLP_DLP__REPLACEMENT_TOKEN", "[ENV]")

    assert load_config(path).dlp.replacement_token == "[ENV]"


def test_environment_cannot_be_overridden_into_insecure_tls(tmp_path, monkeypatch):
    """A stale config.yaml must not undo a hardened environment.

    An operator setting AIDLP_PROXY__UPSTREAM_INSECURE=false is asking for
    upstream certificate verification. A leftover `upstream_insecure: true`
    used to win that argument silently.
    """
    path = _write(tmp_path, {"proxy": {"upstream_insecure": True}})
    monkeypatch.setenv("AIDLP_PROXY__UPSTREAM_INSECURE", "false")

    assert load_config(path).proxy.upstream_insecure is False


def test_environment_cannot_be_overridden_into_disabled_ml(tmp_path, monkeypatch):
    path = _write(tmp_path, {"dlp": {"ml_enabled": False}})
    monkeypatch.setenv("AIDLP_DLP__ML_ENABLED", "true")

    assert load_config(path).dlp.ml_enabled is True


def test_yaml_beats_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("AIDLP_PROXY__METRICS_PORT", raising=False)
    path = _write(tmp_path, {"proxy": {"metrics_port": 7777}})

    assert load_config(path).proxy.metrics_port == 7777


def test_sources_merge_per_key(tmp_path, monkeypatch):
    """Env overriding one key must not discard the rest of the YAML section."""
    path = _write(
        tmp_path,
        {"dlp": {"replacement_token": "[YAML]", "ml_threshold": 0.9}},
    )
    monkeypatch.setenv("AIDLP_DLP__REPLACEMENT_TOKEN", "[ENV]")

    config = load_config(path)
    assert config.dlp.replacement_token == "[ENV]"
    assert config.dlp.ml_threshold == 0.9  # untouched by the environment
    assert config.dlp.static_terms_file == "terms.txt"  # still the default


def test_missing_file_falls_back_to_defaults(tmp_path):
    config = load_config(str(tmp_path / "nope.yaml"))
    assert config.proxy.port == 8080


def test_malformed_yaml_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("proxy: [unclosed\n")

    with pytest.raises(yaml.YAMLError):
        load_config(str(path))


def test_non_mapping_yaml_raises_a_clear_error(tmp_path):
    """A top-level list would otherwise fail deep inside the settings source."""
    path = tmp_path / "config.yaml"
    path.write_text("- proxy\n- dlp\n")

    with pytest.raises(TypeError, match="must contain a mapping"):
        load_config(str(path))


def test_empty_yaml_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("")

    assert load_config(str(path)).proxy.port == 8080


def test_find_env_shadowed_keys_reports_nested_conflicts():
    raw = {
        "proxy": {"port": 8080, "upstream_insecure": True},
        "dlp": {"secrets_provider": {"type": "file"}},
    }
    environ = {
        "AIDLP_PROXY__UPSTREAM_INSECURE": "false",
        "AIDLP_DLP__SECRETS_PROVIDER__TYPE": "vault",
    }

    shadowed = find_env_shadowed_keys(raw, environ)

    assert shadowed == [
        "dlp.secrets_provider.type (overridden by AIDLP_DLP__SECRETS_PROVIDER__TYPE)",
        "proxy.upstream_insecure (overridden by AIDLP_PROXY__UPSTREAM_INSECURE)",
    ]


def test_find_env_shadowed_keys_silent_without_conflicts():
    raw = {"proxy": {"port": 8080}}
    assert find_env_shadowed_keys(raw, {"AIDLP_DLP__ML_ENABLED": "true"}) == []
