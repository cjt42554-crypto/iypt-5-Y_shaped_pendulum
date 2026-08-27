from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from ypendulum_hfv2.audit.g3_evidence import build_g3_evidence

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = json.loads(
    (CANDIDATE_ROOT / "contracts" / "p3_acceptance_manifest.json").read_text(encoding="utf-8")
)


@lru_cache(maxsize=1)
def _evidence() -> dict[str, object]:
    return build_g3_evidence(CANDIDATE_ROOT)


def test_manifest_driven_g3_evidence_preserves_the_frozen_no_go() -> None:
    evidence = _evidence()
    assert evidence["status"] == ACCEPTANCE["fail_status"]
    gates = evidence["gate_summary"]
    assert isinstance(gates, dict)
    assert gates == {
        "contract_and_formal_source_binding": True,
        "exact_runtime": True,
        "small_benchmarks_before_target": True,
        "architecture": True,
        "p2_regression": True,
        "frozen_target": False,
    }
    target = evidence["target"]
    assert isinstance(target, dict)
    assert target["completed_seed_count"] == 1
    assert target["qualified_seed_count"] == 0
    seeds = target["seeds"]
    assert isinstance(seeds, list)
    assert [seed["execution_status"] for seed in seeds] == [
        "COMPLETED",
        "FAIL_CLOSED_CONTACT_GEOMETRY",
        "FAIL_CLOSED_CONTACT_GEOMETRY",
    ]
    analytic = seeds[0]
    assert analytic["gap_active_ids"] != ACCEPTANCE["target_case"]["expected_active_constraint_ids"]
    assert analytic["supported_ids"] == ACCEPTANCE["target_case"]["expected_active_constraint_ids"]
    assert analytic["kkt"]["active_constraint_rank"] == 3


def test_single_command_generates_json_and_report(tmp_path: Path) -> None:
    metrics = tmp_path / "g3_metrics.json"
    report = tmp_path / "G3_REPORT.md"
    subprocess.run(
        [
            sys.executable,
            str(CANDIDATE_ROOT / "tools" / "generate_g3_evidence.py"),
            "--output",
            str(metrics),
            "--report",
            str(report),
        ],
        cwd=CANDIDATE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    evidence = json.loads(metrics.read_text(encoding="utf-8"))
    assert evidence["status"] == ACCEPTANCE["fail_status"]
    report_text = report.read_text(encoding="utf-8")
    assert "NO_GO_G3_STATIC_CONTACT_ALGORITHM" in report_text
    assert hashlib.sha256(metrics.read_bytes()).hexdigest() in report_text


def test_committed_g3_evidence_hashes_match_current_inputs() -> None:
    evidence = json.loads(
        (CANDIDATE_ROOT / "reports" / "g3_metrics.json").read_text(encoding="utf-8")
    )
    binding = evidence["evidence_binding"]
    paths = dict(binding["named_paths"])
    paths.update(binding["source_sha256"])
    paths.update(binding["test_sha256"])
    for relative, expected_sha256 in paths.items():
        actual = hashlib.sha256((CANDIDATE_ROOT / relative).read_bytes()).hexdigest()
        assert actual == expected_sha256, relative
