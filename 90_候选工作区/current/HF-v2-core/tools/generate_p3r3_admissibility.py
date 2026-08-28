#!/usr/bin/env python3
"""Execute once or statically verify the P3R3 admissibility campaign."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ypendulum_hfv2_p3r3.admissibility import (  # noqa: E402
    render_admissibility_report,
    run_admissibility_campaign,
)

METRICS = ROOT / "reports/p3r3_admissibility_metrics.json"
TARGETS = ROOT / "contracts/p3r3_qualification_targets.json"
REPORT = ROOT / "reports/P3R3_ADMISSIBILITY_REPORT.md"
PARTIAL = ROOT / "reports/p3r3_admissibility_metrics.json.partial"


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


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _repository_clean() -> bool:
    output = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return not output.strip()


def _checkpoint(outcomes: list[dict[str, object]]) -> None:
    _atomic_write(
        PARTIAL,
        _json_bytes(
            {
                "schema": "YPS-HFV2-P3R3-ADMISSIBILITY-PARTIAL-1.0",
                "do_not_rerun_completed_designs": True,
                "completed_design_count": len(outcomes),
                "outcomes": outcomes,
            }
        ),
    )


def _run_once() -> int:
    outputs = (METRICS, TARGETS, REPORT, PARTIAL)
    if any(path.exists() for path in outputs):
        raise RuntimeError(
            "P3R3 one-shot output or partial ledger already exists; refusing to rerun."
        )
    if not _repository_clean():
        raise RuntimeError("P3R3 admissibility must start from a clean committed tree.")
    metrics, targets, report = run_admissibility_campaign(
        ROOT,
        checkpoint=_checkpoint,
    )
    _atomic_write(METRICS, _json_bytes(metrics))
    _atomic_write(TARGETS, _json_bytes(targets))
    _atomic_write(REPORT, report.encode("utf-8"))
    PARTIAL.unlink()
    return 0


def _check() -> int:
    if PARTIAL.exists() or not all(path.exists() for path in (METRICS, TARGETS, REPORT)):
        return 1
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    report = render_admissibility_report(metrics).encode("utf-8")
    counts_pass = bool(
        metrics["reference_discovery_run_count"] == 6
        and metrics["qualification_seed_run_count"] == 0
        and all(
            item["reference_discovery_execution_count"] == 1
            and item["qualification_seed_execution_count"] == 0
            for item in metrics["outcomes"]
        )
    )
    selection_pass = metrics["selected_design_ids"] == targets["selected_design_ids"]
    target_zero = bool(
        targets["qualification_seed_results_observed_before_target_freeze"] == 0
        and all(
            value == 0
            for value in targets[
                "qualification_seed_execution_counts_before_target_freeze"
            ].values()
        )
    )
    return int(
        not counts_pass or not selection_pass or not target_zero or REPORT.read_bytes() != report
    )


def main() -> int:
    arguments = _arguments()
    return _run_once() if arguments.run_once else _check()


if __name__ == "__main__":
    raise SystemExit(main())
