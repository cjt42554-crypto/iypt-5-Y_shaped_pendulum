"""Frozen tension-only activation and its energy primitive.

The functions in this module reproduce equations (F.11)--(F.12) exactly.
No tangent-length epsilon or softplus substitute is used.
"""

from __future__ import annotations

import numpy as np


def positive_part(x):
    """Return ``max(x, 0)`` elementwise without smoothing."""

    return np.maximum(np.asarray(x, dtype=float), 0.0)


def activation(x, delta: float):
    """Evaluate :math:`P_delta(x)` from equation (F.11)."""

    x_arr = np.asarray(x, dtype=float)
    out = np.zeros_like(x_arr)
    middle = (x_arr > 0.0) & (x_arr < delta)
    upper = x_arr >= delta
    xm = x_arr[middle]
    out[middle] = xm * xm * (2.0 * delta - xm) / (delta * delta)
    out[upper] = x_arr[upper]
    return float(out) if out.ndim == 0 else out


def activation_prime(x, delta: float):
    """Evaluate :math:`P'_delta(x)` from equation (F.11)."""

    x_arr = np.asarray(x, dtype=float)
    out = np.zeros_like(x_arr)
    middle = (x_arr > 0.0) & (x_arr < delta)
    upper = x_arr >= delta
    xm = x_arr[middle]
    out[middle] = 4.0 * xm / delta - 3.0 * xm * xm / (delta * delta)
    out[upper] = 1.0
    return float(out) if out.ndim == 0 else out


def activation_primitive(x, delta: float):
    """Evaluate ``integral_0^x P_delta(u) du`` exactly.

    This is the axial stored-energy density used by equation (F.25).
    """

    x_arr = np.asarray(x, dtype=float)
    out = np.zeros_like(x_arr)
    middle = (x_arr > 0.0) & (x_arr < delta)
    upper = x_arr >= delta
    xm = x_arr[middle]
    out[middle] = 2.0 * xm**3 / (3.0 * delta) - xm**4 / (
        4.0 * delta * delta
    )
    out[upper] = 0.5 * x_arr[upper] ** 2 - delta * delta / 12.0
    return float(out) if out.ndim == 0 else out


def tension_components(
    stretch_ratio,
    stretch_rate,
    *,
    EA: float,
    Ca: float,
    delta: float,
):
    """Return ``(N_e, N_v, N)`` from equation (F.12)."""

    strain = np.asarray(stretch_ratio, dtype=float) - 1.0
    rate = np.asarray(stretch_rate, dtype=float)
    elastic = EA * activation(strain, delta)
    viscous = Ca * activation_prime(strain, delta) * rate
    total = positive_part(elastic + viscous)
    return elastic, viscous, total

