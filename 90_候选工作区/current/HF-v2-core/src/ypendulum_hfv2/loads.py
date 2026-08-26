"""Pure external-load interfaces for gravity, buoyancy and isotropic drag."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _vector3(value: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape != (3,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be a finite three-vector.")
    return array


@dataclass(frozen=True)
class IsotropicDragLaw:
    """Explicitly activated drag relative to a prescribed air velocity.

    The quadratic coefficient already includes density and reference area, so
    the force is ``-c1*u_rel - c2*|u_rel|*u_rel``.
    """

    enabled: bool
    linear_coefficient: float = 0.0
    quadratic_coefficient: float = 0.0

    def __post_init__(self) -> None:
        coefficients = np.asarray(
            [self.linear_coefficient, self.quadratic_coefficient], dtype=float
        )
        if not np.all(np.isfinite(coefficients)) or np.any(coefficients < 0.0):
            raise ValueError("Drag coefficients must be finite and non-negative.")

    def force(self, velocity: np.ndarray, air_velocity: np.ndarray) -> np.ndarray:
        body_velocity = _vector3(velocity, "velocity")
        fluid_velocity = _vector3(air_velocity, "air_velocity")
        if not self.enabled:
            return np.zeros(3, dtype=float)
        relative = body_velocity - fluid_velocity
        speed = float(np.linalg.norm(relative))
        return -(self.linear_coefficient * relative + self.quadratic_coefficient * speed * relative)


@dataclass(frozen=True)
class PointLoadResponse:
    gravity_force: np.ndarray
    buoyancy_force: np.ndarray
    air_force: np.ndarray
    total_force: np.ndarray
    relative_air_dissipation_rate: float
    air_work_rate: float

    @property
    def body_air_power(self) -> float:
        return -self.relative_air_dissipation_rate + self.air_work_rate


def point_external_load(
    *,
    mass: float,
    displaced_volume: float,
    fluid_density: float,
    gravity: np.ndarray,
    velocity: np.ndarray,
    air_velocity: np.ndarray,
    drag: IsotropicDragLaw,
    buoyancy_enabled: bool,
) -> PointLoadResponse:
    """Evaluate a point/body translational load without I/O or configuration access."""

    scalars = np.asarray([mass, displaced_volume, fluid_density], dtype=float)
    if not np.all(np.isfinite(scalars)):
        raise ValueError("Mass, displaced volume and fluid density must be finite.")
    if mass <= 0.0 or displaced_volume < 0.0 or fluid_density < 0.0:
        raise ValueError("Mass must be positive; volume and fluid density non-negative.")
    gravity_vector = _vector3(gravity, "gravity")
    body_velocity = _vector3(velocity, "velocity")
    fluid_velocity = _vector3(air_velocity, "air_velocity")
    gravity_force = mass * gravity_vector
    buoyancy_force = (
        -fluid_density * displaced_volume * gravity_vector
        if buoyancy_enabled
        else np.zeros(3, dtype=float)
    )
    air_force = drag.force(body_velocity, fluid_velocity)
    relative = body_velocity - fluid_velocity
    relative_speed = float(np.linalg.norm(relative))
    relative_dissipation = (
        drag.linear_coefficient * relative_speed**2 + drag.quadratic_coefficient * relative_speed**3
        if drag.enabled
        else 0.0
    )
    air_work = float(np.dot(air_force, fluid_velocity))
    total = gravity_force + buoyancy_force + air_force
    return PointLoadResponse(
        gravity_force=gravity_force,
        buoyancy_force=buoyancy_force,
        air_force=air_force,
        total_force=total,
        relative_air_dissipation_rate=relative_dissipation,
        air_work_rate=air_work,
    )
