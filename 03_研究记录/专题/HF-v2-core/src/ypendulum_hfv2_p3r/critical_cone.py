"""True one-sided critical-cone second-order audit for P3R contact."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np

from ypendulum_hfv2.audit.statics import force_scale
from ypendulum_hfv2.rigid.rotation import hat
from ypendulum_hfv2.statics.contact_assembly import ContactCoordinates

from .assembly import P3RContactAssembly
from .kkt import P3RKKTAudit, matrix_rank


@dataclass(frozen=True)
class CriticalConeAudit:
    passed: bool
    normalized_unsymmetrized_lagrangian_hessian: np.ndarray
    normalized_symmetric_lagrangian_hessian: np.ndarray
    unsymmetrized_relative_asymmetry: float
    gauge_dimension: int
    critical_equality_rank: int
    near_active_count: int
    near_active_rank: int
    supported_tangent_dimension: int
    supported_tangent_eigenvalues: np.ndarray
    minimum_supported_tangent_curvature: float
    critical_direction_count: int
    critical_directions: np.ndarray
    critical_direction_minimum_linearized_gap: np.ndarray
    matrix_directional_curvatures: np.ndarray
    independent_directional_curvatures: np.ndarray
    maximum_curvature_crosscheck_error: float
    minimum_critical_cone_curvature: float


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


def _gauge_rows(
    assembly: P3RContactAssembly,
    coordinates: ContactCoordinates,
) -> np.ndarray:
    size = coordinates.values.size
    rotation_slice = assembly.base_assembly.layout.bob_rotation_slice.slice
    arm = assembly.base_assembly.bob.attachment_arm_body
    arm_norm = float(np.linalg.norm(arm))
    body_directions = np.eye(3) if arm_norm == 0.0 else (arm / arm_norm)[None, :]
    right_jacobian = _right_jacobian_so3(coordinates.values[rotation_slice])
    rows = []
    for body_direction in body_directions:
        row = np.zeros(size)
        row[rotation_slice] = np.linalg.solve(right_jacobian, body_direction)
        row /= np.linalg.norm(row)
        rows.append(row)
    return np.vstack(rows)


def _nullspace(rows: np.ndarray, relative_tolerance: float) -> np.ndarray:
    matrix = np.asarray(rows, dtype=float)
    if matrix.shape[0] == 0:
        return np.eye(matrix.shape[1])
    _, singular, right = np.linalg.svd(matrix, full_matrices=True)
    rank = 0
    if singular.size and singular[0] > 0.0:
        rank = int(np.count_nonzero(singular > relative_tolerance * singular[0]))
    return right[rank:].T


def _append_unique_direction(
    directions: list[np.ndarray],
    candidate: np.ndarray,
    duplicate_tolerance: float,
) -> None:
    direction = np.asarray(candidate, dtype=float)
    norm = float(np.linalg.norm(direction))
    if norm <= duplicate_tolerance:
        return
    direction = direction / norm
    if any(float(np.linalg.norm(existing - direction)) <= duplicate_tolerance for existing in directions):
        return
    directions.append(direction)


def _critical_face_directions(
    hessian: np.ndarray,
    equality_rows: np.ndarray,
    inequality_rows: np.ndarray,
    *,
    rank_relative_tolerance: float,
    cone_feasibility_tolerance: float,
    duplicate_direction_tolerance: float,
    maximum_enumerated_inequalities: int,
) -> np.ndarray:
    count = inequality_rows.shape[0]
    if count > maximum_enumerated_inequalities:
        raise ValueError("Critical-cone face count exceeds the frozen enumeration limit.")
    directions: list[np.ndarray] = []
    indices = tuple(range(count))
    for face_size in range(count + 1):
        for face in combinations(indices, face_size):
            rows = equality_rows
            if face:
                rows = np.vstack([rows, inequality_rows[np.array(face, dtype=int)]])
            basis = _nullspace(rows, rank_relative_tolerance)
            if basis.shape[1] == 0:
                continue
            projected = basis.T @ hessian @ basis
            _, eigenvectors = np.linalg.eigh(projected)
            for column in range(eigenvectors.shape[1]):
                raw = basis @ eigenvectors[:, column]
                for sign in (-1.0, 1.0):
                    direction = sign * raw
                    if inequality_rows.size:
                        linearized = inequality_rows @ direction
                        if float(np.min(linearized)) < -cone_feasibility_tolerance:
                            continue
                    if equality_rows.size:
                        if float(np.linalg.norm(equality_rows @ direction, ord=np.inf)) > (
                            10.0 * cone_feasibility_tolerance
                        ):
                            continue
                    _append_unique_direction(
                        directions,
                        direction,
                        duplicate_direction_tolerance,
                    )
    size = hessian.shape[0]
    return np.vstack(directions) if directions else np.empty((0, size))


def audit_critical_cone(
    assembly: P3RContactAssembly,
    coordinates: ContactCoordinates,
    kkt: P3RKKTAudit,
    *,
    hessian_difference_step: float,
    directional_difference_step: float,
    rank_relative_tolerance: float,
    cone_feasibility_tolerance: float,
    duplicate_direction_tolerance: float,
    maximum_enumerated_inequalities: int,
    asymmetry_max: float,
    minimum_normalized_curvature: float,
    curvature_crosscheck_absolute_max: float,
) -> CriticalConeAudit:
    """Audit the cone ``J_A d >= 0`` and ``grad(Pi) dot d = 0`` directly."""

    if hessian_difference_step <= 0.0 or directional_difference_step <= 0.0:
        raise ValueError("Critical-cone difference steps must be strictly positive.")
    evaluation = assembly.evaluate(coordinates)
    contact = evaluation.contact
    multipliers = np.asarray(kkt.canonical_multipliers_N, dtype=float)
    if multipliers.shape != contact.gaps_m.shape:
        raise ValueError("Critical-cone multiplier vector has the wrong shape.")
    scale = force_scale(assembly.base_assembly)
    size = coordinates.values.size

    def lagrangian_gradient(values: np.ndarray) -> np.ndarray:
        current = assembly.evaluate(assembly.coordinates_from_values(values))
        return (
            -current.generalized_force
            - current.contact.gap_jacobian.T @ multipliers
        )

    hessian = np.empty((size, size))
    for column in range(size):
        plus = np.array(coordinates.values, copy=True)
        minus = np.array(coordinates.values, copy=True)
        plus[column] += hessian_difference_step
        minus[column] -= hessian_difference_step
        hessian[:, column] = (
            lagrangian_gradient(plus) - lagrangian_gradient(minus)
        ) / (2.0 * hessian_difference_step)
    normalized = hessian / scale
    symmetric = 0.5 * (normalized + normalized.T)
    asymmetry = float(
        np.linalg.norm(normalized - normalized.T)
        / max(float(np.linalg.norm(normalized)), np.finfo(float).tiny)
    )

    gauges = _gauge_rows(assembly, coordinates)
    gradient = -contact.generalized_force
    gradient_norm = float(np.linalg.norm(gradient))
    equality_rows = np.array(gauges, copy=True)
    if gradient_norm > np.finfo(float).tiny:
        equality_rows = np.vstack([equality_rows, gradient / gradient_norm])
    near_rows = contact.gap_jacobian[kkt.near_active_indices]
    directions = _critical_face_directions(
        symmetric,
        equality_rows,
        near_rows,
        rank_relative_tolerance=rank_relative_tolerance,
        cone_feasibility_tolerance=cone_feasibility_tolerance,
        duplicate_direction_tolerance=duplicate_direction_tolerance,
        maximum_enumerated_inequalities=maximum_enumerated_inequalities,
    )
    if directions.shape[0] == 0:
        raise ValueError("The frozen critical-cone audit found no nonzero feasible direction.")
    matrix_curvatures = np.einsum("ij,jk,ik->i", directions, symmetric, directions)

    def lagrangian_value(values: np.ndarray) -> float:
        current = assembly.evaluate(assembly.coordinates_from_values(values))
        return float(current.total_potential - multipliers @ current.contact.gaps_m)

    base_value = lagrangian_value(coordinates.values)
    independent = np.empty(directions.shape[0])
    for index, direction in enumerate(directions):
        plus = coordinates.values + directional_difference_step * direction
        minus = coordinates.values - directional_difference_step * direction
        independent[index] = (
            lagrangian_value(plus) - 2.0 * base_value + lagrangian_value(minus)
        ) / (directional_difference_step**2 * scale)
    crosscheck = float(np.max(np.abs(independent - matrix_curvatures)))
    linearized_minimum = (
        np.min(directions @ near_rows.T, axis=1)
        if near_rows.size
        else np.full(directions.shape[0], float("inf"))
    )

    supported_rows = contact.gap_jacobian[kkt.supported_indices]
    supported_exclusions = np.vstack([gauges, supported_rows])
    supported_tangent = _nullspace(supported_exclusions, rank_relative_tolerance)
    supported_projected = supported_tangent.T @ symmetric @ supported_tangent
    supported_eigenvalues = (
        np.linalg.eigvalsh(supported_projected)
        if supported_projected.size
        else np.empty(0)
    )
    minimum_supported = (
        float(np.min(supported_eigenvalues))
        if supported_eigenvalues.size
        else float("inf")
    )
    minimum = float(np.min(matrix_curvatures))
    passed = bool(
        asymmetry <= asymmetry_max
        and minimum_supported >= minimum_normalized_curvature
        and minimum >= minimum_normalized_curvature
        and crosscheck <= curvature_crosscheck_absolute_max
        and float(np.min(linearized_minimum)) >= -cone_feasibility_tolerance
    )
    return CriticalConeAudit(
        passed=passed,
        normalized_unsymmetrized_lagrangian_hessian=np.array(normalized, copy=True),
        normalized_symmetric_lagrangian_hessian=np.array(symmetric, copy=True),
        unsymmetrized_relative_asymmetry=asymmetry,
        gauge_dimension=gauges.shape[0],
        critical_equality_rank=matrix_rank(equality_rows, rank_relative_tolerance),
        near_active_count=near_rows.shape[0],
        near_active_rank=matrix_rank(near_rows, rank_relative_tolerance),
        supported_tangent_dimension=supported_tangent.shape[1],
        supported_tangent_eigenvalues=np.array(supported_eigenvalues, copy=True),
        minimum_supported_tangent_curvature=minimum_supported,
        critical_direction_count=directions.shape[0],
        critical_directions=np.array(directions, copy=True),
        critical_direction_minimum_linearized_gap=np.array(linearized_minimum, copy=True),
        matrix_directional_curvatures=np.array(matrix_curvatures, copy=True),
        independent_directional_curvatures=np.array(independent, copy=True),
        maximum_curvature_crosscheck_error=crosscheck,
        minimum_critical_cone_curvature=minimum,
    )
