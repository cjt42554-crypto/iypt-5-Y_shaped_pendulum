"""Optional rotating-frame inertial forces (not enabled by default)."""

from __future__ import annotations

import numpy as np


def rotating_frame_acceleration(
    position: np.ndarray,
    velocity: np.ndarray,
    omega: np.ndarray,
    omega_dot: np.ndarray | None = None,
    origin_acceleration: np.ndarray | None = None,
) -> np.ndarray:
    omega_dot = np.zeros(3) if omega_dot is None else np.asarray(omega_dot, dtype=float)
    origin_acceleration = (
        np.zeros(3) if origin_acceleration is None else np.asarray(origin_acceleration, dtype=float)
    )
    r = np.asarray(position, dtype=float)
    v = np.asarray(velocity, dtype=float)
    w = np.asarray(omega, dtype=float)
    return (
        -origin_acceleration
        - 2.0 * np.cross(w, v)
        - np.cross(w, np.cross(w, r))
        - np.cross(omega_dot, r)
    )
