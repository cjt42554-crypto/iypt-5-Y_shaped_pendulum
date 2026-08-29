"""Configuration-driven ideal-torus pattern atlas.

The atlas is a consumer of the formal FWD-TORUS-1.0 backend.  It does not
carry a second copy of the torus equations and it never interprets numerical
tuning as experimental calibration.
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg", force=True)

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np
from scipy.optimize import brentq
from scipy.special import ellipk

from .backend import (
    FormalTorusBackend,
    find_repository_root,
    load_formal_backend,
)
from .source_manifest import (
    ATLAS_IDENTITY,
    FORMAL_BACKEND_RELATIVE_PATH,
    FORMAL_CONTRACTS_RELATIVE_PATH,
    FORMAL_THEORY_RELATIVE_PATH,
    BoundSourceManifest,
    load_json_strict,
    sha256_file,
    validate_json_contract,
    verify_source_manifest,
)

matplotlib.rcParams["svg.fonttype"] = "none"
matplotlib.rcParams["svg.hashsalt"] = "yps-ideal-torus-pattern-atlas-1.1"


CONFIG_SCHEMA = "YPS-FORMAL-PATTERN-ATLAS-CONFIG-1.1"
OUTPUT_SCHEMA = "YPS-FORMAL-PATTERN-ATLAS-OUTPUT-1.1"
RUN_EVIDENCE_SCHEMA = "YPS-FORMAL-PATTERN-ATLAS-RUN-EVIDENCE-1.0"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "atlas_config.schema.json"
OUTPUT_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "atlas_output.schema.json"
RUN_EVIDENCE_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "atlas_run_evidence.schema.json"
CLAIM_LIMIT = (
    "Ideal symmetric all-taut torus model only; numerical tuning is internal "
    "to FWD-TORUS-1.0 and is neither device calibration nor experimental validation."
)
FIGURE_METADATA = {
    "Creator": ATLAS_IDENTITY,
    "Date": None,
}


@dataclass(frozen=True, order=True)
class Target:
    p: int
    q: int

    def __post_init__(self) -> None:
        if type(self.p) is not int or type(self.q) is not int:
            raise ValueError("Target p and q must be JSON integers without conversion.")
        if self.p <= 0 or self.q <= 0 or math.gcd(self.p, self.q) != 1:
            raise ValueError("Target p:q must be a positive reduced ratio.")
        if self.p <= self.q:
            raise ValueError("This torus atlas requires a fast:slow ratio p:q > 1.")

    @property
    def label(self) -> str:
        return f"{self.p}:{self.q}"

    @property
    def ratio(self) -> float:
        return self.p / self.q

    @property
    def eta0(self) -> float:
        return self.ratio**2 - 1.0


def _load_config(path: Path) -> dict[str, Any]:
    config = load_json_strict(path)
    validate_json_contract(config, CONFIG_SCHEMA_PATH, label="atlas configuration")
    if not isinstance(config, dict):
        raise ValueError("Atlas configuration must be a JSON object.")
    targets = _targets(config)
    amplitudes = _amplitudes(config)
    slow_cycles = config["analysis"]["slow_cycles"]
    if any(slow_cycles % target.q != 0 for target in targets):
        raise ValueError(
            "analysis.slow_cycles must contain an integer number of common "
            "pattern periods for every target denominator."
        )
    if not amplitudes:
        raise ValueError("At least one amplitude pair is required.")
    if (
        config["numerics"]["step_halving_maximum_step"]
        >= config["numerics"]["maximum_step"]
    ):
        raise ValueError(
            "numerics.step_halving_maximum_step must be smaller than maximum_step."
        )
    return config


def _targets(config: dict[str, Any]) -> tuple[Target, ...]:
    raw = config.get("targets")
    if not isinstance(raw, list) or not raw:
        raise ValueError("targets must be a non-empty array.")
    targets = tuple(Target(item["p"], item["q"]) for item in raw)
    if len(targets) != len(set(targets)):
        raise ValueError("Target ratios must be unique.")
    return targets


def _amplitudes(config: dict[str, Any]) -> tuple[tuple[float, float], ...]:
    raw = config.get("amplitudes_rad")
    if not isinstance(raw, list):
        raise ValueError("amplitudes_rad must be an array.")
    result: list[tuple[float, float]] = []
    for pair in raw:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("Each amplitude entry must contain A_phi and A_theta.")
        a_phi, a_theta = pair
        if isinstance(a_phi, bool) or isinstance(a_theta, bool):
            raise ValueError("Amplitude entries must be JSON numbers, not booleans.")
        if not (
            np.isfinite(a_phi)
            and np.isfinite(a_theta)
            and 0.0 < a_phi < math.pi / 2
            and 0.0 < a_theta < math.pi / 2
        ):
            raise ValueError("Amplitude pairs must be finite and in (0, pi/2).")
        result.append((float(a_phi), float(a_theta)))
    if len(result) != len(set(result)):
        raise ValueError("Amplitude pairs must be unique.")
    return tuple(result)


def _initial_state(
    eta: float,
    a_phi: float,
    a_theta: float,
    *,
    phase_phi: float = 0.0,
    phase_theta: float = 0.0,
) -> np.ndarray:
    omega_theta = 1.0 / math.sqrt(1.0 + eta)
    return np.array(
        [
            a_phi * math.cos(phase_phi),
            a_theta * math.cos(phase_theta),
            -a_phi * math.sin(phase_phi),
            -a_theta * omega_theta * math.sin(phase_theta),
        ],
        dtype=float,
    )


def _formal_run_config(
    backend: FormalTorusBackend,
    config: dict[str, Any],
    *,
    eta: float,
    initial_state: np.ndarray,
    end_time: float,
    maximum_step: float,
    output_step: float,
) -> dict[str, Any]:
    analysis = config["analysis"]
    numerics = config["numerics"]
    ell = 1.0
    h = eta * ell
    half_support_distance = float(analysis["symmetric_upper_slope"]) * h
    upper_length = math.hypot(h, half_support_distance)
    return {
        "schema_version": "YPS-FWD-CONFIG-1.0",
        "model_id": "FWD-TORUS-1.0",
        "theory_sha256": backend.embedded_theory_sha256,
        "units": "SI",
        "physical": {
            "A": [-half_support_distance, 0.0, 0.0],
            "B": [half_support_distance, 0.0, 0.0],
            "e_z": [0.0, 0.0, 1.0],
            "g": 1.0,
            "mass": 1.0,
            "s_A": upper_length,
            "s_B": upper_length,
            "lower_length": ell,
            "initial_state": np.asarray(initial_state, dtype=float).tolist(),
            "T": float(end_time),
        },
        "numerics": {
            "method": str(numerics["method"]),
            "rtol": float(numerics["rtol"]),
            "atol_angle": float(numerics["atol_angle"]),
            "atol_rate": float(numerics["atol_rate"]),
            "max_step": float(maximum_step),
            "output_dt": float(output_step),
            "event_cluster_tolerance": float(numerics["event_cluster_tolerance"]),
        },
        "metadata": {
            "purpose": "ideal-torus parameter-pattern atlas",
            "tuning_interpretation": ("ideal_model_internal_not_experimental_calibration"),
        },
    }


def _run_states(
    backend: FormalTorusBackend,
    config: dict[str, Any],
    *,
    eta: float,
    initial_state: np.ndarray,
    end_time: float,
    maximum_step: float,
    output_step: float,
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    result = backend.run(
        _formal_run_config(
            backend,
            config,
            eta=eta,
            initial_state=initial_state,
            end_time=end_time,
            maximum_step=maximum_step,
            output_step=output_step,
        )
    )
    return (
        np.asarray(result.time, dtype=float),
        np.asarray(result.state["X_torus"], dtype=float),
        {key: np.asarray(value) for key, value in result.derived.items()},
    )


def _fit_phase(
    time: np.ndarray, coordinate: np.ndarray, rate: np.ndarray, omega_reference: float
) -> tuple[np.ndarray, float, float]:
    phase = np.unwrap(np.arctan2(-rate / omega_reference, coordinate))
    slope, intercept = np.polyfit(time, phase, 1)
    residual = phase - (slope * time + intercept)
    return phase, float(slope), float(np.sqrt(np.mean(residual * residual)))


def _analyze(
    backend: FormalTorusBackend,
    config: dict[str, Any],
    target: Target,
    eta: float,
    a_phi: float,
    a_theta: float,
    *,
    maximum_step: float,
) -> dict[str, Any]:
    analysis = config["analysis"]
    kappa = 1.0 + eta
    nominal_slow_period = 2.0 * math.pi * math.sqrt(kappa)
    end_time = (
        float(analysis["slow_cycles"]) + float(analysis["end_window_extra_slow_cycles"])
    ) * nominal_slow_period
    output_step = min(
        float(analysis["maximum_output_step"]),
        nominal_slow_period / int(analysis["phase_samples_per_slow_period"]),
    )
    time, states, derived = _run_states(
        backend,
        config,
        eta=eta,
        initial_state=_initial_state(eta, a_phi, a_theta),
        end_time=end_time,
        maximum_step=maximum_step,
        output_step=output_step,
    )
    phase_phi, omega_phi, rms_phi = _fit_phase(time, states[:, 0], states[:, 2], 1.0)
    phase_theta, omega_theta, rms_theta = _fit_phase(
        time, states[:, 1], states[:, 3], 1.0 / math.sqrt(kappa)
    )
    target_theta_phase = 2.0 * math.pi * int(analysis["slow_cycles"])
    if np.any(np.diff(phase_theta) <= -1.0e-5) or phase_theta[-1] <= target_theta_phase:
        raise RuntimeError("Phase interpolation guard failed.")
    closure_time = float(np.interp(target_theta_phase, phase_theta, time))
    closure_state = np.array(
        [np.interp(closure_time, time, states[:, index]) for index in range(4)]
    )
    phi_at_closure = float(np.interp(closure_time, time, phase_phi))
    resonant_phase = target.q * phi_at_closure - target.p * target_theta_phase
    normalization = np.array(
        [
            (closure_state[0] - a_phi) / a_phi,
            closure_state[2] / a_phi,
            (closure_state[1] - a_theta) / a_theta,
            closure_state[3] / (a_theta / math.sqrt(kappa)),
        ]
    )
    energy = np.asarray(derived["E_torus"], dtype=float)
    energy_drift = float(
        np.max(np.abs(energy - energy[0])) / max(abs(float(energy[0])), np.finfo(float).tiny)
    )
    guards = {
        "R_m": float(np.min(derived["R"])),
        "T_A_N": float(np.min(derived["T_A"])),
        "T_B_N": float(np.min(derived["T_B"])),
        "T_lower_N": float(np.min(derived["T_lower"])),
    }
    if min(guards.values()) <= 0.0:
        raise AssertionError("Formal trajectory left the sampled all-taut branch.")
    return {
        "eta": float(eta),
        "omega_phi": omega_phi,
        "omega_theta": omega_theta,
        "frequency_ratio": omega_phi / omega_theta,
        "ratio_error": omega_phi / omega_theta - target.ratio,
        "resonant_phase_error_rad": float(resonant_phase),
        "normalized_state_closure_error": float(np.linalg.norm(normalization)),
        "relative_energy_drift_max": energy_drift,
        "phase_fit_rms_phi_rad": rms_phi,
        "phase_fit_rms_theta_rad": rms_theta,
        "closure_time_s_at_g_equals_ell_equals_one": closure_time,
        "minimum_guards": guards,
    }


def _quartic_eta(target: Target, a_phi: float, a_theta: float) -> float:
    ratio_squared = target.ratio**2
    return (
        target.eta0
        + (ratio_squared / 8.0 + 1.0 / 4.0) * a_phi**2
        - 3.0 * ratio_squared * a_theta**2 / 8.0
    )


def _measured_ratio(
    backend: FormalTorusBackend,
    config: dict[str, Any],
    target: Target,
    eta: float,
    a_phi: float,
    a_theta: float,
) -> float:
    analysis = config["analysis"]
    kappa = 1.0 + eta
    slow_period = 2.0 * math.pi * math.sqrt(kappa)
    end_time = (
        float(analysis["slow_cycles"]) + float(analysis["end_window_extra_slow_cycles"])
    ) * slow_period
    output_step = slow_period / int(analysis["tuning_samples_per_slow_period"])
    time, states, _ = _run_states(
        backend,
        config,
        eta=eta,
        initial_state=_initial_state(eta, a_phi, a_theta),
        end_time=end_time,
        maximum_step=float(config["numerics"]["maximum_step"]),
        output_step=output_step,
    )
    _, omega_phi, _ = _fit_phase(time, states[:, 0], states[:, 2], 1.0)
    _, omega_theta, _ = _fit_phase(time, states[:, 1], states[:, 3], 1.0 / math.sqrt(kappa))
    return omega_phi / omega_theta


def _tune_eta(
    backend: FormalTorusBackend,
    config: dict[str, Any],
    target: Target,
    a_phi: float,
    a_theta: float,
) -> tuple[float, dict[str, Any]]:
    analysis = config["analysis"]
    guess = _quartic_eta(target, a_phi, a_theta)
    cache: dict[float, float] = {}

    def objective(eta: float) -> float:
        key = round(float(eta), 13)
        if key not in cache:
            cache[key] = (
                _measured_ratio(backend, config, target, eta, a_phi, a_theta) - target.ratio
            )
        return cache[key]

    half_width = float(analysis["tuning_initial_half_width_eta"])
    floor = -math.cos(a_phi) + float(analysis["tuning_positive_radius_margin"])
    left = max(guess - half_width, floor)
    right = guess + half_width
    bracket_expansions = 0
    for attempt in range(
        int(analysis["tuning_maximum_bracket_expansions"])
    ):
        bracket_expansions = attempt
        objective_left = objective(left)
        objective_right = objective(right)
        if objective_left * objective_right <= 0.0:
            break
        half_width *= float(analysis["tuning_bracket_growth"])
        left = max(guess - half_width, floor)
        right = guess + half_width
    else:
        raise RuntimeError(f"Could not bracket eta for target {target.label}.")
    root = float(brentq(objective, left, right, xtol=3.0e-10, rtol=2.0e-11))
    residual = float(objective(root))
    diagnostics = {
        "target": target.label,
        "A_phi_rad": float(a_phi),
        "A_theta_rad": float(a_theta),
        "method": "scipy.optimize.brentq",
        "state": "CONVERGED",
        "bracket_left_eta": float(left),
        "bracket_right_eta": float(right),
        "objective_left": float(objective(left)),
        "objective_right": float(objective(right)),
        "bracket_expansions": int(bracket_expansions),
        "function_evaluations": len(cache),
        "xtol": 3.0e-10,
        "rtol": 2.0e-11,
        "root_eta": root,
        "root_residual": residual,
    }
    return root, diagnostics


def _first_downward_zero(time: np.ndarray, coordinate: np.ndarray) -> float:
    indices = np.flatnonzero((coordinate[:-1] >= 0.0) & (coordinate[1:] < 0.0))
    if indices.size == 0:
        raise RuntimeError("Pure-mode quarter-period crossing was not sampled.")
    index = int(indices[0])
    x0 = float(coordinate[index])
    x1 = float(coordinate[index + 1])
    fraction = x0 / (x0 - x1)
    return float(time[index] + fraction * (time[index + 1] - time[index]))


def _pure_mode_period_checks(
    backend: FormalTorusBackend, config: dict[str, Any]
) -> list[dict[str, Any]]:
    analysis = config["analysis"]
    eta = float(analysis["pure_mode_eta"])
    rows: list[dict[str, Any]] = []
    for coordinate, index, scale in (
        ("phi_fast", 0, 1.0),
        ("theta_slow", 1, 1.0 + eta),
    ):
        for amplitude in map(float, analysis["pure_mode_amplitudes_rad"]):
            exact = 4.0 * math.sqrt(scale) * float(ellipk(math.sin(amplitude / 2.0) ** 2))
            state = np.zeros(4)
            state[index] = amplitude
            time, states, _ = _run_states(
                backend,
                config,
                eta=eta,
                initial_state=state,
                end_time=0.55 * exact,
                maximum_step=min(float(config["numerics"]["maximum_step"]), 0.01),
                output_step=float(analysis["pure_mode_output_step"]),
            )
            numerical = 4.0 * _first_downward_zero(time, states[:, index])
            rows.append(
                {
                    "coordinate": coordinate,
                    "amplitude_rad": amplitude,
                    "period_exact": exact,
                    "period_numeric": numerical,
                    "relative_difference": (numerical - exact) / exact,
                }
            )
    return rows


def _step_halving_checks(
    backend: FormalTorusBackend,
    config: dict[str, Any],
    targets: Iterable[Target],
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in targets:
        target_cases = [item for item in cases if item["target"] == target.label]
        if not target_cases:
            raise ValueError(f"No atlas case is available for {target.label}.")
        case = max(
            target_cases,
            key=lambda item: (float(item["A_phi_rad"]), float(item["A_theta_rad"])),
        )
        a_phi = float(case["A_phi_rad"])
        a_theta = float(case["A_theta_rad"])
        coarse = case["numeric"]
        fine = _analyze(
            backend,
            config,
            target,
            float(coarse["eta"]),
            a_phi,
            a_theta,
            maximum_step=float(config["numerics"]["step_halving_maximum_step"]),
        )
        rows.append(
            {
                "target": target.label,
                "coarse_maximum_step": float(config["numerics"]["maximum_step"]),
                "fine_maximum_step": float(config["numerics"]["step_halving_maximum_step"]),
                "frequency_ratio_abs_difference": abs(
                    float(coarse["frequency_ratio"]) - float(fine["frequency_ratio"])
                ),
                "resonant_phase_abs_difference_rad": abs(
                    float(coarse["resonant_phase_error_rad"])
                    - float(fine["resonant_phase_error_rad"])
                ),
                "closure_abs_difference": abs(
                    float(coarse["normalized_state_closure_error"])
                    - float(fine["normalized_state_closure_error"])
                ),
            }
        )
    return rows


def _summary_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        zero = case["zero"]
        quartic = case["quartic"]
        numeric = case["numeric"]
        rows.append(
            {
                "target": case["target"],
                "p": case["p"],
                "q": case["q"],
                "A_phi_rad": case["A_phi_rad"],
                "A_theta_rad": case["A_theta_rad"],
                "eta_zero": zero["eta"],
                "eta_quartic": quartic["eta"],
                "eta_numeric": numeric["eta"],
                "delta_eta_quartic": quartic["eta"] - zero["eta"],
                "delta_eta_numeric": numeric["eta"] - zero["eta"],
                "quartic_minus_numeric_eta": quartic["eta"] - numeric["eta"],
                "phase_error_zero_rad": zero["resonant_phase_error_rad"],
                "phase_error_quartic_rad": quartic["resonant_phase_error_rad"],
                "phase_error_numeric_rad": numeric["resonant_phase_error_rad"],
                "closure_zero": zero["normalized_state_closure_error"],
                "closure_quartic": quartic["normalized_state_closure_error"],
                "closure_numeric": numeric["normalized_state_closure_error"],
                "energy_drift_numeric": numeric["relative_energy_drift_max"],
                "minimum_guard_numeric": min(numeric["minimum_guards"].values()),
            }
        )
    return rows


def _geometry_tolerance_rows(
    config: dict[str, Any], targets: Iterable[Target]
) -> list[dict[str, Any]]:
    analysis = config["analysis"]
    cycles = int(analysis["slow_cycles"])
    phase_tolerance = float(analysis["phase_tolerance_rad"])
    reference_length = float(analysis["reference_lower_length_m"])
    rows: list[dict[str, Any]] = []
    for target in targets:
        delta_eta = phase_tolerance * target.p / (math.pi * target.q**2 * cycles)
        rows.append(
            {
                "target": target.label,
                "p": target.p,
                "q": target.q,
                "slow_cycles": cycles,
                "phase_tolerance_rad": phase_tolerance,
                "delta_eta_tolerance": delta_eta,
                "delta_h_tolerance_mm_at_reference_length": (delta_eta * reference_length * 1000.0),
                "reference_lower_length_m": reference_length,
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _plot_compensation(
    path_base: Path, rows: list[dict[str, Any]], targets: Iterable[Target]
) -> None:
    figure, axis = plt.subplots(figsize=(6.4, 5.2))
    for target in targets:
        part = [row for row in rows if row["target"] == target.label]
        axis.scatter(
            [row["delta_eta_quartic"] for row in part],
            [row["delta_eta_numeric"] for row in part],
            label=target.label,
        )
    values = [float(row[key]) for row in rows for key in ("delta_eta_quartic", "delta_eta_numeric")]
    low, high = min(values), max(values)
    padding = 0.08 * max(high - low, 1.0e-5)
    axis.plot(
        [low - padding, high + padding],
        [low - padding, high + padding],
        "--",
        label="quartic = numerical",
    )
    axis.set(
        xlabel="quartic delta h/ell",
        ylabel="numerically tuned delta h/ell",
        title="Ideal-model finite-amplitude geometry compensation",
    )
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(path_base.with_suffix(".svg"), metadata=FIGURE_METADATA)
    figure.savefig(path_base.with_suffix(".png"), dpi=180, metadata=FIGURE_METADATA)
    plt.close(figure)


def _plot_phase_atlas(
    backend: FormalTorusBackend,
    config: dict[str, Any],
    path_base: Path,
    eta: float,
) -> None:
    target = Target(3, 2)
    a_phi, a_theta = 0.10, 0.08
    end_time = 2.1 * target.q * 2.0 * math.pi * math.sqrt(1.0 + eta)
    phases = (0.0, math.pi / 4.0, math.pi / 2.0, 3.0 * math.pi / 4.0)
    figure, axes = plt.subplots(2, 2, figsize=(8.4, 8.0), sharex=True, sharey=True)
    for axis, phase in zip(axes.flat, phases, strict=True):
        time, states, _ = _run_states(
            backend,
            config,
            eta=eta,
            initial_state=_initial_state(eta, a_phi, a_theta, phase_phi=phase / target.q),
            end_time=end_time,
            maximum_step=float(config["numerics"]["step_halving_maximum_step"]),
            output_step=end_time / 419.0,
        )
        del time
        x = np.sin(states[:, 0])
        y = (eta + np.cos(states[:, 0])) * np.sin(states[:, 1])
        axis.plot(x, y, linewidth=1.0)
        axis.scatter([x[0]], [y[0]], s=18)
        axis.set_aspect("equal", adjustable="box")
        axis.grid(alpha=0.2)
        axis.set_title(f"Psi = {phase / math.pi:.2g} pi")
    figure.suptitle("Ideal-model nonlinear 3:2 phase atlas")
    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.96))
    figure.savefig(path_base.with_suffix(".svg"), metadata=FIGURE_METADATA)
    figure.savefig(path_base.with_suffix(".png"), dpi=180, metadata=FIGURE_METADATA)
    plt.close(figure)


def _aggregate_gates(
    config: dict[str, Any],
    pure: list[dict[str, Any]],
    step: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> dict[str, bool]:
    thresholds = config["validation_thresholds"]
    all_results = [case[key] for case in cases for key in ("zero", "quartic", "numeric")]
    return {
        "pure_mode_period": all(
            abs(float(row["relative_difference"]))
            <= float(thresholds["pure_mode_relative_period_error_max"])
            for row in pure
        ),
        "energy": all(
            float(result["relative_energy_drift_max"])
            <= float(thresholds["relative_energy_drift_max"])
            for result in all_results
        ),
        "sampled_taut_guards": all(
            min(result["minimum_guards"].values())
            > float(thresholds["minimum_guard_strictly_positive"])
            for result in all_results
        ),
        "step_halving": all(
            float(row["frequency_ratio_abs_difference"])
            <= float(thresholds["step_halving_frequency_ratio_difference_max"])
            and float(row["resonant_phase_abs_difference_rad"])
            <= float(thresholds["step_halving_resonant_phase_difference_rad_max"])
            and float(row["closure_abs_difference"])
            <= float(thresholds["step_halving_closure_difference_max"])
            for row in step
        ),
    }


def _single_source_entry(
    source_manifest: BoundSourceManifest, role: str
) -> dict[str, str]:
    matches = source_manifest.entries_by_role.get(role, [])
    if len(matches) != 1:
        raise RuntimeError(f"Expected one source-manifest entry for {role}, got {len(matches)}")
    return matches[0]


def _build_run_evidence(
    *,
    source_manifest: BoundSourceManifest,
    repository_root: Path,
    config: dict[str, Any],
    config_path: Path,
    targets: tuple[Target, ...],
    amplitudes: tuple[tuple[float, float], ...],
    cases: list[dict[str, Any]],
    pure: list[dict[str, Any]],
    step: list[dict[str, Any]],
    aggregate: dict[str, bool],
    tuning_diagnostics: list[dict[str, Any]],
    smoke: bool,
) -> dict[str, Any]:
    return {
        "schema": RUN_EVIDENCE_SCHEMA,
        "run_kind": "SMOKE_SUBSET" if smoke else "FULL_16_CASE_48_PRIMARY_TRAJECTORY_MATRIX",
        "claim_limit": CLAIM_LIMIT,
        "source_manifest": source_manifest.manifest,
        "source_manifest_sha256": source_manifest.source_manifest_sha256,
        "source_manifest_lock": {
            "path": source_manifest.lock_path.relative_to(repository_root).as_posix(),
            "sha256": source_manifest.lock_sha256,
        },
        "configuration_binding": {
            "path": config_path.relative_to(repository_root).as_posix(),
            "sha256": sha256_file(config_path),
        },
        "execution": {
            "target_count": len(targets),
            "amplitude_pair_count": len(amplitudes),
            "atlas_case_count": len(cases),
            "primary_result_trajectory_count": 3 * len(cases),
            "pure_mode_trajectory_count": len(pure),
            "step_halving_trajectory_count": len(step),
        },
        "solver_settings": config["numerics"],
        "validation_thresholds": config["validation_thresholds"],
        "optimizer": {
            "method": "scipy.optimize.brentq",
            "all_states": "CONVERGED",
            "case_count": len(tuning_diagnostics),
            "cases": tuning_diagnostics,
        },
        "diagnostics": {
            "aggregate_gates": aggregate,
            "all_sampled_taut_guards_strictly_positive": aggregate[
                "sampled_taut_guards"
            ],
            "all_numerical_gates_passed": all(aggregate.values()),
        },
    }


def run_atlas(
    config_path: Path,
    output_directory: Path,
    *,
    repository_root: Path | None = None,
    smoke: bool = False,
) -> dict[str, Any]:
    """Run the configured atlas and write deterministic JSON/CSV/figure artifacts."""

    config_path = config_path.resolve()
    output_directory = output_directory.resolve()
    config = _load_config(config_path)
    root = (
        repository_root.resolve()
        if repository_root is not None
        else find_repository_root(Path(__file__))
    )
    source_manifest = verify_source_manifest(PROJECT_ROOT, root)
    configuration_entry = _single_source_entry(source_manifest, "configuration")
    bound_configuration_path = (root / configuration_entry["path"]).resolve()
    if config_path != bound_configuration_path:
        raise ValueError(
            "result-bearing atlas runs require the source-locked configuration: "
            f"expected {bound_configuration_path}, got {config_path}"
        )
    formal_theory_entry = _single_source_entry(source_manifest, "formal_theory")
    formal_contracts_entry = _single_source_entry(source_manifest, "formal_contracts")
    formal_backend_entry = _single_source_entry(source_manifest, "formal_backend")
    backend = load_formal_backend(
        root,
        expected_source_sha256=formal_backend_entry["sha256"],
        expected_contracts_sha256=formal_contracts_entry["sha256"],
        expected_theory_source_sha256=formal_theory_entry["sha256"],
    )
    targets = _targets(config)
    amplitudes = _amplitudes(config)
    if smoke:
        targets = targets[:1]
        amplitudes = amplitudes[:1]

    cases: list[dict[str, Any]] = []
    tuned: dict[tuple[str, float, float], float] = {}
    tuning_diagnostics: list[dict[str, Any]] = []
    for target in targets:
        for a_phi, a_theta in amplitudes:
            eta_zero = target.eta0
            eta_quartic = _quartic_eta(target, a_phi, a_theta)
            eta_numeric, tuning = _tune_eta(
                backend, config, target, a_phi, a_theta
            )
            tuned[(target.label, a_phi, a_theta)] = eta_numeric
            tuning_diagnostics.append(tuning)
            zero = _analyze(
                backend,
                config,
                target,
                eta_zero,
                a_phi,
                a_theta,
                maximum_step=float(config["numerics"]["maximum_step"]),
            )
            quartic = _analyze(
                backend,
                config,
                target,
                eta_quartic,
                a_phi,
                a_theta,
                maximum_step=float(config["numerics"]["maximum_step"]),
            )
            numeric = _analyze(
                backend,
                config,
                target,
                eta_numeric,
                a_phi,
                a_theta,
                maximum_step=float(config["numerics"]["maximum_step"]),
            )
            cases.append(
                {
                    "target": target.label,
                    "p": target.p,
                    "q": target.q,
                    "A_phi_rad": a_phi,
                    "A_theta_rad": a_theta,
                    "zero": zero,
                    "quartic": quartic,
                    "numeric": numeric,
                }
            )

    pure = _pure_mode_period_checks(backend, config)
    step = _step_halving_checks(backend, config, targets, cases)
    aggregate = _aggregate_gates(config, pure, step, cases)
    if not all(aggregate.values()):
        raise AssertionError(f"Atlas validation gate failed: {aggregate}")

    output_directory.mkdir(parents=True, exist_ok=True)
    run_evidence = _build_run_evidence(
        source_manifest=source_manifest,
        repository_root=root,
        config=config,
        config_path=config_path,
        targets=targets,
        amplitudes=amplitudes,
        cases=cases,
        pure=pure,
        step=step,
        aggregate=aggregate,
        tuning_diagnostics=tuning_diagnostics,
        smoke=smoke,
    )
    validate_json_contract(
        run_evidence,
        RUN_EVIDENCE_SCHEMA_PATH,
        label="atlas run evidence",
    )
    run_evidence_path = output_directory / "atlas_run_evidence.json"
    run_evidence_path.write_text(
        json.dumps(
            run_evidence,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    payload = {
        "schema": OUTPUT_SCHEMA,
        "model_identity": {
            "backend_model_id": "FWD-TORUS-1.0",
            "atlas_identity": ATLAS_IDENTITY,
            "tuning_interpretation": ("ideal_model_internal_not_experimental_calibration"),
            "formal_contract_embedded_theory_sha256": backend.embedded_theory_sha256,
        },
        "claim_limit": CLAIM_LIMIT,
        "source_binding": {
            "config_path": configuration_entry["path"],
            "config_sha256": configuration_entry["sha256"],
            "formal_theory_path": FORMAL_THEORY_RELATIVE_PATH.as_posix(),
            "formal_theory_sha256": backend.theory_source_sha256,
            "formal_contracts_path": FORMAL_CONTRACTS_RELATIVE_PATH.as_posix(),
            "formal_contracts_sha256": backend.contracts_sha256,
            "formal_torus_backend_path": FORMAL_BACKEND_RELATIVE_PATH.as_posix(),
            "formal_torus_backend_sha256": backend.source_sha256,
            "source_manifest_lock_path": source_manifest.lock_path.relative_to(root).as_posix(),
            "source_manifest_lock_sha256": source_manifest.lock_sha256,
            "source_manifest_sha256": source_manifest.source_manifest_sha256,
            "runtime_identity_sha256": source_manifest.manifest[
                "runtime_identity_sha256"
            ],
            "run_evidence_path": run_evidence_path.relative_to(output_directory).as_posix(),
            "run_evidence_sha256": sha256_file(run_evidence_path),
        },
        "configuration": {
            "targets": [target.label for target in targets],
            "amplitudes_rad": [list(pair) for pair in amplitudes],
            "slow_cycles": int(config["analysis"]["slow_cycles"]),
            "scope": config["scope"],
            "numerics": config["numerics"],
            "validation_thresholds": config["validation_thresholds"],
            "smoke_subset": bool(smoke),
        },
        "validation": {
            "pure_mode_period_checks": pure,
            "step_halving_checks": step,
            "aggregate_gates": aggregate,
        },
        "cases": cases,
    }

    validate_json_contract(payload, OUTPUT_SCHEMA_PATH, label="atlas output")
    result_path = output_directory / "atlas_results.json"
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    summary = _summary_rows(cases)
    _write_csv(output_directory / "atlas_summary.csv", summary)
    _write_csv(
        output_directory / "geometry_tolerance.csv",
        _geometry_tolerance_rows(config, targets),
    )
    figures = output_directory / "figures"
    figures.mkdir(exist_ok=True)
    _plot_compensation(figures / "compensation_accuracy", summary, targets)
    if not smoke and any(target.label == "3:2" for target in targets):
        eta = tuned[("3:2", 0.10, 0.08)]
        _plot_phase_atlas(backend, config, figures / "phase_atlas_3to2", eta)

    artifact_paths = sorted(
        path
        for path in output_directory.rglob("*")
        if path.is_file() and path.name != "artifact_manifest.json"
    )
    manifest = {
        "schema": "YPS-FORMAL-PATTERN-ATLAS-ARTIFACT-MANIFEST-1.0",
        "deterministic": True,
        "artifacts": [
            {
                "path": path.relative_to(output_directory).as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in artifact_paths
        ],
    }
    (output_directory / "artifact_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload
