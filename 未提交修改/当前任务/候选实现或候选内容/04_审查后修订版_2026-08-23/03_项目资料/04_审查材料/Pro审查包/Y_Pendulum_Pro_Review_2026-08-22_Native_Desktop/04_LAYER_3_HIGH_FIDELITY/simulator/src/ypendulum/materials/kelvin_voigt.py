"""Unilateral Kelvin--Voigt axial material."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from .base import AxialResponse

Array = npt.NDArray[np.float64]


def evaluate_kelvin_voigt(
    delta: Array,
    delta_dot: Array,
    rest_length: Array,
    ea: Array,
    eta_a: Array,
) -> AxialResponse:
    """Evaluate the exact piecewise tension-only law required by the frozen spec.

    If a stretched element unloads so rapidly that the Kelvin--Voigt trial force
    is negative, the force is clipped to zero.  The corresponding loss of stored
    energy is explicitly counted as ``release`` dissipation so the work-energy
    ledger remains closed.
    """

    delta = np.asarray(delta, dtype=float)
    delta_dot = np.asarray(delta_dot, dtype=float)
    rest_length = np.asarray(rest_length, dtype=float)
    k = np.asarray(ea, dtype=float) / rest_length
    c = np.asarray(eta_a, dtype=float) / rest_length
    trial = k * delta + c * delta_dot
    stretched = delta > 0.0
    active = stretched & (trial > 0.0)
    tension = np.where(active, trial, 0.0)
    elastic_energy = 0.5 * k * np.maximum(delta, 0.0) ** 2
    viscous = np.where(active, c * delta_dot**2, 0.0)
    release = np.where(stretched & ~active, np.maximum(-k * delta * delta_dot, 0.0), 0.0)
    dissipation = viscous + release
    d_tension_d_delta = np.where(active, k, 0.0)
    d_tension_d_delta_dot = np.where(active, c, 0.0)
    return AxialResponse(
        tension=tension,
        active=active,
        elastic_energy=elastic_energy,
        dissipation_rate=dissipation,
        d_tension_d_delta=d_tension_d_delta,
        d_tension_d_delta_dot=d_tension_d_delta_dot,
    )
