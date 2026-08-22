#!/usr/bin/env python3
"""Convenience wrapper for the structural finite-window evidence audit."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(
        ROOT
        / "02_第一性原理高保真模拟器"
        / "Y-Pendulum-Simulator-v1.0.0-rc1"
        / "src"
    ),
)

from ypendulum.scientific_revision.structural_audit import audit_structural_results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    arguments = parser.parse_args()
    audit_structural_results(arguments.input, arguments.output)
    print(Path(arguments.output).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
