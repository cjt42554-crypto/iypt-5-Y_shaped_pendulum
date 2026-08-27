from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = CANDIDATE_ROOT.parents[2]
G1R_IMPLEMENTATION_COMMIT = "55cb5db754adde63af77363b3d2d59aa4c9a31d9"
G2_ACCEPTANCE = json.loads(
    (CANDIDATE_ROOT / "contracts" / "g2_acceptance_manifest.json").read_text(encoding="utf-8")
)


def test_pro_accepted_g1r_artifacts_remain_byte_identical() -> None:
    historical = G2_ACCEPTANCE["historical_g1r"]
    for path_key, hash_key in (
        ("metrics_path", "metrics_sha256"),
        ("report_path", "report_sha256"),
    ):
        path = CANDIDATE_ROOT / historical[path_key]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == historical[hash_key]


def _historical_bytes(commit: str, relative: str) -> bytes:
    repository_path = (CANDIDATE_ROOT / relative).relative_to(REPOSITORY_ROOT)
    return subprocess.run(
        ["git", "show", f"{commit}:{repository_path.as_posix()}"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def test_historical_g1r_binding_matches_the_accepted_commit() -> None:
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
        actual = hashlib.sha256(_historical_bytes(G1R_IMPLEMENTATION_COMMIT, relative)).hexdigest()
        assert actual == expected_sha256, relative


def test_historical_g1r_is_not_claimed_as_current_p2_recomputation() -> None:
    assert G2_ACCEPTANCE["historical_g1r"]["treatment"] == (
        "immutable_historical_artifact_not_recomputed_against_p2_source"
    )
    evidence = json.loads(
        (CANDIDATE_ROOT / "reports" / "g1r_metrics.json").read_text(encoding="utf-8")
    )
    assert evidence["status"] == "PASS_G1R_LOCAL_MODEL_CONTRACT_ONLY"
