"""Objective three-point discrete bending energy and analytic nodal force."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class BendingGeometryError(FloatingPointError):
    """Raised when a discrete bending configuration is geometrically singular."""


@dataclass(frozen=True)
class BendingResponse:
    energy: float
    forces: np.ndarray
    minimum_segment_length: float
    minimum_turn_clearance: float


def _validated_geometry(
    points: np.ndarray, segment_rest_length: np.ndarray, bending_stiffness: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    coordinates = np.asarray(points, dtype=float)
    rest = np.asarray(segment_rest_length, dtype=float)
    if coordinates.ndim != 2 or coordinates.shape[1] != 3:
        raise ValueError("points must have shape (n, 3).")
    if coordinates.shape[0] < 3:
        raise ValueError("A bending interaction requires at least three nodes.")
    if rest.shape != (coordinates.shape[0] - 1,):
        raise ValueError("segment_rest_length must contain one value per segment.")
    if not np.all(np.isfinite(coordinates)) or not np.all(np.isfinite(rest)):
        raise ValueError("Bending geometry and rest lengths must be finite.")
    if np.any(rest <= 0.0):
        raise ValueError("Bending rest lengths must be strictly positive.")
    if not np.isfinite(bending_stiffness) or bending_stiffness < 0.0:
        raise ValueError("Bending stiffness must be finite and non-negative.")
    segment = coordinates[1:] - coordinates[:-1]
    length = np.linalg.norm(segment, axis=1)
    geometry_scale = max(float(np.max(rest)), float(np.max(length)))
    if np.any(length <= 64.0 * np.finfo(float).eps * geometry_scale):
        raise BendingGeometryError("Collapsed segment in discrete bending interaction.")
    tangent = segment / length[:, None]
    turn_clearance = 1.0 + np.einsum("ij,ij->i", tangent[:-1], tangent[1:])
    if np.any(turn_clearance <= 256.0 * np.finfo(float).eps):
        raise BendingGeometryError(
            "Anti-parallel adjacent tangents make the bending geometry singular."
        )
    return coordinates, rest, length, tangent


def bending_energy_forces(
    points: np.ndarray,
    segment_rest_length: np.ndarray,
    bending_stiffness: float,
) -> BendingResponse:
    """Return energy and the exact analytic negative coordinate gradient.

    For adjacent unit tangents, the local energy is
    ``0.5 * EI / dual_length * ||t_right - t_left||**2``.  Exact
    anti-parallel turns and collapsed segments fail closed; no repair direction
    or special-case force is inserted.
    """

    coordinates, rest, length, tangent = _validated_geometry(
        points, segment_rest_length, bending_stiffness
    )
    forces = np.zeros_like(coordinates)
    energy = 0.0
    identity = np.eye(3)
    for center in range(1, coordinates.shape[0] - 1):
        left_tangent = tangent[center - 1]
        right_tangent = tangent[center]
        tangent_difference = right_tangent - left_tangent
        dual_length = 0.5 * (rest[center - 1] + rest[center])
        coefficient = bending_stiffness / dual_length
        energy += 0.5 * coefficient * float(np.dot(tangent_difference, tangent_difference))
        left_segment_gradient = (
            -coefficient
            * ((identity - np.outer(left_tangent, left_tangent)) @ tangent_difference)
            / length[center - 1]
        )
        right_segment_gradient = (
            coefficient
            * ((identity - np.outer(right_tangent, right_tangent)) @ tangent_difference)
            / length[center]
        )
        forces[center - 1] += left_segment_gradient
        forces[center] += -left_segment_gradient + right_segment_gradient
        forces[center + 1] -= right_segment_gradient
    turn_clearance = 1.0 + np.einsum("ij,ij->i", tangent[:-1], tangent[1:])
    return BendingResponse(
        energy=float(energy),
        forces=forces,
        minimum_segment_length=float(np.min(length)),
        minimum_turn_clearance=float(np.min(turn_clearance)),
    )


def bending_energy(
    points: np.ndarray, segment_rest_length: np.ndarray, bending_stiffness: float
) -> float:
    return bending_energy_forces(points, segment_rest_length, bending_stiffness).energy
