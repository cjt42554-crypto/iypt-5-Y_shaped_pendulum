#!/usr/bin/env python3
"""Freeze P3R5 qualification targets after committed complete admissibility."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ypendulum_hfv2_p3r5.target_freeze import generate_target_freeze  # noqa: E402

OUTPUT = ROOT / "contracts/p3r5_qualification_targets.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true")
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


def _freeze() -> int:
    if OUTPUT.exists():
        raise RuntimeError("P3R5 target freeze already exists; refusing to regenerate.")
    _atomic_write(OUTPUT, _json_bytes(generate_target_freeze(ROOT)))
    return 0


def _check() -> int:
    if not OUTPUT.exists():
        return 1
    target = json.loads(OUTPUT.read_text(encoding="utf-8"))
    counts = target["qualification_seed_execution_counts_before_target_freeze"]
    return int(
        target["status"] != "TARGETS_AND_SOLVER_INITIAL_GUESSES_FROZEN"
        or len(target["qualification_targets"]) != 2
        or target["qualification_seed_results_observed_before_target_freeze"] != 0
        or not counts
        or any(value != 0 for value in counts.values())
    )


def main() -> int:
    arguments = _arguments()
    return _freeze() if arguments.freeze else _check()


if __name__ == "__main__":
    raise SystemExit(main())
