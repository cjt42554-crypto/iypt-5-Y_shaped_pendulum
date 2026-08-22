from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
import yaml

import ypendulum.api as public_api
from ypendulum.api import (
    analyze_linear_modes,
    analyze_run,
    compare_experiment,
    compare_runs,
    simulate,
)
from ypendulum.hf import read_hf_certificate_sidecar
from ypendulum.hf.model import HighFidelityModel

_HF_COMPARISON_METRICS = (
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


def _api_config(config, target: Path):
    config.run.mode = "high_fidelity"
    config.run.output_directory = str(target)
    config.high_fidelity.contact_guard_enabled = True
    config.solver.t_end = {"value": 2.0e-4, "unit": "s"}
    config.solver.output_dt = {"value": 1.0e-4, "unit": "s"}
    config.solver.max_step = {"value": 5.0e-5, "unit": "s"}
    model = HighFidelityModel(config)
    # Rebuild the strict protocol object so explicit reduced-angle fields from
    # the generic fixture cannot be silently carried into an HF Cartesian run.
    config.initial_condition = config.initial_condition.__class__(
        type="cartesian_release",
        bob_position={
            "value": model.reference_bob_position.tolist(),
            "unit": "m",
        },
        bob_velocity={"value": [0.0, 0.0, 0.0], "unit": "m/s"},
        bob_angular_velocity={"value": [0.0, 0.0, 0.0], "unit": "rad/s"},
    )
    return config


def _write_permissive_validation_spec(config, path: Path) -> Path:
    permissive = {metric: 1.0e6 for metric in _HF_COMPARISON_METRICS}
    spec = {
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
            "intended_window_s": 2.0e-4,
            "production_mesh_beads": {
                branch: int(getattr(config.cables, branch).elements)
                for branch in ("upper_A", "upper_B", "lower")
            },
        },
    }
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def test_public_hf_run_commits_complete_identity_bound_directory(config, tmp_path: Path) -> None:
    target = tmp_path / "hf-run"
    cfg = _api_config(config, target)
    result = simulate(cfg)

    assert result.run_directory == target
    assert target.is_dir()
    expected = {
        "config_original.yaml",
        "config_resolved.yaml",
        "result.h5",
        "summary.json",
        "diagnostics.json",
        "events.csv",
        "events.json",
        "observer_output.npz",
        "observer_summary.json",
        "provenance.json",
        "execution_identity.json",
        "report.md",
    }
    assert expected.issubset({path.name for path in target.iterdir()})
    with h5py.File(target / "result.h5", "r") as h5:
        assert h5.attrs["model"] == "HF-DISCRETE-ROD-RIGID-BOB-1.0"
        assert h5.attrs["units"] == "SI"
        assert np.asarray(h5["/bodies/bob/quaternion_body_to_world"]).shape == (3, 4)
        assert "/energy/elastic_bending" in h5
        certificate_time = np.asarray(
            h5["/numerical_certificate/accepted_step_time"]
        )
        assert certificate_time[0] == 0.0
        assert certificate_time[-1] == 2.0e-4
        assert np.all(np.diff(certificate_time) > 0.0)
        assert h5[
            "/numerical_certificate/material_particles/position"
        ].shape[0] == certificate_time.size
        assert h5.attrs["physical_status"] == "UNDETERMINED"
        assert (
            h5.attrs["numerical_status"]
            == "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"
        )
        model = HighFidelityModel(cfg)
        expected_guard_metadata = model.guard_component_metadata()
        assert set(h5["/validity/guard_margin"]) == set(expected_guard_metadata)
        for name, metadata in expected_guard_metadata.items():
            guard = h5[f"/validity/guard_margin/{name}"]
            assert guard.attrs["unit"] == metadata["unit"]
            assert guard.attrs["normalization_scale"] == pytest.approx(
                metadata["scale"]
            )
            assert guard.attrs["raw_machine_tolerance"] == pytest.approx(
                metadata["tolerance"]
            )
        for branch in ("upper_A", "upper_B", "lower"):
            signed = np.asarray(
                h5[f"/cables/{branch}/segments/signed_axial_force"]
            )
            tension = np.asarray(h5[f"/cables/{branch}/segments/tension"])
            assert np.array_equal(tension, np.maximum(signed, 0.0))
    observer = np.load(target / "observer_output.npz")
    assert observer["operator_id"].item() == "orthographic_xy_world"
    assert observer["value_unit"].item() == "m"
    assert not (target / "hf_single_bundle_certificate.json").exists()

    analysis = analyze_run(target)
    assert analysis["physical_status"] == "UNDETERMINED"
    assert analysis["numerical_status"] == "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"
    assert analysis["certificate_sha256"] is None
    assert analysis["result_interpretation"].startswith(
        "RAW_PERSONAL_RESEARCH_RESULT"
    )

    with pytest.raises(FileExistsError):
        simulate(cfg)


def test_failed_run_never_publishes_partial_target(config, tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "failed-hf-run"
    cfg = _api_config(config, target)

    def fail_after_partial(_cfg, staging, **_kwargs):
        (staging / "partial.txt").write_text("not a result", encoding="utf-8")
        raise RuntimeError("deliberate integration failure")

    monkeypatch.setattr(public_api, "_simulate_into_directory", fail_after_partial)
    with pytest.raises(RuntimeError, match="deliberate integration failure"):
        simulate(cfg)
    assert not target.exists()
    assert not list(tmp_path.glob(".failed-hf-run.staging-*"))


def test_hf_analysis_and_comparison_use_com_position_and_common_window(
    config, tmp_path: Path
) -> None:
    target = tmp_path / "hf-analysis-run"
    cfg = _api_config(config, target)
    cfg.solver.output_dt = {"value": 1.0e-5, "unit": "s"}
    validation_spec = _write_permissive_validation_spec(
        cfg, tmp_path / "hf-validation.yaml"
    )
    simulate(cfg, hf_validation_spec=validation_spec)

    analysis = analyze_run(target)
    assert analysis["model"] == "HF-DISCRETE-ROD-RIGID-BOB-1.0"
    assert analysis["raw_physical_status"] == "UNDETERMINED"
    assert (
        analysis["raw_numerical_status"]
        == "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"
    )
    certificate = read_hf_certificate_sidecar(target)["certificate"]
    if certificate["passed"]:
        assert analysis["physical_status"] == "COMPLETED_INDEPENDENTLY_CERTIFIED"
        assert (
            analysis["numerical_status"]
            == "SUCCESS_SINGLE_RUN_GUARDS_CERTIFIED_BY_VALIDATION"
        )
    else:
        assert analysis["physical_status"] == "UNDETERMINED"
        assert (
            analysis["numerical_status"]
            == "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"
        )

    comparison = compare_runs(target, target)
    assert comparison["model_a"] == "HF-DISCRETE-ROD-RIGID-BOB-1.0"
    assert comparison["model_b"] == "HF-DISCRETE-ROD-RIGID-BOB-1.0"
    assert comparison["common_interval_s"] == [0.0, 2.0e-4]
    assert comparison["maximum_position_difference_m"] == pytest.approx(0.0)

    with h5py.File(target / "result.h5", "r") as h5:
        time = np.asarray(h5["/time"], dtype=float)
        bob = np.asarray(h5["/bodies/bob/com_position"], dtype=float)
    experiment = tmp_path / "hf-cartesian.csv"
    pd.DataFrame(
        {
            "time": time,
            "x": bob[:, 0],
            "y": bob[:, 1],
            "z": bob[:, 2],
        }
    ).to_csv(experiment, index=False)
    report = compare_experiment(target, experiment)
    assert report["observation_kind"] == "cartesian_xyz"
    assert report["normalized_rms_error"] == pytest.approx(0.0, abs=1.0e-14)

    observer_summary = target / "observer_summary.json"
    original = observer_summary.read_bytes()
    observer_summary.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="identity drifted"):
        read_hf_certificate_sidecar(target, require_full=True)


def test_hf_pixel_comparison_rejects_metre_orthographic_fallback(
    config, tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "hf-observer-run"
    cfg = _api_config(config, target)
    simulate(cfg)
    monkeypatch.setattr(
        "ypendulum.hf.read_hf_certificate_sidecar",
        lambda *_args, **_kwargs: {"certificate": {"passed": True}},
    )
    pixels = tmp_path / "pixels.csv"
    pd.DataFrame(
        {
            "time": [0.0, 1.0e-4, 2.0e-4],
            "u_pixel": [0.0, 0.0, 0.0],
            "v_pixel": [0.0, 0.0, 0.0],
        }
    ).to_csv(pixels, index=False)
    with pytest.raises(ValueError, match="metre-valued or unidentified"):
        compare_experiment(target, pixels)


def test_hf_linear_modes_fail_closed_instead_of_using_a0(config, tmp_path: Path) -> None:
    cfg = _api_config(config, tmp_path / "unused")
    with pytest.raises(ValueError, match="not silently replaced"):
        analyze_linear_modes(cfg)
