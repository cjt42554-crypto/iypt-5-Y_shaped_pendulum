"""P3R2 coordinate units, characteristic scales, gauge and NNLS support."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import nnls

from ypendulum_hfv2.audit.statics import force_scale
from ypendulum_hfv2.rigid.rotation import hat
from ypendulum_hfv2_p3r.kkt import matrix_rank

from .assembly import P3R2ContactAssembly

COORDINATE_IDS = (
    "bob_position_x",
    "bob_position_y",
    "bob_position_z",
    "bob_rotation_x",
    "bob_rotation_y",
    "bob_rotation_z",
)
COORDINATE_UNITS = ("m", "m", "m", "rad", "rad", "rad")
STATIONARITY_UNITS = ("N", "N", "N", "N*m", "N*m", "N*m")


def _readonly_vector(value: np.ndarray, name: str) -> np.ndarray:
    array = np.array(value, dtype=float, copy=True)
    if array.ndim != 1 or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be one finite vector.")
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class CharacteristicScales:
    length_m: float
    force_N: float
    energy_N_m: float
    coordinate_scales: np.ndarray
    stationarity_scales: np.ndarray

    def __post_init__(self) -> None:
        length = float(self.length_m)
        force = float(self.force_N)
        energy = float(self.energy_N_m)
        if not np.all(np.isfinite([length, force, energy])) or min(
            length, force, energy
        ) <= 0.0:
            raise ValueError("P3R2 characteristic scales must be finite and positive.")
        coordinates = _readonly_vector(self.coordinate_scales, "coordinate_scales")
        stationarity = _readonly_vector(
            self.stationarity_scales,
            "stationarity_scales",
        )
        if coordinates.shape != (6,) or stationarity.shape != (6,):
            raise ValueError("P3R2 certification currently requires six coordinates.")
        if np.any(coordinates <= 0.0) or np.any(stationarity <= 0.0):
            raise ValueError("P3R2 component scales must be strictly positive.")
        object.__setattr__(self, "length_m", length)
        object.__setattr__(self, "force_N", force)
        object.__setattr__(self, "energy_N_m", energy)
        object.__setattr__(self, "coordinate_scales", coordinates)
        object.__setattr__(self, "stationarity_scales", stationarity)


def characteristic_scales(assembly: P3R2ContactAssembly) -> CharacteristicScales:
    rest = np.asarray(assembly.base_assembly.layout.segment_rest_lengths, dtype=float)
    if rest.size == 0:
        raise ValueError("P3R2 requires at least one bound reference segment.")
    length = float(np.max(rest))
    force = float(force_scale(assembly.base_assembly))
    energy = force * length
    return CharacteristicScales(
        length_m=length,
        force_N=force,
        energy_N_m=energy,
        coordinate_scales=np.array([length, length, length, 1.0, 1.0, 1.0]),
        stationarity_scales=np.array([force, force, force, energy, energy, energy]),
    )


def _right_jacobian_so3(rotation_vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(rotation_vector, dtype=float)
    squared = float(vector @ vector)
    angle = float(np.sqrt(squared))
    generator = hat(vector)
    if angle < 1.0e-6:
        fourth = squared**2
        first = 0.5 - squared / 24.0 + fourth / 720.0
        second = 1.0 / 6.0 - squared / 120.0 + fourth / 5040.0
    else:
        first = float((1.0 - np.cos(angle)) / squared)
        second = float((angle - np.sin(angle)) / (squared * angle))
    return np.eye(3) - first * generator + second * (generator @ generator)


def gauge_direction_and_projection(
    assembly: P3R2ContactAssembly,
    values: np.ndarray,
    scales: CharacteristicScales,
) -> tuple[np.ndarray, np.ndarray]:
    vector = np.asarray(values, dtype=float)
    if vector.shape != (6,):
        raise ValueError("P3R2 gauge projection requires six coordinates.")
    rotation_slice = assembly.base_assembly.layout.bob_rotation_slice.slice
    arm = np.asarray(assembly.base_assembly.bob.attachment_arm_body, dtype=float)
    arm_norm = float(np.linalg.norm(arm))
    if arm_norm <= 0.0:
        raise ValueError("P3R2 freezes a nonzero attachment-arm rotation gauge.")
    body_direction = arm / arm_norm
    right = _right_jacobian_so3(vector[rotation_slice])
    raw_direction = np.zeros(6)
    raw_direction[rotation_slice] = np.linalg.solve(right, body_direction)
    dimensionless = raw_direction / scales.coordinate_scales
    dimensionless /= np.linalg.norm(dimensionless)
    _, _, right_vectors = np.linalg.svd(dimensionless[None, :], full_matrices=True)
    projection = right_vectors[1:].T
    return np.array(dimensionless, copy=True), np.array(projection, copy=True)


def gauge_coordinate(
    assembly: P3R2ContactAssembly,
    values: np.ndarray,
) -> float:
    rotation_slice = assembly.base_assembly.layout.bob_rotation_slice.slice
    arm = np.asarray(assembly.base_assembly.bob.attachment_arm_body, dtype=float)
    arm_unit = arm / np.linalg.norm(arm)
    return float(arm_unit @ np.asarray(values, dtype=float)[rotation_slice])


def gauge_coordinate_row(assembly: P3R2ContactAssembly) -> np.ndarray:
    row = np.zeros(6)
    rotation_slice = assembly.base_assembly.layout.bob_rotation_slice.slice
    arm = np.asarray(assembly.base_assembly.bob.attachment_arm_body, dtype=float)
    row[rotation_slice] = arm / np.linalg.norm(arm)
    return row


def scaled_canonical_multipliers(
    evaluation: object,
    near_active_indices: np.ndarray,
    scales: CharacteristicScales,
) -> np.ndarray:
    gaps = np.asarray(evaluation.contact.gaps_m, dtype=float)
    jacobian = np.asarray(evaluation.contact.gap_jacobian, dtype=float)
    gradient = -np.asarray(evaluation.generalized_force, dtype=float)
    indices = np.asarray(near_active_indices, dtype=int)
    multipliers = np.zeros(gaps.size)
    if indices.size:
        weighted_jacobian = jacobian[indices].T / scales.stationarity_scales[:, None]
        weighted_gradient = gradient / scales.stationarity_scales
        active, _ = nnls(weighted_jacobian, weighted_gradient)
        multipliers[indices] = active
    return multipliers


@dataclass(frozen=True)
class RestorationActivity:
    near_active_indices: np.ndarray
    restore_indices: np.ndarray
    weak_active_indices: np.ndarray
    canonical_multipliers_N: np.ndarray
    near_active_rank: int
    restore_rank: int


def select_restoration_activity(
    evaluation: object,
    scales: CharacteristicScales,
    *,
    near_active_gap_max_m: float,
    supported_multiplier_min_N: float,
    rank_relative_tolerance: float,
) -> RestorationActivity:
    gaps = np.asarray(evaluation.contact.gaps_m, dtype=float)
    jacobian = np.asarray(evaluation.contact.gap_jacobian, dtype=float)
    near = np.flatnonzero(gaps <= near_active_gap_max_m)
    multipliers = scaled_canonical_multipliers(evaluation, near, scales)
    restore = near[multipliers[near] > supported_multiplier_min_N]
    weak = np.setdiff1d(near, restore, assume_unique=True)
    return RestorationActivity(
        near_active_indices=np.array(near, copy=True),
        restore_indices=np.array(restore, copy=True),
        weak_active_indices=np.array(weak, copy=True),
        canonical_multipliers_N=np.array(multipliers, copy=True),
        near_active_rank=matrix_rank(jacobian[near], rank_relative_tolerance),
        restore_rank=matrix_rank(jacobian[restore], rank_relative_tolerance),
    )


def stationarity_vector(
    evaluation: object,
    multipliers_N: np.ndarray,
) -> np.ndarray:
    gradient = -np.asarray(evaluation.generalized_force, dtype=float)
    jacobian = np.asarray(evaluation.contact.gap_jacobian, dtype=float)
    multipliers = np.asarray(multipliers_N, dtype=float)
    if multipliers.shape != evaluation.contact.gaps_m.shape:
        raise ValueError("P3R2 multiplier vector must match physical contact identities.")
    return gradient - jacobian.T @ multipliers
