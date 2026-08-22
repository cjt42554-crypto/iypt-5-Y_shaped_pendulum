"""Instantaneous phase and p:q resonant phase."""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, hilbert, sosfiltfilt


def analytic_phase(
    time: np.ndarray,
    signal: np.ndarray,
    *,
    center_frequency: float | None = None,
    fractional_bandwidth: float = 0.5,
) -> np.ndarray:
    t = np.asarray(time, dtype=float)
    x = np.asarray(signal, dtype=float) - np.mean(signal)
    if center_frequency is not None and len(t) >= 32:
        fs = 1.0 / float(np.median(np.diff(t)))
        low = max(center_frequency * (1.0 - fractional_bandwidth), 1.0 / (t[-1] - t[0]))
        high = min(center_frequency * (1.0 + fractional_bandwidth), 0.45 * fs)
        if 0 < low < high < 0.5 * fs:
            sos = butter(4, [low, high], btype="bandpass", fs=fs, output="sos")
            x = sosfiltfilt(sos, x)
    return np.unwrap(np.angle(hilbert(x)))


def resonant_phase(
    phase_fast: np.ndarray, phase_slow: np.ndarray, p: int, q: int
) -> np.ndarray:
    return np.unwrap(q * np.asarray(phase_fast) - p * np.asarray(phase_slow))


def linear_phase_drift(time: np.ndarray, phase: np.ndarray) -> tuple[float, float]:
    t = np.asarray(time, dtype=float)
    y = np.asarray(phase, dtype=float)
    design = np.column_stack([t, np.ones_like(t)])
    slope, intercept = np.linalg.lstsq(design, y, rcond=None)[0]
    residual = y - (slope * t + intercept)
    return float(slope), float(np.sqrt(np.mean(residual**2)))
