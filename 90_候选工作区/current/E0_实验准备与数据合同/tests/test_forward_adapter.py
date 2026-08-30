from hashlib import sha256
from pathlib import Path

import pytest
from real_shape_fixture import apparatus_document, measurement_record_hash

from yps_experiment_pipeline.contracts import sha256_document, validate_document
from yps_experiment_pipeline.forward_adapter import (
    ADAPTER_LIMITATION,
    CABLE_INCOMPLETE,
    CABLE_REQUIRED_FIELDS,
    FORMAL_FORWARD_RELATIVE,
    TORUS_INCOMPATIBLE,
    TORUS_READY,
    FormalAdapterError,
    cable_compatibility,
    formal_identity,
    load_formal_forward,
    model_input_binding,
    run_formal_config,
    run_formal_ensemble,
    torus_compatibility,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def digest(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def cable_evidence(initial_state_representable: bool = True) -> dict:
    return {
        "input_completeness_sha256": digest("cable-input-completeness"),
        "initial_state_representable": initial_state_representable,
        "initial_state_evidence_sha256": digest("cable-initial-state"),
    }


def parameter_binding(name: str, source_type: str = "MEASURED") -> dict:
    measurement_ids = [] if source_type == "ASSUMPTION_SENSITIVITY_ONLY" else [f"{name}_M"]
    source_record_sha256 = digest(f"record:{name}")
    derivation = (
        {
            "method_id": f"DERIVE_{name}",
            "method_version": "1.0",
            "description": f"Synthetic derivation contract for {name}.",
            "input_measurement_ids": measurement_ids,
            "input_record_sha256": source_record_sha256,
            "configuration": {"mode": "SYNTHETIC_UNIT_TEST"},
        }
        if source_type == "DERIVED_FROM_MEASURED"
        else None
    )
    return {
        "parameter_name": name,
        "source_type": source_type,
        "measurement_ids": measurement_ids,
        "measurement_bundle_sha256": digest("measurement-bundle"),
        "source_record_sha256": source_record_sha256,
        "derivation": derivation,
        "derivation_sha256": sha256_document(derivation) if derivation is not None else None,
    }


def torus_evidence(*, domain_decision: bool = True) -> dict:
    return {
        "geometry_embedding": {"decision": True, "evidence_sha256": digest("geometry")},
        "initial_state_mapping": {"decision": True, "evidence_sha256": digest("initial")},
        "domain_window": {"decision": domain_decision, "evidence_sha256": digest("domain")},
        "mapping_residual": 0.1,
        "mapping_standard_uncertainty": 0.2,
    }


def test_adapter_loads_only_repository_formal_package():
    module = load_formal_forward(REPOSITORY_ROOT)
    expected_root = (REPOSITORY_ROOT / FORMAL_FORWARD_RELATIVE).resolve()
    assert expected_root in Path(module.__file__).resolve().parents
    identity = formal_identity(REPOSITORY_ROOT)
    assert identity["program_version"] == module.PROGRAM_VERSION
    assert identity["theory_sha256"] == module.THEORY_SHA256
    assert len(identity["formal_source_sha256"]) == 64
    result = run_formal_config(REPOSITORY_ROOT, {})
    assert isinstance(result, module.SimulationResult)
    assert result.numerical_status == "INPUT_REJECTED"
    ensemble_result = run_formal_ensemble(REPOSITORY_ROOT, {})
    assert ensemble_result.status == "INVALID_ENSEMBLE_INPUT"


def test_torus_compatibility_positive_and_negative_cases():
    positive = {"torus_evidence": torus_evidence()}
    assert torus_compatibility(positive) == TORUS_READY
    negative = {"torus_evidence": torus_evidence(domain_decision=False)}
    assert torus_compatibility(negative) == TORUS_INCOMPATIBLE
    assert (
        torus_compatibility(
            {
                "geometry_embedding_compatible": True,
                "initial_state_mappable": True,
                "no_slack_or_contact_in_window": True,
            }
        )
        == TORUS_INCOMPATIBLE
    )


def test_cable_missing_input_and_adapter_limitation_fail_closed():
    status, missing = cable_compatibility(
        {
            "purpose": "EXPERIMENT_COMPARISON",
            "parameter_bindings": [],
            "cable_evidence": cable_evidence(),
        }
    )
    assert status == CABLE_INCOMPLETE
    assert "initial_centerlines" in missing
    status, _ = cable_compatibility(
        {
            "purpose": "EXPERIMENT_COMPARISON",
            "parameter_bindings": [],
            "cable_evidence": cable_evidence(initial_state_representable=False),
        }
    )
    assert status == ADAPTER_LIMITATION


def test_cable_assumptions_are_never_ready_for_experiment_comparison():
    measured_bindings = [parameter_binding(key) for key in sorted(CABLE_REQUIRED_FIELDS)]
    status, missing = cable_compatibility(
        {
            "purpose": "EXPERIMENT_COMPARISON",
            "parameter_bindings": measured_bindings,
            "cable_evidence": cable_evidence(),
        }
    )
    assert status == TORUS_READY
    assert missing == []

    sensitivity_bindings = [
        parameter_binding(
            key,
            "ASSUMPTION_SENSITIVITY_ONLY" if key == "air_drag" else "MEASURED",
        )
        for key in sorted(CABLE_REQUIRED_FIELDS)
    ]
    status, missing = cable_compatibility(
        {
            "purpose": "EXPERIMENT_COMPARISON",
            "parameter_bindings": sensitivity_bindings,
            "cable_evidence": cable_evidence(),
        }
    )
    assert status == CABLE_INCOMPLETE
    assert "air_drag:INVALID_SOURCE" in missing

    status, missing = cable_compatibility(
        {
            "purpose": "SENSITIVITY_ONLY",
            "parameter_bindings": sensitivity_bindings,
            "cable_evidence": cable_evidence(),
        }
    )
    assert status == TORUS_READY
    assert missing == []


def test_model_binding_records_formal_and_input_hashes_and_validates():
    identity = formal_identity(REPOSITORY_ROOT)
    apparatus = apparatus_document()
    measurement_bundle_hash = sha256_document(apparatus)
    measurement_ids = ["SUPPORT_A_XYZ", "SUPPORT_B_XYZ"]
    parameter_bindings = [
        {
            "parameter_name": "geometry_embedding",
            "source_type": "SYNTHETIC_REAL_SHAPE_FIXTURE",
            "measurement_ids": measurement_ids,
            "measurement_bundle_sha256": measurement_bundle_hash,
            "source_record_sha256": measurement_record_hash(apparatus, measurement_ids),
            "derivation": None,
            "derivation_sha256": None,
        }
    ]
    compatibility_evidence = {"torus": torus_evidence(), "cable": None}
    binding = model_input_binding(
        REPOSITORY_ROOT,
        model_id="FWD-TORUS-1.0",
        purpose="SYNTHETIC_CONTRACT_TEST",
        measurement_document=apparatus,
        measurement_bundle_sha256=measurement_bundle_hash,
        trajectory_bundle_sha256=digest("trajectory-bundle"),
        parameter_bindings=parameter_bindings,
        compatibility_evidence=compatibility_evidence,
        compatibility_status=TORUS_READY,
        missing_fields=[],
    )
    validate_document("model_input_binding.schema.json", binding)
    assert binding["formal_source_sha256"] == identity["formal_source_sha256"]
    assert binding["measurement_bundle_sha256"] == measurement_bundle_hash


def test_derived_parameter_hash_must_match_actual_derivation_content():
    apparatus = apparatus_document()
    apparatus["data_origin"] = "MEASURED_BUNDLE"
    apparatus["apparatus_revision"] = "REAL_RIG_V1"
    for record in apparatus["measurements"]:
        record["source_type"] = "MEASURED"
    measurement_bundle_hash = sha256_document(apparatus)
    measurement_ids = ["SUPPORT_A_XYZ", "SUPPORT_B_XYZ"]
    source_record_sha256 = measurement_record_hash(apparatus, measurement_ids)
    derivation = {
        "method_id": "SUPPORT_BASELINE_FROM_ENDPOINTS",
        "method_version": "1.0",
        "description": "Subtract measured support coordinates to obtain the support baseline.",
        "input_measurement_ids": measurement_ids,
        "input_record_sha256": source_record_sha256,
        "configuration": {"coordinate_frame": "WORLD"},
    }
    parameter_bindings = [
        {
            "parameter_name": "support_baseline",
            "source_type": "DERIVED_FROM_MEASURED",
            "measurement_ids": measurement_ids,
            "measurement_bundle_sha256": measurement_bundle_hash,
            "source_record_sha256": source_record_sha256,
            "derivation": derivation,
            "derivation_sha256": sha256_document(derivation),
        }
    ]
    compatibility_evidence = {"torus": torus_evidence(), "cable": None}
    binding = model_input_binding(
        REPOSITORY_ROOT,
        model_id="FWD-TORUS-1.0",
        purpose="EXPERIMENT_COMPARISON",
        measurement_document=apparatus,
        measurement_bundle_sha256=measurement_bundle_hash,
        trajectory_bundle_sha256=digest("trajectory-bundle"),
        parameter_bindings=parameter_bindings,
        compatibility_evidence=compatibility_evidence,
        compatibility_status=TORUS_READY,
        missing_fields=[],
    )
    validate_document("model_input_binding.schema.json", binding)

    incomplete = [dict(parameter_bindings[0])]
    incomplete_derivation = dict(derivation)
    incomplete_derivation.pop("method_version")
    incomplete[0]["derivation"] = incomplete_derivation
    incomplete[0]["derivation_sha256"] = sha256_document(incomplete_derivation)
    with pytest.raises(FormalAdapterError, match="model input binding contract"):
        model_input_binding(
            REPOSITORY_ROOT,
            model_id="FWD-TORUS-1.0",
            purpose="EXPERIMENT_COMPARISON",
            measurement_document=apparatus,
            measurement_bundle_sha256=measurement_bundle_hash,
            trajectory_bundle_sha256=digest("trajectory-bundle"),
            parameter_bindings=incomplete,
            compatibility_evidence=compatibility_evidence,
            compatibility_status=TORUS_READY,
            missing_fields=[],
        )

    tampered = [dict(parameter_bindings[0])]
    tampered[0]["derivation"] = dict(derivation)
    tampered[0]["derivation"]["method_version"] = "2.0"
    with pytest.raises(FormalAdapterError, match="derivation hash"):
        model_input_binding(
            REPOSITORY_ROOT,
            model_id="FWD-TORUS-1.0",
            purpose="EXPERIMENT_COMPARISON",
            measurement_document=apparatus,
            measurement_bundle_sha256=measurement_bundle_hash,
            trajectory_bundle_sha256=digest("trajectory-bundle"),
            parameter_bindings=tampered,
            compatibility_evidence=compatibility_evidence,
            compatibility_status=TORUS_READY,
            missing_fields=[],
        )
