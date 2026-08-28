"""Passive unilateral axial Kelvin--Voigt material."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _vector3(value: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape != (3,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be a finite three-vector.")
    return array


@dataclass(frozen=True)
class AxialMaterial:
    """One material segment described by ``EA``, ``eta*A`` and rest length."""

    rest_length: float
    axial_rigidity: float
    axial_viscosity: float

    def __post_init__(self) -> None:
        values = np.asarray(
            [self.rest_length, self.axial_rigidity, self.axial_viscosity], dtype=float
        )
        if not np.all(np.isfinite(values)):
            raise ValueError("Axial material parameters must be finite.")
        if self.rest_length <= 0.0 or self.axial_rigidity <= 0.0:
            raise ValueError("Rest length and axial rigidity must be strictly positive.")
        if self.axial_viscosity < 0.0:
            raise ValueError("Axial viscosity must be non-negative.")

    @property
    def stiffness(self) -> float:
        return self.axial_rigidity / self.rest_length

    @property
    def viscosity(self) -> float:
        return self.axial_viscosity / self.rest_length


@dataclass(frozen=True)
class AxialResponse:
    current_length: float
    unit_tangent: np.ndarray
    extension: float
    extension_rate: float
    active: bool
    trial_force: float
    tension: float
    stored_energy: float
    stored_energy_rate: float
    viscous_dissipation_rate: float
    unilateral_release_dissipation_rate: float
    internal_power: float
    power_balance_residual: float
    force_on_start: np.ndarray
    force_on_end: np.ndarray

    @property
    def total_dissipation_rate(self) -> float:
        return self.viscous_dissipation_rate + self.unilateral_release_dissipation_rate


def axial_segment_response(
    start_position: np.ndarray,
    end_position: np.ndarray,
    start_velocity: np.ndarray,
    end_velocity: np.ndarray,
    material: AxialMaterial,
) -> AxialResponse:
    """Evaluate the unilateral constitutive equation and its nodal forces.

    No bilateral signed force is assembled and later hidden.  ``trial_force``
    is diagnostic evidence; ``tension`` is the force that enters the equation.
    """

    start = _vector3(start_position, "start_position")
    end = _vector3(end_position, "end_position")
    start_rate = _vector3(start_velocity, "start_velocity")
    end_rate = _vector3(end_velocity, "end_velocity")
    segment = end - start
    current_length = float(np.linalg.norm(segment))
    geometry_scale = max(material.rest_length, current_length)
    if current_length <= 64.0 * np.finfo(float).eps * geometry_scale:
        raise FloatingPointError("Collapsed segment in unilateral axial material.")
    tangent = segment / current_length
    extension = current_length - material.rest_length
    extension_rate = float(np.dot(tangent, end_rate - start_rate))
    trial_force = material.stiffness * extension + material.viscosity * extension_rate

    active = extension > 0.0 and trial_force > 0.0
    tension = float(trial_force) if active else 0.0
    positive_extension = extension if extension > 0.0 else 0.0
    stored_energy = 0.5 * material.stiffness * positive_extension**2
    stored_energy_rate = material.stiffness * extension * extension_rate if extension > 0.0 else 0.0
    if active:
        viscous_dissipation = material.viscosity * extension_rate**2
        unilateral_release_dissipation = 0.0
    elif extension > 0.0:
        viscous_dissipation = 0.0
        unilateral_release_dissipation = -material.stiffness * extension * extension_rate
        if unilateral_release_dissipation < 0.0:
            raise FloatingPointError("Unilateral projection produced negative dissipation.")
    else:
        viscous_dissipation = 0.0
        unilateral_release_dissipation = 0.0

    force_on_start = tension * tangent
    force_on_end = -force_on_start
    internal_power = -tension * extension_rate
    power_balance_residual = (
        internal_power + stored_energy_rate + viscous_dissipation + unilateral_release_dissipation
    )
    return AxialResponse(
        current_length=current_length,
        unit_tangent=tangent,
        extension=extension,
        extension_rate=extension_rate,
        active=active,
        trial_force=float(trial_force),
        tension=tension,
        stored_energy=float(stored_energy),
        stored_energy_rate=float(stored_energy_rate),
        viscous_dissipation_rate=float(viscous_dissipation),
        unilateral_release_dissipation_rate=float(unilateral_release_dissipation),
        internal_power=float(internal_power),
        power_balance_residual=float(power_balance_residual),
        force_on_start=force_on_start,
        force_on_end=force_on_end,
    )
