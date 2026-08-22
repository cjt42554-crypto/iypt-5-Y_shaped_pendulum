#!/usr/bin/env python3
"""Reproducible local performance probes; never extrapolates timed-out cases."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("A0 analytic", "configs/examples/analytic_3to2.yaml", 60),
    ("A1 torus", "configs/examples/ideal_3to2.yaml", 60),
    ("H1 quick", "configs/examples/full_quick_3to2.yaml", 180),
    ("H1 Newmark quick", "configs/examples/full_quick_newmark_3to2.yaml", 180),
]


def main() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    rows = []
    for name, config, timeout in CASES:
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "ypendulum.cli", "simulate", config],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
            rows.append(
                {
                    "name": name,
                    "config": config,
                    "wall_seconds": time.perf_counter() - start,
                    "returncode": proc.returncode,
                    "timed_out": False,
                    "stdout_tail": proc.stdout[-1000:],
                    "stderr_tail": proc.stderr[-1000:],
                }
            )
        except subprocess.TimeoutExpired:
            rows.append(
                {
                    "name": name,
                    "config": config,
                    "wall_seconds": time.perf_counter() - start,
                    "timed_out": True,
                }
            )
    payload = {
        "python": sys.version,
        "platform": platform.platform(),
        "cases": rows,
    }
    target = ROOT / "benchmarks/performance_report.json"
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
