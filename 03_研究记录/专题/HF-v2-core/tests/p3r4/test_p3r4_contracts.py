from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ypendulum_hfv2_p3r4 import (
    P3R4_ACTUAL_MULTISEED_ID,
    P3R4_COMPOSITE_ALGORITHM_ID,
    P3R4_CONTACT_MODEL_ID,
    P3R4_MANIFOLD_RETRACTION_ID,
    P3R4_SECOND_ORDER_ID,
    P3R4_TARGET_ADMISSIBILITY_ID,
)

ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _sha256(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def test_prefreeze_contract_identities_and_zero_result_counts() -> None:
    manifest = _load("contracts/p3r4_acceptance_manifest.json")
    design = _load("contracts/p3r4_design_cards.json")
    assert manifest["contact_model_id"] == P3R4_CONTACT_MODEL_ID
    assert manifest["composite_algorithm_identity"] == P3R4_COMPOSITE_ALGORITHM_ID
    assert manifest["target_admissibility_identity"] == P3R4_TARGET_ADMISSIBILITY_ID
    assert manifest["second_order_identity"] == P3R4_SECOND_ORDER_ID
    assert manifest["manifold_retraction_identity"] == P3R4_MANIFOLD_RETRACTION_ID
    assert manifest["actual_multiseed_attraction_identity"] == P3R4_ACTUAL_MULTISEED_ID
    zero_keys = (
        "reference_discovery_results_observed_before_freeze",
        "target_admissibility_results_observed_before_freeze",
        "second_order_results_observed_before_freeze",
        "manifold_retraction_results_observed_before_freeze",
        "target_freeze_results_observed_before_freeze",
        "qualification_seed_results_observed_before_freeze",
        "dynamic_contact_results_observed_before_freeze",
    )
    assert all(manifest[key] == 0 for key in zero_keys)
    assert [item["design_id"] for item in design["design_cards"]] == [
        "R4_ASYM_B01",
        "R4_ASYM_B02",
        "R4_ASYM_B03",
        "R4_ASYM_B04",
        "R4_SCALE_T01",
        "R4_SCALE_T02",
        "R4_SCALE_T03",
        "R4_SCALE_T04",
    ]


def test_prefreeze_and_historical_hash_bindings_are_exact() -> None:
    manifest = _load("contracts/p3r4_acceptance_manifest.json")
    for relative, expected in manifest["prefreeze_source_sha256"].items():
        assert _sha256(relative) == expected
    for relative, expected in manifest["historical_artifact_sha256"].items():
        assert _sha256(relative) == expected


def test_implementation_binding_is_complete_and_has_no_new_results() -> None:
    manifest = _load("contracts/p3r4_acceptance_manifest.json")
    binding = _load("contracts/p3r4_implementation_binding.json")
    assert binding["prefreeze_commit"] == "411e1dd6537be50f55c5c5229b2e9a23350f44be"
    assert binding["initial_implementation_commit"] == "7519585cdf35fd202ed8e822a0aca733b63d6eb6"
    assert binding["zero_result_correction_reason"] == (
        "R4_ASYM_B02 input assembly raised ContactGeometryError before any design solver "
        "or result output; classify each frozen card independently and fail invalid input closed"
    )
    assert binding["admissibility_not_yet_executed"] is True
    assert binding["targets_and_solver_initial_guesses_not_yet_frozen"] is True
    result_keys = (
        "reference_discovery_results_observed_before_implementation_commit",
        "target_admissibility_results_observed_before_implementation_commit",
        "second_order_results_observed_before_implementation_commit",
        "manifold_retraction_results_observed_before_implementation_commit",
        "target_freeze_results_observed_before_implementation_commit",
        "qualification_seed_results_observed_before_implementation_commit",
    )
    assert all(binding[key] == 0 for key in result_keys)
    assert set(binding["source_sha256"]) == set(manifest["planned_implementation_paths"]) - {
        "contracts/p3r4_implementation_binding.json"
    }
    for relative, expected in binding["source_sha256"].items():
        assert _sha256(relative) == expected


def test_module_manifest_covers_every_source_below_line_limit() -> None:
    manifest = _load("contracts/p3r4_acceptance_manifest.json")
    module_manifest = _load("contracts/p3r4_module_manifest.json")
    source_root = ROOT / "src/ypendulum_hfv2_p3r4"
    discovered = {path.name for path in source_root.glob("*.py")}
    declared = {item["path"] for item in module_manifest["modules"]}
    assert discovered == declared
    limit = manifest["architecture"]["source_lines_per_module_max_exclusive"]
    assert all(
        len(path.read_text(encoding="utf-8").splitlines()) < limit
        for path in source_root.glob("*.py")
    )
