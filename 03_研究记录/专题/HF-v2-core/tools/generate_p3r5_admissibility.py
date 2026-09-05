#!/usr/bin/env python3
"""Execute once or statically verify the P3R5 holdout admissibility campaign."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ypendulum_hfv2_p3r5.admissibility import (  # noqa: E402
    render_admissibility_report,
    run_admissibility_campaign,
)
from ypendulum_hfv2_p3r5.attempt_ledger import (  # noqa: E402
    AttemptLedger,
    load_records,
    startup_record,
)
from ypendulum_hfv2_p3r5.evidence_support import (  # noqa: E402
    contract_binding,
    git_head,
    git_status,
    load_json,
    sha256,
)

METRICS = ROOT / "reports/p3r5_admissibility_metrics.json"
SELECTION = ROOT / "contracts/p3r5_admissibility_selection.json"
REPORT = ROOT / "reports/P3R5_ADMISSIBILITY_REPORT.md"
LEDGER = ROOT / "reports/p3r5_attempt_ledger.jsonl"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run-once", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--expected-protocol-sha256")
    parser.add_argument("--expected-implementation-binding-sha256")
    parser.add_argument("--expected-holdout-cards-sha256")
    parser.add_argument("--expected-acceptance-manifest-sha256")
    return parser.parse_args()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _expected_hashes(arguments: argparse.Namespace) -> dict[Path, str]:
    values = {
        ROOT / "contracts/P3R5_FROZEN_PROTOCOL.md": arguments.expected_protocol_sha256,
        ROOT / "contracts/p3r5_implementation_binding.json": (
            arguments.expected_implementation_binding_sha256
        ),
        ROOT / "contracts/p3r5_holdout_cards.json": arguments.expected_holdout_cards_sha256,
        ROOT / "contracts/p3r5_acceptance_manifest.json": (
            arguments.expected_acceptance_manifest_sha256
        ),
    }
    for value in values.values():
        if (
            value is None
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError("P3R5 run-once requires four lowercase SHA-256 arguments.")
    return values


def _run_once(arguments: argparse.Namespace) -> int:
    outputs = (METRICS, SELECTION, REPORT, LEDGER)
    if any(path.exists() for path in outputs):
        raise RuntimeError("P3R5 one-shot output or attempt ledger exists; refusing to rerun.")
    status_before = git_status(REPOSITORY_ROOT)
    if status_before.strip():
        raise RuntimeError("P3R5 admissibility must start from a clean committed tree.")
    expected = _expected_hashes(arguments)
    started_at = datetime.now().astimezone().isoformat(timespec="microseconds")
    head = git_head(REPOSITORY_ROOT)
    ledger = AttemptLedger.create(
        LEDGER,
        startup_record(
            started_at=started_at,
            repository_head=head,
            working_tree_status=status_before,
            expected_protocol_sha256=expected[ROOT / "contracts/P3R5_FROZEN_PROTOCOL.md"],
            expected_implementation_binding_sha256=expected[
                ROOT / "contracts/p3r5_implementation_binding.json"
            ],
            expected_holdout_cards_sha256=expected[ROOT / "contracts/p3r5_holdout_cards.json"],
            expected_acceptance_manifest_sha256=expected[
                ROOT / "contracts/p3r5_acceptance_manifest.json"
            ],
        ),
    )
    try:
        actual = {path: sha256(path) for path in expected}
        if any(actual[path] != expected[path] for path in expected):
            raise RuntimeError("P3R5 startup hash binding failed after ledger creation.")
        manifest = load_json(ROOT / "contracts/p3r5_acceptance_manifest.json")
        predecessor = load_json(ROOT / "contracts/p3r4_acceptance_manifest.json")
        holdout = load_json(ROOT / "contracts/p3r5_holdout_cards.json")
        binding = contract_binding(ROOT, manifest, required_stage="holdout")
        if binding["status"] != "PASS" or head != binding["holdout_freeze_commit"]:
            raise RuntimeError("P3R5 holdout commit order or hash binding failed.")
        ledger.checkpoint(
            "STARTUP_HASH_BINDINGS_AND_HOLDOUT_FILE_VERIFIED",
            actual_sha256={str(path.relative_to(ROOT)): value for path, value in actual.items()},
            holdout_file_open_count=1,
            binding_status=binding["status"],
        )
        metrics, selection, report = run_admissibility_campaign(
            ROOT,
            manifest,
            predecessor,
            holdout,
            ledger,
            implementation_commit=str(binding["implementation_commit"]),
            holdout_freeze_commit=str(binding["holdout_freeze_commit"]),
        )
        _atomic_write(METRICS, _json_bytes(metrics))
        _atomic_write(SELECTION, _json_bytes(selection))
        _atomic_write(REPORT, report.encode("utf-8"))
    except BaseException as error:
        ledger.checkpoint(
            "ATTEMPT_ABORTED_LEDGER_PRESERVED",
            failure_type=type(error).__name__,
            failure_message=str(error),
            self_rerun_forbidden=True,
        )
        raise
    return 0


def _check() -> int:
    if not all(path.exists() for path in (METRICS, SELECTION, REPORT, LEDGER)):
        return 1
    metrics = load_json(METRICS)
    selection = load_json(SELECTION)
    records = load_records(LEDGER)
    outcomes = metrics["outcomes"]
    counts_pass = bool(
        metrics["input_assembly_run_count"]
        == sum(item["input_assembly_execution_count"] for item in outcomes)
        and metrics["reference_construction_run_count"]
        == sum(item["reference_construction_execution_count"] for item in outcomes)
        and metrics["target_admissibility_run_count"]
        == sum(item["target_admissibility_execution_count"] for item in outcomes)
        and metrics["second_order_run_count"]
        == sum(item["second_order_execution_count"] for item in outcomes)
        and metrics["manifold_neighborhood_run_count"]
        == sum(item["manifold_neighborhood_execution_count"] for item in outcomes)
        and metrics["target_freeze_run_count"] == 0
        and metrics["qualification_seed_run_count"] == 0
    )
    ledger_pass = bool(
        records
        and records[0]["event"] == "ATTEMPT_STARTED_BEFORE_HOLDOUT_FILE_OPEN"
        and records[0]["attempt_number"] == 1
        and records[-1]["event"] == "ADMISSIBILITY_CAMPAIGN_CLOSED"
        and metrics["attempt_ledger_sha256"] == sha256(LEDGER)
    )
    selection_pass = bool(
        metrics["selected_holdout_ids"] == selection["selected_holdout_ids"]
        and metrics["status"] == selection["status"]
        and selection["target_freeze_generated"] is False
        and selection["qualification_seed_results_observed_before_separate_target_freeze"] == 0
        and selection["qualification_seed_execution_counts_before_separate_target_freeze"] == {}
    )
    report_pass = REPORT.read_bytes() == render_admissibility_report(metrics).encode("utf-8")
    return int(not counts_pass or not ledger_pass or not selection_pass or not report_pass)


def main() -> int:
    arguments = _arguments()
    return _run_once(arguments) if arguments.run_once else _check()


if __name__ == "__main__":
    raise SystemExit(main())
