from pathlib import Path

from yps_experiment_pipeline.contracts import validate_document
from yps_experiment_pipeline.forward_adapter import (
    ADAPTER_LIMITATION,
    CABLE_INCOMPLETE,
    CABLE_REQUIRED_FIELDS,
    FORMAL_FORWARD_RELATIVE,
    TORUS_INCOMPATIBLE,
    TORUS_READY,
    cable_compatibility,
    formal_identity,
    load_formal_forward,
    model_input_binding,
    run_formal_config,
    run_formal_ensemble,
    torus_compatibility,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


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
    positive = {
        "geometry_embedding_compatible": True,
        "initial_state_mappable": True,
        "no_slack_or_contact_in_window": True,
        "mapping_residual": 0.1,
        "mapping_standard_uncertainty": 0.2,
    }
    assert torus_compatibility(positive) == TORUS_READY
    negative = dict(positive, no_slack_or_contact_in_window=False)
    assert torus_compatibility(negative) == TORUS_INCOMPATIBLE


def test_cable_missing_input_and_adapter_limitation_fail_closed():
    status, missing = cable_compatibility(
        {"parameter_sources": {}, "initial_state_representable": True}
    )
    assert status == CABLE_INCOMPLETE
    assert "initial_centerlines" in missing
    status, _ = cable_compatibility({"parameter_sources": {}, "initial_state_representable": False})
    assert status == ADAPTER_LIMITATION


def test_cable_assumptions_are_never_ready_for_experiment_comparison():
    measured_sources = {key: "MEASURED" for key in CABLE_REQUIRED_FIELDS}
    status, missing = cable_compatibility(
        {
            "purpose": "EXPERIMENT_COMPARISON",
            "parameter_sources": measured_sources,
            "initial_state_representable": True,
        }
    )
    assert status == TORUS_READY
    assert missing == []

    sensitivity_sources = dict(measured_sources, air_drag="ASSUMPTION_SENSITIVITY_ONLY")
    status, missing = cable_compatibility(
        {
            "purpose": "EXPERIMENT_COMPARISON",
            "parameter_sources": sensitivity_sources,
            "initial_state_representable": True,
        }
    )
    assert status == CABLE_INCOMPLETE
    assert "air_drag:INVALID_SOURCE" in missing

    status, missing = cable_compatibility(
        {
            "purpose": "SENSITIVITY_ONLY",
            "parameter_sources": sensitivity_sources,
            "initial_state_representable": True,
        }
    )
    assert status == TORUS_READY
    assert missing == []


def test_model_binding_records_formal_hash_and_validates():
    identity = formal_identity(REPOSITORY_ROOT)
    binding = model_input_binding(
        REPOSITORY_ROOT,
        model_id="FWD-TORUS-1.0",
        purpose="EXPERIMENT_COMPARISON",
        parameter_sources={"geometry": "MEASURED"},
        compatibility_status=TORUS_READY,
        missing_fields=[],
    )
    validate_document("model_input_binding.schema.json", binding)
    assert binding["formal_source_sha256"] == identity["formal_source_sha256"]
