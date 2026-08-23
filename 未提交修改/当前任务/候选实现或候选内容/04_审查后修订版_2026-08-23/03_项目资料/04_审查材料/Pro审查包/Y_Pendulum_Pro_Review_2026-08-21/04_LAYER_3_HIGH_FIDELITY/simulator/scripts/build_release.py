#!/usr/bin/env python3
"""Build a deterministic complete-source ZIP and SHA-256 sidecar.

The full project ZIP is distinct from the Python wheel/sdist: it includes tests,
configs, validation evidence, documentation and the Codex continuation contract.
Generated run directories and build caches are excluded.
"""

from __future__ import annotations

import hashlib
import json
import stat
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PEP440_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"
]["version"]
ARTIFACT_VERSION = PEP440_VERSION.replace("rc", "-rc")
FIXED_ZIP_TIME = (2026, 8, 18, 0, 0, 0)
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "build",
    "dist",
    "runs",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_GENERATED_PREFIXES = {
    "validation/build_release",
    "validation/release_zip_verification",
    "validation/reproducible_zip_hashes",
}
REQUIRED_RELEASE_PATHS = {
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "CODEX_CONTINUATION_AND_ENVIRONMENT_GAPS.md",
    "pyproject.toml",
    "docs/frozen_specification.md",
    "docs/theory.md",
    "tests/conftest.py",
    "validation/validation_report.md",
    "validation/convergence_report.md",
    "configs/examples/full_quick_3to2.yaml",
    "src/ypendulum/api.py",
}


def _excluded(relative: Path) -> bool:
    relative_text = relative.as_posix()
    return (
        any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in relative.parts)
        or relative.suffix in EXCLUDED_SUFFIXES
        or relative.name in {".DS_Store"}
        or any(relative_text.startswith(prefix) for prefix in EXCLUDED_GENERATED_PREFIXES)
    )


def included_files(*, include_manifest: bool = True) -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if _excluded(relative) or not path.is_file():
            continue
        if not include_manifest and relative.as_posix() == "PROJECT_FILE_MANIFEST.json":
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.relative_to(ROOT).as_posix())


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_zip_member(archive: zipfile.ZipFile, path: Path, archive_name: str) -> None:
    info = zipfile.ZipInfo(archive_name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    executable = bool(path.stat().st_mode & stat.S_IXUSR)
    permissions = 0o755 if executable else 0o644
    info.external_attr = permissions << 16
    info.flag_bits |= 0x800  # UTF-8 names
    archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> None:
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    source_files = included_files(include_manifest=False)
    relative_names = {path.relative_to(ROOT).as_posix() for path in source_files}
    missing = sorted(REQUIRED_RELEASE_PATHS.difference(relative_names))
    if missing:
        raise RuntimeError(f"Complete release ZIP is missing required paths: {missing}")

    manifest = {
        "format_version": 1,
        "project_version_pep440": PEP440_VERSION,
        "artifact_version": ARTIFACT_VERSION,
        "manifest_self_excluded": True,
        "files": {
            path.relative_to(ROOT).as_posix(): {
                "sha256": sha(path),
                "size_bytes": path.stat().st_size,
            }
            for path in source_files
        },
    }
    manifest_path = ROOT / "PROJECT_FILE_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    files = included_files(include_manifest=True)

    target = dist / f"Y-Pendulum-Simulator-v{ARTIFACT_VERSION}.zip"
    target.unlink(missing_ok=True)
    prefix = f"Y-Pendulum-Simulator-v{ARTIFACT_VERSION}"
    with zipfile.ZipFile(target, "w") as archive:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            _write_zip_member(archive, path, f"{prefix}/{relative}")

    checksum = sha(target)
    checksum_path = target.with_suffix(target.suffix + ".sha256.txt")
    checksum_path.write_text(f"{checksum}  {target.name}\n", encoding="utf-8")
    print(target)
    print(checksum)


if __name__ == "__main__":
    main()
