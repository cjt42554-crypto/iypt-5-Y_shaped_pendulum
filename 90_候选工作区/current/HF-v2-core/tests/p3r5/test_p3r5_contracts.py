from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from ypendulum_hfv2_p3r5 import (
    P3R5_ACTUAL_MULTISEED_ID,
    P3R5_CONTACT_MODEL_ID,
    P3R5_MANIFOLD_RETRACTION_ID,
    P3R5_QUALIFICATION_ALGORITHM_ID,
    P3R5_REFERENCE_CONSTRUCTOR_ID,
    P3R5_SECOND_ORDER_ID,
    P3R5_TARGET_ADMISSIBILITY_ID,
)
from ypendulum_hfv2_p3r5.evidence_support import architecture_metrics

ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _sha256(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def test_prefreeze_identities_and_all_result_counts_are_zero() -> None:
    manifest = _load("contracts/p3r5_acceptance_manifest.json")
    domain = _load("contracts/p3r5_holdout_domain.json")
    assert manifest["contact_model_id"] == P3R5_CONTACT_MODEL_ID
    assert manifest["reference_constructor_identity"] == P3R5_REFERENCE_CONSTRUCTOR_ID
    assert manifest["qualification_algorithm_identity"] == P3R5_QUALIFICATION_ALGORITHM_ID
    assert manifest["target_admissibility_identity"] == P3R5_TARGET_ADMISSIBILITY_ID
    assert manifest["second_order_identity"] == P3R5_SECOND_ORDER_ID
    assert manifest["manifold_retraction_identity"] == P3R5_MANIFOLD_RETRACTION_ID
    assert manifest["actual_multiseed_attraction_identity"] == P3R5_ACTUAL_MULTISEED_ID
    zero_keys = (
        "holdout_cards_generated_before_freeze",
        "input_assembly_results_observed_before_freeze",
        "reference_construction_results_observed_before_freeze",
        "target_admissibility_results_observed_before_freeze",
        "second_order_results_observed_before_freeze",
        "manifold_retraction_results_observed_before_freeze",
        "target_freeze_results_observed_before_freeze",
        "qualification_seed_results_observed_before_freeze",
        "dynamic_contact_results_observed_before_freeze",
    )
    assert all(manifest[key] == 0 for key in zero_keys)
    assert domain["holdout_cards_generated_before_freeze"] == 0


def test_prefreeze_and_historical_hashes_are_exact() -> None:
    manifest = _load("contracts/p3r5_acceptance_manifest.json")
    for relative, expected in manifest["prefreeze_source_sha256"].items():
        assert _sha256(relative) == expected
    for relative, expected in manifest["historical_artifact_sha256"].items():
        assert _sha256(relative) == expected


def test_inherited_sections_change_only_declared_identity_fields() -> None:
    current = _load("contracts/p3r5_acceptance_manifest.json")
    predecessor = _load("contracts/p3r4_acceptance_manifest.json")
    for key in current["inherited_p3r4_contract"]["equal_sections"]:
        assert current[key] == predecessor[key]
    for key in current["inherited_p3r4_contract"]["identity_only_change_sections"]:
        left = copy.deepcopy(current[key])
        right = copy.deepcopy(predecessor[key])
        if key == "composite_solver":
            for value in (left, right):
                value.pop("identity")
                value.pop("behavior_predecessor")
                value["restoration"].pop("method_identity")
                value["restoration"].pop("behavior_predecessor")
        else:
            left.pop("identity")
            right.pop("identity")
        assert left == right


def test_implementation_binding_covers_every_planned_path() -> None:
    manifest = _load("contracts/p3r5_acceptance_manifest.json")
    binding = _load("contracts/p3r5_implementation_binding.json")
    expected = set(manifest["planned_implementation_paths"]) - {
        "contracts/p3r5_implementation_binding.json"
    }
    assert set(binding["source_sha256"]) == expected
    assert binding["prefreeze_commit"] == "fc110ca8ab980b3628a510ede5badacde6652e6a"
    assert binding["holdout_cards_not_yet_generated"] is True
    assert binding["holdout_numerical_results_observed_before_implementation_commit"] == 0
    for relative, expected_hash in binding["source_sha256"].items():
        assert _sha256(relative) == expected_hash


def test_module_manifest_covers_every_source_below_line_limit() -> None:
    manifest = _load("contracts/p3r5_acceptance_manifest.json")
    module_manifest = _load("contracts/p3r5_module_manifest.json")
    source_root = ROOT / "src/ypendulum_hfv2_p3r5"
    discovered = {path.name for path in source_root.glob("*.py")}
    declared = {item["path"] for item in module_manifest["modules"]}
    assert discovered == declared
    limit = manifest["architecture"]["source_lines_per_module_max_exclusive"]
    assert all(
        len(path.read_text(encoding="utf-8").splitlines()) < limit
        for path in source_root.glob("*.py")
    )


def test_module_architecture_gate_passes() -> None:
    result = architecture_metrics(ROOT, _load("contracts/p3r5_acceptance_manifest.json"))
    assert result["status"] == "PASS"
    assert result["production_try_statement_count"] == 0
    assert result["production_random_call_count"] == 0
