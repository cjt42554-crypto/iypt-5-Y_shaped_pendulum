"""Always-executed projected KKT restoration for the P3R2 composite solver."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .assembly import P3R2ContactAssembly
from .certification import (
    CharacteristicScales,
    RestorationActivity,
    gauge_coordinate,
    gauge_coordinate_row,
    gauge_direction_and_projection,
    select_restoration_activity,
    stationarity_vector,
)


@dataclass(frozen=True)
class P3R2RestorationSettings:
    near_active_gap_max_m: float
    supported_multiplier_min_N: float
    required_active_count: int
    rank_relative_tolerance: float
    initial_non_near_gap_strict_min_m: float
    primal_penetration_max_m: float
    validity_normalized_margin_min: float
    translation_hessian_step_m: float
    rotation_hessian_step_rad: float
    linear_system_relative_singular_value_min: float
    maximum_newton_iterations: int
    convergence_composite_infinity_max: float
    maximum_backtracks: int
    armijo_coefficient: float

    def __post_init__(self) -> None:
        expected = {
            "near_active_gap_max_m": 1.0e-7,
            "supported_multiplier_min_N": 1.0e-9,
            "required_active_count": 2,
            "rank_relative_tolerance": 1.0e-10,
            "initial_non_near_gap_strict_min_m": 1.0e-7,
            "primal_penetration_max_m": 1.0e-10,
            "validity_normalized_margin_min": 1.0e-5,
            "translation_hessian_step_m": 2.0e-6,
            "rotation_hessian_step_rad": 2.0e-6,
            "linear_system_relative_singular_value_min": 1.0e-12,
            "maximum_newton_iterations": 12,
            "convergence_composite_infinity_max": 1.0e-11,
            "maximum_backtracks": 20,
            "armijo_coefficient": 1.0e-4,
        }
        for name, frozen in expected.items():
            value = getattr(self, name)
            if value != frozen:
                raise ValueError(f"P3R2 freezes {name}={frozen!r}.")


@dataclass(frozen=True)
class P3R2RestorationResult:
    executed: bool
    converged: bool
    status: str
    iterations: int
    total_backtracks: int
    initial_coordinates: object
    coordinates: object
    initial_evaluation: object
    evaluation: object
    activity: RestorationActivity
    restore_constraint_ids: tuple[str, ...]
    weak_constraint_ids: tuple[str, ...]
    initial_restore_multipliers_N: np.ndarray
    final_restore_multipliers_N: np.ndarray
    initial_composite_residual: np.ndarray
    final_composite_residual: np.ndarray
    accepted_step_lengths: np.ndarray
    linear_system_relative_singular_values: np.ndarray


@dataclass(frozen=True)
class _RestorationState:
    coordinates: object
    evaluation: object
    active_multipliers_N: np.ndarray
    composite_residual: np.ndarray


def _active_full_multipliers(
    contact_count: int,
    active_indices: np.ndarray,
    active_multipliers_N: np.ndarray,
) -> np.ndarray:
    result = np.zeros(contact_count)
    result[active_indices] = active_multipliers_N
    return result


def _state(
    assembly: P3R2ContactAssembly,
    values: np.ndarray,
    active_indices: np.ndarray,
    active_multipliers_N: np.ndarray,
    scales: CharacteristicScales,
) -> _RestorationState:
    coordinates = assembly.coordinates_from_values(values)
    evaluation = assembly.evaluate(coordinates)
    full = _active_full_multipliers(
        evaluation.contact.gaps_m.size,
        active_indices,
        active_multipliers_N,
    )
    raw = stationarity_vector(evaluation, full)
    dimensionless = raw / scales.stationarity_scales
    _, projection = gauge_direction_and_projection(assembly, values, scales)
    projected = projection.T @ dimensionless
    active_gaps = evaluation.contact.gaps_m[active_indices] / scales.length_m
    gauge = gauge_coordinate(assembly, values)
    residual = np.concatenate([projected, active_gaps, [gauge]])
    return _RestorationState(
        coordinates=coordinates,
        evaluation=evaluation,
        active_multipliers_N=np.array(active_multipliers_N, copy=True),
        composite_residual=np.array(residual, copy=True),
    )


def _feasible(
    state: _RestorationState,
    non_near_indices: np.ndarray,
    settings: P3R2RestorationSettings,
) -> bool:
    gaps = state.evaluation.contact.gaps_m
    validity = state.evaluation.validity.normalized_residuals
    return bool(
        np.all(np.isfinite(state.coordinates.values))
        and np.all(np.isfinite(gaps))
        and np.all(np.isfinite(validity))
        and float(np.min(gaps)) >= -settings.primal_penetration_max_m
        and (
            non_near_indices.size == 0
            or float(np.min(gaps[non_near_indices]))
            > settings.initial_non_near_gap_strict_min_m
        )
        and float(np.min(validity)) >= settings.validity_normalized_margin_min
    )


def _lagrangian_hessian(
    assembly: P3R2ContactAssembly,
    values: np.ndarray,
    active_indices: np.ndarray,
    active_multipliers_N: np.ndarray,
    settings: P3R2RestorationSettings,
) -> np.ndarray:
    size = values.size
    rotation_start = assembly.base_assembly.layout.bob_rotation_slice.start
    hessian = np.empty((size, size))
    for column in range(size):
        step = (
            settings.translation_hessian_step_m
            if column < rotation_start
            else settings.rotation_hessian_step_rad
        )
        plus = np.array(values, copy=True)
        minus = np.array(values, copy=True)
        plus[column] += step
        minus[column] -= step
        plus_evaluation = assembly.evaluate(assembly.coordinates_from_values(plus))
        minus_evaluation = assembly.evaluate(assembly.coordinates_from_values(minus))
        plus_full = _active_full_multipliers(
            plus_evaluation.contact.gaps_m.size,
            active_indices,
            active_multipliers_N,
        )
        minus_full = _active_full_multipliers(
            minus_evaluation.contact.gaps_m.size,
            active_indices,
            active_multipliers_N,
        )
        hessian[:, column] = (
            stationarity_vector(plus_evaluation, plus_full)
            - stationarity_vector(minus_evaluation, minus_full)
        ) / (2.0 * step)
    return hessian


def _newton_matrix(
    assembly: P3R2ContactAssembly,
    state: _RestorationState,
    active_indices: np.ndarray,
    scales: CharacteristicScales,
    settings: P3R2RestorationSettings,
) -> np.ndarray:
    values = state.coordinates.values
    hessian = _lagrangian_hessian(
        assembly,
        values,
        active_indices,
        state.active_multipliers_N,
        settings,
    )
    _, projection = gauge_direction_and_projection(assembly, values, scales)
    active_jacobian = state.evaluation.contact.gap_jacobian[active_indices]
    scaled_hessian = (
        hessian * scales.coordinate_scales[None, :]
    ) / scales.stationarity_scales[:, None]
    scaled_multiplier_block = (
        -active_jacobian.T * scales.force_N
    ) / scales.stationarity_scales[:, None]
    stationarity_block = np.hstack(
        [projection.T @ scaled_hessian, projection.T @ scaled_multiplier_block]
    )
    gap_block = np.hstack(
        [
            active_jacobian * scales.coordinate_scales[None, :] / scales.length_m,
            np.zeros((active_indices.size, active_indices.size)),
        ]
    )
    gauge_block = np.hstack(
        [
            gauge_coordinate_row(assembly) * scales.coordinate_scales,
            np.zeros(active_indices.size),
        ]
    )[None, :]
    return np.vstack([stationarity_block, gap_block, gauge_block])


def _result(
    *,
    converged: bool,
    status: str,
    iterations: int,
    total_backtracks: int,
    initial_state: _RestorationState,
    final_state: _RestorationState,
    activity: RestorationActivity,
    constraint_ids: tuple[str, ...],
    initial_multipliers: np.ndarray,
    accepted_steps: list[float],
    singular_values: list[float],
) -> P3R2RestorationResult:
    return P3R2RestorationResult(
        executed=True,
        converged=converged,
        status=status,
        iterations=iterations,
        total_backtracks=total_backtracks,
        initial_coordinates=initial_state.coordinates,
        coordinates=final_state.coordinates,
        initial_evaluation=initial_state.evaluation,
        evaluation=final_state.evaluation,
        activity=activity,
        restore_constraint_ids=tuple(
            constraint_ids[int(index)] for index in activity.restore_indices
        ),
        weak_constraint_ids=tuple(
            constraint_ids[int(index)] for index in activity.weak_active_indices
        ),
        initial_restore_multipliers_N=np.array(initial_multipliers, copy=True),
        final_restore_multipliers_N=np.array(
            final_state.active_multipliers_N,
            copy=True,
        ),
        initial_composite_residual=np.array(
            initial_state.composite_residual,
            copy=True,
        ),
        final_composite_residual=np.array(
            final_state.composite_residual,
            copy=True,
        ),
        accepted_step_lengths=np.array(accepted_steps, dtype=float),
        linear_system_relative_singular_values=np.array(
            singular_values,
            dtype=float,
        ),
    )


def restore_contact_kkt(
    assembly: P3R2ContactAssembly,
    coordinates: object,
    scales: CharacteristicScales,
    settings: P3R2RestorationSettings,
) -> P3R2RestorationResult:
    """Execute the fixed projected KKT stage for every SLSQP result."""

    initial_evaluation = assembly.evaluate(coordinates)
    activity = select_restoration_activity(
        initial_evaluation,
        scales,
        near_active_gap_max_m=settings.near_active_gap_max_m,
        supported_multiplier_min_N=settings.supported_multiplier_min_N,
        rank_relative_tolerance=settings.rank_relative_tolerance,
    )
    initial_multipliers = activity.canonical_multipliers_N[
        activity.restore_indices
    ]
    initial_state = _state(
        assembly,
        coordinates.values,
        activity.restore_indices,
        initial_multipliers,
        scales,
    )
    constraint_ids = initial_evaluation.contact.constraint_ids
    if (
        activity.restore_indices.size != settings.required_active_count
        or activity.restore_rank != settings.required_active_count
    ):
        return _result(
            converged=False,
            status="FAIL_CLOSED_ACTIVE_SET_CARDINALITY_OR_RANK",
            iterations=0,
            total_backtracks=0,
            initial_state=initial_state,
            final_state=initial_state,
            activity=activity,
            constraint_ids=constraint_ids,
            initial_multipliers=initial_multipliers,
            accepted_steps=[],
            singular_values=[],
        )
    all_indices = np.arange(initial_evaluation.contact.gaps_m.size)
    non_near = np.setdiff1d(
        all_indices,
        activity.near_active_indices,
        assume_unique=True,
    )
    current = initial_state
    current_norm = float(np.linalg.norm(current.composite_residual, ord=np.inf))
    accepted_steps: list[float] = []
    relative_singular_values: list[float] = []
    total_backtracks = 0
    if current_norm <= settings.convergence_composite_infinity_max:
        return _result(
            converged=True,
            status="CONVERGED_AT_ENTRY",
            iterations=0,
            total_backtracks=0,
            initial_state=initial_state,
            final_state=current,
            activity=activity,
            constraint_ids=constraint_ids,
            initial_multipliers=initial_multipliers,
            accepted_steps=accepted_steps,
            singular_values=relative_singular_values,
        )
    for iteration in range(1, settings.maximum_newton_iterations + 1):
        matrix = _newton_matrix(
            assembly,
            current,
            activity.restore_indices,
            scales,
            settings,
        )
        singular = np.linalg.svd(matrix, compute_uv=False)
        relative = float(singular[-1] / singular[0]) if singular[0] > 0.0 else 0.0
        relative_singular_values.append(relative)
        if relative < settings.linear_system_relative_singular_value_min:
            return _result(
                converged=False,
                status="FAIL_CLOSED_LINEAR_SYSTEM",
                iterations=iteration - 1,
                total_backtracks=total_backtracks,
                initial_state=initial_state,
                final_state=current,
                activity=activity,
                constraint_ids=constraint_ids,
                initial_multipliers=initial_multipliers,
                accepted_steps=accepted_steps,
                singular_values=relative_singular_values,
            )
        direction = np.linalg.solve(matrix, -current.composite_residual)
        coordinate_direction = scales.coordinate_scales * direction[:6]
        multiplier_direction = scales.force_N * direction[6:]
        accepted_state = current
        accepted = False
        accepted_alpha = 0.0
        for backtrack in range(settings.maximum_backtracks + 1):
            alpha = float(2.0 ** (-backtrack))
            candidate = _state(
                assembly,
                current.coordinates.values + alpha * coordinate_direction,
                activity.restore_indices,
                current.active_multipliers_N + alpha * multiplier_direction,
                scales,
            )
            candidate_norm = float(
                np.linalg.norm(candidate.composite_residual, ord=np.inf)
            )
            decrease = (1.0 - settings.armijo_coefficient * alpha) * current_norm
            if _feasible(candidate, non_near, settings) and candidate_norm <= decrease:
                accepted_state = candidate
                accepted = True
                accepted_alpha = alpha
                total_backtracks += backtrack
                break
        if not accepted:
            return _result(
                converged=False,
                status="FAIL_CLOSED_NO_ACCEPTED_STEP",
                iterations=iteration - 1,
                total_backtracks=total_backtracks,
                initial_state=initial_state,
                final_state=current,
                activity=activity,
                constraint_ids=constraint_ids,
                initial_multipliers=initial_multipliers,
                accepted_steps=accepted_steps,
                singular_values=relative_singular_values,
            )
        current = accepted_state
        current_norm = float(np.linalg.norm(current.composite_residual, ord=np.inf))
        accepted_steps.append(accepted_alpha)
        if current_norm <= settings.convergence_composite_infinity_max:
            return _result(
                converged=True,
                status="CONVERGED",
                iterations=iteration,
                total_backtracks=total_backtracks,
                initial_state=initial_state,
                final_state=current,
                activity=activity,
                constraint_ids=constraint_ids,
                initial_multipliers=initial_multipliers,
                accepted_steps=accepted_steps,
                singular_values=relative_singular_values,
            )
    return _result(
        converged=False,
        status="FAIL_CLOSED_ITERATION_LIMIT",
        iterations=settings.maximum_newton_iterations,
        total_backtracks=total_backtracks,
        initial_state=initial_state,
        final_state=current,
        activity=activity,
        constraint_ids=constraint_ids,
        initial_multipliers=initial_multipliers,
        accepted_steps=accepted_steps,
        singular_values=relative_singular_values,
    )
