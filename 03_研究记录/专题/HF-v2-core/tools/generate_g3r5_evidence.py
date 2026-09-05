#!/usr/bin/env python3
"""Execute once or statically verify the frozen G3R5 qualification campaign."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ypendulum_hfv2_p3r5.evidence import (  # noqa: E402
    generate_g3r5_evidence,
    render_human_report,
    render_raw_report,
)

METRICS = ROOT / "reports/g3r5_metrics.json"
RAW = ROOT / "reports/G3R5_REPORT_RAW.md"
REPORT = ROOT / "reports/G3R5_REPORT.md"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run-once", action="store_true")
    mode.add_argument("--check", action="store_true")
    return parser.parse_args()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _repository_clean() -> bool:
    output = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return not output.strip()


def _run_once() -> int:
    if any(path.exists() for path in (METRICS, RAW, REPORT)):
        raise RuntimeError("G3R5 evidence exists; refusing to rerun.")
    if not _repository_clean():
        raise RuntimeError("G3R5 evidence requires a clean target-freeze commit.")
    metrics = generate_g3r5_evidence(ROOT)
    _atomic_write(METRICS, _json_bytes(metrics))
    _atomic_write(RAW, render_raw_report(metrics).encode("utf-8"))
    _atomic_write(REPORT, render_human_report(metrics).encode("utf-8"))
    return 0


def _check() -> int:
    if not all(path.exists() for path in (METRICS, RAW, REPORT)):
        return 1
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    return int(
        RAW.read_bytes() != render_raw_report(metrics).encode("utf-8")
        or REPORT.read_bytes() != render_human_report(metrics).encode("utf-8")
    )


def main() -> int:
    arguments = _arguments()
    return _run_once() if arguments.run_once else _check()


if __name__ == "__main__":
    raise SystemExit(main())
