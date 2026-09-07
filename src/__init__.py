"""aidlp -- a DLP proxy for traffic bound for LLM endpoints."""

from importlib.metadata import PackageNotFoundError, version as _installed_version

# Single source of truth for the running contract version. Prefer the
# installed distribution metadata; fall back to this literal, which the
# container needs because the image copies src/ without installing the
# package. tests/test_version.py asserts the two never drift apart.
__version__ = "4.0.1"

try:  # pragma: no cover - depends on how the package was installed
    __version__ = _installed_version("aidlp")
except PackageNotFoundError:
    pass
