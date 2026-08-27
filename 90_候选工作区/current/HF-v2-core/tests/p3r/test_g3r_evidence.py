from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from ypendulum_hfv2_p3r.evidence import build_g3r_evidence

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads(
    (CANDIDATE_ROOT / "contracts" / "p3r_acceptance_manifest.json").read_text(
        encoding="utf-8"
    )
)


@lru_cache(maxsize=1)
def _evidence() -> dict[str, object]:
    return build_g3r_evidence(CANDIDATE_ROOT)


def test_manifest_driven_g3r_evidence_preserves_the_frozen_no_go() -> None:
    evidence = _evidence()
    assert evidence["status"] == MANIFEST["fail_status"]
    assert evidence["gate_summary"] == {
        "contract_and_frozen_source_binding": True,
        "exact_runtime": True,
        "architecture": True,
        "benchmark_identity_binding_before_target": True,
        "observed_symmetric_regression_before_target": True,
        "unobserved_qualification_target": False,
    }
    target = evidence["qualification_target"]
    assert target["completed_seed_count"] == 3
    assert target["qualified_seed_count"] == 2
    failed = [seed for seed in target["seeds"] if not seed["qualified"]]
    assert [seed["seed_id"] for seed in failed] == ["target_seed_02_counter_skew"]
    assert failed[0]["audits"]["kkt"]["stationarity_residual_N"] > 1.0e-8


def test_committed_g3r_evidence_binding_and_historical_g3_hashes_match() -> None:
    evidence = json.loads(
        (CANDIDATE_ROOT / "reports" / "g3r_metrics.json").read_text(encoding="utf-8")
    )
    for relative, expected_sha256 in evidence["evidence_binding"].items():
        actual = hashlib.sha256((CANDIDATE_ROOT / relative).read_bytes()).hexdigest()
        assert actual == expected_sha256, relative
    historical = hashlib.sha256(
        (CANDIDATE_ROOT / "reports" / "g3_metrics.json").read_bytes()
    ).hexdigest()
    assert historical == MANIFEST["historical_g3_metrics_sha256"]


def test_committed_g3r_evidence_and_report_are_reproducible() -> None:
    subprocess.run(
        [
            sys.executable,
            str(CANDIDATE_ROOT / "tools" / "generate_g3r_evidence.py"),
            "--check",
            "--report",
            str(CANDIDATE_ROOT / "reports" / "G3R_REPORT_RAW.md"),
        ],
        cwd=CANDIDATE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    metrics = CANDIDATE_ROOT / "reports" / "g3r_metrics.json"
    report = (CANDIDATE_ROOT / "reports" / "G3R_REPORT.md").read_text(encoding="utf-8")
    assert MANIFEST["fail_status"] in report
    assert hashlib.sha256(metrics.read_bytes()).hexdigest() in report
    assert "1.1056080207858155e-8 N" in report
