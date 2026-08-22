"""Independent damping-envelope diagnostics and model comparison."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class EnvelopeFit:
    model: str
    coefficient: float
    intercept: float
    rms_transformed: float
    r_squared_transformed: float
    rms_amplitude: float
    aic: float
    point_count: int

    @property
    def rms(self) -> float:
        """Backward-compatible alias for the transformed-space residual RMS."""

        return self.rms_transformed

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate(time: np.ndarray, amplitude: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    t = np.asarray(time, dtype=float)
    a = np.asarray(amplitude, dtype=float)
    if t.shape != a.shape or t.ndim != 1 or t.size < 4:
        raise ValueError("time and amplitude must be one-dimensional arrays with at least four points.")
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(a)):
        raise ValueError("Envelope data contain NaN or infinity.")
    if np.any(np.diff(t) <= 0.0):
        raise ValueError("Envelope time must be strictly increasing.")
    if np.any(a <= 0.0):
        raise ValueError("Envelope amplitudes must be positive.")
    return t, a


def _finish(model: str, coefficient: float, intercept: float, transformed: np.ndarray, fitted_transformed: np.ndarray, predicted_amplitude: np.ndarray) -> EnvelopeFit:
    residual_t = transformed - fitted_transformed
    ss_res = float(np.sum(residual_t**2))
    ss_tot = float(np.sum((transformed - np.mean(transformed)) ** 2))
    residual_a = predicted_amplitude - (
        np.exp(transformed) if model == "exponential" else 1.0 / transformed
    )
    n = transformed.size
    aic = float(n * np.log(max(ss_res / n, np.finfo(float).tiny)) + 2.0 * 2)
    return EnvelopeFit(
        model=model,
        coefficient=float(coefficient),
        intercept=float(intercept),
        rms_transformed=float(np.sqrt(np.mean(residual_t**2))),
        r_squared_transformed=1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0,
        rms_amplitude=float(np.sqrt(np.mean(residual_a**2))),
        aic=aic,
        point_count=int(n),
    )


def fit_exponential_envelope(time: np.ndarray, amplitude: np.ndarray) -> EnvelopeFit:
    t, a = _validate(time, amplitude)
    transformed = np.log(a)
    slope, intercept = np.polyfit(t, transformed, 1)
    fitted = slope * t + intercept
    predicted = np.exp(fitted)
    return _finish("exponential", -float(slope), float(intercept), transformed, fitted, predicted)


def fit_inverse_envelope(time: np.ndarray, amplitude: np.ndarray) -> EnvelopeFit:
    t, a = _validate(time, amplitude)
    transformed = 1.0 / a
    slope, intercept = np.polyfit(t, transformed, 1)
    fitted = slope * t + intercept
    if np.any(fitted <= 0.0):
        raise ValueError("Inverse-envelope fit predicts a non-positive reciprocal amplitude.")
    predicted = 1.0 / fitted
    return _finish("inverse", float(slope), float(intercept), transformed, fitted, predicted)


def compare_envelope_models(time: np.ndarray, amplitude: np.ndarray) -> dict[str, Any]:
    """Compare weak linear-drag and quadratic-drag envelope signatures.

    The comparison is diagnostic rather than a proof of mechanism.  Mixed drag,
    Coulomb friction, amplitude-dependent frequency and release transients can
    invalidate both scalar envelope laws.
    """

    fits = [fit_exponential_envelope(time, amplitude), fit_inverse_envelope(time, amplitude)]
    preferred = min(fits, key=lambda fit: fit.aic)
    delta = {fit.model: float(fit.aic - preferred.aic) for fit in fits}
    return {
        "preferred_by_transformed_aic": preferred.model,
        "delta_aic": delta,
        "fits": {fit.model: fit.as_dict() for fit in fits},
        "interpretation": (
            "A lower AIC only selects between these two envelope transforms. "
            "It does not identify aerodynamic versus joint/material dissipation without independent experiments."
        ),
    }
