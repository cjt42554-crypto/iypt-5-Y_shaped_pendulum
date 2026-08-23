#!/usr/bin/env python3
"""Generate the portable FWD delivery identity consumed by the unified case."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def source_tree_hash(project_root: Path) -> str:
    paths = [
        *sorted((project_root / "y_pendulum_forward").glob("*.py")),
        project_root / "run.py",
        project_root / "pyproject.toml",
        project_root / "requirements.txt",
    ]
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(project_root).as_posix()):
        relative = path.relative_to(project_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    simulator_root = Path(__file__).resolve().parents[1]
    project_root = (
        simulator_root
        / "../../01_前向预测数值求解器/y_pendulum_forward_solver"
    ).resolve()
    output = project_root / "validation" / "delivery_root.json"
    selected = [
        project_root / "pyproject.toml",
        project_root / "requirements.txt",
        project_root / "run.py",
        *sorted((project_root / "configs").glob("*.json")),
        *sorted((project_root / "y_pendulum_forward").glob("*.py")),
        *sorted((project_root / "tests").glob("test_*.py")),
    ]
    files: dict[str, dict[str, Any]] = {}
    for path in selected:
        raw = path.read_bytes()
        files[path.relative_to(project_root).as_posix()] = {
            "bytes": len(raw),
            "sha256": sha256(raw),
        }
    config_path = project_root / "configs" / "cable_example.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    payload = {
        "schema_version": "YPS-FWD-PORTABLE-DELIVERY-ROOT-1.1",
        "stage": "forward_numerical_computation_stage_2",
        "gate_status": "READY_FOR_INDEPENDENT_READ_ONLY_GATE",
        "project_root_relative_to_delivery_root": "..",
        "file_count": len(files),
        "files": files,
        "tree_sha256": canonical_hash(files),
        "source_tree_sha256": source_tree_hash(project_root),
        "production_config_sha256": {
            "FWD-CABLE-1.0": canonical_hash(config)
        },
        "frozen_theory_sha256": config["theory_sha256"],
        "numerical_theory_sha256": (
            "14b9e5bae0778753acbc46757286b4d5e646b120698ddd2bc33e16158efa78a7"
        ),
        "identity_policy": (
            "content hashes and paths relative to this delivery root; no workstation "
            "absolute path participates in identity"
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(sha256(output.read_bytes()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
