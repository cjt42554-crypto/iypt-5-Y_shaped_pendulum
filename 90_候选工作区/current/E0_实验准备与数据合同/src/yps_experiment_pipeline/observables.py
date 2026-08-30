"""Common observables from preregistered modal coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import periodogram

from .contracts import canonical_json_bytes, sha256_file

REQUIRED_COMMON_ARRAYS = {
    "time_s",
    "r_bob_W_m",
    "r_junction_W_m",
    "modal_basis_W",
    "q_fast_m",
    "q_slow_m",
    "resonant_phase_rad",
    "valid_mask",
}


@dataclass(frozen=True)
class DampedModeEstimate:
    amplitude: float
    damping_per_s: float
    omega_rad_s: float
    phase_rad: float
    offset: float
    residual_rms: float


def sampling_diagnostics(
    time_s: np.ndarray,
    *,
    maximum_relative_interval_deviation: float = 0.01,
) -> dict[str, float | str | None]:
    time = np.asarray(time_s, dtype=float)
    if time.ndim != 1 or time.size < 2 or not np.all(np.isfinite(time)):
        raise ValueError("time must be a finite one-dimensional array")
    intervals = np.diff(time)
    if not np.all(intervals > 0):
        raise ValueError("time must be strictly increasing")
    median = float(np.median(intervals))
    relative_deviation = float(np.max(np.abs(intervals - median)) / median)
    if relative_deviation > maximum_relative_interval_deviation:
        raise ValueError(
            "irregular sampling exceeds the native-series gate; a separately "
            "preregistered, hash-bound resampling step is required"
        )
    return {
        "method": "NATIVE_UNIFORM",
        "median_interval_s": median,
        "maximum_relative_interval_deviation": relative_deviation,
        "resampling_configuration_sha256": None,
    }


def _check_series(time_s: np.ndarray, coordinate: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    time = np.asarray(time_s, dtype=float)
    values = np.asarray(coordinate, dtype=float)
    if time.ndim != 1 or values.shape != time.shape or time.size < 32:
        raise ValueError(
            "time and coordinate need a common one-dimensional shape with at least 32 samples"
        )
    if not (np.all(np.isfinite(time)) and np.all(np.isfinite(values))):
        raise ValueError("time and coordinate must be finite")
    if not np.all(np.diff(time) > 0):
        raise ValueError("time must be strictly increasing")
    sampling_diagnostics(time)
    return time, values


def estimate_damped_mode(time_s: np.ndarray, coordinate: np.ndarray) -> DampedModeEstimate:
    """Fit ``offset + A exp(-gamma t) cos(omega t + phase)``."""

    time, values = _check_series(time_s, coordinate)
    relative = time - time[0]
    dt = float(np.median(np.diff(relative)))
    frequencies_hz, power = periodogram(values - np.mean(values), fs=1.0 / dt)
    positive = frequencies_hz > 0
    if not np.any(positive):
        raise ValueError("no positive frequency bin")
    omega_guess = 2.0 * np.pi * float(frequencies_hz[positive][np.argmax(power[positive])])
    amplitude_guess = max(0.5 * float(np.ptp(values)), np.finfo(float).eps)
    offset_guess = float(np.mean(values))

    def model(parameters: np.ndarray) -> np.ndarray:
        amplitude, damping, omega, phase, offset = parameters
        return offset + amplitude * np.exp(-damping * relative) * np.cos(omega * relative + phase)

    def residual(parameters: np.ndarray) -> np.ndarray:
        return model(parameters) - values

    lower = np.array([0.0, 0.0, 0.25 * omega_guess, -4.0 * np.pi, -np.inf])
    upper = np.array(
        [10.0 * amplitude_guess, 10.0 / relative[-1], 4.0 * omega_guess, 4.0 * np.pi, np.inf]
    )
    initial = np.array([amplitude_guess, 0.01 / relative[-1], omega_guess, 0.0, offset_guess])
    fit = least_squares(
        residual, initial, bounds=(lower, upper), xtol=1e-13, ftol=1e-13, gtol=1e-13
    )
    if not fit.success:
        raise ValueError("damped-mode fit did not converge")
    amplitude, damping, omega, phase, offset = (float(value) for value in fit.x)
    return DampedModeEstimate(
        amplitude=amplitude,
        damping_per_s=damping,
        omega_rad_s=omega,
        phase_rad=float(np.arctan2(np.sin(phase), np.cos(phase))),
        offset=offset,
        residual_rms=float(np.sqrt(np.mean(np.square(fit.fun)))),
    )


def resonant_phase(
    phase_fast_rad: np.ndarray,
    phase_slow_rad: np.ndarray,
    *,
    p: int,
    q: int,
) -> np.ndarray:
    fast = np.asarray(phase_fast_rad, dtype=float)
    slow = np.asarray(phase_slow_rad, dtype=float)
    if fast.shape != slow.shape or fast.ndim != 1 or p <= 0 or q <= 0:
        raise ValueError("phase arrays must match and p, q must be positive")
    if not (np.all(np.isfinite(fast)) and np.all(np.isfinite(slow))):
        raise ValueError("phase arrays must be finite")
    return np.unwrap(q * fast - p * slow)


def normalized_closure_error(start_state: np.ndarray, end_state: np.ndarray, scale: float) -> float:
    start = np.asarray(start_state, dtype=float)
    end = np.asarray(end_state, dtype=float)
    if (
        start.shape != end.shape
        or not (np.all(np.isfinite(start)) and np.all(np.isfinite(end)))
        or not np.isfinite(scale)
        or scale <= 0
    ):
        raise ValueError("states must match and scale must be positive")
    return float(np.linalg.norm(end - start) / scale)


def _validate_common_arrays(arrays: dict[str, np.ndarray], units: dict[str, str]) -> np.ndarray:
    missing = sorted(REQUIRED_COMMON_ARRAYS - set(arrays))
    if missing:
        raise ValueError(f"common observable bundle lacks required arrays: {missing}")
    if set(units) != set(arrays):
        raise ValueError("common observable units must have exactly one entry per array")
    time = np.asarray(arrays["time_s"], dtype=float)
    if time.ndim != 1 or time.size < 32:
        raise ValueError("common observable time axis must contain at least 32 samples")
    sampling_diagnostics(time)
    valid = np.asarray(arrays["valid_mask"], dtype=bool)
    if valid.shape != time.shape or not np.any(valid):
        raise ValueError("common observable valid mask must select at least one sample")
    bob = np.asarray(arrays["r_bob_W_m"], dtype=float)
    junction = np.asarray(arrays["r_junction_W_m"], dtype=float)
    basis = np.asarray(arrays["modal_basis_W"], dtype=float)
    fast = np.asarray(arrays["q_fast_m"], dtype=float)
    slow = np.asarray(arrays["q_slow_m"], dtype=float)
    phase = np.asarray(arrays["resonant_phase_rad"], dtype=float)
    if bob.shape != (time.size, 3) or junction.shape != (time.size, 3):
        raise ValueError("common bob and junction trajectories must have shape (sample, 3)")
    if basis.shape != (2, 3) or not np.all(np.isfinite(basis)):
        raise ValueError("modal_basis_W must have shape (2, 3) and finite entries")
    if np.max(np.abs(basis @ basis.T - np.eye(2))) > 1e-8:
        raise ValueError("modal basis rows must be orthonormal")
    for name, value in (("q_fast_m", fast), ("q_slow_m", slow), ("resonant_phase_rad", phase)):
        if value.shape != time.shape:
            raise ValueError(f"{name} must have the common sample axis")
    if not (
        np.all(np.isfinite(time))
        and np.all(np.isfinite(bob[valid]))
        and np.all(np.isfinite(junction[valid]))
        and np.all(np.isfinite(fast[valid]))
        and np.all(np.isfinite(slow[valid]))
        and np.all(np.isfinite(phase[valid]))
    ):
        raise ValueError("common observable arrays must be finite on valid samples")
    return valid


def common_observable_manifest(
    *,
    data_origin: str,
    identity: dict,
    trajectory_manifest_file: Path,
    array_file: Path,
    arrays: dict[str, np.ndarray],
    units: dict[str, str],
    modal_basis_provenance: dict[str, Any],
    fast: DampedModeEstimate,
    slow: DampedModeEstimate,
    closure_error: float,
    events: list[dict],
    uncertainty: dict,
    domain_status: str,
) -> dict[str, Any]:
    if fast.omega_rad_s <= slow.omega_rad_s:
        raise ValueError("fast-mode frequency must exceed slow-mode frequency")
    valid = _validate_common_arrays(arrays, units)
    if not trajectory_manifest_file.is_file() or not array_file.is_file():
        raise ValueError("common observables require existing trajectory and array files")
    if not np.isfinite(closure_error) or closure_error < 0:
        raise ValueError("closure error must be finite and non-negative")
    time = np.asarray(arrays["time_s"], dtype=float)
    fields = {}
    for name, value in sorted(arrays.items()):
        array = np.asarray(value)
        fields[name] = {"shape": list(array.shape), "unit": units[name], "dtype": str(array.dtype)}
    return {
        "schema_id": "YPS-EXPERIMENT-COMMON-OBSERVABLES-1.1",
        "data_origin": data_origin,
        "identity": identity,
        "trajectory_manifest_sha256": sha256_file(trajectory_manifest_file),
        "array_file": array_file.name,
        "array_sha256": sha256_file(array_file),
        "fields": fields,
        "sample_count": int(time.size),
        "modal_basis_provenance": dict(modal_basis_provenance),
        "sampling": sampling_diagnostics(time),
        "valid_interval_s": [float(time[valid][0]), float(time[valid][-1])],
        "frequency": {
            "omega_fast_rad_s": fast.omega_rad_s,
            "omega_slow_rad_s": slow.omega_rad_s,
            "ratio": fast.omega_rad_s / slow.omega_rad_s,
        },
        "damping": {"fast_per_s": fast.damping_per_s, "slow_per_s": slow.damping_per_s},
        "closure_error": float(closure_error),
        "event_list": list(events),
        "uncertainty": dict(uncertainty),
        "domain_status": domain_status,
    }


def write_common_observables(
    output_directory: Path,
    *,
    data_origin: str,
    identity: dict,
    trajectory_manifest_file: Path,
    arrays: dict[str, np.ndarray],
    units: dict[str, str],
    modal_basis_provenance: dict[str, Any],
    fast: DampedModeEstimate,
    slow: DampedModeEstimate,
    closure_error: float,
    events: list[dict],
    uncertainty: dict,
    domain_status: str,
) -> dict[str, Any]:
    _validate_common_arrays(arrays, units)
    if not trajectory_manifest_file.is_file():
        raise ValueError("source trajectory manifest does not exist")
    output_directory.mkdir(parents=True, exist_ok=False)
    array_file = output_directory / "common_observables.npz"
    np.savez_compressed(array_file, **arrays)
    manifest = common_observable_manifest(
        data_origin=data_origin,
        identity=identity,
        trajectory_manifest_file=trajectory_manifest_file,
        array_file=array_file,
        arrays=arrays,
        units=units,
        modal_basis_provenance=modal_basis_provenance,
        fast=fast,
        slow=slow,
        closure_error=closure_error,
        events=events,
        uncertainty=uncertainty,
        domain_status=domain_status,
    )
    (output_directory / "processed_observables.json").write_bytes(
        canonical_json_bytes(manifest) + b"\n"
    )
    return manifest
