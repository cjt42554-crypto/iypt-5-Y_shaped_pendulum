"""Common observables from preregistered modal coordinates."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import periodogram


@dataclass(frozen=True)
class DampedModeEstimate:
    amplitude: float
    damping_per_s: float
    omega_rad_s: float
    phase_rad: float
    offset: float
    residual_rms: float


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


def common_observables(
    *,
    data_origin: str,
    identity: dict,
    valid_interval_s: tuple[float, float],
    fast: DampedModeEstimate,
    slow: DampedModeEstimate,
    phase: np.ndarray,
    closure_error: float,
    events: list[dict],
    uncertainty: dict,
    domain_status: str,
) -> dict:
    if fast.omega_rad_s <= slow.omega_rad_s:
        raise ValueError("fast-mode frequency must exceed slow-mode frequency")
    interval = np.asarray(valid_interval_s, dtype=float)
    phase_array = np.asarray(phase, dtype=float)
    if interval.shape != (2,) or not np.all(np.isfinite(interval)) or interval[0] >= interval[1]:
        raise ValueError("valid interval must contain two increasing finite times")
    if phase_array.ndim != 1 or not np.all(np.isfinite(phase_array)):
        raise ValueError("resonant phase must be a finite one-dimensional array")
    if not np.isfinite(closure_error) or closure_error < 0:
        raise ValueError("closure error must be finite and non-negative")
    return {
        "schema_id": "YPS-EXPERIMENT-COMMON-OBSERVABLES-1.0",
        "data_origin": data_origin,
        "identity": identity,
        "valid_interval_s": interval.tolist(),
        "frequency": {
            "omega_fast_rad_s": fast.omega_rad_s,
            "omega_slow_rad_s": slow.omega_rad_s,
            "ratio": fast.omega_rad_s / slow.omega_rad_s,
        },
        "damping": {"fast_per_s": fast.damping_per_s, "slow_per_s": slow.damping_per_s},
        "resonant_phase": phase_array.tolist(),
        "closure_error": float(closure_error),
        "event_list": list(events),
        "uncertainty": dict(uncertainty),
        "domain_status": domain_status,
    }
