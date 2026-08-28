"""Rigid-motion objectivity and internal resultant audits."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ypendulum_static_reference.rigid.rotation import validate_rotation


def _points(value: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim != 2 or array.shape[1] != 3 or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must have shape (n, 3) and be finite.")
    return array


@dataclass(frozen=True)
class InternalBalance:
    force_resultant: np.ndarray
    moment_resultant: np.ndarray
    scaled_force_resultant: float
    scaled_moment_resultant: float


def internal_balance(
    points: np.ndarray,
    forces: np.ndarray,
    origin: np.ndarray,
    *,
    force_scale: float,
    length_scale: float,
) -> InternalBalance:
    positions = _points(points, "points")
    nodal_force = _points(forces, "forces")
    reference = np.asarray(origin, dtype=float)
    if nodal_force.shape != positions.shape:
        raise ValueError("forces must match points.")
    if reference.shape != (3,) or not np.all(np.isfinite(reference)):
        raise ValueError("origin must be a finite three-vector.")
    if force_scale <= 0.0 or length_scale <= 0.0:
        raise ValueError("force_scale and length_scale must be positive.")
    resultant = np.sum(nodal_force, axis=0)
    moment = np.sum(np.cross(positions - reference, nodal_force), axis=0)
    return InternalBalance(
        force_resultant=resultant,
        moment_resultant=moment,
        scaled_force_resultant=float(np.linalg.norm(resultant) / force_scale),
        scaled_moment_resultant=float(np.linalg.norm(moment) / (force_scale * length_scale)),
    )


@dataclass(frozen=True)
class ObjectivityAudit:
    relative_energy_change: float
    relative_force_covariance_error: float


def objectivity_audit(
    energy_and_force: Callable[[np.ndarray], tuple[float, np.ndarray]],
    points: np.ndarray,
    rotation: np.ndarray,
    translation: np.ndarray,
    *,
    energy_scale: float,
    force_scale: float,
) -> ObjectivityAudit:
    positions = _points(points, "points")
    matrix = validate_rotation(rotation)
    offset = np.asarray(translation, dtype=float)
    if offset.shape != (3,) or not np.all(np.isfinite(offset)):
        raise ValueError("translation must be a finite three-vector.")
    if energy_scale <= 0.0 or force_scale <= 0.0:
        raise ValueError("energy_scale and force_scale must be positive.")
    energy, force = energy_and_force(positions)
    transformed = positions @ matrix.T + offset
    transformed_energy, transformed_force = energy_and_force(transformed)
    expected_force = np.asarray(force, dtype=float) @ matrix.T
    return ObjectivityAudit(
        relative_energy_change=abs(float(transformed_energy) - float(energy)) / energy_scale,
        relative_force_covariance_error=float(
            np.linalg.norm(np.asarray(transformed_force) - expected_force) / force_scale
        ),
    )
