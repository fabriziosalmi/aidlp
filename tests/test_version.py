"""The advertised version must match the packaged one."""

import re
from pathlib import Path

from src import __version__


def test_version_matches_pyproject():
    """A drifting version makes /_health and --version lie to callers.

    src/__init__.py carries a literal because the container image copies
    src/ without installing the distribution, so importlib.metadata has
    nothing to read there.
    """
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    declared = re.search(r'^version = "([^"]+)"', pyproject.read_text(), re.M)

    assert declared, "no version found in pyproject.toml"
    assert __version__ == declared.group(1)
