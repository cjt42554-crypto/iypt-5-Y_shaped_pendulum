from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import ypendulum_hfv2


CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = CANDIDATE_ROOT.parents[2]


def _load_contract(name: str) -> dict:
    return json.loads((CANDIDATE_ROOT / "contracts" / name).read_text(encoding="utf-8"))


def test_candidate_package_imports_with_frozen_identity() -> None:
    assert ypendulum_hfv2.MODEL_ID == "HFV2-DISCRETE-CORD-RIGID-BOB-0.1-CANDIDATE"


def test_all_json_contracts_parse_and_share_model_identity() -> None:
    contract_names = [
        "acceptance_manifest.json",
        "baseline_sources.json",
        "model_identity.json",
        "rc1_characterization_case.json",
        "rc1_public_interface.json",
    ]
    contracts = [_load_contract(name) for name in contract_names]
    assert all(contract["schema"].startswith("YPS-HFV2-") for contract in contracts)
    assert _load_contract("model_identity.json")["model_id"] == ypendulum_hfv2.MODEL_ID


def test_formal_rc1_worktree_files_match_frozen_git_blobs() -> None:
    baseline = _load_contract("baseline_sources.json")
    for source in baseline["sources"]:
        path = REPOSITORY_ROOT / source["path"]
        actual = subprocess.run(
            ["git", "hash-object", str(path)],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert actual == source["git_blob_sha"], source["path"]


def test_characterization_contract_does_not_freeze_a_trajectory() -> None:
    case = _load_contract("rc1_characterization_case.json")
    assert case["contact_geometry_used"] is False
    assert case["trajectory_frozen_as_truth"] is False
    assert "trajectory" not in case["input"]
    canonical_input = json.dumps(case["input"], sort_keys=True).encode("utf-8")
    assert len(hashlib.sha256(canonical_input).hexdigest()) == 64
