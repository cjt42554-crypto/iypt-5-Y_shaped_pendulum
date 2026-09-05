#!/usr/bin/env python3
"""Execute once or statically verify frozen G3R3 qualification evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ypendulum_hfv2_p3r3.evidence import (  # noqa: E402
    generate_g3r3_evidence,
    render_human_report,
    render_raw_report,
)

METRICS = ROOT / "reports/g3r3_metrics.json"
RAW_REPORT = ROOT / "reports/G3R3_REPORT_RAW.md"
REPORT = ROOT / "reports/G3R3_REPORT.md"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run-once", action="store_true")
    mode.add_argument("--check", action="store_true")
    return parser.parse_args()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _repository_clean() -> bool:
    output = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return not output.strip()


def _run_once() -> int:
    outputs = (METRICS, RAW_REPORT, REPORT)
    if any(path.exists() for path in outputs):
        raise RuntimeError("G3R3 one-shot evidence already exists; refusing to rerun.")
    if not _repository_clean():
        raise RuntimeError("G3R3 qualification must start from a clean committed tree.")
    metrics = generate_g3r3_evidence(ROOT)
    METRICS.write_bytes(_json_bytes(metrics))
    RAW_REPORT.write_text(render_raw_report(metrics), encoding="utf-8")
    REPORT.write_text(render_human_report(metrics), encoding="utf-8")
    return 0


def _check() -> int:
    if not all(path.exists() for path in (METRICS, RAW_REPORT, REPORT)):
        return 1
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    counts = metrics["qualification_seed_execution_counts"]
    counts_pass = bool(counts and all(value == 3 for value in counts.values()))
    return int(
        not counts_pass
        or RAW_REPORT.read_text(encoding="utf-8") != render_raw_report(metrics)
        or REPORT.read_text(encoding="utf-8") != render_human_report(metrics)
    )


def main() -> int:
    arguments = _arguments()
    return _run_once() if arguments.run_once else _check()


if __name__ == "__main__":
    raise SystemExit(main())
