from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from ypendulum_hfv2.audit.evidence import build_g1r_evidence

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = json.loads(
    (CANDIDATE_ROOT / "contracts" / "g1r_acceptance_manifest.json").read_text(encoding="utf-8")
)


def test_manifest_driven_evidence_recomputes_every_local_gate() -> None:
    evidence = build_g1r_evidence(CANDIDATE_ROOT)
    assert evidence["status"] == "PASS_G1R_LOCAL_MODEL_CONTRACT_ONLY"
    assert evidence["allowed_claim"] == ACCEPTANCE["allowed_claim"]
    assert evidence["axial_gradient"]["final_relative_error"] <= ACCEPTANCE[
        "finite_difference"
    ]["final_relative_error_max"]
    for case in evidence["bending_gradient"].values():
        assert case["final_relative_error"] <= ACCEPTANCE["finite_difference"][
            "final_relative_error_max"
        ]
        assert case["strict_decrease_interval_indices"] is not None


def test_committed_evidence_hashes_match_current_source_and_contracts() -> None:
    evidence = json.loads(
        (CANDIDATE_ROOT / "reports" / "g1r_metrics.json").read_text(encoding="utf-8")
    )
    binding = evidence["evidence_binding"]
    paths = {
        binding["acceptance_manifest"]: binding["acceptance_manifest_sha256"],
        binding["module_manifest"]: binding["module_manifest_sha256"],
        binding["model_identity"]: binding["model_identity_sha256"],
        binding["evidence_generator"]: binding["evidence_generator_sha256"],
        **binding["source_sha256"],
        **binding["historical_g1_artifact_sha256"],
    }
    for relative, expected_sha256 in paths.items():
        actual = hashlib.sha256((CANDIDATE_ROOT / relative).read_bytes()).hexdigest()
        assert actual == expected_sha256, relative


def test_single_command_generates_complete_json(tmp_path: Path) -> None:
    output = tmp_path / "g1r_metrics.json"
    subprocess.run(
        [
            sys.executable,
            str(CANDIDATE_ROOT / "tools" / "generate_g1r_evidence.py"),
            "--output",
            str(output),
        ],
        cwd=CANDIDATE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["status"] == "PASS_G1R_LOCAL_MODEL_CONTRACT_ONLY"
    assert evidence["architecture"]["unclassified_files"] == []
