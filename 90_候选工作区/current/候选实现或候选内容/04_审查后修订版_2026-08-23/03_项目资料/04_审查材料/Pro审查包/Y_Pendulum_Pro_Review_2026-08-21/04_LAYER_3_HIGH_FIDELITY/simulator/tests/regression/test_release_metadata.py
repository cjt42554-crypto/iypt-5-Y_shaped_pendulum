from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

from ypendulum.version import __version__


ROOT = Path(__file__).resolve().parents[2]


def test_release_version_metadata_is_consistent() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    build_script = (ROOT / "scripts/build_release.py").read_text(encoding="utf-8")
    assert pyproject["project"]["version"] == __version__
    assert citation["version"] == __version__
    assert 'PEP440_VERSION' in build_script
    assert 'ARTIFACT_VERSION = PEP440_VERSION.replace("rc", "-rc")' in build_script
