"""Independent gap, KKT, action-reaction and second-order contact audits."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import nnls

from ypendulum_hfv2.audit.statics import force_scale
from ypendulum_hfv2.rigid.rotation import hat
from ypendulum_hfv2.statics.contact_assembly import (
    ContactCoordinates,
    ContactStaticAssembly,
    ContactStaticEvaluation,
)


@dataclass(frozen=True)
class ContactKKTThresholds:
    active_gap_max_m: float
    primal_penetration_max_m: float
    dual_negative_max_N: float
    stationarity_absolute_max_N: float
    stationarity_force_scale_factor_max: float
    complementarity_absolute_max_N_m: float
    complementarity_energy_scale_factor_max: float
    supported_multiplier_min_N: float
    active_constraint_rank_relative_tolerance: float

    def __post_init__(self) -> None:
        values = np.asarray(list(self.__dict__.values()), dtype=float)
        if not np.all(np.isfinite(values)) or np.any(values < 0.0):
            raise ValueError("Contact KKT thresholds must be finite and non-negative.")
        if self.active_gap_max_m <= 0.0 or self.active_constraint_rank_relative_tolerance <= 0.0:
            raise ValueError("Active-gap and rank thresholds must be strictly positive.")


@dataclass(frozen=True)
class ContactKKTAudit:
    passed: bool
    finite: bool
    force_scale_N: float
    energy_scale_N_m: float
    active_indices: np.ndarray
    supported_indices: np.ndarray
    active_constraint_rank: int
    supported_constraint_rank: int
    multipliers_N: np.ndarray
    stationarity_vector_N: np.ndarray
    primal_violation_m: float
    dual_violation_N: float
    stationarity_residual_N: float
    stationarity_limit_N: float
    complementarity_residual_N_m: float
    complementarity_limit_N_m: float


@dataclass(frozen=True)
class GapJacobianSample:
    relative_step: float
    maximum_row_relative_error: float
    matrix_relative_error: float


@dataclass(frozen=True)
class ContactActionReactionAudit:
    maximum_individual_force_residual_N: float
    maximum_individual_moment_residual_N_m: float
    global_force_residual_N: np.ndarray
    global_moment_residual_N_m: np.ndarray


@dataclass(frozen=True)
class ContactHessianAudit:
    normalized_unsymmetrized_lagrangian_hessian: np.ndarray
    normalized_symmetric_lagrangian_hessian: np.ndarray
    unsymmetrized_relative_asymmetry: float
    active_constraint_rank: int
    gauge_dimension: int
    tested_tangent_dimension: int
    projected_eigenvalues: np.ndarray
    directional_curvatures: np.ndarray


def _matrix_rank(matrix: np.ndarray, relative_tolerance: float) -> int:
    if matrix.size == 0:
        return 0
    singular = np.linalg.svd(matrix, compute_uv=False)
    if singular.size == 0 or singular[0] == 0.0:
        return 0
    return int(np.count_nonzero(singular > relative_tolerance * singular[0]))


def audit_kkt_arrays(
    *,
    gradient_N: np.ndarray,
    gaps_m: np.ndarray,
    gap_jacobian: np.ndarray,
    force_scale_N: float,
    energy_scale_N_m: float,
    thresholds: ContactKKTThresholds,
) -> ContactKKTAudit:
    gradient = np.asarray(gradient_N, dtype=float)
    gaps = np.asarray(gaps_m, dtype=float)
    jacobian = np.asarray(gap_jacobian, dtype=float)
    if gradient.ndim != 1 or gaps.ndim != 1 or jacobian.shape != (gaps.size, gradient.size):
        raise ValueError("KKT arrays have incompatible dimensions.")
    active = np.flatnonzero(gaps <= thresholds.active_gap_max_m)
    multipliers = np.zeros(gaps.size)
    if active.size:
        active_multipliers, _ = nnls(jacobian[active].T, gradient)
        multipliers[active] = active_multipliers
    supported = active[multipliers[active] > thresholds.supported_multiplier_min_N]
    stationarity = gradient - jacobian.T @ multipliers
    primal = max(0.0, -float(np.min(gaps))) if gaps.size else 0.0
    dual = max(0.0, -float(np.min(multipliers))) if multipliers.size else 0.0
    stationarity_residual = float(np.linalg.norm(stationarity, ord=np.inf))
    complementarity = float(np.max(np.abs(multipliers * gaps))) if gaps.size else 0.0
    stationarity_limit = max(
        thresholds.stationarity_absolute_max_N,
        thresholds.stationarity_force_scale_factor_max * force_scale_N,
    )
    complementarity_limit = max(
        thresholds.complementarity_absolute_max_N_m,
        thresholds.complementarity_energy_scale_factor_max * energy_scale_N_m,
    )
    active_rank = _matrix_rank(
        jacobian[active], thresholds.active_constraint_rank_relative_tolerance
    )
    supported_rank = _matrix_rank(
        jacobian[supported], thresholds.active_constraint_rank_relative_tolerance
    )
    finite = bool(
        np.all(np.isfinite(gradient))
        and np.all(np.isfinite(gaps))
        and np.all(np.isfinite(jacobian))
        and np.all(np.isfinite(multipliers))
        and np.all(np.isfinite(stationarity))
    )
    passed = bool(
        finite
        and primal <= thresholds.primal_penetration_max_m
        and dual <= thresholds.dual_negative_max_N
        and stationarity_residual <= stationarity_limit
        and complementarity <= complementarity_limit
        and active_rank == active.size
        and supported_rank == supported.size
    )
    return ContactKKTAudit(
        passed=passed,
        finite=finite,
        force_scale_N=float(force_scale_N),
        energy_scale_N_m=float(energy_scale_N_m),
        active_indices=np.array(active, copy=True),
        supported_indices=np.array(supported, copy=True),
        active_constraint_rank=active_rank,
        supported_constraint_rank=supported_rank,
        multipliers_N=np.array(multipliers, copy=True),
        stationarity_vector_N=np.array(stationarity, copy=True),
        primal_violation_m=primal,
        dual_violation_N=dual,
        stationarity_residual_N=stationarity_residual,
        stationarity_limit_N=stationarity_limit,
        complementarity_residual_N_m=complementarity,
        complementarity_limit_N_m=complementarity_limit,
    )


def audit_contact_kkt(
    assembly: ContactStaticAssembly,
    evaluation: ContactStaticEvaluation,
    thresholds: ContactKKTThresholds,
) -> ContactKKTAudit:
    scale = force_scale(assembly.base_assembly)
    return audit_kkt_arrays(
        gradient_N=-evaluation.generalized_force,
        gaps_m=evaluation.gaps_m,
        gap_jacobian=evaluation.gap_jacobian,
        force_scale_N=scale,
        energy_scale_N_m=scale,
        thresholds=thresholds,
    )


def gap_jacobian_samples(
    assembly: ContactStaticAssembly,
    coordinates: ContactCoordinates,
    relative_steps: tuple[float, ...],
) -> tuple[GapJacobianSample, ...]:
    base = assembly.evaluate(coordinates)
    analytic = base.gap_jacobian
    samples = []
    for relative_step in relative_steps:
        step = float(relative_step)
        if not np.isfinite(step) or step <= 0.0:
            raise ValueError("Gap-Jacobian finite-difference steps must be finite and positive.")
        finite_difference = np.empty_like(analytic)
        for column in range(coordinates.values.size):
            plus = coordinates.values.copy()
            minus = coordinates.values.copy()
            plus[column] += step
            minus[column] -= step
            plus_gaps = assembly.evaluate(assembly.coordinates_from_values(plus)).gaps_m
            minus_gaps = assembly.evaluate(assembly.coordinates_from_values(minus)).gaps_m
            finite_difference[:, column] = (plus_gaps - minus_gaps) / (2.0 * step)
        row_denominator = np.maximum(
            np.maximum(np.linalg.norm(analytic, axis=1), np.linalg.norm(finite_difference, axis=1)),
            np.finfo(float).tiny,
        )
        row_relative = np.linalg.norm(analytic - finite_difference, axis=1) / row_denominator
        matrix_denominator = max(
            float(np.linalg.norm(analytic)),
            float(np.linalg.norm(finite_difference)),
            np.finfo(float).tiny,
        )
        samples.append(
            GapJacobianSample(
                relative_step=step,
                maximum_row_relative_error=float(np.max(row_relative)),
                matrix_relative_error=float(
                    np.linalg.norm(analytic - finite_difference) / matrix_denominator
                ),
            )
        )
    return tuple(samples)


def contact_action_reaction_audit(
    evaluation: ContactStaticEvaluation,
    multipliers_N: np.ndarray,
) -> ContactActionReactionAudit:
    multipliers = np.asarray(multipliers_N, dtype=float)
    if multipliers.shape != (len(evaluation.witnesses),):
        raise ValueError("Contact multiplier vector has the wrong identity count.")
    global_force = np.zeros(3)
    global_moment = np.zeros(3)
    maximum_force = 0.0
    maximum_moment = 0.0
    for witness, multiplier in zip(evaluation.witnesses, multipliers, strict=True):
        forces = multiplier * witness.object_gap_gradients
        if witness.category == "bob_segment":
            positions = np.vstack(
                [witness.first_point_m, witness.second_point_m, witness.second_point_m]
            )
            segment_parameter = witness.second_parameter
            positions[1] = witness.second_point_m
            positions[2] = witness.second_point_m
            if not 0.0 <= segment_parameter <= 1.0:
                raise ValueError("Bob-segment witness parameter left [0,1].")
        else:
            positions = np.vstack(
                [
                    witness.first_point_m,
                    witness.first_point_m,
                    witness.second_point_m,
                    witness.second_point_m,
                ]
            )
        force_residual = np.sum(forces, axis=0)
        moment_residual = np.sum(np.cross(positions, forces), axis=0)
        maximum_force = max(maximum_force, float(np.linalg.norm(force_residual)))
        maximum_moment = max(maximum_moment, float(np.linalg.norm(moment_residual)))
        global_force += force_residual
        global_moment += moment_residual
    return ContactActionReactionAudit(
        maximum_individual_force_residual_N=maximum_force,
        maximum_individual_moment_residual_N_m=maximum_moment,
        global_force_residual_N=np.array(global_force, copy=True),
        global_moment_residual_N_m=np.array(global_moment, copy=True),
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


def _gauge_rows(
    assembly: ContactStaticAssembly,
    coordinates: ContactCoordinates,
) -> np.ndarray:
    size = coordinates.values.size
    rotation_slice = assembly.base_assembly.layout.bob_rotation_slice.slice
    arm = assembly.base_assembly.bob.attachment_arm_body
    arm_norm = float(np.linalg.norm(arm))
    body_directions = np.eye(3) if arm_norm == 0.0 else (arm / arm_norm)[None, :]
    jacobian = _right_jacobian_so3(coordinates.values[rotation_slice])
    rows = []
    for body_direction in body_directions:
        row = np.zeros(size)
        row[rotation_slice] = np.linalg.solve(jacobian, body_direction)
        row /= np.linalg.norm(row)
        rows.append(row)
    return np.vstack(rows)


def independent_contact_hessian_audit(
    assembly: ContactStaticAssembly,
    coordinates: ContactCoordinates,
    multipliers_N: np.ndarray,
    active_indices: np.ndarray,
    *,
    normalized_step: float,
    directional_step: float,
    direction_count: int,
    rank_relative_tolerance: float,
) -> ContactHessianAudit:
    multipliers = np.asarray(multipliers_N, dtype=float)
    active = np.asarray(active_indices, dtype=int)
    base = assembly.evaluate(coordinates)
    if multipliers.shape != base.gaps_m.shape:
        raise ValueError("Lagrangian multiplier vector has the wrong shape.")
    size = coordinates.values.size
    scale = force_scale(assembly.base_assembly)

    def lagrangian_gradient(values: np.ndarray) -> np.ndarray:
        evaluation = assembly.evaluate(assembly.coordinates_from_values(values))
        return -evaluation.generalized_force - evaluation.gap_jacobian.T @ multipliers

    hessian = np.empty((size, size))
    for column in range(size):
        plus = coordinates.values.copy()
        minus = coordinates.values.copy()
        plus[column] += normalized_step
        minus[column] -= normalized_step
        hessian[:, column] = (
            lagrangian_gradient(plus) - lagrangian_gradient(minus)
        ) / (2.0 * normalized_step)
    normalized = hessian / scale
    symmetric = 0.5 * (normalized + normalized.T)
    asymmetry = float(
        np.linalg.norm(normalized - normalized.T)
        / max(np.linalg.norm(normalized), np.finfo(float).tiny)
    )
    active_rows = base.gap_jacobian[active]
    gauges = _gauge_rows(assembly, coordinates)
    exclusion_rows = np.vstack([active_rows, gauges])
    _, singular, right = np.linalg.svd(exclusion_rows, full_matrices=True)
    rank = 0
    if singular.size and singular[0] > 0.0:
        rank = int(np.count_nonzero(singular > rank_relative_tolerance * singular[0]))
    tangent = right[rank:].T
    projected = tangent.T @ symmetric @ tangent
    eigenvalues = np.linalg.eigvalsh(projected) if projected.size else np.empty(0)

    def lagrangian_value(values: np.ndarray) -> float:
        evaluation = assembly.evaluate(assembly.coordinates_from_values(values))
        return float(evaluation.total_potential - multipliers @ evaluation.gaps_m)

    base_value = lagrangian_value(coordinates.values)
    directional = []
    candidate = 0
    while len(directional) < direction_count and tangent.shape[1] > 0:
        indices = np.arange(1, size + 1, dtype=float)
        raw = np.sin(indices * (candidate + 1) * np.sqrt(2.0))
        raw += np.cos(indices * (candidate + 2) * np.sqrt(3.0))
        direction = tangent @ (tangent.T @ raw)
        candidate += 1
        norm = float(np.linalg.norm(direction))
        if norm <= 1.0e-12:
            continue
        direction /= norm
        plus = coordinates.values + directional_step * direction
        minus = coordinates.values - directional_step * direction
        curvature = (
            lagrangian_value(plus) - 2.0 * base_value + lagrangian_value(minus)
        ) / (directional_step**2 * scale)
        directional.append(float(curvature))
    return ContactHessianAudit(
        normalized_unsymmetrized_lagrangian_hessian=np.array(normalized, copy=True),
        normalized_symmetric_lagrangian_hessian=np.array(symmetric, copy=True),
        unsymmetrized_relative_asymmetry=asymmetry,
        active_constraint_rank=_matrix_rank(active_rows, rank_relative_tolerance),
        gauge_dimension=gauges.shape[0],
        tested_tangent_dimension=tangent.shape[1],
        projected_eigenvalues=np.array(eigenvalues, copy=True),
        directional_curvatures=np.array(directional, copy=True),
    )
