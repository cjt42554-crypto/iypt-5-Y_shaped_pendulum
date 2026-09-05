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
    minimum_segment_length: float | None
    minimum_turn_clearance: float | None


def _validated_inputs(
    points: np.ndarray, segment_rest_length: np.ndarray, bending_stiffness: float
) -> tuple[np.ndarray, np.ndarray, float]:
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
    return coordinates, rest, float(bending_stiffness)


def _validated_geometry(
    coordinates: np.ndarray, rest: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    segment = coordinates[1:] - coordinates[:-1]
    length = np.linalg.norm(segment, axis=1)
    if not np.all(np.isfinite(length)):
        raise BendingGeometryError("Non-finite segment length in discrete bending interaction.")
    if np.any(length == 0.0):
        raise BendingGeometryError("Collapsed segment in discrete bending interaction.")
    tangent = segment / length[:, None]
    turn_clearance = 1.0 + np.einsum("ij,ij->i", tangent[:-1], tangent[1:])
    if np.any(turn_clearance <= 0.0):
        raise BendingGeometryError(
            "Anti-parallel adjacent tangents make the curvature denominator singular."
        )
    return length, tangent, turn_clearance


def bending_energy_forces(
    points: np.ndarray,
    segment_rest_length: np.ndarray,
    bending_stiffness: float,
) -> BendingResponse:
    """Return energy and the exact analytic negative coordinate gradient.

    For adjacent unit tangents, the local curvature binormal is
    ``2 * cross(t_left, t_right) / (1 + dot(t_left, t_right))`` and the
    energy is its squared norm times ``EI / (2 * dual_length)``.  The returned
    force is the closed-form negative coordinate gradient of that equation.

    Positive stiffness therefore makes an exact anti-parallel turn an equation
    singularity.  Zero stiffness is the mathematical zero-energy branch and
    returns before any segment tangent or curvature denominator is evaluated.
    """

    coordinates, rest, stiffness = _validated_inputs(
        points, segment_rest_length, bending_stiffness
    )
    forces = np.zeros_like(coordinates)
    if stiffness == 0.0:
        return BendingResponse(
            energy=0.0,
            forces=forces,
            minimum_segment_length=None,
            minimum_turn_clearance=None,
        )

    length, tangent, turn_clearance = _validated_geometry(coordinates, rest)
    energy = 0.0
    for center in range(1, coordinates.shape[0] - 1):
        left_tangent = tangent[center - 1]
        right_tangent = tangent[center]
        tangent_dot = float(np.dot(left_tangent, right_tangent))
        denominator = float(turn_clearance[center - 1])
        curvature_binormal = 2.0 * np.cross(left_tangent, right_tangent) / denominator
        dual_length = 0.5 * (rest[center - 1] + rest[center])
        energy += (
            0.5
            * stiffness
            / dual_length
            * float(np.dot(curvature_binormal, curvature_binormal))
        )
        energy_derivative_dot = -4.0 * stiffness / (dual_length * denominator**2)
        left_segment_gradient = energy_derivative_dot * (
            right_tangent - tangent_dot * left_tangent
        ) / length[center - 1]
        right_segment_gradient = energy_derivative_dot * (
            left_tangent - tangent_dot * right_tangent
        ) / length[center]
        forces[center - 1] += left_segment_gradient
        forces[center] += -left_segment_gradient + right_segment_gradient
        forces[center + 1] -= right_segment_gradient
    if not np.isfinite(energy) or not np.all(np.isfinite(forces)):
        raise FloatingPointError(
            "Discrete-curvature bending energy or analytic force is non-finite."
        )
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
