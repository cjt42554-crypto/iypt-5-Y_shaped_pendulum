"""Point-bob aerodynamic force and velocity tangent."""

from __future__ import annotations

import numpy as np


def bob_drag(
    velocity: np.ndarray,
    air_velocity: np.ndarray,
    *,
    air_density: float,
    radius: float,
    cd: float,
    linear_coefficient: float,
    enabled: bool,
) -> tuple[np.ndarray, np.ndarray, float]:
    if not enabled:
        return np.zeros(3), np.zeros((3, 3)), 0.0
    rel = np.asarray(velocity, dtype=float) - np.asarray(air_velocity, dtype=float)
    speed = float(np.linalg.norm(rel))
    area = np.pi * radius**2
    q = 0.5 * air_density * cd * area
    force = -q * speed * rel - linear_coefficient * rel
    if speed > 1e-15:
        jac = -q * (speed * np.eye(3) + np.outer(rel, rel) / speed)
    else:
        jac = np.zeros((3, 3), dtype=float)
    jac -= linear_coefficient * np.eye(3)
    # Work on the mechanical system; relative dissipation is always non-negative.
    dissipation = float(q * speed**3 + linear_coefficient * speed**2)
    return force, jac, dissipation
