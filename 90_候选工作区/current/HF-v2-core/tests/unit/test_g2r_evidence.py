from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from ypendulum_hfv2.audit.g2r_evidence import build_g2r_evidence

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = CANDIDATE_ROOT.parents[2]
G2R_IMPLEMENTATION_COMMIT = "ff02beed22d3ab006114ebf29e64a17c88d07196"
ACCEPTANCE = json.loads(
    (CANDIDATE_ROOT / "contracts" / "g2r_acceptance_manifest.json").read_text(encoding="utf-8")
)


def _historical_bytes(relative: str) -> bytes:
    repository_path = (CANDIDATE_ROOT / relative).relative_to(REPOSITORY_ROOT)
    return subprocess.run(
        ["git", "show", f"{G2R_IMPLEMENTATION_COMMIT}:{repository_path.as_posix()}"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def test_historical_g2r_builder_fails_only_the_evolved_architecture_scope() -> None:
    evidence = build_g2r_evidence(CANDIDATE_ROOT)
    assert evidence["status"] == ACCEPTANCE["fail_status"]
    assert evidence["allowed_claim"] == "NO_GO"
    failed = [name for name, passed in evidence["gate_summary"].items() if not passed]
    assert failed == ["architecture"]
    assert evidence["architecture"]["unclassified_files"] == [
        "audit/contact.py",
        "audit/g3_cases.py",
        "audit/g3_evidence.py",
        "contact/__init__.py",
        "contact/contracts.py",
        "contact/geometry.py",
        "contact/registration.py",
        "statics/contact_assembly.py",
        "statics/contact_solver.py",
    ]
    assert evidence["optimizer_success_used_as_gate"] is False
    assert len(evidence["y_anchor_meshes"]) == 3
    assert evidence["full_material_centerline_trend"]["status"] == "PASS"
    assert evidence["historical_g2_equivalence"]["status"] == "PASS"


def test_historical_g2r_command_reports_current_scope_evolution(tmp_path: Path) -> None:
    output = tmp_path / "g2r_metrics.json"
    subprocess.run(
        [
            sys.executable,
            str(CANDIDATE_ROOT / "tools" / "generate_g2r_evidence.py"),
            "--output",
            str(output),
        ],
        cwd=CANDIDATE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["status"] == ACCEPTANCE["fail_status"]
    assert evidence["architecture"]["unclassified_files"] != []
    assert evidence["historical_g2_equivalence"]["status"] == "PASS"


def test_committed_g2r_evidence_hashes_match_the_accepted_commit() -> None:
    evidence = json.loads(
        (CANDIDATE_ROOT / "reports" / "g2r_metrics.json").read_text(encoding="utf-8")
    )
    binding = evidence["evidence_binding"]
    paths = {document["path"]: document["sha256"] for document in binding["paths"].values()}
    paths.update(binding["source_sha256"])
    paths.update(binding["test_sha256"])
    for relative, expected_sha256 in paths.items():
        actual = hashlib.sha256(_historical_bytes(relative)).hexdigest()
        assert actual == expected_sha256, relative
