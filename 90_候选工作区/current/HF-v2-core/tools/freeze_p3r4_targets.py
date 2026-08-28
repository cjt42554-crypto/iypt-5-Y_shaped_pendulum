#!/usr/bin/env python3
"""Freeze P3R4 targets and solver initial guesses after admissibility commit."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ypendulum_hfv2_p3r4.evidence_support import sha256  # noqa: E402
from ypendulum_hfv2_p3r4.target_freeze import generate_target_freeze  # noqa: E402

TARGETS = ROOT / "contracts/p3r4_qualification_targets.json"
METRICS = ROOT / "reports/p3r4_admissibility_metrics.json"
SELECTION = ROOT / "contracts/p3r4_admissibility_selection.json"


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
    if TARGETS.exists():
        raise RuntimeError("P3R4 target freeze already exists; refusing to regenerate it.")
    if not _repository_clean():
        raise RuntimeError("P3R4 target freeze must start from a clean committed tree.")
    target = generate_target_freeze(ROOT)
    temporary = TARGETS.with_name(TARGETS.name + ".tmp")
    temporary.write_bytes(_json_bytes(target))
    temporary.replace(TARGETS)
    return 0


def _check() -> int:
    if not TARGETS.exists() or not METRICS.exists() or not SELECTION.exists():
        return 1
    target = json.loads(TARGETS.read_text(encoding="utf-8"))
    counts = target["qualification_seed_execution_counts_before_target_freeze"]
    return int(
        target["status"] != "TARGETS_AND_SOLVER_INITIAL_GUESSES_FROZEN"
        or target["admissibility_metrics_sha256"] != sha256(METRICS)
        or target["admissibility_selection_sha256"] != sha256(SELECTION)
        or target["qualification_seed_results_observed_before_target_freeze"] != 0
        or len(target["qualification_targets"]) != 2
        or not counts
        or any(value != 0 for value in counts.values())
        or any(
            len(item["deterministic_solver_initial_guesses"]) != 3
            for item in target["qualification_targets"]
        )
    )


def main() -> int:
    arguments = _arguments()
    return _run_once() if arguments.run_once else _check()


if __name__ == "__main__":
    raise SystemExit(main())
