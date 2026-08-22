#!/usr/bin/env python3
"""Run auditable release-candidate checks without modifying scientific baselines."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "Dockerfile",
    "pyproject.toml",
    "docs/frozen_specification.md",
    "docs/theory.md",
    "docs/numerical_method.md",
    "docs/user_guide.md",
    "docs/api.md",
    "docs/limitations.md",
    "validation/validation_report.md",
    "validation/convergence_report.md",
    "tests",
    "configs/examples",
]


def run(command: list[str], *, timeout: int = 300) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
        "passed": proc.returncode == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-validation", action="store_true")
    parser.add_argument("--output", default="validation/release_checks.json")
    args = parser.parse_args()

    missing = [name for name in REQUIRED if not (ROOT / name).exists()]
    commands = [
        [sys.executable, "-m", "compileall", "-q", "src"],
        [sys.executable, "-m", "pytest", "-q"],
        [
            sys.executable,
            "-m",
            "ypendulum.cli",
            "validate-suite",
            *([] if args.full_validation else ["--fast"]),
            "--output-directory",
            "validation/generated/release",
        ],
        [
            sys.executable,
            "-m",
            "ypendulum.cli",
            "diagnose",
            "configs/examples/full_quick_3to2.yaml",
            "--skip-equilibrium",
        ],
    ]
    results = [run(command, timeout=600) for command in commands]
    report = {
        "required_files_missing": missing,
        "checks": results,
        "passed": not missing and all(item["passed"] for item in results),
    }
    target = ROOT / args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
