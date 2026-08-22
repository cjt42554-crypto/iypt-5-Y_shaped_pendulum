from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import ypendulum.cli as cli_module
import ypendulum.hf.validation as validation_module
from ypendulum.config.units import to_si
from ypendulum.hf import HighFidelityModel, run_hf_validation
from ypendulum.hf.independence import _freeze_independence_spec
from ypendulum.hf.reference import (
    reference_snapshot_from_state,
    segment_segment_distance_reference,
)
from ypendulum.hf.solver import prepare_initial_state, simulate_high_fidelity
from ypendulum.hf.state import HighFidelityResult
from ypendulum.hf.validation import (
    _AcceptedStepReferenceCache,
    _accuracy_trend_gate,
    _canonical_config_hash,
    _canonical_series_consistency,
    _cauchy_gate,
    _continuous_guard_certificate,
    _event_stability,
    _expected_axial_event_fingerprints,
    _freeze_and_validate_spec,
    _guard_interval_lower_bounds,
    _independent_energy_balance,
    _interpolate_material_path,
    _level_contract,
    _presentation_certificate_binding,
    _raw_axial_event_fingerprint,
    _RunBundle,
    _validation_target_applicability,
    _write_candidate_artifacts,
    canonical_hf_result_sha256,
    verify_single_hf_certificate_digest,
)

_METRICS = (
    "rms_bob_position_m",
    "max_bob_position_m",
    "rms_bob_velocity_m_s",
    "max_bob_velocity_m_s",
    "rms_junction_position_m",
    "max_junction_position_m",
    "rms_junction_velocity_m_s",
    "max_junction_velocity_m_s",
    "rms_bob_attachment_position_m",
    "max_bob_attachment_position_m",
    "rms_bob_orientation_angle_rad",
    "max_bob_orientation_angle_rad",
    "rms_bob_angular_velocity_rad_s",
    "max_bob_angular_velocity_rad_s",
    "rms_rod_position_m",
    "max_rod_position_m",
    "rms_rod_velocity_m_s",
    "max_rod_velocity_m_s",
    "rms_rod_tension_N",
    "max_rod_tension_N",
    "rms_rod_signed_axial_force_N",
    "max_rod_signed_axial_force_N",
    "rms_mechanical_energy_J",
    "max_mechanical_energy_J",
    "rms_support_reaction_N",
    "max_support_reaction_N",
)


def _validation_config(config, tmp_path: Path):
    config.run.mode = "high_fidelity"
    config.run.output_directory = str(tmp_path / "unused")
    config.cables.upper_A.elements = 12
    config.cables.upper_B.elements = 12
    config.cables.lower.elements = 20
    config.solver.allow_subminimum_mesh = False
    config.initial_condition.bob_position = {
        "value": [0.0, 0.0, -0.711],
        "unit": "m",
    }
    config.initial_condition.junction_position = {
        "value": [0.0, 0.0, -0.40],
        "unit": "m",
    }
    config.initial_condition.type = "geometric_direct_release"
    for unused_field in ("phi", "theta", "phi_dot", "theta_dot"):
        config.initial_condition.model_fields_set.discard(unused_field)
    config.high_fidelity.contact_guard_enabled = True
    config.solver.t_end = {"value": 2.0e-4, "unit": "s"}
    config.solver.output_dt = {"value": 1.0e-4, "unit": "s"}
    config.solver.max_step = {"value": 5.0e-5, "unit": "s"}
    config.solver.rtol = 1.0e-6
    config.solver.position_atol = {"value": 1.0e-8, "unit": "m"}
    config.solver.velocity_atol = {"value": 1.0e-7, "unit": "m/s"}
    config.solver.quaternion_atol = 1.0e-8
    config.solver.angular_velocity_atol = {"value": 1.0e-7, "unit": "rad/s"}
    return config


def _permissive_validation_spec(config) -> dict:
    permissive = {metric: 1.0e6 for metric in _METRICS}
    return {
        "schema_version": "YPS-HF-VALIDATION-1.0",
        "material_comparison_points": 17,
        "cauchy_ratio_slack": 1.0e9,
        "numerical_floor_fraction": 1.0,
        "maximum_event_time_spread_s": 1.0,
        "cross_solver_tolerance_factors": {"Radau": 1.0, "BDF": 0.001},
        "thresholds": {
            "space": dict(permissive),
            "time": dict(permissive),
            "cross_solver": dict(permissive),
        },
        "physics_checks": {
            "minimum_normalized_guard_margin": 0.0,
            "maximum_negative_dissipation_W": 1.0e-12,
            "maximum_energy_balance_residual": 1.0,
            "maximum_quaternion_norm_error": 1.0e-5,
            "maximum_normalized_rate_defect": 1.0e6,
            "maximum_normalized_nonsmooth_increment_defect": 1.0e6,
            "maximum_normalized_signed_cumulative_defect": 1.0e6,
            "maximum_normalized_absolute_cumulative_defect": 1.0e6,
            "maximum_nonsmooth_time_fraction": 1.0,
            "maximum_nonsmooth_step_s": 1.0,
        },
        "metadata": {
            "intended_window_s": float(
                to_si(config.solver.t_end, default_unit="s")
            ),
            "production_mesh_beads": {
                branch: int(getattr(config.cables, branch).elements)
                for branch in ("upper_A", "upper_B", "lower")
            },
        },
    }


def _minimal_identity_result() -> HighFidelityResult:
    zeros_particle = np.zeros((2, 1, 3))
    zeros_vector = np.zeros((2, 3))
    return HighFidelityResult(
        time=np.array([0.0, 1.0]),
        integration_time=np.array([0.0, 1.0]),
        integration_particle_positions=zeros_particle.copy(),
        integration_particle_velocities=zeros_particle.copy(),
        integration_bob_position=zeros_vector.copy(),
        integration_bob_velocity=zeros_vector.copy(),
        integration_bob_quaternion=np.tile([1.0, 0.0, 0.0, 0.0], (2, 1)),
        integration_bob_angular_velocity=zeros_vector.copy(),
        particle_positions=zeros_particle.copy(),
        particle_velocities=zeros_particle.copy(),
        junction_position=zeros_vector.copy(),
        junction_velocity=zeros_vector.copy(),
        bob_position=zeros_vector.copy(),
        bob_velocity=zeros_vector.copy(),
        bob_quaternion=np.tile([1.0, 0.0, 0.0, 0.0], (2, 1)),
        bob_angular_velocity=zeros_vector.copy(),
        bob_attachment_position=zeros_vector.copy(),
        cable_positions={},
        cable_velocities={},
        cable_axial_force={},
        cable_tension={},
        guard_margins={},
        energy={},
        reactions={},
        events=[],
        diagnostics={"finite": True},
        physical_status="UNDETERMINED",
        numerical_status="SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED",
        valid_interval=(0.0, 1.0),
    )


def _simulated_bundle(config, tmp_path: Path) -> _RunBundle:
    cfg = _validation_config(config, tmp_path)
    model = HighFidelityModel(cfg)
    preparation = prepare_initial_state(cfg, model)
    result = simulate_high_fidelity(cfg, model=model, preparation=preparation)
    config_hash = _canonical_config_hash(cfg)
    return _RunBundle(
        config=cfg,
        config_hash=config_hash,
        model=model,
        preparation=preparation,
        result=result,
        source_start="stable",
        source_end="stable",
        config_hash_end=config_hash,
        runtime_identity_start={"runtime": "stable"},
        runtime_identity_end={"runtime": "stable"},
    )


def test_hf_validation_binds_finest_config_whole_state_and_two_solvers(
    config, tmp_path: Path
) -> None:
    cfg = _validation_config(config, tmp_path)
    spec = _permissive_validation_spec(cfg)
    report = run_hf_validation(cfg, spec)

    assert report["qualification"] == "HF_REFINEMENT_SUPPORTED"
    assert report["passed"]
    assert report["base_config_is_finest_level"]
    assert report["source_stable_during_study"]
    assert report["runtime_stable_during_study"]
    assert report["input_files_stable_during_study"]
    assert report["unique_run_count"] == 6
    assert report["studies"]["space"]["levels"][-1]["elements"] == {
        "upper_A": 12,
        "upper_B": 12,
        "lower": 20,
    }
    assert report["studies"]["time"]["levels"][-1]["config_sha256"] == report[
        "base_config_sha256"
    ]
    assert report["cross_solver"]["methods"] == ["Radau", "BDF"]
    assert report["cross_solver"]["alternate_tolerance_factor"] == 0.001
    assert all(
        level["contract"]["checks"]["initial_state_exact"]
        for study in report["studies"].values()
        for level in study["levels"]
    )
    assert all(
        level["contract"]["accuracy_role"] == (
            "finest_accuracy_required"
            if index == 2
            else "coarse_finite_and_trend_only"
        )
        for study in report["studies"].values()
        for index, level in enumerate(study["levels"])
    )
    assert report["studies"]["time"]["accuracy_trend"]["passed"]
    assert (
        report["studies"]["space"]["accuracy_trend"]["applicability"]
        == "not_applicable_to_space_refinement"
    )
    for study in report["studies"].values():
        for level in study["levels"]:
            defect = level["contract"]["dynamics_defect"]
            assert defect["smooth_step_count"] + defect["nonsmooth_step_count"] == defect[
                "certificate_step_count"
            ]
            assert defect["nonsmooth_time_fraction"] <= 1.0
    assert report["model_id"] == HighFidelityModel.model_id


def test_validation_spec_rejects_dimensionless_global_floor_and_missing_metric() -> None:
    permissive = {metric: 1.0 for metric in _METRICS}
    base = {
        "schema_version": "YPS-HF-VALIDATION-1.0",
        "material_comparison_points": 17,
        "cauchy_ratio_slack": 1.1,
        "numerical_floor_fraction": 0.01,
        "maximum_event_time_spread_s": 1.0e-4,
        "cross_solver_tolerance_factors": {"Radau": 1.0, "BDF": 0.001},
        "thresholds": {
            "space": dict(permissive),
            "time": dict(permissive),
            "cross_solver": dict(permissive),
        },
        "physics_checks": {
            "minimum_normalized_guard_margin": 0.0,
            "maximum_negative_dissipation_W": 0.0,
            "maximum_energy_balance_residual": 1.0e-6,
            "maximum_quaternion_norm_error": 1.0e-8,
            "maximum_normalized_rate_defect": 1.0e-5,
            "maximum_normalized_nonsmooth_increment_defect": 1.0e-5,
            "maximum_normalized_signed_cumulative_defect": 1.0e-5,
            "maximum_normalized_absolute_cumulative_defect": 1.0e-5,
            "maximum_nonsmooth_time_fraction": 0.01,
            "maximum_nonsmooth_step_s": 1.0e-5,
        },
    }
    invalid_floor = dict(base)
    invalid_floor.pop("numerical_floor_fraction")
    invalid_floor["normalized_numerical_floor"] = 1.0e-3
    with pytest.raises(ValueError, match="frozen contract"):
        _freeze_and_validate_spec(invalid_floor)

    missing = dict(base)
    missing["thresholds"] = {
        key: dict(value) for key, value in base["thresholds"].items()
    }
    missing["thresholds"]["space"].pop("max_rod_tension_N")
    with pytest.raises(ValueError, match="every canonical comparison metric"):
        _freeze_and_validate_spec(missing)

    legacy_guard_unit = deepcopy(base)
    legacy_guard_unit["physics_checks"]["minimum_guard_margin_m"] = (
        legacy_guard_unit["physics_checks"].pop(
            "minimum_normalized_guard_margin"
        )
    )
    with pytest.raises(ValueError, match="dimensionally invalid"):
        _freeze_and_validate_spec(legacy_guard_unit)

    partial_target = deepcopy(base)
    partial_target["metadata"] = {"intended_window_s": 0.12}
    with pytest.raises(ValueError, match="provide intended_window_s.*together"):
        _freeze_and_validate_spec(partial_target)


def test_production_certificate_target_rejects_short_window_and_wrong_mesh(
    config, tmp_path: Path, monkeypatch
) -> None:
    cfg = _validation_config(config, tmp_path)
    spec = _freeze_and_validate_spec(_permissive_validation_spec(cfg))
    baseline = _validation_target_applicability(cfg, spec)
    assert baseline["passed"]
    assert baseline["checks"] == {
        "intended_window_s_exact": True,
        "production_mesh_beads_exact": True,
    }

    output_only = deepcopy(cfg)
    output_only.run.output_directory = str(tmp_path / "different-artifact-root")
    output_evidence = _validation_target_applicability(output_only, spec)
    assert output_evidence["passed"]
    assert output_evidence["target_sha256"] == baseline["target_sha256"]
    assert output_evidence["explicitly_unbound_config_fields"] == [
        "run.output_directory"
    ]

    short_window = deepcopy(cfg)
    short_window.solver.t_end = {"value": 1.0e-4, "unit": "s"}
    wrong_mesh = deepcopy(cfg)
    wrong_mesh.cables.upper_A.elements += 1
    attacks = (
        (short_window, "intended_window_s_exact"),
        (wrong_mesh, "production_mesh_beads_exact"),
    )

    def forbidden_run(*args, **kwargs):
        pytest.fail("target mismatch must be rejected before any HF candidate run")

    def forbidden_level(*args, **kwargs):
        pytest.fail("target mismatch must be rejected before contract evaluation")

    monkeypatch.setattr(validation_module, "_run_bundle", forbidden_run)
    monkeypatch.setattr(validation_module, "_level_contract", forbidden_level)
    monkeypatch.setattr(validation_module, "validate_physical_config", lambda cfg: None)
    result = _minimal_identity_result()
    for attacked_config, failed_check in attacks:
        applicability = _validation_target_applicability(attacked_config, spec)
        assert not applicability["passed"]
        assert not applicability["checks"][failed_check]

        certificate = validation_module.certify_single_hf_bundle(
            attacked_config,
            result,
            model=SimpleNamespace(cfg=attacked_config),
            validation_spec=spec,
        )
        assert not certificate["passed"]
        assert not certificate["full_accuracy_spec_bound"]
        assert certificate["certification_level"] == "UNDETERMINED"
        assert not certificate["certification_target"]["passed"]
        assert verify_single_hf_certificate_digest(certificate)

        with pytest.raises(ValueError, match="not applicable.*production target"):
            run_hf_validation(attacked_config, spec)


def test_streaming_result_identity_covers_arrays_and_rejects_nonfinite() -> None:
    result = _minimal_identity_result()
    baseline = canonical_hf_result_sha256(result)
    result.bob_position[1, 0] = 1.0
    assert canonical_hf_result_sha256(result) != baseline
    result.bob_position[1, 0] = float("nan")
    with pytest.raises(ValueError, match="non-finite arrays"):
        canonical_hf_result_sha256(result)

    assert not verify_single_hf_certificate_digest({})
    assert not verify_single_hf_certificate_digest(
        {
            "schema_version": "YPS-HF-SINGLE-BUNDLE-CERTIFICATE-1.0",
            "certificate_sha256": "0" * 64,
        }
    )


def test_each_time_accuracy_defect_must_independently_decrease() -> None:
    def contract(energy: float, rate: float, signed: float, absolute: float):
        return {
            "energy_balance_residual": energy,
            "dynamics_defect": {
                "maximum_normalized_rate_defect": rate,
                "maximum_normalized_nonsmooth_increment_defect": 1.0e-8,
                "maximum_normalized_signed_cumulative_defect": signed,
                "maximum_normalized_absolute_cumulative_defect": absolute,
            },
        }

    contracts = [
        contract(1.0e-2, 1.0e-2, 1.0e-8, 1.0e-2),
        contract(1.0e-3, 1.0e-3, 1.0e-6, 1.0e-3),
        contract(1.0e-4, 1.0e-4, 1.0e-5, 1.0e-4),
    ]
    thresholds = {
        "maximum_energy_balance_residual": 1.0e-3,
        "maximum_normalized_rate_defect": 1.0e-3,
        "maximum_normalized_nonsmooth_increment_defect": 1.0e-4,
        "maximum_normalized_signed_cumulative_defect": 1.0e-4,
        "maximum_normalized_absolute_cumulative_defect": 1.0e-3,
    }
    gate = _accuracy_trend_gate(
        contracts,
        thresholds,
        ratio_slack=1.05,
        numerical_floor_fraction=0.01,
    )
    assert not gate["passed"]
    assert not gate["metrics"][
        "maximum_normalized_signed_cumulative_defect"
    ]["passed"]


def test_bilateral_event_ledger_uses_signed_axial_regimes_not_slack() -> None:
    signed = np.array([[-1.0], [0.0], [1.0]])
    result = SimpleNamespace(
        time=np.array([0.0, 0.5, 1.0]),
        cable_axial_force={"lower": signed},
        cable_tension={"lower": np.maximum(signed, 0.0)},
    )
    bundle = SimpleNamespace(
        result=result,
        model=SimpleNamespace(
            tension_zero_tolerance=1.0e-12,
            compression_regularization_scale=1.0,
        ),
    )
    fingerprints = _expected_axial_event_fingerprints(bundle)
    assert fingerprints is not None
    assert sum(fingerprints.values()) == 3
    assert any(item[-1] == "COMPRESSION" for item in fingerprints)
    assert any(item[-1] == "COMPRESSION->PURE_ZERO" for item in fingerprints)
    assert any(item[-1] == "PURE_ZERO->TENSION" for item in fingerprints)

    forbidden_slack = _raw_axial_event_fingerprint(
        {
            "type": "HF_SEGMENT_SLACKENING_SAMPLED_BRACKET",
            "branch": "lower",
            "material_segment": 0,
            "time": 0.5,
            "bracket_start_s": 0.0,
            "bracket_end_s": 0.5,
        },
        bilateral_weight=1.0,
    )
    assert forbidden_slack == ("INVALID_AXIAL_EVENT",)


def test_hf_validation_cli_checks_target_before_run_and_commits_atomically(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "hf-report.json"
    calls = []

    def fake_run(config, spec, *, artifact_directory):
        calls.append((config, spec))
        Path(artifact_directory).mkdir(parents=True)
        return {
            "qualification": "HF_REFINEMENT_SUPPORTED",
            "passed": True,
            "base_config_sha256": "a" * 64,
            "validation_spec_sha256": "b" * 64,
            "source_hash_start_sha256": "c" * 64,
            "source_hash_end_sha256": "c" * 64,
            "runtime_stable_during_study": True,
            "input_files_stable_during_study": True,
        }

    monkeypatch.setattr(cli_module, "run_hf_validation", fake_run)
    assert cli_module.main(
        ["hf-validate", "base.yaml", "spec.yaml", "--output", str(target)]
    ) == 0
    assert target.is_dir()
    assert (target / "report.json").is_file()
    assert (target / "artifact_manifest.json").is_file()
    assert (target / "delivery_root.json").is_file()
    assert len(calls) == 1
    assert not list(tmp_path.glob(".hf-report.json.staging-*"))

    assert cli_module.main(
        ["hf-validate", "base.yaml", "spec.yaml", "--output", str(target)]
    ) == 1
    assert len(calls) == 1


def test_level_contract_recomputes_tension_instead_of_trusting_derived_output(
    config, tmp_path: Path
) -> None:
    cfg = _validation_config(config, tmp_path)
    model = HighFidelityModel(cfg)
    preparation = prepare_initial_state(cfg, model)
    result = simulate_high_fidelity(cfg, model=model, preparation=preparation)
    result.cable_tension["lower"] = result.cable_tension["lower"] + 0.01
    bundle = _RunBundle(
        config=cfg,
        config_hash=_canonical_config_hash(cfg),
        model=model,
        preparation=preparation,
        result=result,
        source_start="stable",
        source_end="stable",
    )
    physics = {
        "minimum_normalized_guard_margin": 0.0,
        "maximum_negative_dissipation_W": 1.0e-12,
        "maximum_energy_balance_residual": 1.0,
        "maximum_quaternion_norm_error": 1.0e-5,
        "maximum_normalized_rate_defect": 1.0e6,
        "maximum_normalized_nonsmooth_increment_defect": 1.0e6,
        "maximum_normalized_signed_cumulative_defect": 1.0e6,
        "maximum_normalized_absolute_cumulative_defect": 1.0e6,
        "maximum_nonsmooth_time_fraction": 1.0,
        "maximum_nonsmooth_step_s": 1.0,
    }
    contract = _level_contract(bundle, physics, apply_accuracy=True)
    assert contract["continuous_guard_certificate"]["passed"]
    assert (
        contract["continuous_guard_certificate"]["status"]
        == "CERTIFIED_POSITIVE"
    )
    assert not contract["passed"]
    assert not contract["checks"]["nonnegative_tension_consistent"]

    artifact_root = tmp_path / "candidate-artifacts"
    records = _write_candidate_artifacts(
        artifact_root, {bundle.config_hash: bundle}
    )
    candidate = artifact_root / records[bundle.config_hash]["relative_directory"]
    assert (candidate / "result.h5").is_file()
    assert (candidate / "config_resolved.json").is_file()
    assert (candidate / "identity.json").is_file()
    assert (candidate / "candidate_manifest.json").is_file()


def test_public_presentation_is_bound_to_accepted_steps_and_q_sign_is_equivalent(
    config, tmp_path: Path
) -> None:
    bundle = _simulated_bundle(config, tmp_path)
    baseline = _presentation_certificate_binding(bundle)
    assert baseline["passed"]
    assert baseline["certified_sample_count"] == baseline["public_sample_count_t_gt_0"]

    sign_flipped = deepcopy(bundle.result)
    sign_flipped.bob_quaternion[1:] *= -1.0
    sign_bundle = deepcopy(bundle)
    sign_bundle.result = sign_flipped
    assert _presentation_certificate_binding(sign_bundle)["passed"]

    stationary = deepcopy(bundle.result)
    for name in (
        "particle_positions",
        "particle_velocities",
        "bob_position",
        "bob_velocity",
        "bob_quaternion",
        "bob_angular_velocity",
    ):
        values = getattr(stationary, name)
        values[1:] = values[0]
    stationary_bundle = deepcopy(bundle)
    stationary_bundle.result = stationary
    certificate = _presentation_certificate_binding(stationary_bundle)
    assert not certificate["passed"]
    assert any(
        item.get("accepted_endpoint_exact") and not item["passed"]
        for item in certificate["sample_certificates"]
    )


def test_reference_kernel_rejects_bending_reaction_and_signed_force_tampering(
    config, tmp_path: Path
) -> None:
    bundle = _simulated_bundle(config, tmp_path)
    baseline = _canonical_series_consistency(bundle)
    assert baseline["passed"], baseline

    bending_bundle = deepcopy(bundle)
    bending_bundle.result.energy["elastic_bending"] += 1.0e-6
    bending = _canonical_series_consistency(bending_bundle)
    assert not bending["checks"]["instantaneous_energy_consistent"]

    reaction_bundle = deepcopy(bundle)
    reaction_bundle.result.reactions["support_A"] += 1.0e-4
    reaction = _canonical_series_consistency(reaction_bundle)
    assert not reaction["checks"]["support_reaction_consistent"]

    signed_bundle = deepcopy(bundle)
    signed_series = signed_bundle.result.cable_axial_force
    signed_series["lower"] += 1.0e-4
    signed = _canonical_series_consistency(signed_bundle)
    assert not signed["checks"]["signed_axial_force_consistent"]

    dissipation_bundle = deepcopy(bundle)
    dissipation_bundle.result.energy["axial_dissipation_rate"] -= 1.0e-4
    dissipation = _canonical_series_consistency(dissipation_bundle)
    assert not dissipation["checks"]["instantaneous_power_consistent"]

    contact_bundle = deepcopy(bundle)
    contact_bundle.result.guard_margins["BOB_ROD_CLEARANCE"] += 1.0e-5
    contact = _canonical_series_consistency(contact_bundle)
    assert not contact["checks"]["bob_rod_guard_consistent"]

    representative_guard_mutations = {
        "AERODYNAMIC_CHORD_LENGTH": "aerodynamic_chord_guard_consistent",
        "BOB_SOCKET_RADIAL_MONOTONICITY": (
            "bob_socket_radial_monotonicity_consistent"
        ),
        "JUNCTION_SOCKET_PROJECTIVE_OPENING": (
            "junction_socket_projective_opening_consistent"
        ),
    }
    for guard_name, check_name in representative_guard_mutations.items():
        guard_bundle = deepcopy(bundle)
        guard_bundle.result.guard_margins[guard_name] += 1.0e-5
        guard_contract = _canonical_series_consistency(guard_bundle)
        assert not guard_contract["checks"][check_name]


def test_reference_kernel_matches_raw_force_power_without_production_evaluate(
    config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _validation_config(config, tmp_path)
    cfg.environment.air_velocity = {"value": [0.07, -0.02, 0.03], "unit": "m/s"}
    cfg.supports.A.motion = {
        "model": "sinusoidal",
        "amplitude": {"value": [1.0e-4, 0.0, 0.0], "unit": "m"},
        "frequency": {"value": 2.0, "unit": "Hz"},
        "phase": {"value": 0.0, "unit": "rad"},
    }
    cfg.supports.A.type = "prescribed"
    cfg.junction.drag_linear = {"value": 0.01, "unit": "N*s/m"}
    cfg.bob.drag.enabled = True
    cfg.bob.drag.linear_coefficient = {"value": 0.02, "unit": "N*s/m"}
    for name in ("upper_A", "upper_B", "lower"):
        getattr(cfg.cables, name).drag_enabled = True
    model = HighFidelityModel(cfg)
    preparation = prepare_initial_state(cfg, model)
    state = preparation.state.copy()
    velocity_offset = model.position_size + 7
    rng = np.random.default_rng(20260821)
    state[velocity_offset : velocity_offset + model.position_size + 3] = rng.normal(
        scale=0.01, size=model.position_size + 3
    )
    state[velocity_offset + model.position_size + 3 :] = rng.normal(
        scale=0.02, size=3
    )
    particles, bob, quaternion, velocities, bob_velocity, omega = model.unpack_state(
        state
    )
    production = model.evaluate(
        0.0,
        particles,
        velocities,
        bob,
        bob_velocity,
        quaternion,
        omega,
        compute_contact=False,
    )

    def forbidden_evaluate(*_args, **_kwargs):
        raise AssertionError("the independent reference kernel called model.evaluate")

    monkeypatch.setattr(model, "evaluate", forbidden_evaluate)
    reference = reference_snapshot_from_state(
        model, 0.0, state, compute_contact=False
    )
    np.testing.assert_allclose(reference.particle_force, production.particle_force)
    np.testing.assert_allclose(reference.bob_force, production.bob_force)
    np.testing.assert_allclose(reference.bob_torque, production.bob_torque)
    for name in ("support_A", "support_B"):
        np.testing.assert_allclose(
            reference.support_force[name], production.support_force[name]
        )
    for name in model.branches:
        np.testing.assert_allclose(
            reference.branch_axial_force[name], production.branch_axial_force[name]
        )
        np.testing.assert_allclose(
            reference.branch_tension[name], production.branch_tension[name]
        )
    assert reference.axial_energy == pytest.approx(production.axial_energy)
    assert reference.bending_energy == pytest.approx(production.bending_energy)
    assert reference.axial_dissipation_rate == pytest.approx(
        production.axial_dissipation_rate, abs=1.0e-15
    )
    assert reference.aero_dissipation_rate == pytest.approx(
        production.aero_dissipation_rate, abs=1.0e-15
    )
    assert reference.air_work_rate == pytest.approx(
        production.air_work_rate, abs=1.0e-15
    )
    assert reference.support_work_rate == pytest.approx(
        production.support_work_rate, abs=1.0e-15
    )
    assert abs(reference.support_work_rate) > 0.0


def test_independent_energy_normalization_is_origin_translation_invariant(
    config, tmp_path: Path
) -> None:
    bundle = _simulated_bundle(config, tmp_path)
    baseline = _independent_energy_balance(bundle)
    translation = np.array([2.0, -3.0, 5.0])

    translated_config = bundle.config.model_copy(deep=True)
    translated_config.supports.A.position = {
        "value": (np.array([-0.15, 0.0, 0.0]) + translation).tolist(),
        "unit": "m",
    }
    translated_config.supports.B.position = {
        "value": (np.array([0.15, 0.0, 0.0]) + translation).tolist(),
        "unit": "m",
    }
    translated_result = deepcopy(bundle.result)
    for name in (
        "particle_positions",
        "integration_particle_positions",
        "junction_position",
        "bob_position",
        "integration_bob_position",
        "bob_attachment_position",
    ):
        getattr(translated_result, name)[...] += translation
    for values in translated_result.cable_positions.values():
        values[...] += translation
    translated_model = HighFidelityModel(translated_config)
    translated_bundle = deepcopy(bundle)
    translated_bundle.config = translated_config
    translated_bundle.config_hash = _canonical_config_hash(translated_config)
    translated_bundle.model = translated_model
    translated_bundle.result = translated_result
    translated = _independent_energy_balance(translated_bundle)

    assert translated["normalization_scale_J"] == baseline["normalization_scale_J"]
    assert translated["maximum_abs_residual"] == pytest.approx(
        baseline["maximum_abs_residual"], abs=1.0e-12
    )


def test_hidden_positive_negative_positive_and_tangent_guard_paths_are_rejected(
    config, tmp_path: Path
) -> None:
    cfg = _validation_config(config, tmp_path)
    model = HighFidelityModel(cfg)
    preparation = prepare_initial_state(cfg, model)
    controls = np.tile(preparation.state, (4, 1))
    branch = model.branches["upper_A"]
    bead = int(branch.bead_indices[0])
    coordinate = slice(3 * bead, 3 * bead + 3)
    support, _, _ = model.support_motion["support_A"].state(0.0)
    endpoint = preparation.state[coordinate]

    # The endpoints are the untouched safe state, while the cubic midpoint
    # collapses the first material segment: a positive-negative-positive leak.
    midpoint_target = support
    interior_control = (8.0 * midpoint_target - 2.0 * endpoint) / 6.0
    controls[1:3, coordinate] = interior_control
    lower, midpoint, _ = _guard_interval_lower_bounds(model, controls, 0.0, 1.0e-4)
    assert midpoint["MINIMUM_SEGMENT_LENGTH"] < 0.0
    assert lower["MINIMUM_SEGMENT_LENGTH"] < 0.0

    # Exact tangency to the registered length guard is also non-certifiable.
    direction = endpoint - support
    direction /= np.linalg.norm(direction)
    tangent_target = support + model.length_guard * direction
    tangent_controls = np.tile(preparation.state, (4, 1))
    tangent_controls[1:3, coordinate] = (8.0 * tangent_target - 2.0 * endpoint) / 6.0
    tangent_lower, tangent_midpoint, _ = _guard_interval_lower_bounds(
        model, tangent_controls, 0.0, 1.0e-4
    )
    assert tangent_midpoint["MINIMUM_SEGMENT_LENGTH"] <= 64.0 * np.finfo(float).eps
    assert tangent_lower["MINIMUM_SEGMENT_LENGTH"] <= 0.0


@pytest.mark.parametrize("contact_enabled, expected_guard_count", [(False, 3), (True, 11)])
def test_static_guard_certificate_covers_exact_contact_vocabulary(
    config, tmp_path: Path, contact_enabled: bool, expected_guard_count: int
) -> None:
    cfg = _validation_config(config, tmp_path)
    cfg.high_fidelity.contact_guard_enabled = contact_enabled
    model = HighFidelityModel(cfg)
    state = prepare_initial_state(cfg, model).state
    cache = _AcceptedStepReferenceCache(
        time=np.array([0.0, 1.0e-7]),
        state=np.vstack([state, state]),
        rhs=np.zeros((2, state.size)),
        axial_active_signature=(np.ones(1, dtype=bool),) * 2,
    )
    certificate = _continuous_guard_certificate(
        SimpleNamespace(model=model),
        minimum_normalized_guard_margin=0.0,
        accepted_cache=cache,
    )
    expected = set(model.guard_component_metadata())
    assert len(expected) == expected_guard_count
    assert certificate["passed"], certificate
    assert certificate["status"] == "CERTIFIED_POSITIVE"
    assert set(certificate["guard_component_metadata"]) == expected
    assert set(certificate["step_certificates"][0]["guard_components"]) == expected


def test_reference_segment_distance_handles_collinear_nested_segments_symmetrically() -> None:
    outer_start = np.array([0.0, 0.0, 0.0])
    outer_end = np.array([10.0, 0.0, 0.0])
    inner_start = np.array([2.0, 0.0, 0.0])
    inner_end = np.array([3.0, 0.0, 0.0])
    forward = segment_segment_distance_reference(
        outer_start, outer_end, inner_start, inner_end
    )
    reverse = segment_segment_distance_reference(
        inner_start, inner_end, outer_start, outer_end
    )
    assert forward == 0.0
    assert reverse == forward


def test_cauchy_gate_rejects_fine_error_growth_above_explicit_floor() -> None:
    thresholds = {metric: 10.0 for metric in _METRICS}
    coarse_to_middle = {metric: 1.0 for metric in _METRICS}
    middle_to_fine = {metric: 1.01 for metric in _METRICS}
    gate = _cauchy_gate(
        [coarse_to_middle, middle_to_fine],
        thresholds,
        ratio_slack=1.0,
        numerical_floor_fraction=1.0e-6,
    )
    assert not gate["passed"]
    assert all(
        not item["decreasing_or_at_floor"] for item in gate["metrics"].values()
    )


def test_event_stability_uses_material_brackets_and_includes_not_fully_taut(
    config, tmp_path: Path
) -> None:
    bundles = []
    for elements in (12, 24, 48):
        candidate = _validation_config(config.model_copy(deep=True), tmp_path)
        candidate.high_fidelity.compression_regularization_scale = 0.0
        candidate.high_fidelity.controlled_limit_study = True
        candidate.run.claim_level = "OUT_OF_SCOPE"
        candidate.cables.upper_A.elements = elements
        model = HighFidelityModel(candidate)
        segment_count = model.branches["upper_A"].segment_rest_length.size
        physical_middle_segment = (segment_count - 1) // 2
        result = SimpleNamespace(
            events=[
                {
                    "type": "HF_SEGMENT_SLACKENING_SAMPLED_BRACKET",
                    "branch": "upper_A",
                    "material_segment": physical_middle_segment,
                    "time": 2.0e-4,
                    "bracket_start_s": 1.0e-4,
                    "bracket_end_s": 2.0e-4,
                },
                {
                    "type": "HF_BRANCH_NOT_FULLY_TAUT",
                    "branch": "upper_A",
                    "time": 2.0e-4,
                    "bracket_start_s": 1.0e-4,
                    "bracket_end_s": 2.0e-4,
                },
            ]
        )
        bundles.append(
            _RunBundle(
                config=candidate,
                config_hash=_canonical_config_hash(candidate),
                model=model,
                preparation=None,  # type: ignore[arg-type]
                result=result,  # type: ignore[arg-type]
                source_start="stable",
                source_end="stable",
            )
        )

    stability = _event_stability(bundles, tolerance=0.0)
    assert stability["passed"], stability
    assert any("HF_BRANCH_NOT_FULLY_TAUT" in key for key in stability["comparisons"])
    segment_records = [
        record
        for summary in stability["summaries"]
        for record in summary
        if record["type"] == "HF_SEGMENT_SLACKENING_SAMPLED_BRACKET"
    ]
    assert len(segment_records) == 3
    assert all(record["material_coordinate_bracket"] is not None for record in segment_records)
    assert len(
        {
            tuple(record["material_coordinate_bracket"])
            for record in segment_records
        }
    ) == 3

    invalid = deepcopy(bundles)
    invalid[1].result.events[0]["material_segment"] = 10**6
    invalid_stability = _event_stability(invalid, tolerance=0.0)
    assert not invalid_stability["passed"]
    assert "INVALID_EVENT_RECORDS" in invalid_stability["comparisons"]


def test_material_path_comparison_uses_rest_material_nodes() -> None:
    rest_length = np.array([0.1, 0.2, 0.7])
    material_nodes = np.array([0.0, 0.1, 0.3, 1.0])
    values = np.zeros((1, material_nodes.size, 3))
    values[0, :, 0] = material_nodes
    common = np.linspace(0.0, 1.0, 21)
    interpolated = _interpolate_material_path(values, rest_length, common)
    np.testing.assert_allclose(interpolated[0, :, 0], common, atol=1.0e-15)


def _independence_spec() -> dict:
    return {
        "schema_version": "YPS-HF-INDEPENDENCE-1.0",
        "limit_scales": [1.0, 1.0e-2, 1.0e-4, 1.0e-6],
        "cauchy_ratio_slack": 1.5,
        "cross_solver_floor_multiplier": 10.0,
        "separation_factor": 100.0,
        "minimum_separation_metric_count": 2,
        "minimum_finite_to_limit": {
            "max_bob_position_m": 1.0e-6,
            "max_bob_angular_velocity_rad_s": 1.0e-3,
        },
        "minimum_peak_bending_energy_J": 1.0e-12,
        "minimum_peak_angular_velocity_rad_s": 1.0e-3,
        "material_comparison_points": 17,
    }


def test_hf_independence_spec_is_strict_and_ratio_slack_is_not_below_one() -> None:
    frozen = _freeze_independence_spec(_independence_spec())
    assert frozen["limit_scales"] == [1.0, 1.0e-2, 1.0e-4, 1.0e-6]

    invalid = _independence_spec()
    invalid["cauchy_ratio_slack"] = 0.99
    with pytest.raises(ValueError, match="at least one"):
        _freeze_independence_spec(invalid)

    invalid = _independence_spec()
    invalid["metadata"] = {"bad": float("nan")}
    with pytest.raises(ValueError, match="frozen schema"):
        _freeze_independence_spec(invalid)

    invalid = _independence_spec()
    invalid["limit_scales"] = [1.0, 1.0e-2, 1.0e-6]
    with pytest.raises(ValueError, match="locked list"):
        _freeze_independence_spec(invalid)


def test_hf_independence_cli_commits_separate_identity_bound_delivery(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "hf-independence"
    calls = []

    def fake_run(config, validation_spec, independence_spec, *, artifact_directory):
        calls.append((config, validation_spec, independence_spec))
        Path(artifact_directory).mkdir(parents=True)
        return {
            "qualification": "HF_INDEPENDENCE_SUPPORTED",
            "passed": True,
            "base_config_sha256": "a" * 64,
            "validation_spec_sha256": "b" * 64,
            "independence_spec_sha256": "d" * 64,
            "source_hash_start_sha256": "c" * 64,
            "source_hash_end_sha256": "c" * 64,
            "runtime_stable_during_study": True,
            "input_files_stable_during_study": True,
        }

    monkeypatch.setattr(cli_module, "run_hf_independence_study", fake_run)
    assert cli_module.main(
        [
            "hf-independence",
            "base.yaml",
            "physics.yaml",
            "independence.yaml",
            "--output",
            str(target),
        ]
    ) == 0
    assert len(calls) == 1
    root = (target / "delivery_root.json").read_text(encoding="utf-8")
    assert "controlled_physics_limit" in root
    assert "d" * 64 in root
