from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import guard_contract_v2 as guard_v2


def _load_alpha_module():
    path = ROOT / "compression_limit" / "build_alpha_specific_candidate.py"
    spec = importlib.util.spec_from_file_location("alpha_specific_candidate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_saved_two_component_hybrid_has_nine_prepared_passes_but_no_promotion() -> None:
    saved = json.loads(
        (ROOT / "guard_contract_v2" / "evaluation.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved["prepared_level_count"] == 9
    assert saved["all_prepared_levels_passed_two_component_hybrid"] is True
    assert saved["historical_dynamic_qualification"] == (
        "HF_NUMERICAL_QUALIFICATION_NO_GO_UNCHANGED"
    )
    assert saved["source_endpoint_probe_status"] == (
        "SOURCE_ENDPOINT_PROBE_INVALID_UNCHANGED"
    )
    assert saved["formal_change_authorized"] is False
    assert saved["hybrid_evaluation_only"] is True
    assert saved["full_component_mesh_objectivity_audit_complete"] is False
    assert saved["contract_sha256"] == _sha256(ROOT / "guard_contract_v2" / "spec.json")
    for anchor in saved["anchors"]:
        assert anchor["all_prepared_levels_passed_two_component_hybrid"] is True
        for level in anchor["levels"]:
            assert level["two_component_hybrid_prepared_state_guard_passed"] is True
            assert level["two_component_hybrid_minimum_normalized_margin"] > 3.0e-4
            assert level["rod_self_clearance_v2"]["physical_domain_changed"] is False
            assert level["rod_self_clearance_v2"]["raw_guard_changed"] is False
            assert level["bob_socket_radial_monotonicity_v2"][
                "raw_guard_changed"
            ] is False


def test_saved_candidate_v2_evaluation_reproduces_from_full_root_cause_report() -> None:
    report_path = ROOT / "results" / "guard_root_cause.json"
    if not report_path.exists():
        pytest.skip("Full repository root-cause report is unavailable in this fixture.")
    spec_path = ROOT / "guard_contract_v2" / "spec.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    contract = json.loads(spec_path.read_text(encoding="utf-8"))
    observed = guard_v2.evaluate_report(
        report,
        contract,
        source_report_sha256=_sha256(report_path),
        contract_sha256=_sha256(spec_path),
    )
    expected = json.loads(
        (ROOT / "guard_contract_v2" / "evaluation.json").read_text(
            encoding="utf-8"
        )
    )
    assert observed == expected


def test_local_rod_normalisation_is_similarity_invariant() -> None:
    original = guard_v2._candidate_record(
        label="original",
        raw_margin=3.2e-5,
        local_scale=3.2e-3,
        metadata={},
    )
    scaled = guard_v2._candidate_record(
        label="scaled",
        raw_margin=3.2e-2,
        local_scale=3.2,
        metadata={},
    )
    assert original["normalized_margin"] == pytest.approx(
        scaled["normalized_margin"], abs=1.0e-15
    )
    assert original["normalized_margin"] == pytest.approx(0.01)


def test_raw_sign_gate_remains_fail_closed() -> None:
    zero = guard_v2._candidate_record(
        label="zero", raw_margin=0.0, local_scale=1.0, metadata={}
    )
    negative = guard_v2._candidate_record(
        label="negative", raw_margin=-1.0e-12, local_scale=1.0, metadata={}
    )
    assert zero["raw_positive"] is False
    assert negative["raw_positive"] is False


def test_alpha_candidate_configs_change_only_prefrozen_fields() -> None:
    alpha = _load_alpha_module()
    base = yaml.safe_load((ROOT / "configs" / "4to3.yaml").read_text(encoding="utf-8"))
    allowed = {
        "run.name",
        "run.output_directory",
        "run.claim_level",
        "high_fidelity.compression_regularization_scale",
        "high_fidelity.controlled_limit_study",
    }
    for scale in alpha.TARGET_SCALES:
        path = (
            ROOT
            / "compression_limit"
            / "alpha_specific_configs"
            / f"{alpha.scale_slug(scale)}.yaml"
        )
        candidate = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert set(alpha.leaf_differences(base, candidate)) == allowed
        assert candidate["run"]["claim_level"] == "OUT_OF_SCOPE"
        assert candidate["initial_condition"] == base["initial_condition"]
        assert candidate["high_fidelity"]["controlled_limit_study"] is True
        assert candidate["high_fidelity"][
            "compression_regularization_scale"
        ] == pytest.approx(scale)


def test_alpha_candidate_patch_matches_exact_formal_blobs_and_compiles() -> None:
    alpha = _load_alpha_module()
    if not alpha.FORMAL_SOURCE_ROOT.exists():
        pytest.skip("Formal repository source tree is unavailable in this fixture.")
    records = alpha.audit_formal_source()
    assert set(records) == set(alpha.EXPECTED_FORMAL_GIT_BLOBS)
    for path, record in records.items():
        assert record["formal_git_blob_sha1"] == alpha.EXPECTED_FORMAL_GIT_BLOBS[path]
        assert record["formal_sha256"] != record["candidate_sha256"]
        assert record["replacement_labels"]


def test_alpha_protocol_separates_equilibrium_and_quench_identities() -> None:
    protocol = json.loads(
        (ROOT / "compression_limit" / "alpha_specific_protocol.json").read_text(
            encoding="utf-8"
        )
    )
    assert protocol["decision"]["primary"] == "ALPHA_SPECIFIC_HELD_EQUILIBRIUM"
    assert protocol["decision"]["secondary_sensitivity"] == (
        "SHARED_ALPHA1_STATE_CONSTITUTIVE_QUENCH"
    )
    assert protocol["exact_zero"]["executable"] is False
    assert protocol["formal_change_authorized"] is False
    assert "conditioning_extension" in protocol["preparation_algorithm"]


def test_alpha_prefreeze_plan_hashes_all_candidate_inputs() -> None:
    plan = json.loads(
        (ROOT / "compression_limit" / "alpha_specific_plan.json").read_text(
            encoding="utf-8"
        )
    )
    assert plan["builder_sha256"] == _sha256(
        ROOT / "compression_limit" / "build_alpha_specific_candidate.py"
    )
    assert plan["protocol_sha256"] == _sha256(
        ROOT / "compression_limit" / "alpha_specific_protocol.json"
    )
    for record in plan["configs"]:
        assert record["sha256"] == _sha256(ROOT / record["path"])
    assert plan["overlay_validation_count"] == 0
    assert plan["prepared_state_count"] == 0
    assert plan["dynamic_run_count"] == 0
