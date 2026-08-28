from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from ypendulum_hfv2_p3r2.evidence import build_g3r2_evidence

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads(
    (CANDIDATE_ROOT / "contracts" / "p3r2_acceptance_manifest.json").read_text(
        encoding="utf-8"
    )
)


@lru_cache(maxsize=1)
def _evidence() -> dict[str, object]:
    return build_g3r2_evidence(CANDIDATE_ROOT)


def test_manifest_driven_g3r2_evidence_applies_all_or_nothing_gate() -> None:
    evidence = _evidence()
    all_gates = all(evidence["gate_summary"].values())
    expected = MANIFEST["pass_status"] if all_gates else MANIFEST["fail_status"]
    assert evidence["status"] == expected
    assert evidence["mandatory_stop"] == "G3R2_PRO_REVIEW"
    assert evidence["historical_g3_status_preserved"] == (
        "NO_GO_G3_STATIC_CONTACT_ALGORITHM"
    )
    assert evidence["historical_g3r_status_preserved"] == (
        "NO_GO_G3R_STATIC_CONTACT_ALGORITHM"
    )
    assert evidence["observed_p3r_35_degree_regression"]["seed_count"] == 3
    assert [target["seed_count"] for target in evidence["qualification_targets"]] == [
        3,
        3,
    ]


def test_committed_g3r2_evidence_binding_matches_current_inputs() -> None:
    evidence = json.loads(
        (CANDIDATE_ROOT / "reports" / "g3r2_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    for relative, expected in evidence["evidence_binding"].items():
        actual = hashlib.sha256((CANDIDATE_ROOT / relative).read_bytes()).hexdigest()
        assert actual == expected, relative
    assert hashlib.sha256(
        (CANDIDATE_ROOT / "reports" / "g3_metrics.json").read_bytes()
    ).hexdigest() == MANIFEST["historical_artifact_sha256"]["reports/g3_metrics.json"]
    assert hashlib.sha256(
        (CANDIDATE_ROOT / "reports" / "g3r_metrics.json").read_bytes()
    ).hexdigest() == MANIFEST["historical_artifact_sha256"]["reports/g3r_metrics.json"]


def test_committed_g3r2_evidence_and_reports_are_reproducible() -> None:
    subprocess.run(
        [
            sys.executable,
            str(CANDIDATE_ROOT / "tools" / "generate_g3r2_evidence.py"),
            "--check",
        ],
        cwd=CANDIDATE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    metrics = CANDIDATE_ROOT / "reports" / "g3r2_metrics.json"
    report = (CANDIDATE_ROOT / "reports" / "G3R2_REPORT.md").read_text(
        encoding="utf-8"
    )
    assert hashlib.sha256(metrics.read_bytes()).hexdigest() in report
    assert "G3R2_PRO_REVIEW" in report
