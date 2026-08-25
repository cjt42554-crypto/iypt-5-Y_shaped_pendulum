#!/usr/bin/env python3
"""Three-anchor Y-pendulum model ladder.

This candidate driver keeps the three model identities separate:

* FWD-TORUS-1.0: ideal taut torus;
* FWD-CABLE-1.0: continuous tension-only cable finite elements;
* HF-DISCRETE-ROD-RIGID-BOB-1.0: independent discrete-rod/rigid-bob backend.

It reads the formal implementations in ``02_模拟程序`` without modifying
them.  Compact summaries are written below this candidate directory; restart
caches are written to ``generated/`` and are intentionally not release files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import runpy
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
CANDIDATE_ROOT = SCRIPT_PATH.parent
REPOSITORY_ROOT = SCRIPT_PATH.parents[3]
FORWARD_ROOT = (
    REPOSITORY_ROOT
    / "02_模拟程序"
    / "01_前向预测数值求解器"
    / "y_pendulum_forward_solver"
)
HF_ROOT = (
    REPOSITORY_ROOT
    / "02_模拟程序"
    / "02_第一性原理高保真模拟器"
    / "Y-Pendulum-Simulator-v1.0.0-rc1"
)
ATLAS_PATH = (
    REPOSITORY_ROOT
    / "90_候选工作区"
    / "current"
    / "无实验参数图谱"
    / "pattern_atlas.py"
)

for package_path in (str(FORWARD_ROOT), str(HF_ROOT / "src")):
    if package_path not in sys.path:
        sys.path.insert(0, package_path)

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["svg.fonttype"] = "none"
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import minimize_scalar

from y_pendulum_forward.contracts import (
    config_sha256 as forward_config_sha256,
    source_tree_sha256,
)
from y_pendulum_forward.runner import run_config
from ypendulum.api import simulate
from ypendulum.config import load_config
from ypendulum.config.identity import resolved_config_sha256
from ypendulum.io.provenance import source_hash
from ypendulum.ui.desktop_config import (
    InitialReleaseParameters,
    apply_initial_release_to_forward,
    default_desktop_configuration,
    shared_input_audit,
    synchronize_shared_forward_to_hf,
)

G_M_S2 = 9.80665
ELL_M = 0.300
UPPER_SLOPE = 0.4
BOB_MASS_KG = 0.08
EA_N = 12.0
COMMON_PERIODS = 3


@dataclass(frozen=True)
class Anchor:
    p: int
    q: int
    amplitude_phi_rad: float
    amplitude_theta_rad: float

    @property
    def label(self) -> str:
        return f"{self.p}:{self.q}"

    @property
    def slug(self) -> str:
        return f"{self.p}to{self.q}"

    @property
    def target_ratio(self) -> float:
        return self.p / self.q


ANCHORS = (
    Anchor(4, 3, 0.05, 0.04),
    Anchor(3, 2, 0.15, 0.10),
    Anchor(2, 1, 0.20, 0.12),
)


@dataclass
class Series:
    time_s: np.ndarray
    bob_position_m: np.ndarray
    bob_velocity_m_s: np.ndarray


_ATLAS_NAMESPACE: dict[str, Any] | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(child) for child in value]
    if isinstance(value, np.ndarray):
        return json_value(value.tolist())
    if isinstance(value, np.generic):
        return json_value(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(
            json_value(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row}) if rows else []
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json_value(row.get(key)) for key in fieldnames})
    os.replace(temporary, path)


def save_series(path: Path, series: Series) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(
            stream,
            time_s=np.asarray(series.time_s, dtype=float),
            bob_position_m=np.asarray(series.bob_position_m, dtype=float),
            bob_velocity_m_s=np.asarray(series.bob_velocity_m_s, dtype=float),
        )
    os.replace(temporary, path)


def load_series(path: Path) -> Series:
    with np.load(path) as archive:
        return Series(
            time_s=np.asarray(archive["time_s"], dtype=float),
            bob_position_m=np.asarray(archive["bob_position_m"], dtype=float),
            bob_velocity_m_s=np.asarray(archive["bob_velocity_m_s"], dtype=float),
        )


def atlas_namespace() -> dict[str, Any]:
    global _ATLAS_NAMESPACE
    if _ATLAS_NAMESPACE is None:
        _ATLAS_NAMESPACE = runpy.run_path(str(ATLAS_PATH))
    return _ATLAS_NAMESPACE


def anchor_setup(anchor: Anchor) -> dict[str, Any]:
    atlas = atlas_namespace()
    target = atlas["Target"](anchor.p, anchor.q)
    eta = float(
        atlas["tune_eta"](
            target,
            anchor.amplitude_phi_rad,
            anchor.amplitude_theta_rad,
        )
    )
    eta_quartic = float(
        atlas["quartic_eta"](
            target,
            anchor.amplitude_phi_rad,
            anchor.amplitude_theta_rad,
        )
    )
    h = eta * ELL_M
    half_span = UPPER_SLOPE * h
    support_span = 2.0 * half_span
    upper_loaded_length = math.hypot(h, half_span)
    phi = anchor.amplitude_phi_rad
    theta = anchor.amplitude_theta_rad
    lower_tension = BOB_MASS_KG * G_M_S2 * math.cos(phi) * math.cos(theta)
    upper_a_tension = (
        upper_loaded_length
        * lower_tension
        / support_span
        * (math.sin(phi) + UPPER_SLOPE * math.cos(phi))
    )
    upper_b_tension = (
        upper_loaded_length
        * lower_tension
        / support_span
        * (UPPER_SLOPE * math.cos(phi) - math.sin(phi))
    )
    if min(lower_tension, upper_a_tension, upper_b_tension) <= 0.0:
        raise ValueError(f"Anchor {anchor.label} is not initially taut.")
    mean_upper_tension = 0.5 * (upper_a_tension + upper_b_tension)
    upper_rest_length = upper_loaded_length / (1.0 + mean_upper_tension / EA_N)
    lower_rest_length = ELL_M / (1.0 + lower_tension / EA_N)
    fast_period = 2.0 * math.pi * math.sqrt(ELL_M / G_M_S2)
    slow_period = 2.0 * math.pi * math.sqrt((h + ELL_M) / G_M_S2)
    return {
        "anchor": anchor.label,
        "eta_numeric": eta,
        "eta_quartic": eta_quartic,
        "eta_zero": anchor.target_ratio**2 - 1.0,
        "h_m": h,
        "half_support_span_m": half_span,
        "support_span_m": support_span,
        "upper_loaded_length_m": upper_loaded_length,
        "lower_loaded_length_m": ELL_M,
        "upper_rest_length_m": upper_rest_length,
        "lower_rest_length_m": lower_rest_length,
        "ideal_initial_tension_N": {
            "A": upper_a_tension,
            "B": upper_b_tension,
            "lower": lower_tension,
            "upper_mean_used_for_symmetric_prestretch": mean_upper_tension,
        },
        "nominal_fast_period_s": fast_period,
        "nominal_slow_period_s": slow_period,
        "nominal_fast_frequency_hz": 1.0 / fast_period,
        "nominal_slow_frequency_hz": 1.0 / slow_period,
        "mapping": (
            "same support/gravity frame and bob-COM endpoint state; symmetric "
            "upper rest lengths use the mean ideal initial upper tension; HF "
            "retains its independent rigid-bob surface attachment"
        ),
    }


def build_configs(
    anchor: Anchor,
    setup: dict[str, Any],
    *,
    horizon_s: float,
    output_dt_s: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    torus = json.loads(
        (FORWARD_ROOT / "configs" / "torus_example.json").read_text(
            encoding="utf-8"
        )
    )
    half_span = float(setup["half_support_span_m"])
    upper_length = float(setup["upper_loaded_length_m"])
    torus["physical"].update(
        {
            "A": [-half_span, 0.0, 0.0],
            "B": [half_span, 0.0, 0.0],
            "g": G_M_S2,
            "mass": BOB_MASS_KG,
            "s_A": upper_length,
            "s_B": upper_length,
            "lower_length": ELL_M,
            "initial_state": [
                anchor.amplitude_phi_rad,
                anchor.amplitude_theta_rad,
                0.0,
                0.0,
            ],
            "T": horizon_s,
        }
    )
    torus["numerics"].update(
        {
            "method": "DOP853",
            "rtol": 3.0e-11,
            "atol": 3.0e-13,
            "max_step": output_dt_s * 2.0,
            "output_dt": output_dt_s,
        }
    )
    torus["observation"] = None
    torus["metadata"]["candidate_case"] = anchor.label

    forward, high_fidelity = default_desktop_configuration()
    forward["inputs"]["support_A"]["value"] = [-half_span, 0.0, 0.0]
    forward["inputs"]["support_B"]["value"] = [half_span, 0.0, 0.0]
    forward["physical"]["g"] = G_M_S2
    forward["physical"]["bob_mass"] = BOB_MASS_KG
    forward["physical"]["branches"]["A"]["L0"] = float(
        setup["upper_rest_length_m"]
    )
    forward["physical"]["branches"]["B"]["L0"] = float(
        setup["upper_rest_length_m"]
    )
    forward["physical"]["branches"]["lower"]["L0"] = float(
        setup["lower_rest_length_m"]
    )
    forward["physical"]["T"] = horizon_s
    for branch in forward["physical"]["branches"].values():
        domain = branch["material_domain"]
        for key in (
            "lambda_lower",
            "lambda_upper",
            "rate_lower",
            "rate_upper",
        ):
            domain[key] = None
    release = InitialReleaseParameters(
        upper_a_length_m=upper_length,
        upper_b_length_m=upper_length,
        junction_roll_deg=math.degrees(anchor.amplitude_theta_rad),
        lower_branch_length_m=ELL_M,
        lower_polar_deg=math.degrees(anchor.amplitude_phi_rad),
        lower_azimuth_deg=0.0,
    )
    forward_direct = apply_initial_release_to_forward(forward, release)
    high_fidelity = synchronize_shared_forward_to_hf(
        forward_direct, high_fidelity
    )
    audit = shared_input_audit(forward_direct, high_fidelity)
    if audit["passed"] is not True:
        raise ValueError(
            f"Shared FWD/HF input audit failed for {anchor.label}: {audit}"
        )

    endpoints = {
        "junction": deepcopy(forward_direct["initial_state"]["r_J"]),
        "bob": deepcopy(forward_direct["initial_state"]["r_m"]),
    }
    forward_cable = deepcopy(forward_direct)
    forward_cable["initial_state"] = {
        "mode": "STATIC_HOLD_RELEASE",
        "hold": {"fixed_nodes": deepcopy(endpoints)},
        "seed": {
            "r_J": deepcopy(endpoints["junction"]),
            "r_m": deepcopy(endpoints["bob"]),
        },
    }
    forward_cable["numerics"].update(
        {
            "elements": {"A": 2, "B": 2, "lower": 3},
            "method": "BDF",
            "rtol": 1.0e-7,
            "atol": 1.0e-9,
            "max_step": output_dt_s,
            "output_dt": output_dt_s,
            "static_multistart": 5,
            "static_maxiter": 5000,
            "static_gradient_tolerance": 1.0e-6,
        }
    )
    forward_cable["observation"] = None
    forward_cable["metadata"]["candidate_case"] = anchor.label

    high_fidelity["initial_condition"]["type"] = (
        "held_endpoint_equilibrium_release"
    )
    high_fidelity["run"]["name"] = f"model_ladder_{anchor.slug}"
    high_fidelity["run"]["claim_level"] = "DERIVED"
    high_fidelity["solver"].update(
        {
            "profile": "quick",
            "t_end": horizon_s,
            "output_dt": output_dt_s,
            "max_step": output_dt_s,
            "method": "BDF",
            "rtol": 1.0e-7,
            "position_atol": 1.0e-9,
            "velocity_atol": 1.0e-8,
            "quaternion_atol": 1.0e-9,
            "angular_velocity_atol": 1.0e-8,
            "resolve_longitudinal_waves": False,
            "allow_subminimum_mesh": True,
        }
    )
    high_fidelity["analysis"]["target_ratio"] = [anchor.p, anchor.q]
    high_fidelity["analysis"]["slow_period_count"] = COMMON_PERIODS * anchor.q
    for branch in ("upper_A", "upper_B", "lower"):
        high_fidelity["cables"][branch]["elements"] = 1

    return torus, forward_cable, high_fidelity, audit


def variant_config(
    model: str, base: dict[str, Any], variant: str, *, output_dt_s: float
) -> dict[str, Any]:
    config = deepcopy(base)
    if model == "torus":
        if variant == "time_fine":
            config["numerics"]["max_step"] = output_dt_s
        return config
    if model == "cable":
        if variant in {"time_fine", "space_fine"}:
            config["numerics"].update(
                {
                    "rtol": 3.0e-8,
                    "atol": 3.0e-10,
                    "max_step": 0.5 * output_dt_s,
                }
            )
        if variant == "space_fine":
            config["numerics"]["elements"] = {
                "A": 4,
                "B": 4,
                "lower": 6,
            }
        return config
    if model == "high_fidelity":
        if variant in {"time_fine", "space_fine"}:
            config["solver"].update(
                {
                    "rtol": 3.0e-8,
                    "position_atol": 3.0e-10,
                    "velocity_atol": 3.0e-9,
                    "quaternion_atol": 3.0e-10,
                    "angular_velocity_atol": 3.0e-9,
                    "max_step": 0.5 * output_dt_s,
                }
            )
        if variant == "space_fine":
            for branch in ("upper_A", "upper_B", "lower"):
                config["cables"][branch]["elements"] = 2
        return config
    raise ValueError(model)


def config_identity(model: str, config: dict[str, Any]) -> str:
    if model in {"torus", "cable"}:
        return forward_config_sha256(config)
    return resolved_config_sha256(load_config(config))


def fit_frequency(
    time_s: np.ndarray,
    signal: np.ndarray,
    *,
    reference_hz: float,
    skip_s: float,
) -> dict[str, Any]:
    time = np.asarray(time_s, dtype=float)
    values = np.asarray(signal, dtype=float)
    mask = time >= time[0] + skip_s
    time = time[mask]
    values = values[mask]
    if time.size < 24 or time[-1] <= time[0]:
        return {
            "frequency_hz": None,
            "amplitude_m": None,
            "fit_r2": None,
            "observed_cycles": 0.0,
            "phase_at_t0_rad": None,
            "reliable": False,
            "reason": "insufficient_samples_or_duration",
        }
    center = float(np.mean(time))
    centered_time = time - center

    def solve_at(frequency: float) -> tuple[float, np.ndarray]:
        angle = 2.0 * math.pi * frequency * centered_time
        design = np.column_stack(
            (
                np.cos(angle),
                np.sin(angle),
                np.ones_like(angle),
                centered_time,
            )
        )
        coefficients, *_ = np.linalg.lstsq(design, values, rcond=None)
        residual = values - design @ coefficients
        return float(np.dot(residual, residual)), coefficients

    lower = 0.55 * reference_hz
    upper = 1.45 * reference_hz
    coarse_frequencies = np.linspace(lower, upper, 257)
    coarse_residuals = np.asarray(
        [solve_at(float(frequency))[0] for frequency in coarse_frequencies],
        dtype=float,
    )
    coarse_index = int(np.argmin(coarse_residuals))
    left_index = max(0, coarse_index - 1)
    right_index = min(coarse_frequencies.size - 1, coarse_index + 1)
    local_lower = float(coarse_frequencies[left_index])
    local_upper = float(coarse_frequencies[right_index])
    if not local_lower < local_upper:
        local_lower, local_upper = lower, upper
    optimum = minimize_scalar(
        lambda frequency: solve_at(float(frequency))[0],
        bounds=(local_lower, local_upper),
        method="bounded",
        options={"xatol": 1.0e-10},
    )
    frequency = float(optimum.x)
    residual_sum, coefficients = solve_at(frequency)
    centered_values = values - float(np.mean(values))
    total_sum = float(np.dot(centered_values, centered_values))
    fit_r2 = 1.0 - residual_sum / max(total_sum, np.finfo(float).tiny)
    amplitude = float(math.hypot(coefficients[0], coefficients[1]))
    phase_at_center = math.atan2(-coefficients[1], coefficients[0])
    phase_at_t0 = phase_at_center - 2.0 * math.pi * frequency * center
    duration = float(time[-1] - time[0])
    observed_cycles = frequency * duration
    reasons: list[str] = []
    if observed_cycles < 3.0:
        reasons.append(f"only_{observed_cycles:.3g}_cycles")
    if fit_r2 < 0.5:
        reasons.append(f"fit_r2_{fit_r2:.3g}")
    if frequency <= lower * 1.01 or frequency >= upper * 0.99:
        reasons.append("frequency_at_search_boundary")
    return {
        "frequency_hz": frequency,
        "amplitude_m": amplitude,
        "fit_r2": fit_r2,
        "observed_cycles": observed_cycles,
        "phase_at_t0_rad": phase_at_t0,
        "reliable": not reasons,
        "reason": "ok" if not reasons else ";".join(reasons),
    }


def interpolate_vector(
    source_time: np.ndarray, source: np.ndarray, target_time: float | np.ndarray
) -> np.ndarray:
    query = np.asarray(target_time, dtype=float)
    values = np.asarray(source, dtype=float)
    columns = [
        np.interp(query, source_time, values[:, index])
        for index in range(values.shape[1])
    ]
    return np.stack(columns, axis=-1)


def modal_metrics(
    series: Series,
    anchor: Anchor,
    setup: dict[str, Any],
    *,
    closure_cycles: int,
) -> dict[str, Any]:
    time = np.asarray(series.time_s, dtype=float)
    if time.size < 2:
        return {"reliable": False, "reason": "empty_or_single_sample"}
    x_fast = np.asarray(series.bob_position_m[:, 0], dtype=float)
    y_slow = np.asarray(series.bob_position_m[:, 1], dtype=float)
    skip = 0.5 * float(setup["nominal_slow_period_s"])
    fast = fit_frequency(
        time,
        x_fast,
        reference_hz=float(setup["nominal_fast_frequency_hz"]),
        skip_s=skip,
    )
    slow = fit_frequency(
        time,
        y_slow,
        reference_hz=float(setup["nominal_slow_frequency_hz"]),
        skip_s=skip,
    )
    result: dict[str, Any] = {"fast": fast, "slow": slow}
    fast_frequency = fast["frequency_hz"]
    slow_frequency = slow["frequency_hz"]
    if fast_frequency is None or slow_frequency is None or slow_frequency <= 0.0:
        result.update(
            {
                "reliable": False,
                "reason": "frequency_fit_unavailable",
                "frequency_ratio": None,
                "frequency_ratio_error": None,
                "resonant_phase_initial_rad": None,
                "resonant_phase_drift_rad": None,
                "closure_time_s": None,
                "normalized_four_state_closure_error": None,
            }
        )
        return result
    ratio = fast_frequency / slow_frequency
    drift = (
        2.0
        * math.pi
        * closure_cycles
        * (anchor.q * ratio - anchor.p)
    )
    resonant_initial = (
        anchor.q * float(fast["phase_at_t0_rad"])
        - anchor.p * float(slow["phase_at_t0_rad"])
    )
    resonant_initial = math.atan2(
        math.sin(resonant_initial), math.cos(resonant_initial)
    )
    closure_time = float(time[0] + closure_cycles / slow_frequency)
    closure_error: float | None = None
    if closure_time <= time[-1] + 1.0e-12:
        initial_position = series.bob_position_m[0]
        initial_velocity = series.bob_velocity_m_s[0]
        close_position = interpolate_vector(
            time, series.bob_position_m, closure_time
        )
        close_velocity = interpolate_vector(
            time, series.bob_velocity_m_s, closure_time
        )
        fast_scale = max(
            abs(float(initial_position[0])),
            float(fast["amplitude_m"]),
            1.0e-12,
        )
        slow_scale = max(
            abs(float(initial_position[1])),
            float(slow["amplitude_m"]),
            1.0e-12,
        )
        normalized = np.asarray(
            [
                (close_position[0] - initial_position[0]) / fast_scale,
                (close_velocity[0] - initial_velocity[0])
                / (2.0 * math.pi * fast_frequency * fast_scale),
                (close_position[1] - initial_position[1]) / slow_scale,
                (close_velocity[1] - initial_velocity[1])
                / (2.0 * math.pi * slow_frequency * slow_scale),
            ],
            dtype=float,
        )
        closure_error = float(np.linalg.norm(normalized))
    reliable = bool(fast["reliable"] and slow["reliable"])
    reasons = [
        f"fast:{fast['reason']}",
        f"slow:{slow['reason']}",
    ]
    if closure_error is None:
        reliable = False
        reasons.append("closure_time_outside_returned_interval")
    result.update(
        {
            "reliable": reliable,
            "reason": "ok" if reliable else ";".join(reasons),
            "frequency_ratio": ratio,
            "frequency_ratio_error": ratio - anchor.target_ratio,
            "resonant_phase_initial_rad": resonant_initial,
            "resonant_phase_drift_rad": drift,
            "closure_time_s": closure_time,
            "normalized_four_state_closure_error": closure_error,
        }
    )
    return result


def tension_summary(
    time_s: np.ndarray,
    tensile: dict[str, np.ndarray],
    signed: dict[str, np.ndarray],
) -> dict[str, Any]:
    finite_arrays = [np.asarray(values, dtype=float) for values in signed.values()]
    scale = max(
        [float(np.max(np.abs(values))) for values in finite_arrays if values.size]
        + [1.0]
    )
    tolerance = max(1.0e-12, 1.0e-10 * scale)
    first_time: float | None = None
    first_branches: list[str] = []
    branch_summary: dict[str, Any] = {}
    for branch in sorted(signed):
        signed_values = np.asarray(signed[branch], dtype=float)
        tensile_values = np.asarray(tensile[branch], dtype=float)
        branch_summary[branch] = {
            "minimum_tensile_force_N": float(np.min(tensile_values)),
            "maximum_tensile_force_N": float(np.max(tensile_values)),
            "minimum_signed_axial_force_N": float(np.min(signed_values)),
            "maximum_signed_axial_force_N": float(np.max(signed_values)),
        }
        per_sample = np.min(signed_values.reshape(signed_values.shape[0], -1), axis=1)
        indices = np.flatnonzero(per_sample <= tolerance)
        if indices.size:
            candidate = float(time_s[int(indices[0])])
            if first_time is None or candidate < first_time - 1.0e-15:
                first_time = candidate
                first_branches = [branch]
            elif abs(candidate - first_time) <= 1.0e-15:
                first_branches.append(branch)
    return {
        "zero_tolerance_N": tolerance,
        "first_non_tensile_sample_time_s": first_time,
        "first_non_tensile_branches": sorted(first_branches),
        "branches": branch_summary,
    }


def torus_result_summary(
    result: Any, anchor: Anchor, setup: dict[str, Any], wall_s: float
) -> tuple[dict[str, Any], Series | None]:
    states = np.asarray(result.state.get("X_torus", np.empty((0, 4))), dtype=float)
    time = np.asarray(result.time, dtype=float)
    if time.size == 0 or states.shape != (time.size, 4):
        return (
            {
                "model_id": result.model_id,
                "physical_status": list(result.contract_status),
                "numerical_status": result.numerical_status,
                "wall_seconds": wall_s,
                "sample_count": int(time.size),
                "error": "canonical torus series unavailable",
            },
            None,
        )
    phi, theta, phi_dot, theta_dot = states.T
    h = float(setup["h_m"])
    radius = h + ELL_M * np.cos(phi)
    bob_position = np.asarray(result.derived["r_m"], dtype=float)
    bob_velocity = np.column_stack(
        (
            ELL_M * np.cos(phi) * phi_dot,
            -ELL_M * np.sin(phi) * phi_dot * np.sin(theta)
            + radius * np.cos(theta) * theta_dot,
            -ELL_M * np.sin(phi) * phi_dot * np.cos(theta)
            - radius * np.sin(theta) * theta_dot,
        )
    )
    series = Series(time, bob_position, bob_velocity)
    tensile = {
        name: np.asarray(result.derived[name], dtype=float)[:, None]
        for name in ("T_A", "T_B", "T_lower")
    }
    energy = np.asarray(result.derived["E_torus"], dtype=float)
    energy_scale = max(abs(float(energy[0])), BOB_MASS_KG * G_M_S2 * ELL_M, 1.0e-30)
    normalized_guards = {
        "R": float(np.min(result.derived["R"])) / ELL_M,
        "T_A": float(np.min(result.derived["T_A"])) / (BOB_MASS_KG * G_M_S2),
        "T_B": float(np.min(result.derived["T_B"])) / (BOB_MASS_KG * G_M_S2),
        "T_lower": float(np.min(result.derived["T_lower"]))
        / (BOB_MASS_KG * G_M_S2),
    }
    summary = {
        "model_id": result.model_id,
        "physical_status": list(result.contract_status),
        "numerical_status": result.numerical_status,
        "returned_interval": result.returned_interval,
        "duration_s": float(time[-1] - time[0]),
        "sample_count": int(time.size),
        "wall_seconds": wall_s,
        "modal": modal_metrics(
            series,
            anchor,
            setup,
            closure_cycles=COMMON_PERIODS * anchor.q,
        ),
        "tension": tension_summary(time, tensile, tensile),
        "energy": {
            "maximum_relative_conservative_drift": float(
                np.max(np.abs(energy - energy[0])) / energy_scale
            )
        },
        "guards": {
            "minimum_normalized_margin": min(normalized_guards.values()),
            "normalized_minima": normalized_guards,
            "first_physical_exit": result.events[0] if result.events else None,
        },
    }
    return summary, series


def cable_result_summary(
    result: Any, anchor: Anchor, setup: dict[str, Any], wall_s: float
) -> tuple[dict[str, Any], Series | None]:
    time = np.asarray(result.time, dtype=float)
    positions = np.asarray(result.state.get("r_m", np.empty((0, 3))), dtype=float)
    velocities = np.asarray(result.state.get("v_m", np.empty((0, 3))), dtype=float)
    if time.size == 0 or positions.shape != (time.size, 3):
        return (
            {
                "model_id": result.model_id,
                "physical_status": list(result.contract_status),
                "numerical_status": result.numerical_status,
                "wall_seconds": wall_s,
                "sample_count": int(time.size),
                "events": result.events,
                "error": "canonical cable series unavailable",
            },
            None,
        )
    series = Series(time, positions, velocities)
    branch_data = result.derived["branches"]
    tensile = {
        branch: np.asarray(values["N"], dtype=float)
        for branch, values in branch_data.items()
    }
    component_series = result.diagnostics.get("sampled_guard_component_series", {})
    component_scales = result.diagnostics.get("guard_component_scales", {})
    normalized_minima = {
        name: float(np.min(np.asarray(values, dtype=float)))
        / max(float(component_scales[name]), np.finfo(float).tiny)
        for name, values in component_series.items()
        if name in component_scales
        and np.asarray(values).size
        and np.all(np.isfinite(values))
        and math.isfinite(float(component_scales[name]))
        and float(component_scales[name]) > 0.0
    }
    summary = {
        "model_id": result.model_id,
        "physical_status": list(result.contract_status),
        "numerical_status": result.numerical_status,
        "returned_interval": result.returned_interval,
        "duration_s": float(time[-1] - time[0]),
        "sample_count": int(time.size),
        "wall_seconds": wall_s,
        "modal": modal_metrics(
            series,
            anchor,
            setup,
            closure_cycles=COMMON_PERIODS * anchor.q,
        ),
        "tension": tension_summary(time, tensile, tensile),
        "energy": {
            "maximum_relative_power_balance_residual_physical_traction": (
                result.diagnostics.get(
                    "max_relative_energy_power_residual_physical_traction"
                )
            ),
            "minimum_axial_dissipation_W": result.diagnostics.get("min_D_ax"),
            "minimum_string_drag_dissipation_W": result.diagnostics.get(
                "min_D_string"
            ),
            "minimum_bob_drag_dissipation_W": result.diagnostics.get("min_D_b"),
        },
        "guards": {
            "minimum_normalized_margin": (
                min(normalized_minima.values()) if normalized_minima else None
            ),
            "normalized_minima": normalized_minima,
            "first_physical_exit": result.events[0] if result.events else None,
        },
        "preparation": result.diagnostics.get("preparation"),
        "mesh": result.metadata.get("elements"),
    }
    return summary, series


def hf_result_summary(
    result: Any, anchor: Anchor, setup: dict[str, Any], wall_s: float
) -> tuple[dict[str, Any], Series | None]:
    time = np.asarray(result.time, dtype=float)
    positions = np.asarray(result.bob_position, dtype=float)
    velocities = np.asarray(result.bob_velocity, dtype=float)
    if time.size == 0 or positions.shape != (time.size, 3):
        return (
            {
                "model_id": result.model_id,
                "physical_status": result.physical_status,
                "numerical_status": result.numerical_status,
                "wall_seconds": wall_s,
                "sample_count": int(time.size),
                "events": result.events,
                "error": "canonical HF series unavailable",
            },
            None,
        )
    series = Series(time, positions, velocities)
    metadata = result.diagnostics.get("guard_component_metadata", {})
    normalized_minima = {
        name: float(np.min(np.asarray(values, dtype=float)))
        / max(float(metadata[name]["scale"]), np.finfo(float).tiny)
        for name, values in result.guard_margins.items()
        if name in metadata
        and float(metadata[name]["scale"]) > 0.0
        and np.asarray(values).size
    }
    summary = {
        "model_id": result.model_id,
        "physical_status": result.physical_status,
        "numerical_status": result.numerical_status,
        "valid_interval": list(result.valid_interval),
        "duration_s": float(time[-1] - time[0]),
        "sample_count": int(time.size),
        "wall_seconds": wall_s,
        "modal": modal_metrics(
            series,
            anchor,
            setup,
            closure_cycles=COMMON_PERIODS * anchor.q,
        ),
        "tension": tension_summary(
            time,
            {name: np.asarray(values) for name, values in result.cable_tension.items()},
            {
                name: np.asarray(values)
                for name, values in result.cable_axial_force.items()
            },
        ),
        "energy": {
            "maximum_absolute_normalized_balance_residual": float(
                np.max(np.abs(result.energy["balance_residual"]))
            ),
            "minimum_axial_dissipation_rate_W": float(
                np.min(result.energy["axial_dissipation_rate"])
            ),
            "minimum_aerodynamic_dissipation_rate_W": float(
                np.min(result.energy["aero_dissipation_rate"])
            ),
        },
        "guards": {
            "minimum_normalized_margin": (
                min(normalized_minima.values()) if normalized_minima else None
            ),
            "normalized_minima": normalized_minima,
            "first_registered_guard_event": next(
                (
                    event
                    for event in result.events
                    if event.get("type")
                    in {
                        "HF_VALIDITY_GUARD",
                        "HF_EVENT_UNRESOLVED_AT_SAMPLED_GUARD",
                    }
                ),
                None,
            ),
        },
        "preparation": {
            "mode": result.diagnostics.get("preparation_mode"),
            "force_residual_inf_N": result.diagnostics.get(
                "preparation_force_residual_inf_N"
            ),
            "iterations": result.diagnostics.get("preparation_iterations"),
        },
        "accepted_integration_steps": result.diagnostics.get(
            "accepted_integration_step_count"
        ),
        "raw_guard_certification_status": result.diagnostics.get(
            "raw_guard_certification_status"
        ),
        "events": result.events,
    }
    return summary, series


def run_model(
    model: str,
    config: dict[str, Any],
    anchor: Anchor,
    setup: dict[str, Any],
) -> tuple[dict[str, Any], Series | None]:
    started = perf_counter()
    if model in {"torus", "cable"}:
        result = run_config(config)
    elif model == "high_fidelity":
        result = simulate(config, write_output=False)
    else:
        raise ValueError(model)
    wall = perf_counter() - started
    if model == "torus":
        return torus_result_summary(result, anchor, setup, wall)
    if model == "cable":
        return cable_result_summary(result, anchor, setup, wall)
    return hf_result_summary(result, anchor, setup, wall)


def cache_paths(cache_root: Path, run_id: str) -> tuple[Path, Path]:
    return cache_root / f"{run_id}.json", cache_root / f"{run_id}.npz"


def run_cached(
    *,
    cache_root: Path,
    run_id: str,
    model: str,
    variant: str,
    config: dict[str, Any],
    anchor: Anchor,
    setup: dict[str, Any],
    analysis_sha256: str,
    force: bool,
) -> tuple[dict[str, Any], Series | None]:
    identity = config_identity(model, config)
    metadata_path, series_path = cache_paths(cache_root, run_id)
    if not force and metadata_path.is_file():
        cached = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            cached.get("config_sha256") == identity
            and cached.get("analysis_source_sha256") == analysis_sha256
            and cached.get("run_status") == "RETURNED"
            and series_path.is_file()
        ):
            print(f"CACHE {run_id}", flush=True)
            return cached["summary"], load_series(series_path)
    print(f"RUN {run_id}", flush=True)
    try:
        summary, series = run_model(model, config, anchor, setup)
        payload = {
            "run_status": "RETURNED",
            "run_id": run_id,
            "anchor": anchor.label,
            "model": model,
            "variant": variant,
            "config_sha256": identity,
            "analysis_source_sha256": analysis_sha256,
            "summary": summary,
        }
        if series is not None:
            save_series(series_path, series)
        write_json(metadata_path, payload)
        print(
            f"DONE {run_id} status={summary.get('numerical_status')} "
            f"wall={summary.get('wall_seconds')}s",
            flush=True,
        )
        return summary, series
    except Exception as exc:
        payload = {
            "run_status": "ERROR",
            "run_id": run_id,
            "anchor": anchor.label,
            "model": model,
            "variant": variant,
            "config_sha256": identity,
            "analysis_source_sha256": analysis_sha256,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        write_json(metadata_path, payload)
        print(
            f"ERROR {run_id} {type(exc).__name__}: {exc}",
            flush=True,
        )
        return payload, None


def compare_series(reference: Series, candidate: Series) -> dict[str, Any]:
    end = min(float(reference.time_s[-1]), float(candidate.time_s[-1]))
    mask = reference.time_s <= end + 1.0e-14
    time = reference.time_s[mask]
    if time.size < 2 or time[0] < candidate.time_s[0] - 1.0e-14:
        return {"status": "NO_COMMON_SERIES"}
    interpolated = np.column_stack(
        [
            np.interp(time, candidate.time_s, candidate.bob_position_m[:, axis])
            for axis in range(3)
        ]
    )
    difference = interpolated - reference.bob_position_m[mask]
    point = np.linalg.norm(difference, axis=1)
    return {
        "status": "DIFFERENCE_COMPUTED",
        "common_start_s": float(time[0]),
        "common_end_s": float(time[-1]),
        "sample_count": int(time.size),
        "rms_component_bob_position_m": float(np.sqrt(np.mean(difference**2))),
        "rms_point_bob_position_m": float(np.sqrt(np.mean(point**2))),
        "maximum_point_bob_position_m": float(np.max(point)),
    }


def nested(mapping: dict[str, Any], *path: str) -> Any:
    value: Any = mapping
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def flat_run_row(
    anchor: Anchor,
    model: str,
    variant: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    physical = summary.get("physical_status")
    if isinstance(physical, list):
        physical = "+".join(str(value) for value in physical)
    branch_minima = [
        value.get("minimum_tensile_force_N")
        for value in (nested(summary, "tension", "branches") or {}).values()
        if isinstance(value, dict)
        and value.get("minimum_tensile_force_N") is not None
    ]
    signed_minima = [
        value.get("minimum_signed_axial_force_N")
        for value in (nested(summary, "tension", "branches") or {}).values()
        if isinstance(value, dict)
        and value.get("minimum_signed_axial_force_N") is not None
    ]
    energy_value = next(
        (
            value
            for value in (summary.get("energy") or {}).values()
            if isinstance(value, (float, int))
        ),
        None,
    )
    return {
        "anchor": anchor.label,
        "p": anchor.p,
        "q": anchor.q,
        "A_phi_rad": anchor.amplitude_phi_rad,
        "A_theta_rad": anchor.amplitude_theta_rad,
        "model": model,
        "variant": variant,
        "model_id": summary.get("model_id"),
        "physical_status": physical,
        "numerical_status": summary.get("numerical_status"),
        "duration_s": summary.get("duration_s"),
        "sample_count": summary.get("sample_count"),
        "wall_seconds": summary.get("wall_seconds"),
        "fast_frequency_hz": nested(
            summary, "modal", "fast", "frequency_hz"
        ),
        "slow_frequency_hz": nested(
            summary, "modal", "slow", "frequency_hz"
        ),
        "fast_fit_r2": nested(summary, "modal", "fast", "fit_r2"),
        "slow_fit_r2": nested(summary, "modal", "slow", "fit_r2"),
        "modal_reliable": nested(summary, "modal", "reliable"),
        "frequency_ratio": nested(summary, "modal", "frequency_ratio"),
        "frequency_ratio_error": nested(
            summary, "modal", "frequency_ratio_error"
        ),
        "resonant_phase_drift_rad": nested(
            summary, "modal", "resonant_phase_drift_rad"
        ),
        "normalized_four_state_closure_error": nested(
            summary, "modal", "normalized_four_state_closure_error"
        ),
        "minimum_tensile_force_N": min(branch_minima) if branch_minima else None,
        "minimum_signed_axial_force_N": min(signed_minima) if signed_minima else None,
        "first_non_tensile_sample_time_s": nested(
            summary, "tension", "first_non_tensile_sample_time_s"
        ),
        "energy_ledger_primary_metric": energy_value,
        "minimum_normalized_guard_margin": nested(
            summary, "guards", "minimum_normalized_margin"
        ),
        "error": summary.get("error"),
    }


def plot_base_trajectories(
    path: Path,
    series_by_key: dict[tuple[str, str, str], Series],
) -> None:
    figure, axes = plt.subplots(1, 3, figsize=(14.0, 4.2), constrained_layout=True)
    colors = {
        "torus": "#2457C5",
        "cable": "#178B56",
        "high_fidelity": "#C94B3C",
    }
    labels = {
        "torus": "ideal torus",
        "cable": "continuous cable",
        "high_fidelity": "HF rod + rigid bob",
    }
    for axis, anchor in zip(axes, ANCHORS, strict=True):
        for model in ("torus", "cable", "high_fidelity"):
            series = series_by_key.get((anchor.label, model, "base"))
            if series is None:
                continue
            stride = max(1, series.time_s.size // 4000)
            axis.plot(
                1000.0 * series.bob_position_m[::stride, 0],
                1000.0 * series.bob_position_m[::stride, 1],
                color=colors[model],
                linewidth=1.0,
                alpha=0.88,
                label=labels[model],
            )
        axis.set_title(f"{anchor.label}; ({anchor.amplitude_phi_rad:.2f}, {anchor.amplitude_theta_rad:.2f}) rad")
        axis.set_xlabel("support-axis bob COM / mm")
        axis.set_ylabel("transverse bob COM / mm")
        axis.grid(True, alpha=0.25)
        axis.set_aspect("equal", adjustable="datalim")
    handles, legend_labels = axes[0].get_legend_handles_labels()
    if handles:
        figure.legend(handles, legend_labels, loc="outside lower center", ncol=3)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, format="svg")
    plt.close(figure)


def git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def runtime_versions() -> dict[str, Any]:
    names = (
        "numpy",
        "scipy",
        "pydantic",
        "PyYAML",
        "h5py",
        "pandas",
        "matplotlib",
        "pint",
    )
    versions: dict[str, Any] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def write_manifest(path: Path, files: list[Path]) -> None:
    rows: list[str] = []
    for file in sorted(files):
        if not file.is_file():
            continue
        try:
            label = file.relative_to(path.parent).as_posix()
        except ValueError:
            label = f"external-source/{file.name}"
        rows.append(f"{sha256_file(file)}  {label}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument(
        "--refinement-scope",
        choices=("all", "representative", "none"),
        default="all",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=CANDIDATE_ROOT,
        help="Root receiving results/, figures/, and generated/.",
    )
    parser.add_argument("--hf-postprocess-workers", type=int, default=1)
    args = parser.parse_args(argv)
    if args.hf_postprocess_workers < 1:
        parser.error("--hf-postprocess-workers must be positive")
    os.environ["YPS_HF_POSTPROCESS_WORKERS"] = str(
        args.hf_postprocess_workers
    )

    output_root = args.output_root.expanduser().resolve()
    results_root = output_root / "results"
    figures_root = output_root / "figures"
    cache_root = output_root / "generated" / "runs"
    for directory in (results_root, figures_root, cache_root):
        directory.mkdir(parents=True, exist_ok=True)

    analysis_sha = sha256_file(SCRIPT_PATH)
    formal_identity_start = {
        "git_head": git_head(),
        "forward_source_tree_sha256": source_tree_sha256(),
        "hf_source_tree_sha256": source_hash(HF_ROOT / "src" / "ypendulum"),
        "atlas_source_sha256": sha256_file(ATLAS_PATH),
        "analysis_source_sha256": analysis_sha,
    }
    anchors = ANCHORS[:1] if args.smoke else ANCHORS
    run_summaries: dict[tuple[str, str, str], dict[str, Any]] = {}
    series_by_key: dict[tuple[str, str, str], Series] = {}
    setup_rows: list[dict[str, Any]] = []
    audit_rows: dict[str, Any] = {}

    for anchor in anchors:
        setup = anchor_setup(anchor)
        setup_rows.append(setup)
        if args.smoke:
            horizon_s = 0.05
            output_dt_s = 0.0005
        else:
            horizon_s = (
                COMMON_PERIODS * anchor.q + 1.25
            ) * float(setup["nominal_slow_period_s"])
            output_dt_s = 0.005
        torus, cable, hf, audit = build_configs(
            anchor,
            setup,
            horizon_s=horizon_s,
            output_dt_s=output_dt_s,
        )
        audit_rows[anchor.label] = audit
        base_configs = {
            "torus": torus,
            "cable": cable,
            "high_fidelity": hf,
        }
        variants: list[tuple[str, str]] = [
            ("torus", "base"),
            ("cable", "base"),
            ("high_fidelity", "base"),
        ]
        if not args.smoke:
            variants.append(("torus", "time_fine"))
            refine_this_anchor = args.refinement_scope == "all" or (
                args.refinement_scope == "representative" and anchor.label == "3:2"
            )
            if refine_this_anchor:
                variants.extend(
                    (
                        ("cable", "time_fine"),
                        ("cable", "space_fine"),
                        ("high_fidelity", "time_fine"),
                        ("high_fidelity", "space_fine"),
                    )
                )
        for model, variant in variants:
            config = variant_config(
                model,
                base_configs[model],
                variant,
                output_dt_s=output_dt_s,
            )
            run_id = f"{anchor.slug}__{model}__{variant}"
            summary, series = run_cached(
                cache_root=cache_root,
                run_id=run_id,
                model=model,
                variant=variant,
                config=config,
                anchor=anchor,
                setup=setup,
                analysis_sha256=analysis_sha,
                force=args.force,
            )
            run_summaries[(anchor.label, model, variant)] = summary
            if series is not None:
                series_by_key[(anchor.label, model, variant)] = series

    formal_identity_end = {
        "git_head": git_head(),
        "forward_source_tree_sha256": source_tree_sha256(),
        "hf_source_tree_sha256": source_hash(HF_ROOT / "src" / "ypendulum"),
        "atlas_source_sha256": sha256_file(ATLAS_PATH),
        "analysis_source_sha256": sha256_file(SCRIPT_PATH),
    }
    identity_stable = formal_identity_start == formal_identity_end
    if not identity_stable:
        raise RuntimeError(
            "Formal source, atlas source, candidate source, or git HEAD changed during run."
        )

    run_rows = [
        flat_run_row(anchor, model, variant, summary)
        for anchor in anchors
        for (label, model, variant), summary in run_summaries.items()
        if label == anchor.label
    ]
    refinement_rows: list[dict[str, Any]] = []
    for anchor in anchors:
        for model in ("torus", "cable", "high_fidelity"):
            base = series_by_key.get((anchor.label, model, "base"))
            if base is None:
                continue
            for variant in ("time_fine", "space_fine"):
                candidate = series_by_key.get((anchor.label, model, variant))
                if candidate is None:
                    continue
                difference = compare_series(base, candidate)
                base_summary = run_summaries[(anchor.label, model, "base")]
                candidate_summary = run_summaries[
                    (anchor.label, model, variant)
                ]
                refinement_rows.append(
                    {
                        "anchor": anchor.label,
                        "model": model,
                        "study": variant,
                        **difference,
                        "frequency_ratio_abs_difference": (
                            abs(
                                float(
                                    nested(
                                        candidate_summary,
                                        "modal",
                                        "frequency_ratio",
                                    )
                                )
                                - float(
                                    nested(
                                        base_summary,
                                        "modal",
                                        "frequency_ratio",
                                    )
                                )
                            )
                            if nested(candidate_summary, "modal", "frequency_ratio")
                            is not None
                            and nested(base_summary, "modal", "frequency_ratio")
                            is not None
                            else None
                        ),
                        "closure_abs_difference": (
                            abs(
                                float(
                                    nested(
                                        candidate_summary,
                                        "modal",
                                        "normalized_four_state_closure_error",
                                    )
                                )
                                - float(
                                    nested(
                                        base_summary,
                                        "modal",
                                        "normalized_four_state_closure_error",
                                    )
                                )
                            )
                            if nested(
                                candidate_summary,
                                "modal",
                                "normalized_four_state_closure_error",
                            )
                            is not None
                            and nested(
                                base_summary,
                                "modal",
                                "normalized_four_state_closure_error",
                            )
                            is not None
                            else None
                        ),
                    }
                )

    comparison_rows: list[dict[str, Any]] = []
    pairs = (
        ("torus", "cable"),
        ("cable", "high_fidelity"),
        ("torus", "high_fidelity"),
    )
    for anchor in anchors:
        for reference_model, candidate_model in pairs:
            reference = series_by_key.get((anchor.label, reference_model, "base"))
            candidate = series_by_key.get((anchor.label, candidate_model, "base"))
            if reference is None or candidate is None:
                continue
            comparison_rows.append(
                {
                    "anchor": anchor.label,
                    "reference_model": reference_model,
                    "candidate_model": candidate_model,
                    **compare_series(reference, candidate),
                }
            )

    write_csv(results_root / "anchor_run_metrics.csv", run_rows)
    write_csv(results_root / "refinement_sensitivity.csv", refinement_rows)
    write_csv(results_root / "model_form_differences.csv", comparison_rows)
    write_json(results_root / "anchor_definitions.json", setup_rows)
    write_json(
        results_root / "run_summary.json",
        {
            "schema_version": "YPS-THREE-ANCHOR-LADDER-1.0",
            "profile": "smoke" if args.smoke else "full",
            "refinement_scope": args.refinement_scope,
            "common_period_count": COMMON_PERIODS,
            "closure_slow_cycles_by_anchor": {
                anchor.label: COMMON_PERIODS * anchor.q for anchor in anchors
            },
            "formal_identity_start": formal_identity_start,
            "formal_identity_end": formal_identity_end,
            "formal_identity_stable_during_run": identity_stable,
            "shared_input_audits": audit_rows,
            "runtime": {
                "python": sys.version,
                "executable": sys.executable,
                "dependencies": runtime_versions(),
                "hf_postprocess_workers": args.hf_postprocess_workers,
            },
            "runs": {
                f"{label}/{model}/{variant}": summary
                for (label, model, variant), summary in run_summaries.items()
            },
            "status": (
                "COMPLETE_RETURN_SET"
                if all(summary.get("run_status") != "ERROR" for summary in run_summaries.values())
                else "PARTIAL_RETURN_SET"
            ),
            "claim_boundary": (
                "candidate model-form comparison; raw single-run HF status remains "
                "guard-uncertified; two-level sensitivities are not convergence proofs; "
                "no experiment or calibration is used"
            ),
        },
    )
    if not args.smoke:
        plot_base_trajectories(
            figures_root / "three_anchor_modal_trajectories.svg",
            series_by_key,
        )
    release_files = [
        SCRIPT_PATH,
        results_root / "anchor_run_metrics.csv",
        results_root / "refinement_sensitivity.csv",
        results_root / "model_form_differences.csv",
        results_root / "anchor_definitions.json",
        results_root / "run_summary.json",
    ]
    figure_path = figures_root / "three_anchor_modal_trajectories.svg"
    if figure_path.is_file():
        release_files.append(figure_path)
    write_manifest(output_root / "MANIFEST.sha256", release_files)
    print(
        f"COMPLETE output={output_root} runs={len(run_summaries)} "
        f"identity_stable={identity_stable}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
