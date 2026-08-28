#!/usr/bin/env python3
"""Generate or verify frozen G3R2 metrics and both Markdown reports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ypendulum_hfv2_p3r2.evidence import (  # noqa: E402
    build_g3r2_evidence,
    report_for_metrics,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "g3r2_metrics.json",
    )
    parser.add_argument(
        "--raw-report",
        type=Path,
        default=ROOT / "reports" / "G3R2_REPORT_RAW.md",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "reports" / "G3R2_REPORT.md",
    )
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    evidence = build_g3r2_evidence(ROOT)
    metrics, report = report_for_metrics(evidence)
    report_bytes = report.encode("utf-8")
    if arguments.check:
        paths = (arguments.output, arguments.raw_report, arguments.report)
        if not all(path.exists() for path in paths):
            return 1
        return int(
            arguments.output.read_bytes() != metrics
            or arguments.raw_report.read_bytes() != report_bytes
            or arguments.report.read_bytes() != report_bytes
        )
    arguments.output.write_bytes(metrics)
    arguments.raw_report.write_bytes(report_bytes)
    arguments.report.write_bytes(report_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
