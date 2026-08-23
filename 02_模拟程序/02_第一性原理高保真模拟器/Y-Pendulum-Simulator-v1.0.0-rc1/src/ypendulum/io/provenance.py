"""Run provenance and deterministic source/config hashing."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess

import numpy as np
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ypendulum.version import __version__


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def source_hash(package_root: str | Path) -> str:
    root = Path(package_root)
    h = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        h.update(str(path.relative_to(root)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def git_commit(root: str | Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def dependency_versions(names: list[str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in names:
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            out[name] = None
    return out


def build_provenance(
    *,
    project_root: str | Path,
    config_hash: str,
    seed: int,
    solver: dict[str, Any],
    mesh: dict[str, Any],
    claim_level: str,
    assumptions: list[str],
) -> dict[str, Any]:
    root = Path(project_root)
    source_root = root / "src" / "ypendulum"
    if not source_root.exists():
        source_root = Path(__file__).resolve().parents[1]
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "project_version": __version__,
        "git_commit": git_commit(root),
        "source_hash_sha256": source_hash(source_root),
        "config_hash_sha256": config_hash,
        "python": sys.version,
        "platform": platform.platform(),
        "executable": sys.executable,
        "dependencies": dependency_versions(
            ["numpy", "scipy", "pydantic", "pint", "PyYAML", "h5py", "pandas", "matplotlib"]
        ),
        "seed": seed,
        "solver": solver,
        "mesh": mesh,
        "claim_level": claim_level,
        "assumptions": assumptions,
        "environment": {"OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS")},
    }


def json_safe(obj: Any) -> Any:
    """Convert scientific Python values to strict RFC-compatible JSON data."""

    if isinstance(obj, dict):
        return {str(key): json_safe(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(value) for value in obj]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, np.ndarray):
        return json_safe(obj.tolist())
    if isinstance(obj, np.generic):
        return json_safe(obj.item())
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (str, int, bool)) or obj is None:
        return obj
    if hasattr(obj, "tolist"):
        return json_safe(obj.tolist())
    raise TypeError(f"Cannot JSON-serialise {type(obj).__name__}")


def write_json(path: str | Path, payload: Any) -> None:
    Path(path).write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
