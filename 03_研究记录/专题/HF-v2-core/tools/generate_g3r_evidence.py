#!/usr/bin/env python3
"""Generate or verify the frozen G3R evidence and Markdown report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ypendulum_hfv2_p3r.evidence import build_g3r_evidence, report_for_metrics  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "g3r_metrics.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "reports" / "G3R_REPORT.md",
    )
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    evidence = build_g3r_evidence(ROOT)
    metrics, report = report_for_metrics(evidence)
    report_bytes = report.encode("utf-8")
    if arguments.check:
        if not arguments.output.exists() or not arguments.report.exists():
            return 1
        return int(
            arguments.output.read_bytes() != metrics
            or arguments.report.read_bytes() != report_bytes
        )
    arguments.output.write_bytes(metrics)
    arguments.report.write_bytes(report_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
