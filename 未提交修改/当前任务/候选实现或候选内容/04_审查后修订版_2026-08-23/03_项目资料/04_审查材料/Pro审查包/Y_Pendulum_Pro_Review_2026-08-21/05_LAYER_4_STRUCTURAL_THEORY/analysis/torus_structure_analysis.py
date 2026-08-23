#!/usr/bin/env python3
"""Stage-4 structural analysis for the IYPT Y-shaped pendulum.

This file does not define a new forward model.  It evaluates the dimensionless
form of equations (T.13)--(T.18) from the frozen Stage-1 theory, and extracts
structural quantities (frequencies, phase drift, closure and taut-domain
boundaries).  The saved Stage-3 trajectory is only read for short-window
mechanism evidence; it is never used to manufacture a long-window frequency.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import h5py
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml
from matplotlib.colors import BoundaryNorm, ListedColormap
from scipy.integrate import solve_ivp
from scipy.optimize import brentq
from scipy.special import ellipk


THEORY_SHA256 = "7eaf18e30087438507aef73c481b49e5b1427a146d79c0fd2b35ca10dc02cdb2"
P_TARGET = 3
Q_TARGET = 2


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def rhs_dimensionless(_tau: float, state: np.ndarray, eta: float) -> np.ndarray:
    """Dimensionless Stage-1 torus equations; tau=t*sqrt(g/ell)."""

    phi, theta, phi_rate, theta_rate = state
    radius = eta + math.cos(phi)
    if radius <= 0.0:
        raise FloatingPointError("R/ell left the positive torus branch")
    phi_accel = -(
        radius * math.sin(phi) * theta_rate**2
        + math.sin(phi) * math.cos(theta)
    )
    theta_accel = (
        2.0 * math.sin(phi) * phi_rate * theta_rate - math.sin(theta)
    ) / radius
    return np.array([phi_rate, theta_rate, phi_accel, theta_accel], dtype=float)


def normalized_guards(
    states: np.ndarray, eta: float, upper_slope_ratio: float
) -> dict[str, np.ndarray]:
    """Sign-equivalent R and tension guards for a symmetric support triangle."""

    states = np.asarray(states, dtype=float)
    phi = states[..., 0]
    theta = states[..., 1]
    phi_rate = states[..., 2]
    theta_rate = states[..., 3]
    radius = eta + np.cos(phi)
    lower = (
        phi_rate**2
        + radius * np.cos(phi) * theta_rate**2
        + np.cos(phi) * np.cos(theta)
    )
    return {
        "R": radius,
        "T_A_factor": np.sin(phi) + upper_slope_ratio * np.cos(phi),
        "T_B_factor": upper_slope_ratio * np.cos(phi) - np.sin(phi),
        "T_lower_over_mg": lower,
    }


def integrate_dense(
    eta: float,
    initial: np.ndarray,
    end_time: float,
    *,
    max_step: float = 0.04,
) -> Any:
    solution = solve_ivp(
        lambda tau, state: rhs_dimensionless(tau, state, eta),
        (0.0, float(end_time)),
        np.asarray(initial, dtype=float),
        method="DOP853",
        rtol=2.0e-11,
        atol=2.0e-13,
        max_step=max_step,
        dense_output=True,
    )
    if not solution.success:
        raise RuntimeError(solution.message)
    return solution


def phase_fit(time: np.ndarray, coordinate: np.ndarray, rate: np.ndarray, omega0: float) -> dict[str, float]:
    phase = np.unwrap(np.arctan2(-rate / omega0, coordinate))
    slope, intercept = np.polyfit(time, phase, 1)
    fitted = slope * time + intercept
    residual = phase - fitted
    total = phase - np.mean(phase)
    r2 = 1.0 - float(residual @ residual) / float(total @ total)
    return {
        "omega": float(slope),
        "intercept": float(intercept),
        "phase_fit_r2": float(r2),
        "phase_residual_rms_rad": float(np.sqrt(np.mean(residual**2))),
        "phase": phase,
    }


def birkhoff_frequencies(eta: float, amplitude_phi: float, amplitude_theta: float) -> tuple[float, float, float]:
    kappa = 1.0 + eta
    omega_phi = 1.0 - amplitude_phi**2 / 16.0 + amplitude_theta**2 / 8.0
    omega_theta = (1.0 / math.sqrt(kappa)) * (
        1.0 - amplitude_theta**2 / 16.0 + amplitude_phi**2 / (8.0 * kappa)
    )
    return omega_phi, omega_theta, omega_phi / omega_theta


def mixed_case(
    eta: float,
    amplitude_phi: float,
    amplitude_theta: float,
    *,
    slow_cycles: int,
    upper_slope_ratio: float = 0.4,
) -> dict[str, Any]:
    kappa = 1.0 + eta
    nominal_slow_period = 2.0 * math.pi * math.sqrt(kappa)
    end_time = (slow_cycles + 0.75) * nominal_slow_period
    solution = integrate_dense(
        eta,
        np.array([amplitude_phi, amplitude_theta, 0.0, 0.0]),
        end_time,
    )
    sample_dt = min(0.02, nominal_slow_period / 500.0)
    time = np.arange(0.0, end_time, sample_dt)
    if time[-1] < end_time:
        time = np.append(time, end_time)
    states = np.asarray(solution.sol(time), dtype=float).T
    phi_fit = phase_fit(time, states[:, 0], states[:, 2], 1.0)
    theta_fit = phase_fit(time, states[:, 1], states[:, 3], 1.0 / math.sqrt(kappa))
    ratio = phi_fit["omega"] / theta_fit["omega"]

    target_slow_phase = 2.0 * math.pi * slow_cycles
    theta_phase = np.asarray(theta_fit["phase"])
    if theta_phase[-1] <= target_slow_phase:
        raise RuntimeError("integration window did not contain requested slow cycles")
    close_time = float(np.interp(target_slow_phase, theta_phase, time))
    close_state = np.asarray(solution.sol(close_time), dtype=float)
    phi_phase_at_close = float(np.interp(close_time, time, np.asarray(phi_fit["phase"])))
    resonant_phase_error = (
        Q_TARGET * phi_phase_at_close - P_TARGET * target_slow_phase
    )
    closure_terms = np.array(
        [
            (close_state[0] - amplitude_phi) / amplitude_phi,
            close_state[2] / amplitude_phi,
            (close_state[1] - amplitude_theta) / amplitude_theta,
            close_state[3] / (amplitude_theta / math.sqrt(kappa)),
        ],
        dtype=float,
    )
    guards = normalized_guards(states, eta, upper_slope_ratio)
    omega_phi_bnf, omega_theta_bnf, ratio_bnf = birkhoff_frequencies(
        eta, amplitude_phi, amplitude_theta
    )
    return {
        "eta": float(eta),
        "kappa": float(kappa),
        "amplitude_phi_rad": float(amplitude_phi),
        "amplitude_theta_rad": float(amplitude_theta),
        "slow_cycles": int(slow_cycles),
        "omega_phi_numerical": float(phi_fit["omega"]),
        "omega_theta_numerical": float(theta_fit["omega"]),
        "frequency_ratio_numerical": float(ratio),
        "omega_phi_birkhoff_O_A2": float(omega_phi_bnf),
        "omega_theta_birkhoff_O_A2": float(omega_theta_bnf),
        "frequency_ratio_birkhoff_O_A2": float(ratio_bnf),
        "ratio_birkhoff_minus_numerical": float(ratio_bnf - ratio),
        "phi_phase_fit_r2": float(phi_fit["phase_fit_r2"]),
        "theta_phase_fit_r2": float(theta_fit["phase_fit_r2"]),
        "phi_phase_residual_rms_rad": float(phi_fit["phase_residual_rms_rad"]),
        "theta_phase_residual_rms_rad": float(theta_fit["phase_residual_rms_rad"]),
        "closure_time_dimensionless": close_time,
        "resonant_phase_error_after_slow_cycles_rad": float(resonant_phase_error),
        "normalized_state_closure_error": float(np.linalg.norm(closure_terms)),
        "minimum_normalized_guards": {
            name: float(np.min(values)) for name, values in guards.items()
        },
    }


def pure_period_numeric(eta: float, amplitude: float, coordinate_index: int) -> float:
    kappa = 1.0 + eta
    initial = np.zeros(4)
    initial[coordinate_index] = amplitude

    def coordinate_zero(_time: float, state: np.ndarray) -> float:
        return float(state[coordinate_index])

    coordinate_zero.direction = -1
    coordinate_zero.terminal = True
    scale = 1.0 if coordinate_index == 0 else math.sqrt(kappa)
    solution = solve_ivp(
        lambda tau, state: rhs_dimensionless(tau, state, eta),
        (0.0, 3.0 * math.pi * scale),
        initial,
        method="DOP853",
        rtol=1.0e-12,
        atol=1.0e-14,
        max_step=0.01,
        events=coordinate_zero,
    )
    if not solution.t_events[0].size:
        raise RuntimeError("pure-mode quarter-period event was not found")
    return 4.0 * float(solution.t_events[0][0])


def pure_mode_checks(eta: float) -> list[dict[str, Any]]:
    kappa = 1.0 + eta
    rows: list[dict[str, Any]] = []
    for coordinate, index, length_scale in (
        ("phi_fast", 0, 1.0),
        ("theta_slow", 1, kappa),
    ):
        for amplitude in (0.05, 0.15, 0.30):
            exact = 4.0 * math.sqrt(length_scale) * float(
                ellipk(math.sin(amplitude / 2.0) ** 2)
            )
            numerical = pure_period_numeric(eta, amplitude, index)
            rows.append(
                {
                    "coordinate": coordinate,
                    "amplitude_rad": amplitude,
                    "period_exact_dimensionless": exact,
                    "period_numerical_dimensionless": numerical,
                    "relative_difference": (numerical - exact) / exact,
                }
            )
    return rows


def first_exit(
    eta: float,
    upper_slope_ratio: float,
    amplitude_phi: float,
    amplitude_theta: float,
    end_time: float,
) -> tuple[str, float]:
    initial = np.array([amplitude_phi, amplitude_theta, 0.0, 0.0], dtype=float)
    names = ("R_ZERO", "T_A_ZERO", "T_B_ZERO", "T_LOWER_ZERO")

    def component_event(index: int):
        def event(_time: float, state: np.ndarray) -> float:
            guards = normalized_guards(state[None, :], eta, upper_slope_ratio)
            values = (
                guards["R"][0],
                guards["T_A_factor"][0],
                guards["T_B_factor"][0],
                guards["T_lower_over_mg"][0],
            )
            return float(values[index])

        event.direction = -1
        event.terminal = True
        return event

    initial_guards = normalized_guards(initial[None, :], eta, upper_slope_ratio)
    if min(float(value[0]) for value in initial_guards.values()) <= 0.0:
        return "INITIAL_INVALID", 0.0
    events = [component_event(index) for index in range(4)]
    solution = solve_ivp(
        lambda tau, state: rhs_dimensionless(tau, state, eta),
        (0.0, end_time),
        initial,
        method="DOP853",
        rtol=2.0e-9,
        atol=2.0e-11,
        max_step=0.08,
        events=events,
    )
    roots = [float(values[0]) if values.size else math.inf for values in solution.t_events]
    tau = min(roots)
    if not math.isfinite(tau):
        return "TAUT_IN_WINDOW", float(end_time)
    triggered = [name for name, value in zip(names, roots) if abs(value - tau) < 1.0e-7]
    return "+".join(triggered), tau


def taut_domain_scan(output_csv: Path, eta: float, upper_slope_ratio: float) -> dict[str, Any]:
    phi_limit = math.atan(upper_slope_ratio)
    phi_grid = np.linspace(0.0, 0.99 * phi_limit, 37)
    theta_grid = np.linspace(0.0, 0.99 * math.pi / 2.0, 43)
    end_time = 6.0 * 2.0 * math.pi * math.sqrt(1.0 + eta)
    rows: list[dict[str, Any]] = []
    status_grid = np.empty((theta_grid.size, phi_grid.size), dtype=int)
    status_codes = {
        "TAUT_IN_WINDOW": 0,
        "T_A_ZERO": 1,
        "T_B_ZERO": 2,
        "T_LOWER_ZERO": 3,
        "R_ZERO": 4,
        "INITIAL_INVALID": 5,
    }
    counts: dict[str, int] = {}
    for j, amplitude_theta in enumerate(theta_grid):
        for i, amplitude_phi in enumerate(phi_grid):
            status, tau = first_exit(
                eta,
                upper_slope_ratio,
                float(amplitude_phi),
                float(amplitude_theta),
                end_time,
            )
            base_status = status.split("+")[0]
            code = status_codes.get(base_status, 6)
            status_grid[j, i] = code
            counts[status] = counts.get(status, 0) + 1
            rows.append(
                {
                    "A_phi_rad": float(amplitude_phi),
                    "A_theta_rad": float(amplitude_theta),
                    "status": status,
                    "first_exit_tau_dimensionless": float(tau),
                }
            )
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {
        "eta": eta,
        "upper_slope_ratio_a_over_h": upper_slope_ratio,
        "phi_stationary_release_geometric_limit_rad": phi_limit,
        "theta_stationary_release_lower_tension_limit_rad": math.pi / 2.0,
        "window_slow_cycles": 6,
        "phi_grid": phi_grid,
        "theta_grid": theta_grid,
        "status_grid": status_grid,
        "counts": counts,
        "csv_sha256": sha256_file(output_csv),
    }


def target_configuration_evidence(project_root: Path) -> dict[str, Any]:
    simulator_root = project_root / "第一性原理模拟" / "Y-Pendulum-Simulator-v1.0.0-rc1"
    resolved_path = simulator_root / "validation" / "target_hf_0p12_raw" / "config_resolved.yaml"
    summary_path = simulator_root / "validation" / "target_hf_0p12_raw" / "summary.json"
    diagnostics_path = simulator_root / "validation" / "target_hf_0p12_raw" / "diagnostics.json"
    h5_path = simulator_root / "validation" / "target_hf_0p12_raw" / "result.h5"
    with resolved_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    with summary_path.open("r", encoding="utf-8") as handle:
        summary = json.load(handle)
    with diagnostics_path.open("r", encoding="utf-8") as handle:
        diagnostics = json.load(handle)

    support_a = np.asarray(config["supports"]["A"]["position"], dtype=float)
    support_b = np.asarray(config["supports"]["B"]["position"], dtype=float)
    d_support = float(np.linalg.norm(support_b - support_a))
    upper = config["cables"]["upper_A"]
    lower = config["cables"]["lower"]
    upper_length = float(upper["rest_length"])
    lower_length = float(lower["rest_length"])
    h_rest = math.sqrt(upper_length**2 - (d_support / 2.0) ** 2)
    eta_rest = h_rest / lower_length
    rho_rest = math.sqrt(1.0 + eta_rest)
    target_ratio = P_TARGET / Q_TARGET
    required_h_3_2 = (target_ratio**2 - 1.0) * lower_length
    required_upper_3_2 = math.hypot(required_h_3_2, d_support / 2.0)
    required_h_4_3 = ((4.0 / 3.0) ** 2 - 1.0) * lower_length
    required_upper_4_3 = math.hypot(required_h_4_3, d_support / 2.0)

    diameter = float(upper["diameter"])
    area = math.pi * diameter**2 / 4.0
    upper_mu = float(upper["density"]) * area
    lower_mu = float(lower["density"]) * area
    total_cable_mass = 2.0 * upper_mu * upper_length + lower_mu * lower_length
    bob_mass = float(config["bob"]["mass"])
    junction_mass = float(config["junction"]["mass"])
    ea = float(upper["young_modulus"]) * area
    omega_reference = math.sqrt(float(config["environment"]["gravity"][2]) / lower_length)
    upper_wave_speed = math.sqrt(float(upper["young_modulus"]) / float(upper["density"]))
    lower_wave_speed = math.sqrt(float(lower["young_modulus"]) / float(lower["density"]))
    bob_radius = float(config["bob"]["radius"])
    bob_inertia = float(diagnostics["bob_inertia_kg_m2"])
    bending_ei = float(diagnostics["branch_bending_stiffness_N_m2"]["lower"])
    bob_weight = bob_mass * float(config["environment"]["gravity"][2])

    junction_position = np.asarray(config["initial_condition"]["junction_position"], dtype=float)
    bob_com = np.asarray(config["initial_condition"]["bob_position"], dtype=float)
    attachment_body = np.asarray(diagnostics["bob_attachment_body_m"], dtype=float)
    attachment_initial = bob_com + attachment_body
    lower_attachment_chord = float(np.linalg.norm(attachment_initial - junction_position))
    upper_chord = float(np.linalg.norm(junction_position - support_a))

    with h5py.File(h5_path, "r") as handle:
        time = np.asarray(handle["time"])
        compression_by_branch: dict[str, float] = {}
        zero_tension_by_branch: dict[str, float] = {}
        for branch in ("upper_A", "upper_B", "lower"):
            signed = np.asarray(handle[f"cables/{branch}/segments/signed_axial_force"])
            tension = np.asarray(handle[f"cables/{branch}/segments/tension"])
            compression_by_branch[branch] = float(np.mean(signed < -1.0e-12))
            zero_tension_by_branch[branch] = float(np.mean(tension <= 1.0e-12))
        bending = np.asarray(handle["energy/elastic_bending"])
        axial = np.asarray(handle["energy/elastic_axial"])
        elastic_total = bending + axial
        elastic_fraction = np.divide(
            bending,
            elastic_total,
            out=np.zeros_like(bending),
            where=elastic_total > 0.0,
        )
        guard_minima = {
            name: float(np.min(np.asarray(dataset)))
            for name, dataset in handle["validity/guard_margin"].items()
        }
        limiting_guard = min(guard_minima, key=guard_minima.get)
        limiting_index = int(
            np.argmin(np.asarray(handle[f"validity/guard_margin/{limiting_guard}"]))
        )

    return {
        "evidence_scope": "saved 0.12 s HF trajectory; short-window mechanism evidence, not frequency evidence",
        "files": {
            "config_resolved_sha256": sha256_file(resolved_path),
            "summary_sha256": sha256_file(summary_path),
            "diagnostics_sha256": sha256_file(diagnostics_path),
            "result_h5_sha256": sha256_file(h5_path),
        },
        "ideal_rest_geometry": {
            "support_separation_m": d_support,
            "upper_rest_length_m": upper_length,
            "lower_rest_length_m": lower_length,
            "h_rest_m": h_rest,
            "eta_h_over_lower": eta_rest,
            "linear_frequency_ratio": rho_rest,
            "relative_detuning_from_3_over_2": rho_rest / target_ratio - 1.0,
            "relative_detuning_from_4_over_3": rho_rest / (4.0 / 3.0) - 1.0,
            "required_h_for_3_over_2_m": required_h_3_2,
            "required_symmetric_upper_length_for_3_over_2_m": required_upper_3_2,
            "required_h_for_4_over_3_m": required_h_4_3,
            "required_symmetric_upper_length_for_4_over_3_m": required_upper_4_3,
        },
        "initial_held_geometry": {
            "upper_A_chord_m": upper_chord,
            "upper_A_chord_minus_rest_m": upper_chord - upper_length,
            "lower_attachment_chord_m": lower_attachment_chord,
            "lower_attachment_chord_minus_rest_m": lower_attachment_chord - lower_length,
            "interpretation": "held HF state requires extensible/bending rod and finite attachment; it is not an inextensible torus state",
        },
        "dimensionless_mechanism_indicators": {
            "junction_to_bob_mass_ratio": junction_mass / bob_mass,
            "total_cable_to_bob_mass_ratio": total_cable_mass / bob_mass,
            "bob_weight_over_EA": bob_weight / ea,
            "upper_wave_separation_omega_L_over_c": omega_reference * upper_length / upper_wave_speed,
            "lower_wave_separation_omega_L_over_c": omega_reference * lower_length / lower_wave_speed,
            "bending_boundary_length_over_lower": math.sqrt(bending_ei / bob_weight) / lower_length,
            "bob_radius_over_lower": bob_radius / lower_length,
            "bob_rotational_inertia_over_m_lower_squared": bob_inertia / (bob_mass * lower_length**2),
            "minimum_rod_self_clearance_over_lower": float(diagnostics["minimum_rod_self_contact_margin_m"]) / lower_length,
            "minimum_signed_force_over_bob_weight": float(summary["minimum_signed_axial_force_N"]) / bob_weight,
            "maximum_signed_force_over_bob_weight": float(summary["maximum_signed_axial_force_N"]) / bob_weight,
        },
        "saved_trajectory": {
            "duration_s": float(time[-1] - time[0]),
            "sample_count": int(time.size),
            "physical_status": summary["physical_status"],
            "numerical_status": summary["numerical_status"],
            "frequency_analysis_reliable": bool(summary["frequency_analysis_reliable"]),
            "observed_candidate_cycles": float(summary["frequency_fast_observed_cycles"]),
            "compression_fraction_by_branch": compression_by_branch,
            "zero_tension_fraction_by_branch": zero_tension_by_branch,
            "peak_bending_fraction_of_axial_plus_bending": float(np.max(elastic_fraction)),
            "minimum_guard_raw_by_component": guard_minima,
            "limiting_raw_guard": limiting_guard,
            "limiting_guard_time_s": float(time[limiting_index]),
            "max_abs_energy_balance_residual": float(summary["max_abs_energy_balance_residual"]),
            "event_count": int(summary["event_count"]),
        },
    }


def plot_design_law(path: Path, target: dict[str, Any]) -> None:
    eta = np.linspace(0.0, 3.3, 500)
    ratio = np.sqrt(1.0 + eta)
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.plot(eta, ratio, color="#1f77b4", lw=2.2, label=r"$\rho=\sqrt{1+h/\ell}$")
    rationals = [(4, 3), (3, 2), (5, 3), (2, 1)]
    for p, q in rationals:
        r = p / q
        e = r * r - 1.0
        ax.scatter([e], [r], s=48)
        ax.annotate(f"{p}:{q}", (e, r), xytext=(5, 6), textcoords="offset points")
    rest = target["ideal_rest_geometry"]
    ax.scatter(
        [rest["eta_h_over_lower"]],
        [rest["linear_frequency_ratio"]],
        marker="x",
        s=100,
        linewidths=2.5,
        color="#d62728",
        label="saved HF config: rest geometry",
    )
    ax.set_xlabel(r"geometry ratio $h/\ell$")
    ax.set_ylabel(r"linear modal ratio $\omega_\parallel/\omega_\perp$")
    ax.set_title("Y-pendulum geometry design law")
    ax.grid(alpha=0.25)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_compensation(path: Path, eta_values: np.ndarray, rows: list[dict[str, Any]], eta_bnf: float, eta_numeric: float) -> None:
    numerical = np.array([row["frequency_ratio_numerical"] for row in rows])
    birkhoff = np.array([row["frequency_ratio_birkhoff_O_A2"] for row in rows])
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.plot(eta_values, numerical, "o-", label="exact torus integration")
    ax.plot(eta_values, birkhoff, "--", label=r"quartic normal form, $O(A^2)$")
    ax.axhline(1.5, color="black", lw=1.1, label="target 3:2")
    ax.axvline(1.25, color="#777777", ls=":", label="zero-amplitude design")
    ax.axvline(eta_bnf, color="#ff7f0e", ls="-.", label="analytic amplitude compensation")
    ax.axvline(eta_numeric, color="#2ca02c", ls="-.", label="numerically tuned compensation")
    ax.set_xlabel(r"$h/\ell$")
    ax.set_ylabel(r"measured or predicted $\Omega_\parallel/\Omega_\perp$")
    ax.set_title(r"Finite-amplitude shift and geometric pre-compensation ($A_\varphi=0.15$, $A_\theta=0.10$)")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_taut_domain(path: Path, scan: dict[str, Any]) -> None:
    phi = np.asarray(scan["phi_grid"])
    theta = np.asarray(scan["theta_grid"])
    grid = np.asarray(scan["status_grid"])
    cmap = ListedColormap(["#2ca02c", "#9467bd", "#ff7f0e", "#d62728", "#1f77b4", "#7f7f7f", "#000000"])
    norm = BoundaryNorm(np.arange(-0.5, 7.5, 1.0), cmap.N)
    fig, ax = plt.subplots(figsize=(7.2, 5.0))
    mesh = ax.pcolormesh(phi, theta, grid, shading="nearest", cmap=cmap, norm=norm)
    cbar = fig.colorbar(mesh, ax=ax, ticks=range(7))
    cbar.ax.set_yticklabels(
        ["taut in 6 cycles", "A slack", "B slack", "lower slack", "R=0", "initial invalid", "multiple/other"]
    )
    ax.axvline(scan["phi_stationary_release_geometric_limit_rad"], color="black", ls="--", lw=1)
    ax.axhline(scan["theta_stationary_release_lower_tension_limit_rad"], color="black", ls="--", lw=1)
    ax.set_xlabel(r"stationary-release fast amplitude $A_\varphi$ [rad]")
    ax.set_ylabel(r"stationary-release slow amplitude $A_\theta$ [rad]")
    ax.set_title(r"Finite-window taut-domain map at $h/\ell=5/4$, $a/h=0.4$")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def json_ready(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value


def main() -> None:
    script_path = Path(__file__).resolve()
    project_root = script_path.parents[2]
    stage4_root = script_path.parents[1]
    results_dir = stage4_root / "results"
    figures_dir = stage4_root / "figures"
    results_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    theory_path = project_root / "理论" / "IYPT_2027_Y_Pendulum.md"
    actual_theory_sha = sha256_file(theory_path)
    if actual_theory_sha != THEORY_SHA256:
        raise RuntimeError(
            f"Stage-1 theory identity changed: {actual_theory_sha} != {THEORY_SHA256}"
        )

    eta_nominal = 5.0 / 4.0
    upper_slope_ratio = 0.4
    amplitude_phi = 0.15
    amplitude_theta = 0.10
    pure_checks = pure_mode_checks(eta_nominal)
    mixed_amplitude_rows = [
        mixed_case(eta_nominal, a_phi, a_theta, slow_cycles=24)
        for a_phi, a_theta in ((0.05, 0.04), (0.10, 0.06), (0.15, 0.10), (0.20, 0.12))
    ]

    kappa_nominal = 1.0 + eta_nominal
    delta_eta_bnf = (
        (kappa_nominal / 8.0 + 1.0 / 4.0) * amplitude_phi**2
        - 3.0 * kappa_nominal * amplitude_theta**2 / 8.0
    )
    eta_compensation_bnf = eta_nominal + delta_eta_bnf

    ratio_cache: dict[float, float] = {}

    def ratio_objective(eta: float) -> float:
        key = round(float(eta), 14)
        if key not in ratio_cache:
            ratio_cache[key] = mixed_case(
                float(eta), amplitude_phi, amplitude_theta, slow_cycles=18
            )["frequency_ratio_numerical"]
        return ratio_cache[key] - P_TARGET / Q_TARGET

    eta_compensation_numeric = float(
        brentq(ratio_objective, eta_nominal - 0.015, eta_nominal + 0.020, xtol=2.0e-10)
    )
    compensation_cases = {
        "zero_amplitude_geometry": mixed_case(
            eta_nominal, amplitude_phi, amplitude_theta, slow_cycles=30
        ),
        "quartic_normal_form_compensation": mixed_case(
            eta_compensation_bnf, amplitude_phi, amplitude_theta, slow_cycles=30
        ),
        "numerically_tuned_compensation": mixed_case(
            eta_compensation_numeric, amplitude_phi, amplitude_theta, slow_cycles=30
        ),
    }
    eta_values = np.linspace(eta_nominal - 0.008, eta_nominal + 0.012, 9)
    compensation_curve = [
        mixed_case(float(eta), amplitude_phi, amplitude_theta, slow_cycles=18)
        for eta in eta_values
    ]

    taut_csv = results_dir / "taut_domain_scan.csv"
    taut_scan = taut_domain_scan(taut_csv, eta_nominal, upper_slope_ratio)
    target = target_configuration_evidence(project_root)

    figure_design = figures_dir / "geometry_frequency_design.png"
    figure_compensation = figures_dir / "finite_amplitude_compensation.png"
    figure_taut = figures_dir / "taut_domain_map.png"
    plot_design_law(figure_design, target)
    plot_compensation(
        figure_compensation,
        eta_values,
        compensation_curve,
        eta_compensation_bnf,
        eta_compensation_numeric,
    )
    plot_taut_domain(figure_taut, taut_scan)

    result = {
        "schema_version": "YPS-STRUCTURE-ANALYSIS-1.0",
        "scope": "Stage-4 structural analysis; not a forward-model or HF-model redefinition",
        "identity": {
            "stage1_theory_path": str(theory_path),
            "stage1_theory_sha256": actual_theory_sha,
            "analysis_script_path": str(script_path),
            "analysis_script_sha256": sha256_file(script_path),
        },
        "normal_form": {
            "kappa_definition": "kappa=1+h/ell",
            "dimensionless_H2": "(p_phi^2+phi^2)/2 + p_theta^2/(2*kappa^2) + kappa*theta^2/2",
            "dimensionless_H4": "-phi^4/24-kappa*theta^4/24-phi^2*theta^2/4+p_theta^2*phi^2/(2*kappa^3)",
            "angle_average_H4": "-I_phi^2/16 + I_phi*I_theta/(4*kappa^(3/2)) - I_theta^2/(16*kappa^2)",
            "frequency_ratio_O_A2": "sqrt(kappa)*[1-(1/16+1/(8*kappa))*A_phi^2+(3/16)*A_theta^2]",
            "separate_reflection_selection_rule": "first ideal p:q resonant harmonic occurs no earlier than degree 2(p+q)",
        },
        "representative_3_over_2_geometry": {
            "eta_h_over_ell": eta_nominal,
            "kappa_H_over_ell": kappa_nominal,
            "symmetric_a_over_h": upper_slope_ratio,
            "upper_stationary_release_slack_angle_rad": math.atan(upper_slope_ratio),
            "lower_stationary_release_slack_angle_rad": math.pi / 2.0,
        },
        "pure_mode_period_checks": pure_checks,
        "mixed_amplitude_checks": mixed_amplitude_rows,
        "finite_amplitude_compensation": {
            "amplitude_phi_rad": amplitude_phi,
            "amplitude_theta_rad": amplitude_theta,
            "eta_zero_amplitude_design": eta_nominal,
            "delta_eta_quartic_prediction": delta_eta_bnf,
            "eta_quartic_prediction": eta_compensation_bnf,
            "eta_numerically_tuned": eta_compensation_numeric,
            "cases": compensation_cases,
            "curve": compensation_curve,
        },
        "taut_domain_scan": {
            key: value
            for key, value in taut_scan.items()
            if key not in {"phi_grid", "theta_grid", "status_grid"}
        },
        "target_hf_configuration": target,
        "figures": {
            "geometry_frequency_design": {
                "path": str(figure_design),
                "sha256": sha256_file(figure_design),
            },
            "finite_amplitude_compensation": {
                "path": str(figure_compensation),
                "sha256": sha256_file(figure_compensation),
            },
            "taut_domain_map": {
                "path": str(figure_taut),
                "sha256": sha256_file(figure_taut),
            },
        },
        "limitations": [
            "Taut scan certifies only the sampled six-slow-cycle window and grid.",
            "Mixed-mode frequencies are phase-fit finite-window rotation rates, not a proof of an invariant torus.",
            "The 0.12 s HF trajectory is too short for trustworthy swing-frequency or locking inference.",
            "No experimental data are used in this analysis.",
        ],
    }
    output_path = results_dir / "structural_analysis_results.json"
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(json_ready(result), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"output": str(output_path), "sha256": sha256_file(output_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
