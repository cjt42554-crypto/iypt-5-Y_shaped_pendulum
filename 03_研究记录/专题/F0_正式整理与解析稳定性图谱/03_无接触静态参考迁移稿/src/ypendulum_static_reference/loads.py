"""Conservative static gravity and buoyancy loads."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _vector3(value: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape != (3,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be a finite three-vector.")
    return array


@dataclass(frozen=True)
class StaticPointLoadResponse:
    gravity_force: np.ndarray
    buoyancy_force: np.ndarray
    total_force: np.ndarray


def point_static_load(
    *,
    mass: float,
    displaced_volume: float,
    fluid_density: float,
    gravity: np.ndarray,
    buoyancy_enabled: bool,
) -> StaticPointLoadResponse:
    """Return the conservative point load used by the static potential."""

    scalars = np.asarray([mass, displaced_volume, fluid_density], dtype=float)
    if not np.all(np.isfinite(scalars)):
        raise ValueError("Mass, displaced volume and fluid density must be finite.")
    if mass <= 0.0 or displaced_volume < 0.0 or fluid_density < 0.0:
        raise ValueError("Mass must be positive; volume and fluid density non-negative.")
    gravity_vector = _vector3(gravity, "gravity")
    gravity_force = float(mass) * gravity_vector
    buoyancy_force = (
        -float(fluid_density) * float(displaced_volume) * gravity_vector
        if buoyancy_enabled
        else np.zeros(3, dtype=float)
    )
    return StaticPointLoadResponse(
        gravity_force=gravity_force,
        buoyancy_force=buoyancy_force,
        total_force=gravity_force + buoyancy_force,
    )
