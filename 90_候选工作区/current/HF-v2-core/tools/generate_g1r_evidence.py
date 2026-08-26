#!/usr/bin/env python3
"""Generate or verify the deterministic HF-v2 G1R evidence JSON."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CANDIDATE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CANDIDATE_ROOT / "src"))

from ypendulum_hfv2.audit.evidence import build_g1r_evidence, canonical_evidence_text  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="compare with the committed report")
    parser.add_argument("--stdout", action="store_true", help="print instead of writing")
    parser.add_argument("--output", type=Path, help="write to an alternate path")
    arguments = parser.parse_args()
    if sum((arguments.check, arguments.stdout, arguments.output is not None)) > 1:
        parser.error("--check, --stdout and --output are mutually exclusive")

    text = canonical_evidence_text(build_g1r_evidence(CANDIDATE_ROOT))
    report_path = arguments.output or CANDIDATE_ROOT / "reports" / "g1r_metrics.json"
    if arguments.check:
        if not report_path.exists() or report_path.read_text(encoding="utf-8") != text:
            print(
                "G1R evidence differs from reports/g1r_metrics.json; regenerate it.",
                file=sys.stderr,
            )
            return 1
        print("G1R evidence check: PASS")
        return 0
    if arguments.stdout:
        sys.stdout.write(text)
        return 0
    report_path.write_text(text, encoding="utf-8")
    print(f"Wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
