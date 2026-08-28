from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ypendulum_hfv2_p3r3 import (
    P3R3_COMPOSITE_ALGORITHM_ID,
    P3R3_CONTACT_MODEL_ID,
    P3R3_DUAL_CERTIFIER_ID,
    P3R3_LOCAL_BASIN_ID,
    P3R3_RESTORATION_JACOBIAN_ID,
    P3R3_TARGET_ADMISSIBILITY_ID,
)

ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _sha256(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def test_prefreeze_contract_identities_and_zero_result_counts() -> None:
    manifest = _load("contracts/p3r3_acceptance_manifest.json")
    design = _load("contracts/p3r3_design_cards.json")
    assert manifest["contact_model_id"] == P3R3_CONTACT_MODEL_ID
    assert manifest["composite_algorithm_identity"] == P3R3_COMPOSITE_ALGORITHM_ID
    assert manifest["target_admissibility_identity"] == P3R3_TARGET_ADMISSIBILITY_ID
    assert manifest["dual_certifier_identity"] == P3R3_DUAL_CERTIFIER_ID
    assert manifest["local_basin_identity"] == P3R3_LOCAL_BASIN_ID
    assert manifest["restoration_jacobian_identity"] == P3R3_RESTORATION_JACOBIAN_ID
    zero_keys = (
        "reference_discovery_results_observed_before_freeze",
        "target_admissibility_results_observed_before_freeze",
        "basin_probe_results_observed_before_freeze",
        "qualification_seed_results_observed_before_freeze",
        "dynamic_contact_results_observed_before_freeze",
    )
    assert all(manifest[key] == 0 for key in zero_keys)
    assert len(design["design_cards"]) == 6
    assert [item["design_id"] for item in design["design_cards"]] == [
        "ASYM_A01",
        "ASYM_A02",
        "ASYM_A03",
        "SCALE_S01",
        "SCALE_S02",
        "SCALE_S03",
    ]


def test_prefreeze_and_historical_hash_bindings_are_exact() -> None:
    manifest = _load("contracts/p3r3_acceptance_manifest.json")
    for relative, expected in manifest["prefreeze_source_sha256"].items():
        assert _sha256(relative) == expected
    for relative, expected in manifest["historical_artifact_sha256"].items():
        assert _sha256(relative) == expected


def test_implementation_binding_is_complete_and_has_no_new_results() -> None:
    binding = _load("contracts/p3r3_implementation_binding.json")
    assert binding["prefreeze_commit"] == "8401cfe617720b3532cdafd1249dd0edfbf6d789"
    assert binding["qualification_targets_not_yet_frozen"] is True
    result_keys = (
        "reference_discovery_results_observed_before_implementation_commit",
        "target_admissibility_results_observed_before_implementation_commit",
        "basin_probe_results_observed_before_implementation_commit",
        "qualification_seed_results_observed_before_implementation_commit",
    )
    assert all(binding[key] == 0 for key in result_keys)
    assert set(binding["source_sha256"]) == set(
        _load("contracts/p3r3_acceptance_manifest.json")["planned_implementation_paths"]
    ) - {"contracts/p3r3_implementation_binding.json"}
    for relative, expected in binding["source_sha256"].items():
        assert _sha256(relative) == expected


def test_module_manifest_covers_every_source_below_line_limit() -> None:
    manifest = _load("contracts/p3r3_acceptance_manifest.json")
    module_manifest = _load("contracts/p3r3_module_manifest.json")
    source_root = ROOT / "src/ypendulum_hfv2_p3r3"
    discovered = {path.name for path in source_root.glob("*.py")}
    declared = {item["path"] for item in module_manifest["modules"]}
    assert discovered == declared
    limit = manifest["architecture"]["source_lines_per_module_max_exclusive"]
    assert all(
        len(path.read_text(encoding="utf-8").splitlines()) < limit
        for path in source_root.glob("*.py")
    )
