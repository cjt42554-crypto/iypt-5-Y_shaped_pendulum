from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_full_guard_mesh_audit_is_bound_to_prefrozen_contract() -> None:
    prefreeze_path = ROOT / "guard_contract_v2" / "prefreeze.json"
    prefreeze = _json(prefreeze_path)
    audit = _json(ROOT / "guard_contract_v2" / "full_mesh_audit.json")
    assert audit["completed_preparation_count"] == 9
    assert audit["all_prepared_states_passed_full_candidate_guard"] is True
    assert audit["contract_identity_stable"] is True
    assert audit["contract_identity_start"]["full_spec_sha256"] == (
        prefreeze["spec_sha256"]
    )
    assert audit["contract_identity_start"][
        "full_implementation_sha256"
    ] == prefreeze["implementation_sha256"]
    assert audit["minimum_observed"]["normalized_margin"] > 3.0e-4
    assert audit["historical_dynamic_qualification"] == (
        "HF_NUMERICAL_QUALIFICATION_NO_GO_UNCHANGED"
    )


def test_alpha_specific_preparation_gate_is_closed_without_dynamics() -> None:
    plan_path = (
        ROOT
        / "compression_limit"
        / "alpha_specific_preparation_run_plan.json"
    )
    result = _json(
        ROOT
        / "compression_limit"
        / "alpha_specific_preparation_results.json"
    )
    assert result["run_plan_sha256"] == _sha256(plan_path)
    assert result["planned_preparation_count"] == 3
    assert result["completed_preparation_count"] == 3
    assert result["passed_preparation_count"] == 0
    assert result["all_preparations_passed"] is False
    assert result["dynamic_gate_open"] is False
    assert result["dynamic_run_count"] == 0
    assert all(result["identity_checks"].values())
    assert [item["compression_regularization_scale"] for item in result["preparations"]] == [
        1.0e-2,
        1.0e-4,
        1.0e-6,
    ]
    assert all(not item["passed"] for item in result["preparations"])


def test_failed_preparation_diagnostic_resolves_only_raw_rod_self_contact() -> None:
    diagnostic = _json(
        ROOT
        / "compression_limit"
        / "failed_preparation_guard_diagnostic.json"
    )
    assert diagnostic["dynamic_gate_open"] is False
    assert diagnostic["dynamic_run_count"] == 0
    assert all(diagnostic["identity_checks"].values())
    assert [item["force_balanced_seed_count"] for item in diagnostic["results"]] == [
        3,
        0,
        0,
    ]
    for scale in diagnostic["results"]:
        assert scale["raw_nonpositive_component_union"] == [
            "ROD_SELF_CLEARANCE"
        ]
        assert scale["candidate_core_records_match_primary_run"] is True
        for seed in scale["seeds"]:
            assert seed["all_guard_components_raw"]["ROD_SELF_CLEARANCE"] < 0.0
            assert set(seed["raw_nonpositive_components"]) == {
                "ROD_SELF_CLEARANCE"
            }
