"""Conservative unilateral elastic segment law for static equilibrium."""

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
    """One unilateral elastic segment described by rest length and $EA$."""

    rest_length: float
    axial_rigidity: float

    def __post_init__(self) -> None:
        values = np.asarray([self.rest_length, self.axial_rigidity], dtype=float)
        if not np.all(np.isfinite(values)):
            raise ValueError("Axial material parameters must be finite.")
        if self.rest_length <= 0.0 or self.axial_rigidity <= 0.0:
            raise ValueError("Rest length and axial rigidity must be strictly positive.")

    @property
    def stiffness(self) -> float:
        return self.axial_rigidity / self.rest_length


@dataclass(frozen=True)
class AxialResponse:
    current_length: float
    unit_tangent: np.ndarray
    extension: float
    active: bool
    tension: float
    stored_energy: float
    force_on_start: np.ndarray
    force_on_end: np.ndarray


def axial_segment_response(
    start_position: np.ndarray,
    end_position: np.ndarray,
    material: AxialMaterial,
) -> AxialResponse:
    """Evaluate the unilateral elastic potential and its nodal forces."""

    start = _vector3(start_position, "start_position")
    end = _vector3(end_position, "end_position")
    segment = end - start
    current_length = float(np.linalg.norm(segment))
    geometry_scale = max(material.rest_length, current_length)
    if current_length <= 64.0 * np.finfo(float).eps * geometry_scale:
        raise FloatingPointError("Collapsed segment in unilateral axial material.")
    tangent = segment / current_length
    extension = current_length - material.rest_length
    active = extension > 0.0
    positive_extension = extension if active else 0.0
    tension = material.stiffness * positive_extension
    stored_energy = 0.5 * material.stiffness * positive_extension**2
    force_on_start = tension * tangent
    force_on_end = -force_on_start
    return AxialResponse(
        current_length=current_length,
        unit_tangent=tangent,
        extension=extension,
        active=active,
        tension=float(tension),
        stored_energy=float(stored_energy),
        force_on_start=force_on_start,
        force_on_end=force_on_end,
    )
