"""Independent power quadrature on accepted solver intervals.

The requested output grid never defines the integration mesh. Each output uses
an accepted-step prefix plus a partial-interval Gauss rule. This is a numerical
ledger, not a proof of the physical model or a quadrature error bound.
"""
from __future__ import annotations

from collections.abc import Callable
import numpy as np


def integrate_power_ledger(
    accepted_times: np.ndarray,
    sample_times: np.ndarray,
    power_at: Callable[[float], np.ndarray],
) -> tuple[np.ndarray, int]:
    """Integrate physical power, algebraic power and absolute port exchange.

    ``power_at(t)`` returns those three finite values in watts. Three-point
    Gauss-Legendre quadrature is exact for polynomials up to degree five; a
    nonsmooth power history still requires time refinement.
    """
    mesh = np.asarray(accepted_times, dtype=float)
    samples = np.asarray(sample_times, dtype=float)
    if mesh.ndim != 1 or mesh.size == 0 or not np.isfinite(mesh).all() or np.any(np.diff(mesh) <= 0):
        raise ValueError("accepted_times must be finite and strictly increasing")
    if samples.ndim != 1 or not np.isfinite(samples).all() or np.any(np.diff(samples) < 0):
        raise ValueError("sample_times must be finite and nondecreasing")
    if samples.size == 0:
        return np.empty((0, 3)), 0
    if samples[0] < mesh[0] or samples[-1] > mesh[-1]:
        raise ValueError("power quadrature cannot extrapolate beyond accepted solver times")
    nodes = np.array([-np.sqrt(3.0 / 5.0), 0.0, np.sqrt(3.0 / 5.0)])
    weights = np.array([5.0 / 9.0, 8.0 / 9.0, 5.0 / 9.0])
    evaluations = 0

    def integral(left: float, right: float) -> np.ndarray:
        nonlocal evaluations
        if right == left:
            return np.zeros(3)
        half = (right - left) / 2.0
        values = np.asarray([power_at(float((right + left) / 2.0 + half * x)) for x in nodes])
        evaluations += 3
        if values.shape != (3, 3) or not np.isfinite(values).all():
            raise FloatingPointError("power callback must return three finite components")
        return half * (weights @ values)

    # Only integrate the accepted intervals preceding the last requested sample.
    indices = np.searchsorted(mesh, samples, side="right") - 1
    last = int(indices[-1])
    prefix = np.zeros((last + 1, 3))
    for index in range(last):
        prefix[index + 1] = prefix[index] + integral(mesh[index], mesh[index + 1])
    values = np.empty((samples.size, 3))
    for row, (sample, index) in enumerate(zip(samples, indices)):
        values[row] = prefix[index] + integral(mesh[index], sample)
    return values, evaluations
