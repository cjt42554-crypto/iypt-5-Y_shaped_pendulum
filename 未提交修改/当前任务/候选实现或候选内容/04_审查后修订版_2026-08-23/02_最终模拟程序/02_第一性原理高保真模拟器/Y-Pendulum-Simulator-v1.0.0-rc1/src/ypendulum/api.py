"""Public orchestration API."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import h5py
import matplotlib.pyplot as plt
import numpy as np
import yaml

from ypendulum.analysis import (
    analytic_phase,
    assess_result_validity,
    automatic_scale_diagnostics,
    dominant_frequency_estimates,
    energy_audit,
    linear_phase_drift,
    linearised_mode_summary,
    modal_coordinates,
    power_spectrum,
    resonant_phase,
    state_closure_error,
)
from ypendulum.analysis import (
    compare_run_to_experiment as _compare_run_to_experiment,
)
from ypendulum.config import (
    SimulationConfig,
    auxiliary_input_identities,
    load_config,
    resolved_config_dict,
    resolved_config_sha256,
    validate_physical_config,
)
from ypendulum.config.units import as_vector3, to_si
from ypendulum.hf import (
    HighFidelityModel,
    HighFidelityResult,
    certify_single_hf_bundle,
    read_hf_certificate_sidecar,
    simulate_high_fidelity,
    write_hf_certificate_sidecar,
)
from ypendulum.io import (
    build_provenance,
    read_h1_result,
    sha256_bytes,
    write_events,
    write_h1_result,
    write_hf_result,
    write_json,
    write_run_report,
)
from ypendulum.io.provenance import source_hash
from ypendulum.models.analytic import predict_analytic
from ypendulum.models.full_cable import FullCableModel
from ypendulum.models.state import SimulationResult, StaticEquilibrium, TorusResult
from ypendulum.models.torus import simulate_torus
from ypendulum.observers import PinholeCamera, sample_with_exposure
from ypendulum.solvers.convergence import run_convergence_matrix
from ypendulum.solvers.dynamic import simulate_full
from ypendulum.solvers.static import solve_static_equilibrium


def _project_positions(
    cfg: SimulationConfig,
    time: np.ndarray,
    bob: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, str, str]:
    if cfg.observer.type == "orthographic_xy":
        return time.copy(), bob[:, :2].copy(), "orthographic_xy_world", "m"
    camera_cfg = cfg.observer.camera
    assert camera_cfg is not None
    K = np.asarray(camera_cfg.intrinsic_matrix, dtype=float)
    R = np.asarray(camera_cfg.rotation_world_to_camera, dtype=float)
    t = as_vector3(camera_cfg.translation_world_to_camera, default_unit="m")
    camera = PinholeCamera(K, R, t, tuple(float(v) for v in camera_cfg.distortion))
    pixels = camera.project(bob)
    frame_rate = float(to_si(camera_cfg.frame_rate, default_unit="Hz"))
    exposure = float(to_si(camera_cfg.exposure_time, default_unit="s"))
    sampled_time, sampled_values = sample_with_exposure(
        time, pixels, frame_rate=frame_rate, exposure_time=exposure
    )
    return sampled_time, sampled_values, "brown_conrady_pinhole", "pixel"


def _project_observer(
    cfg: SimulationConfig, result: SimulationResult
) -> tuple[np.ndarray, np.ndarray, str, str]:
    bob = result.positions[:, -1]  # Bob is deliberately the final topology node.
    return _project_positions(cfg, result.time, bob)


def _short_window_analysis(cfg: SimulationConfig, time: np.ndarray) -> dict[str, Any]:
    return {
        "duration_s": float(time[-1] - time[0]),
        "frequency_analysis_reliable": False,
        "frequency_fast_hz": float("nan"),
        "frequency_slow_hz": float("nan"),
        "frequency_ratio": float("nan"),
        "target_ratio": list(cfg.analysis.target_ratio),
        "frequency_reliability_reason": "insufficient accepted samples for spectral inference",
    }


def _analysis_from_arrays(
    cfg: SimulationConfig,
    time: np.ndarray,
    bob_position: np.ndarray,
    bob_velocity: np.ndarray | None,
    support_a: np.ndarray,
    support_b: np.ndarray,
    gravity: np.ndarray,
) -> dict[str, Any]:
    x, y, basis = modal_coordinates(bob_position, support_a, support_b, gravity)
    duration = float(time[-1] - time[0])
    max_frequency = 0.4 / float(np.median(np.diff(time)))
    estimates = dominant_frequency_estimates(
        time,
        np.column_stack([x, y]),
        maximum_frequency=max_frequency,
        minimum_cycles=3.0,
    )
    estimate_fast, estimate_slow = estimates
    candidate_fast = float(estimate_fast.frequency_hz)
    candidate_slow = float(estimate_slow.frequency_hz)
    frequency_reliable = bool(estimate_fast.reliable and estimate_slow.reliable)
    freq_fast = candidate_fast if frequency_reliable else float("nan")
    freq_slow = candidate_slow if frequency_reliable else float("nan")
    p, q = cfg.analysis.target_ratio
    ratio = float(freq_fast / freq_slow) if frequency_reliable and freq_slow > 0.0 else float("nan")
    phase_drift = float("nan")
    hilbert_phase_drift = float("nan")
    phase_rms = float("nan")
    closure = float("nan")
    if frequency_reliable:
        phase_drift = float(2.0 * np.pi * (q * freq_fast - p * freq_slow))
        phf = analytic_phase(time, x, center_frequency=freq_fast)
        phs = analytic_phase(time, y, center_frequency=freq_slow)
        resonant = resonant_phase(phf, phs, p, q)
        edge = max(0.1 * duration, 1.0 / max(freq_slow, 1e-12))
        interior = (time >= time[0] + edge) & (time <= time[-1] - edge)
        if np.count_nonzero(interior) >= 16:
            hilbert_phase_drift, phase_rms = linear_phase_drift(time[interior], resonant[interior])
        nominal = q / freq_slow
        if bob_velocity is None:
            state = np.column_stack([x, y])
        else:
            velocity = np.asarray(bob_velocity, dtype=float)
            vx = velocity @ basis.fast
            vy = velocity @ basis.slow
            state = np.column_stack([x, y, vx, vy])
        closure = state_closure_error(time, state, nominal)
    return {
        "duration_s": duration,
        "frequency_fast_hz": float(freq_fast),
        "frequency_slow_hz": float(freq_slow),
        "frequency_ratio": ratio,
        "frequency_analysis_reliable": frequency_reliable,
        "frequency_candidate_fast_hz": candidate_fast,
        "frequency_candidate_slow_hz": candidate_slow,
        "frequency_fast_fit_r2": float(estimate_fast.fit_r2),
        "frequency_slow_fit_r2": float(estimate_slow.fit_r2),
        "frequency_fast_observed_cycles": float(estimate_fast.observed_cycles),
        "frequency_slow_observed_cycles": float(estimate_slow.observed_cycles),
        "frequency_fast_reliability_reason": estimate_fast.reason,
        "frequency_slow_reliability_reason": estimate_slow.reason,
        "target_ratio": [p, q],
        "phase_drift_rad_s": phase_drift,
        "hilbert_phase_drift_rad_s": hilbert_phase_drift,
        "phase_fit_rms_rad": phase_rms,
        "state_closure_error": closure,
    }


def _write_common_config(run_dir: Path, cfg: SimulationConfig) -> tuple[dict[str, Any], str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    original = cfg.model_dump(mode="python", exclude={"source_path"})
    resolved = resolved_config_dict(cfg)
    (run_dir / "config_original.yaml").write_text(
        yaml.safe_dump(original, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    resolved_text = yaml.safe_dump(resolved, sort_keys=False, allow_unicode=True)
    (run_dir / "config_resolved.yaml").write_text(resolved_text, encoding="utf-8")
    if cfg.source_path and Path(cfg.source_path).exists():
        (run_dir / "config_source.yaml").write_bytes(Path(cfg.source_path).read_bytes())
    return resolved, resolved_config_sha256(cfg)



def _write_analytic_hdf5(path: Path, prediction) -> None:
    units = {
        "lower_length": "m",
        "upper_drop": "m",
        "slow_length": "m",
        "omega_fast": "rad/s",
        "omega_slow": "rad/s",
        "frequency_ratio": "1",
        "detuning": "rad/s",
        "drift_time": "s",
        "nominal_close_time": "s",
        "h_over_l": "1",
    }
    with h5py.File(path, "w") as h5:
        h5.attrs["format"] = "YP-FPSim A0 result"
        h5.attrs["format_version"] = "1.0"
        h5.attrs["model"] = "A0"
        for key, value in prediction.__dict__.items():
            if key == "target_ratio":
                ds = h5.create_dataset("/analytic/target_ratio", data=np.asarray(value, dtype=int))
                ds.attrs["unit"] = "1"
                ds.attrs["description"] = "Target fast:slow integer ratio p,q"
                continue
            ds = h5.create_dataset(f"/analytic/{key}", data=value)
            ds.attrs["unit"] = units.get(key, "1")
            ds.attrs["description"] = key.replace("_", " ")

def _write_torus_hdf5(path: Path, result: TorusResult) -> None:
    with h5py.File(path, "w") as h5:
        h5.attrs["format"] = "YP-FPSim A1 result"
        h5.attrs["model"] = "A1"
        for name, data, unit, description in (
            ("/time", result.time, "s", "Simulation time"),
            ("/state/generalized", result.state, "mixed", "phi,theta,phi_dot,theta_dot"),
            ("/bodies/bob/position", result.position, "m", "Bob position"),
            ("/cables/tension", result.tensions, "N", "upper_A,upper_B,lower tensions"),
            ("/energy/mechanical", result.energy, "J", "Conserved A1 energy"),
        ):
            ds = h5.create_dataset(name, data=data)
            ds.attrs["unit"] = unit
            ds.attrs["description"] = description



def _append_analysis_hdf5(
    path: Path,
    cfg: SimulationConfig,
    time: np.ndarray,
    bob_position: np.ndarray,
    support_a: np.ndarray,
    support_b: np.ndarray,
    gravity: np.ndarray,
    summary: dict[str, Any],
) -> None:
    """Persist modal coordinates, spectra and phase series in the run HDF5."""

    x, y, _basis = modal_coordinates(bob_position, support_a, support_b, gravity)
    spectrum_fast = power_spectrum(time, x) if cfg.analysis.compute_spectrum else None
    spectrum_slow = power_spectrum(time, y) if cfg.analysis.compute_spectrum else None
    phase_fast = phase_slow = phase_resonant = None
    if summary.get("frequency_analysis_reliable", False):
        ff = float(summary["frequency_fast_hz"])
        fs = float(summary["frequency_slow_hz"])
        phase_fast = analytic_phase(time, x, center_frequency=ff)
        phase_slow = analytic_phase(time, y, center_frequency=fs)
        p, q = cfg.analysis.target_ratio
        phase_resonant = resonant_phase(phase_fast, phase_slow, p, q)

    with h5py.File(path, "a") as h5:
        group = h5.require_group("/analysis")
        group.attrs["frequency_analysis_reliable"] = bool(
            summary.get("frequency_analysis_reliable", False)
        )
        group.attrs["target_ratio_p"] = int(cfg.analysis.target_ratio[0])
        group.attrs["target_ratio_q"] = int(cfg.analysis.target_ratio[1])

        def put(name: str, data: np.ndarray, unit: str, description: str) -> None:
            if name in h5:
                del h5[name]
            ds = h5.create_dataset(name, data=np.asarray(data), compression="gzip")
            ds.attrs["unit"] = unit
            ds.attrs["description"] = description

        put("/analysis/modal/fast", x, "m", "Bob displacement along the support-axis fast coordinate")
        put("/analysis/modal/slow", y, "m", "Bob displacement along the transverse slow coordinate")
        if spectrum_fast is not None and spectrum_slow is not None:
            put(
                "/analysis/spectrum/frequency",
                spectrum_fast["frequency_hz"],
                "Hz",
                "Welch spectrum frequency bins",
            )
            put(
                "/analysis/spectrum/fast_power",
                spectrum_fast["power"],
                "m^2/Hz",
                "Welch power spectral density of the fast modal coordinate",
            )
            put(
                "/analysis/spectrum/slow_power",
                spectrum_slow["power"],
                "m^2/Hz",
                "Welch power spectral density of the slow modal coordinate",
            )
            h5["/analysis/spectrum"].attrs["window"] = spectrum_fast["window"]
            h5["/analysis/spectrum"].attrs["sample_rate_hz"] = spectrum_fast[
                "sample_rate_hz"
            ]
            h5["/analysis/spectrum"].attrs["nperseg"] = spectrum_fast["nperseg"]
        if phase_fast is not None and phase_slow is not None and phase_resonant is not None:
            put("/analysis/phase/fast", phase_fast, "rad", "Unwrapped analytic fast-mode phase")
            put("/analysis/phase/slow", phase_slow, "rad", "Unwrapped analytic slow-mode phase")
            put(
                "/analysis/phase/resonant",
                phase_resonant,
                "rad",
                "Unwrapped q*fast - p*slow resonant phase",
            )

def _write_standard_plots(run_dir: Path, result, *, model=None) -> None:
    """Write deterministic diagnostic figures without duplicating physics logic."""

    plot_dir = run_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(result, TorusResult):
        bob = result.position
        time = result.time
        tension = result.tensions
        energy = result.energy
        labels = ["upper_A", "upper_B", "lower"]
    elif isinstance(result, SimulationResult):
        bob = result.positions[:, -1]
        time = result.time
        assert model is not None
        tension = np.column_stack(
            [
                np.max(result.tension[:, model.topology.cable_slices[name]], axis=1)
                for name in ("upper_A", "upper_B", "lower")
            ]
        )
        energy = result.energy["balance_residual"]
        labels = ["upper_A", "upper_B", "lower"]
    elif isinstance(result, HighFidelityResult):
        bob = result.bob_position
        time = result.time
        tension = np.column_stack(
            [
                np.max(result.cable_tension[name], axis=1)
                for name in ("upper_A", "upper_B", "lower")
            ]
        )
        energy = result.energy["balance_residual"]
        labels = ["upper_A", "upper_B", "lower"]
    else:
        return

    fig, ax = plt.subplots()
    ax.plot(bob[:, 0], bob[:, 1])
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    fig.tight_layout()
    fig.savefig(plot_dir / "lissajous_xy.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots()
    for index, label in enumerate(labels):
        ax.plot(time, tension[:, index], label=label)
    ax.set_xlabel("time [s]")
    ax.set_ylabel("tension [N]")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plot_dir / "tension.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots()
    if isinstance(result, TorusResult):
        denominator = max(abs(float(energy[0])), 1.0e-12)
        ax.plot(time, (energy - energy[0]) / denominator)
        ax.set_ylabel("relative energy drift")
    else:
        ax.plot(time, energy)
        ax.set_ylabel("energy balance residual")
    ax.set_xlabel("time [s]")
    fig.tight_layout()
    fig.savefig(plot_dir / "energy_audit.png", dpi=160)
    plt.close(fig)



def diagnose_config(
    config: SimulationConfig | str | Path | dict[str, Any],
    *,
    solve_equilibrium: bool = True,
    write_output: str | Path | None = None,
) -> dict[str, Any]:
    """Run preflight scale, scope, observability and claim diagnostics.

    For H1 configurations the default performs the static solve because loaded
    geometry, prestress and wave scales are more relevant than natural geometry.
    This command does not perform a dynamic simulation.
    """

    cfg = config if isinstance(config, SimulationConfig) else load_config(config)
    if cfg.run.mode == "high_fidelity":
        model = HighFidelityModel(cfg)
        report = {
            "run_name": cfg.run.name,
            "mode": cfg.run.mode,
            "model_id": "HF-DISCRETE-ROD-RIGID-BOB-1.0",
            "claim_level": cfg.run.claim_level,
            "claim_readiness": {
                "requested_claim_supported": cfg.run.claim_level
                in {"DERIVED", "VERIFIED", "OUT_OF_SCOPE"},
                "configuration_claim_cap": "VERIFIED",
                "note": (
                    "This is an HF configuration/scale diagnostic. Dynamic validity "
                    "still requires the accepted-step, guard and convergence certificates."
                ),
            },
            "model_diagnostics": model.diagnostics(),
        }
        if solve_equilibrium:
            report["preparation_note"] = (
                "HF preparation is part of the registered initial-condition protocol "
                "and is certified by the actual run; no legacy H1 static solve was used."
            )
        if write_output is not None:
            write_json(Path(write_output), report)
        return report
    model = FullCableModel(cfg)
    equilibrium = None
    if solve_equilibrium and cfg.run.mode == "full":
        equilibrium = solve_static_equilibrium(cfg, model)
    report = automatic_scale_diagnostics(cfg, model, equilibrium=equilibrium)
    report["run_name"] = cfg.run.name
    report["mode"] = cfg.run.mode
    if equilibrium is not None:
        report["static_equilibrium"] = {
            "converged": equilibrium.converged,
            "force_residual_max_N": equilibrium.force_residual_max,
            "iterations": equilibrium.iterations,
            "metadata": equilibrium.metadata,
        }
    if write_output is not None:
        write_json(Path(write_output), report)
    return report

def _simulate_into_directory(
    cfg: SimulationConfig,
    run_dir: Path,
    *,
    equilibrium: StaticEquilibrium | None = None,
    write_output: bool = True,
    hf_checkpoint_path: str | Path | None = None,
    hf_resume_checkpoint: bool = False,
):
    resolved, config_hash = _write_common_config(run_dir, cfg) if write_output else ({}, "")

    if cfg.run.mode == "analytic":
        prediction = predict_analytic(cfg)
        summary = {
            "run_name": cfg.run.name,
            "model": "A0",
            "claim_level": cfg.run.claim_level,
            "status": "success",
            **prediction.__dict__,
        }
        if write_output:
            _write_analytic_hdf5(run_dir / "result.h5", prediction)
            write_json(run_dir / "summary.json", summary)
            provenance = build_provenance(
                project_root=Path(__file__).resolve().parents[2],
                config_hash=config_hash,
                seed=cfg.run.seed,
                solver={"method": "analytic"},
                mesh={"model": "A0", "elements": 0},
                claim_level=cfg.run.claim_level,
                assumptions=["linear small-amplitude analytic model"],
            )
            write_json(run_dir / "provenance.json", provenance)
            write_run_report(run_dir / "report.md", summary, {})
        return prediction

    if cfg.run.mode == "torus":
        result = simulate_torus(cfg)
        support_a = as_vector3(cfg.supports.A.position, default_unit="m")
        support_b = as_vector3(cfg.supports.B.position, default_unit="m")
        gravity = as_vector3(cfg.environment.gravity, default_unit="m/s^2")
        summary = {
            "run_name": cfg.run.name,
            "model": "A1",
            "claim_level": cfg.run.claim_level,
            "status": "success",
            **_analysis_from_arrays(
                cfg, result.time, result.position, None, support_a, support_b, gravity
            ),
            "max_relative_energy_drift": float(
                np.max(np.abs(result.energy - result.energy[0]))
                / max(abs(float(result.energy[0])), 1e-12)
            ),
            "event": result.event,
        }
        if write_output:
            _write_torus_hdf5(run_dir / "result.h5", result)
            _append_analysis_hdf5(
                run_dir / "result.h5",
                cfg,
                result.time,
                result.position,
                support_a,
                support_b,
                gravity,
                summary,
            )
            write_json(run_dir / "summary.json", summary)
            write_json(run_dir / "diagnostics.json", {"event": result.event})
            write_events(run_dir / "events.csv", [] if result.event is None else [result.event])
            provenance = build_provenance(
                project_root=Path(__file__).resolve().parents[2],
                config_hash=config_hash,
                seed=cfg.run.seed,
                solver={"method": "DOP853", "rtol": 1e-10, "atol": 1e-12},
                mesh={"model": "A1", "elements": 0},
                claim_level=cfg.run.claim_level,
                assumptions=["massless inextensible strings", "massless junction", "all-taut until event"],
            )
            write_json(run_dir / "provenance.json", provenance)
            write_run_report(run_dir / "report.md", summary, {"event": result.event})
            _write_standard_plots(run_dir, result)
        return result

    if cfg.run.mode == "high_fidelity":
        model = HighFidelityModel(cfg)
        result = simulate_high_fidelity(
            cfg,
            model=model,
            checkpoint_path=hf_checkpoint_path,
            resume_from_checkpoint=hf_resume_checkpoint,
        )
        result.run_directory = run_dir if write_output else None
        support_a, _, _ = model.support_motion["support_A"].state(0.0)
        support_b, _, _ = model.support_motion["support_B"].state(0.0)
        if result.time.size >= 16:
            analysis = _analysis_from_arrays(
                cfg,
                result.time,
                result.bob_position,
                result.bob_velocity,
                support_a,
                support_b,
                model.gravity,
            )
        else:
            analysis = _short_window_analysis(cfg, result.time)
        if (
            result.physical_status == "OUT_OF_SCOPE"
            and result.numerical_status == "SUCCESS_EVENT"
        ):
            run_status = "out_of_scope_prefix"
        else:
            # A no-event HF integration is deliberately provisional until the
            # accepted-step trace has been checked by the independent
            # reference/certificate layer.  The raw result is never relabelled
            # here, even when a full certificate is requested by ``simulate``.
            run_status = "undetermined"
        summary = {
            "run_name": cfg.run.name,
            "model": result.model_id,
            "claim_level": cfg.run.claim_level,
            "status": run_status,
            "physical_status": result.physical_status,
            "numerical_status": result.numerical_status,
            "valid_interval_s": list(result.valid_interval),
            **analysis,
            "minimum_tension_N": result.diagnostics["minimum_tension_N"],
            "maximum_tension_N": result.diagnostics["maximum_tension_N"],
            "minimum_signed_axial_force_N": result.diagnostics[
                "minimum_signed_axial_force_N"
            ],
            "maximum_signed_axial_force_N": result.diagnostics[
                "maximum_signed_axial_force_N"
            ],
            "max_abs_energy_balance_residual": result.diagnostics[
                "max_abs_energy_balance_residual"
            ],
            "maximum_quaternion_norm_error": result.diagnostics[
                "maximum_quaternion_norm_error"
            ],
            "bending_energy_fraction_peak": result.diagnostics[
                "bending_energy_fraction_peak"
            ],
            "accepted_integration_step_count": result.diagnostics[
                "accepted_integration_step_count"
            ],
            "event_count": len(result.events),
        }
        if write_output:
            write_hf_result(run_dir / "result.h5", result, model)
            if result.time.size >= 16:
                _append_analysis_hdf5(
                    run_dir / "result.h5",
                    cfg,
                    result.time,
                    result.bob_position,
                    support_a,
                    support_b,
                    model.gravity,
                    summary,
                )
            observer_time, observer_values, operator_id, value_unit = _project_positions(
                cfg, result.time, result.bob_position
            )
            np.savez_compressed(
                run_dir / "observer_output.npz",
                time=observer_time,
                values=observer_values,
                operator_id=np.asarray(operator_id),
                value_unit=np.asarray(value_unit),
            )
            write_json(
                run_dir / "observer_summary.json",
                {
                    "operator_id": operator_id,
                    "value_unit": value_unit,
                    "coordinate_source": "rigid_bob_center_of_mass",
                    "sample_count": int(observer_time.size),
                },
            )
            write_json(run_dir / "summary.json", summary)
            write_json(run_dir / "diagnostics.json", result.diagnostics)
            write_events(run_dir / "events.csv", result.events)
            write_json(run_dir / "events.json", result.events)
            provenance = build_provenance(
                project_root=Path(__file__).resolve().parents[2],
                config_hash=config_hash,
                seed=cfg.run.seed,
                solver={
                    key: result.diagnostics[key]
                    for key in (
                        "solver_method",
                        "rtol",
                        "position_atol_m",
                        "velocity_atol_m_s",
                        "quaternion_atol",
                        "angular_velocity_atol_rad_s",
                        "max_step_s",
                    )
                },
                mesh={
                    "model_id": result.model_id,
                    "material_particles": model.particle_count,
                    "branch_beads": result.diagnostics["branch_beads"],
                },
                claim_level=cfg.run.claim_level,
                assumptions=[
                    (
                        "local passive unilateral/bilateral Kelvin-Voigt blend "
                        "with non-zero three-point bending"
                    ),
                    "finite spherical rigid bob with eccentric material attachment",
                    "finite-mass translational junction without connector rotation",
                    (
                        "registered rod/bob contact ends the valid prefix; frictional "
                        "contact dynamics, fracture and knot sliding remain outside scope"
                    ),
                ],
            )
            write_json(run_dir / "provenance.json", provenance)
            write_run_report(run_dir / "report.md", summary, result.diagnostics)
            _write_standard_plots(run_dir, result, model=model)
        return result

    model = FullCableModel(cfg)
    preflight = automatic_scale_diagnostics(cfg, model, equilibrium=equilibrium)
    result = simulate_full(cfg, model=model, equilibrium=equilibrium)
    preflight = automatic_scale_diagnostics(
        cfg, model, loaded_positions=result.positions[0]
    )
    validity = assess_result_validity(cfg, model, result, preflight=preflight)
    result.run_directory = run_dir if write_output else None
    support_a = result.positions[0, 0]
    support_b = result.positions[0, 1]
    gravity = model.gravity
    bob = result.positions[:, model.topology.bob_node]
    bob_v = result.velocities[:, model.topology.bob_node]
    summary = {
        "run_name": cfg.run.name,
        "model": "H1",
        "claim_level": cfg.run.claim_level,
        "status": "success",
        **_analysis_from_arrays(cfg, result.time, bob, bob_v, support_a, support_b, gravity),
        "minimum_tension_N": float(np.min(result.tension)),
        "maximum_tension_N": float(np.max(result.tension)),
        "event_count": len(result.events),
        "configuration_claim_cap": preflight["claim_readiness"]["configuration_claim_cap"],
        "requested_claim_supported": preflight["claim_readiness"]["requested_claim_supported"],
        "run_validity_status": validity["status"],
        "observable_support": validity["observable_support"],
        **energy_audit(result.energy),
    }
    structural_events = [
        event
        for event in result.events
        if event.get("type")
        in {
            "cable_slack",
            "cable_retension",
            "cable_initially_not_fully_taut",
            "cable_fully_unloaded",
            "cable_first_local_retension",
            "upper_branch_switch",
            "element_slack",
            "element_retension",
        }
    ]
    if structural_events:
        summary["frequency_analysis_reliable"] = False
        summary["frequency_analysis_note"] = (
            "Structural slack/retension events make a stationary two-frequency fit invalid."
        )
    if write_output:
        observer_time, observer_values, observer_operator, observer_unit = _project_observer(
            cfg, result
        )
        write_h1_result(
            run_dir / "result.h5",
            result,
            model,
            observer_pixels=observer_values if cfg.observer.type == "pinhole" else None,
            observer_time=observer_time if cfg.observer.type == "pinhole" else None,
        )
        _append_analysis_hdf5(
            run_dir / "result.h5",
            cfg,
            result.time,
            bob,
            support_a,
            support_b,
            gravity,
            summary,
        )
        if observer_values is not None:
            np.savez_compressed(
                run_dir / "observer_output.npz",
                time=observer_time,
                values=observer_values,
                operator_id=np.asarray(observer_operator),
                value_unit=np.asarray(observer_unit),
            )
            write_json(
                run_dir / "observer_summary.json",
                {
                    "operator_id": observer_operator,
                    "value_unit": observer_unit,
                    "coordinate_source": "bob_center_of_mass",
                    "sample_count": int(observer_time.size),
                },
            )
        write_json(run_dir / "summary.json", summary)
        combined_diagnostics = {
            "solver_and_model": result.diagnostics,
            "preflight": preflight,
            "result_validity": validity,
        }
        write_json(run_dir / "diagnostics.json", combined_diagnostics)
        write_events(run_dir / "events.csv", result.events)
        provenance = build_provenance(
            project_root=Path(__file__).resolve().parents[2],
            config_hash=config_hash,
            seed=cfg.run.seed,
            solver={
                key: result.diagnostics.get(key)
                for key in (
                    "solver_method",
                    "solver_profile",
                    "rtol",
                    "position_atol",
                    "velocity_atol",
                    "max_step",
                    "jacobian_kind",
                )
            },
            mesh={
                "nodes": model.topology.node_count,
                "elements": model.topology.elements.count,
                "cable_elements": {
                    name: sl.stop - sl.start for name, sl in model.topology.cable_slices.items()
                },
                "mass_matrix": cfg.solver.mass_matrix,
            },
            claim_level=cfg.run.claim_level,
            assumptions=[
                "fixed material knot; no sliding",
                "axial cable/truss; no bending or torsion",
                "bob force line through centre of mass",
            ],
        )
        write_json(run_dir / "provenance.json", provenance)
        write_run_report(run_dir / "report.md", summary, combined_diagnostics)
        _write_standard_plots(run_dir, result, model=model)
    return result


def simulate(
    config: SimulationConfig | str | Path | dict[str, Any],
    *,
    equilibrium: StaticEquilibrium | None = None,
    hf_validation_spec: str | Path | None = None,
    hf_checkpoint_path: str | Path | None = None,
    hf_resume_checkpoint: bool = False,
    write_output: bool = True,
):
    """Run one model and publish a complete directory only after success.

    The public runner deliberately refuses an existing output directory.  A
    failed run is confined to a same-parent staging directory and cannot leave
    a new configuration beside stale trajectory files from an earlier run.
    """

    cfg = config if isinstance(config, SimulationConfig) else load_config(config)
    validate_physical_config(cfg)
    if hf_validation_spec is not None and cfg.run.mode != "high_fidelity":
        raise ValueError(
            "hf_validation_spec is accepted only for high_fidelity runs."
        )
    if hf_validation_spec is not None and not write_output:
        raise ValueError(
            "A full HF validation certificate requires an atomically published "
            "artifact directory; call certify_single_hf_bundle directly for an "
            "in-memory diagnostic."
        )
    hf_validation_spec_source = (
        Path(hf_validation_spec).expanduser().resolve()
        if hf_validation_spec is not None
        else None
    )
    hf_validation_spec_bytes = (
        hf_validation_spec_source.read_bytes()
        if hf_validation_spec_source is not None
        else None
    )
    target = Path(cfg.run.output_directory).expanduser().resolve()
    if (
        write_output
        and cfg.run.mode == "high_fidelity"
        and hf_checkpoint_path is None
    ):
        hf_checkpoint_path = target.parent / f".{target.name}.integration-checkpoint.npz"
    if not write_output:
        return _simulate_into_directory(
            cfg,
            target,
            equilibrium=equilibrium,
            write_output=False,
            hf_checkpoint_path=hf_checkpoint_path,
            hf_resume_checkpoint=hf_resume_checkpoint,
        )
    if target.exists():
        raise FileExistsError(
            f"Output directory already exists and will not be mixed or overwritten: {target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent)
    )
    package_root = Path(__file__).resolve().parent
    source_start = source_hash(package_root)
    config_start = resolved_config_sha256(cfg)
    auxiliary_start = auxiliary_input_identities(cfg)
    try:
        result = _simulate_into_directory(
            cfg,
            staging,
            equilibrium=equilibrium,
            write_output=True,
            hf_checkpoint_path=hf_checkpoint_path,
            hf_resume_checkpoint=hf_resume_checkpoint,
        )
        source_after_run = source_hash(package_root)
        config_after_run = resolved_config_sha256(cfg)
        auxiliary_after_run = auxiliary_input_identities(cfg)
        if source_after_run != source_start:
            raise RuntimeError(
                "Executable source changed during the run; staged evidence was not published."
            )
        if (
            config_after_run != config_start
            or auxiliary_after_run != auxiliary_start
        ):
            raise RuntimeError(
                "Resolved configuration or auxiliary input changed during the run; "
                "staged evidence was not published."
            )
        resolved_path = staging / "config_resolved.yaml"
        execution_identity = {
            "source_hash_start_sha256": source_start,
            "source_hash_end_sha256": source_after_run,
            "source_stable_during_run": True,
            "config_resolved_sha256": config_start,
            "config_resolved_file_sha256": sha256_bytes(resolved_path.read_bytes()),
            "config_stable_during_run": True,
            "auxiliary_inputs_start": auxiliary_start,
            "auxiliary_inputs_end": auxiliary_after_run,
            "auxiliary_inputs_stable_during_run": True,
            "model": getattr(result, "model_id", getattr(result, "model_name", cfg.run.mode)),
            "units": "SI",
        }
        write_json(staging / "execution_identity.json", execution_identity)
        if cfg.run.mode == "high_fidelity" and hf_validation_spec_bytes is not None:
            frozen_validation_spec = None
            frozen_validation_spec = staging / "hf_validation_spec.yaml"
            frozen_validation_spec.write_bytes(hf_validation_spec_bytes)
            certificate = certify_single_hf_bundle(
                cfg,
                result,
                validation_spec=frozen_validation_spec,
            )
            write_hf_certificate_sidecar(staging, certificate)
        source_end = source_hash(package_root)
        config_end = resolved_config_sha256(cfg)
        auxiliary_end = auxiliary_input_identities(cfg)
        if source_end != source_start:
            raise RuntimeError(
                "Executable source changed during HF certification; staged evidence "
                "was not published."
            )
        if config_end != config_start or auxiliary_end != auxiliary_start:
            raise RuntimeError(
                "Resolved configuration or auxiliary input changed during HF "
                "certification; staged evidence was not published."
            )
        if (
            hf_validation_spec_source is not None
            and hf_validation_spec_source.read_bytes() != hf_validation_spec_bytes
        ):
            raise RuntimeError(
                "HF validation specification changed during the run; staged "
                "evidence was not published."
            )
        if target.exists():
            raise FileExistsError(
                f"Output target appeared during execution; staged result retained no mixed commit: {target}"
            )
        os.replace(staging, target)
        if hasattr(result, "run_directory"):
            result.run_directory = target
        return result
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def analyze_run(run: str | Path | SimulationResult) -> dict[str, Any]:
    if isinstance(run, SimulationResult):
        if run.run_directory is None:
            return {
                "model": run.model_name,
                "duration_s": float(run.time[-1] - run.time[0]),
                **energy_audit(run.energy),
            }
        directory = run.run_directory
    else:
        directory = Path(run)
    # New runs persist an exact, replayable protocol-specific configuration.
    # Prefer it over the legacy full-model dump, whose default fields may look
    # like explicitly requested but unconsumed HF initial-condition inputs.
    resolved_config_path = directory / "config_resolved.yaml"
    config_path = (
        resolved_config_path
        if resolved_config_path.is_file()
        else directory / "config_original.yaml"
    )
    cfg = load_config(config_path)
    if not (directory / "result.h5").exists():
        summary_path = directory / "summary.json"
        if summary_path.exists():
            return json.loads(summary_path.read_text(encoding="utf-8"))
        raise FileNotFoundError(f"No result.h5 or summary.json found in {directory}.")
    with h5py.File(directory / "result.h5", "r") as h5:
        model_name = str(h5.attrs.get("model", "H1"))
    if model_name == "A0":
        summary_path = directory / "summary.json"
        if summary_path.exists():
            analysis = json.loads(summary_path.read_text(encoding="utf-8"))
        else:
            with h5py.File(directory / "result.h5", "r") as h5:
                analysis = {
                    "model": "A0",
                    **{key: np.asarray(value)[()].tolist() if np.asarray(value).ndim else float(np.asarray(value)[()])
                       for key, value in h5["/analytic"].items()},
                }
        write_json(directory / "analysis.json", analysis)
        return analysis
    if model_name == "A1":
        with h5py.File(directory / "result.h5", "r") as h5:
            time = np.asarray(h5["/time"])
            bob = np.asarray(h5["/bodies/bob/position"])
            energy = np.asarray(h5["/energy/mechanical"])
        support_a = as_vector3(cfg.supports.A.position, default_unit="m")
        support_b = as_vector3(cfg.supports.B.position, default_unit="m")
        gravity = as_vector3(cfg.environment.gravity, default_unit="m/s^2")
        analysis = _analysis_from_arrays(
            cfg, time, bob, None, support_a, support_b, gravity
        )
        analysis["model"] = "A1"
        analysis["max_relative_energy_drift"] = float(
            np.max(np.abs(energy - energy[0])) / max(abs(float(energy[0])), 1.0e-12)
        )
        write_json(directory / "analysis.json", analysis)
        return analysis
    if model_name == "HF-DISCRETE-ROD-RIGID-BOB-1.0":
        sidecar_path = directory / "hf_single_bundle_certificate.json"
        certificate = None
        if sidecar_path.is_file():
            certificate = read_hf_certificate_sidecar(
                directory, require_full=False
            )["certificate"]
        with h5py.File(directory / "result.h5", "r") as h5:
            raw_physical_status = str(h5.attrs.get("physical_status", ""))
            raw_numerical_status = str(h5.attrs.get("numerical_status", ""))
            if (
                raw_physical_status == "UNDETERMINED"
                and raw_numerical_status
                == "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"
            ):
                if certificate is not None and certificate.get("passed") is True:
                    read_hf_certificate_sidecar(directory, require_full=True)
                    certified = certificate["certified_status_pair"]
                    physical_status = str(certified["physical_status"])
                    numerical_status = str(certified["numerical_status"])
                    interpretation = "INDEPENDENTLY_CERTIFIED"
                else:
                    physical_status = raw_physical_status
                    numerical_status = raw_numerical_status
                    interpretation = (
                        "RAW_PERSONAL_RESEARCH_RESULT; sampled guards are positive "
                        "but continuous guard certification was not requested"
                    )
            elif (
                raw_physical_status == "OUT_OF_SCOPE"
                and raw_numerical_status == "SUCCESS_EVENT"
            ):
                physical_status = raw_physical_status
                numerical_status = raw_numerical_status
                interpretation = "VALID_PREFIX_TERMINATED_AT_REPORTED_EVENT"
            else:
                raise ValueError(
                    "HF analysis refuses an unresolved trajectory: "
                    f"{raw_physical_status}/{raw_numerical_status}."
                )
            time = np.asarray(h5["/time"], dtype=float)
            bob = np.asarray(h5["/bodies/bob/com_position"], dtype=float)
            bob_velocity = np.asarray(h5["/bodies/bob/com_velocity"], dtype=float)
            support_a = np.asarray(
                h5["/cables/upper_A/material_path/position"][0, 0], dtype=float
            )
            support_b = np.asarray(
                h5["/cables/upper_B/material_path/position"][0, 0], dtype=float
            )
            balance = np.asarray(h5["/energy/balance_residual"], dtype=float)
        gravity = as_vector3(cfg.environment.gravity, default_unit="m/s^2")
        analysis = {
            "model": model_name,
            "physical_status": physical_status,
            "numerical_status": numerical_status,
            "raw_physical_status": raw_physical_status,
            "raw_numerical_status": raw_numerical_status,
            "result_interpretation": interpretation,
            "certificate_schema_version": (
                certificate["schema_version"] if certificate is not None else None
            ),
            "certificate_sha256": (
                certificate["certificate_sha256"] if certificate is not None else None
            ),
            **_analysis_from_arrays(
                cfg,
                time,
                bob,
                bob_velocity,
                support_a,
                support_b,
                gravity,
            ),
            "max_abs_energy_balance_residual": float(np.max(np.abs(balance))),
        }
        write_json(directory / "analysis.json", analysis)
        return analysis
    data = read_h1_result(directory / "result.h5")
    support_a = data["positions"][0, 0]
    support_b = data["positions"][0, 1]
    gravity = as_vector3(cfg.environment.gravity, default_unit="m/s^2")
    analysis = _analysis_from_arrays(
        cfg,
        data["time"],
        data["bob_position"],
        None,
        support_a,
        support_b,
        gravity,
    )
    analysis["max_abs_energy_balance_residual"] = float(
        np.max(np.abs(data["energy_balance_residual"]))
    )
    write_json(directory / "analysis.json", analysis)
    return analysis



def analyze_linear_modes(
    config: SimulationConfig | str | Path | dict[str, Any],
    *,
    count: int = 2,
) -> dict[str, Any]:
    """Compute small-vibration modes from the H1 static equilibrium."""

    cfg = config if isinstance(config, SimulationConfig) else load_config(config)
    if cfg.run.mode == "high_fidelity":
        raise ValueError(
            "HF linear modes are not silently replaced by the A0 analytic limit. "
            "A registered rigid-bob/discrete-rod equilibrium linearisation is not "
            "implemented; use hf-validate for the supported dynamic certificate."
        )
    if cfg.run.mode != "full":
        prediction = predict_analytic(cfg)
        return {
            "model": "A0 analytic limit",
            "claim_level": cfg.run.claim_level,
            "modes": [
                {"descriptive_label": "transverse_slow", "angular_frequency_rad_s": prediction.omega_slow, "frequency_hz": prediction.omega_slow / (2.0 * np.pi)},
                {"descriptive_label": "support_axis_fast", "angular_frequency_rad_s": prediction.omega_fast, "frequency_hz": prediction.omega_fast / (2.0 * np.pi)},
            ],
        }
    if count < 1:
        raise ValueError("Mode count must be positive.")
    model = FullCableModel(cfg)
    equilibrium = solve_static_equilibrium(cfg, model)
    modes = linearised_mode_summary(model, equilibrium.positions, count=count)
    return {
        "model": "H1 linearisation",
        "claim_level": cfg.run.claim_level,
        "static_force_residual_N": equilibrium.force_residual_max,
        "node_count": model.topology.node_count,
        "element_count": model.topology.elements.count,
        "modes": modes,
        "diagnostics": model.diagnostics(),
    }

def run_convergence_study(
    config: SimulationConfig | str | Path | dict[str, Any],
    *,
    write_output: bool = True,
) -> dict[str, Any]:
    cfg = config if isinstance(config, SimulationConfig) else load_config(config)
    if cfg.run.mode != "full":
        raise ValueError("Convergence study requires full H1 mode.")
    output = None
    if write_output:
        output = Path(cfg.run.output_directory).parent / f"{cfg.run.name}_convergence"
    return run_convergence_matrix(cfg, output_directory=output)


def compare_runs(run_a: str | Path, run_b: str | Path) -> dict[str, Any]:
    def generic(directory: str | Path) -> dict[str, np.ndarray]:
        root = Path(directory)
        path = root / "result.h5"
        with h5py.File(path, "r") as h5:
            model = str(h5.attrs.get("model", ""))
            if model == "HF-DISCRETE-ROD-RIGID-BOB-1.0":
                physical_status = str(h5.attrs.get("physical_status", ""))
                numerical_status = str(h5.attrs.get("numerical_status", ""))
                if (physical_status, numerical_status) not in {
                    (
                        "UNDETERMINED",
                        "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED",
                    ),
                    ("OUT_OF_SCOPE", "SUCCESS_EVENT"),
                }:
                    raise ValueError(
                        "compare_runs refuses a failed or numerically unresolved "
                        f"HF trajectory: {physical_status}/{numerical_status}."
                    )
            else:
                physical_status = str(h5.attrs.get("physical_status", ""))
                numerical_status = str(h5.attrs.get("numerical_status", ""))
            bob_path = (
                "/bodies/bob/com_position"
                if model == "HF-DISCRETE-ROD-RIGID-BOB-1.0"
                else "/bodies/bob/position"
            )
            return {
                "time": np.asarray(h5["/time"]),
                "bob_position": np.asarray(h5[bob_path]),
                "model": model,
                "physical_status": physical_status,
                "numerical_status": numerical_status,
            }

    a = generic(run_a)
    b = generic(run_b)
    for label, item in (("run_a", a), ("run_b", b)):
        if not (
            item["time"].ndim == 1
            and item["time"].size >= 2
            and item["bob_position"].shape == (item["time"].size, 3)
            and np.all(np.isfinite(item["time"]))
            and np.all(np.isfinite(item["bob_position"]))
            and np.all(np.diff(item["time"]) > 0.0)
        ):
            raise ValueError(f"{label} is not a finite canonical trajectory.")
    start = max(float(a["time"][0]), float(b["time"][0]))
    end = min(float(a["time"][-1]), float(b["time"][-1]))
    if not start < end:
        raise ValueError("compare_runs requires a non-empty common time interval.")
    interior = a["time"][(a["time"] >= start) & (a["time"] <= end)]
    t = np.unique(np.concatenate([[start], interior, [end]]))
    if t.size < 2:
        raise ValueError("compare_runs common interval has fewer than two samples.")
    bob_a = np.column_stack(
        [np.interp(t, a["time"], a["bob_position"][:, j]) for j in range(3)]
    )
    bob_b = np.column_stack(
        [np.interp(t, b["time"], b["bob_position"][:, j]) for j in range(3)]
    )
    diff = bob_a - bob_b
    scale = max(
        float(np.sqrt(np.mean((bob_a - np.mean(bob_a, axis=0)) ** 2))),
        1e-12,
    )
    return {
        "trajectory_normalized_rms": float(np.sqrt(np.mean(diff**2)) / scale),
        "maximum_position_difference_m": float(np.max(np.linalg.norm(diff, axis=1))),
        "run_a": str(run_a),
        "run_b": str(run_b),
        "model_a": a["model"],
        "model_b": b["model"],
        "status_a": {
            "physical_status": a["physical_status"],
            "numerical_status": a["numerical_status"],
        },
        "status_b": {
            "physical_status": b["physical_status"],
            "numerical_status": b["numerical_status"],
        },
        "common_interval_s": [start, end],
        "sample_count": int(t.size),
    }


def compare_experiment(
    run_directory: str | Path,
    experiment_csv: str | Path,
    *,
    estimate_time_shift: bool = False,
    maximum_time_shift_s: float = 0.0,
    estimate_translation: bool = False,
    estimate_planar_rotation: bool = False,
    output_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Compare a frozen forward run with experimental positions or pixels."""

    from ypendulum.analysis.experiment import AlignmentOptions
    options = AlignmentOptions(
        estimate_time_shift=estimate_time_shift,
        maximum_time_shift_s=maximum_time_shift_s,
        estimate_translation=estimate_translation,
        estimate_planar_rotation=estimate_planar_rotation,
    )
    return _compare_run_to_experiment(
        run_directory,
        experiment_csv,
        options=options,
        output_directory=output_directory,
    )
