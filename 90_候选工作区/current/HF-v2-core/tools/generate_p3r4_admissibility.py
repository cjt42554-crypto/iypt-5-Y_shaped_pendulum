#!/usr/bin/env python3
"""Execute once or statically verify the P3R4 admissibility campaign."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ypendulum_hfv2_p3r4.admissibility import (  # noqa: E402
    render_admissibility_report,
    run_admissibility_campaign,
)

METRICS = ROOT / "reports/p3r4_admissibility_metrics.json"
SELECTION = ROOT / "contracts/p3r4_admissibility_selection.json"
REPORT = ROOT / "reports/P3R4_ADMISSIBILITY_REPORT.md"
PARTIAL = ROOT / "reports/p3r4_admissibility_metrics.json.partial"


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
                "schema": "YPS-HFV2-P3R4-ADMISSIBILITY-PARTIAL-1.0",
                "do_not_rerun_completed_designs": True,
                "completed_design_count": len(outcomes),
                "outcomes": outcomes,
            }
        ),
    )


def _run_once() -> int:
    outputs = (METRICS, SELECTION, REPORT, PARTIAL)
    if any(path.exists() for path in outputs):
        raise RuntimeError(
            "P3R4 one-shot output or partial ledger already exists; refusing to rerun."
        )
    if not _repository_clean():
        raise RuntimeError("P3R4 admissibility must start from a clean committed tree.")
    metrics, selection, report = run_admissibility_campaign(
        ROOT,
        checkpoint=_checkpoint,
    )
    _atomic_write(METRICS, _json_bytes(metrics))
    _atomic_write(SELECTION, _json_bytes(selection))
    _atomic_write(REPORT, report.encode("utf-8"))
    PARTIAL.unlink()
    return 0


def _check() -> int:
    if PARTIAL.exists() or not all(path.exists() for path in (METRICS, SELECTION, REPORT)):
        return 1
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    report = render_admissibility_report(metrics).encode("utf-8")
    outcomes = metrics["outcomes"]
    counts_pass = bool(
        metrics["design_card_attempt_count"] == 8
        and metrics["input_assembly_validation_run_count"] == 8
        and len(outcomes) == 8
        and metrics["reference_discovery_run_count"]
        == sum(item["reference_discovery_execution_count"] for item in outcomes)
        and metrics["target_freeze_run_count"] == 0
        and metrics["qualification_seed_run_count"] == 0
        and all(
            item["input_assembly_validation_execution_count"] == 1
            and item["reference_discovery_execution_count"] in (0, 1)
            and item["qualification_seed_execution_count"] == 0
            for item in outcomes
        )
    )
    selection_pass = bool(
        metrics["selected_design_ids"] == selection["selected_design_ids"]
        and selection["all_design_cards_executed_exactly_once"] is True
        and selection["target_freeze_generated"] is False
        and selection["qualification_seed_results_observed_before_separate_target_freeze"] == 0
        and selection["qualification_seed_execution_counts_before_separate_target_freeze"] == {}
    )
    return int(not counts_pass or not selection_pass or REPORT.read_bytes() != report)


def main() -> int:
    arguments = _arguments()
    return _run_once() if arguments.run_once else _check()


if __name__ == "__main__":
    raise SystemExit(main())
