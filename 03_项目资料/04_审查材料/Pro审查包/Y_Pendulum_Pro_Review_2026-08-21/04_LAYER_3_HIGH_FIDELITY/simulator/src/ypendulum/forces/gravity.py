"""Gravity and buoyancy helpers."""

from __future__ import annotations

import numpy as np
from scipy import sparse


def gravity_load(mass_matrix: sparse.spmatrix, gravity: np.ndarray, node_count: int) -> np.ndarray:
    acceleration = np.tile(np.asarray(gravity, dtype=float), node_count)
    return np.asarray(mass_matrix @ acceleration, dtype=float)


def bob_buoyancy_force(
    air_density: float, bob_radius: float, gravity: np.ndarray, enabled: bool
) -> np.ndarray:
    if not enabled:
        return np.zeros(3, dtype=float)
    volume = 4.0 * np.pi * bob_radius**3 / 3.0
    return -air_density * volume * np.asarray(gravity, dtype=float)
