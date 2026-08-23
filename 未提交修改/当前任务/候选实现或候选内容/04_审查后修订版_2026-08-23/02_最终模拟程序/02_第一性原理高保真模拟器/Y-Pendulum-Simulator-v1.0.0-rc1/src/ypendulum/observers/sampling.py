"""Frame sampling and finite-exposure temporal averaging."""

from __future__ import annotations

import numpy as np
from scipy.integrate import trapezoid
from scipy.interpolate import CubicSpline


def sample_with_exposure(
    time: np.ndarray,
    values: np.ndarray,
    *,
    frame_rate: float,
    exposure_time: float = 0.0,
    sub_samples: int = 9,
) -> tuple[np.ndarray, np.ndarray]:
    t = np.asarray(time, dtype=float)
    x = np.asarray(values, dtype=float)
    if t.ndim != 1 or x.shape[0] != t.size:
        raise ValueError("Time and sampled values are incompatible.")
    if frame_rate <= 0 or exposure_time < 0:
        raise ValueError("frame_rate must be positive and exposure_time non-negative.")
    start = float(t[0]) + 0.5 * exposure_time
    end = float(t[-1]) - 0.5 * exposure_time
    if end < start:
        raise ValueError("Exposure time is longer than the available record.")
    frame_t = np.arange(start, end + 0.5 / frame_rate, 1.0 / frame_rate)
    frame_t = frame_t[frame_t <= end + 1e-14]
    spline = CubicSpline(t, x, axis=0, extrapolate=False)
    if exposure_time == 0:
        return frame_t, np.asarray(spline(frame_t), dtype=float)
    offsets = np.linspace(-0.5 * exposure_time, 0.5 * exposure_time, max(sub_samples, 3))
    samples = np.asarray(spline(frame_t[:, None] + offsets[None, :]), dtype=float)
    # scipy.integrate.trapezoid is available throughout the declared
    # NumPy>=1.26 / SciPy>=1.11 compatibility range.  np.trapezoid only
    # appeared in NumPy 2.0.
    averaged = trapezoid(samples, offsets, axis=1) / exposure_time
    return frame_t, averaged
