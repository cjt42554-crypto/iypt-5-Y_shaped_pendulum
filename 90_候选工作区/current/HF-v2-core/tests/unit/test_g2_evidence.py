from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from ypendulum_hfv2.audit.g2_evidence import build_g2_evidence

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = json.loads(
    (CANDIDATE_ROOT / "contracts" / "g2_acceptance_manifest.json").read_text(
        encoding="utf-8"
    )
)


def test_manifest_driven_g2_evidence_recomputes_every_gate() -> None:
    evidence = build_g2_evidence(CANDIDATE_ROOT)
    assert evidence["status"] == ACCEPTANCE["pass_status"]
    assert evidence["allowed_claim"] == ACCEPTANCE["allowed_claim_on_pass"]
    assert all(evidence["gate_summary"].values())
    assert evidence["optimizer_success_used_as_gate"] is False
    assert len(evidence["y_anchor_meshes"]) == 3
    assert evidence["mesh_trend"]["status"] == "PASS"


def test_single_command_generates_complete_g2_json(tmp_path: Path) -> None:
    output = tmp_path / "g2_metrics.json"
    subprocess.run(
        [
            sys.executable,
            str(CANDIDATE_ROOT / "tools" / "generate_g2_evidence.py"),
            "--output",
            str(output),
        ],
        cwd=CANDIDATE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["status"] == ACCEPTANCE["pass_status"]
    assert evidence["architecture"]["unclassified_files"] == []


def test_committed_g2_evidence_hashes_match_current_sources_and_contracts() -> None:
    evidence = json.loads(
        (CANDIDATE_ROOT / "reports" / "g2_metrics.json").read_text(encoding="utf-8")
    )
    binding = evidence["evidence_binding"]
    paths = {
        binding["acceptance_manifest"]: binding["acceptance_manifest_sha256"],
        binding["module_manifest"]: binding["module_manifest_sha256"],
        binding["frozen_protocol"]: binding["frozen_protocol_sha256"],
        binding["model_identity"]: binding["model_identity_sha256"],
        binding["evidence_generator"]: binding["evidence_generator_sha256"],
        binding["pyproject"]: binding["pyproject_sha256"],
        binding["readme"]: binding["readme_sha256"],
        **binding["source_sha256"],
        **binding["test_sha256"],
    }
    for relative, expected_sha256 in paths.items():
        actual = hashlib.sha256((CANDIDATE_ROOT / relative).read_bytes()).hexdigest()
        assert actual == expected_sha256, relative
