"""Fixed declared-dual-active projected KKT Newton reference constructor."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import nnls

from ypendulum_hfv2.contact import ContactGeometryError
from ypendulum_hfv2_p3r4.restoration import quasi_newton_matrix
from ypendulum_hfv2_p3r4.solver import settings_from_manifest as qualification_settings

from .assembly import P3R5ContactAssembly
from .certification import (
    CharacteristicScales,
    characteristic_scales,
    gauge_coordinate,
    gauge_direction_and_projection,
    stationarity_vector,
)


@dataclass(frozen=True)
class ReferenceSettings:
    declared_active_count: int
    full_residual_jacobian_dimensionless_step: float
    linear_system_relative_singular_value_min: float
    maximum_newton_iterations: int
    convergence_composite_infinity_max: float
    maximum_backtracks: int
    armijo_coefficient: float
    primal_penetration_max_m: float
    nonactive_contact_gap_strict_min_m: float
    validity_normalized_margin_min: float
    active_multiplier_candidate_min_N: float
    audit_steps: tuple[float, ...]
    audit_finest_pair_relative_difference_max: float
    audit_block_to_full_relative_difference_max: float

    def __post_init__(self) -> None:
        expected: dict[str, object] = {
            "declared_active_count": 2,
            "full_residual_jacobian_dimensionless_step": 1.0e-6,
            "linear_system_relative_singular_value_min": 1.0e-12,
            "maximum_newton_iterations": 20,
            "convergence_composite_infinity_max": 1.0e-11,
            "maximum_backtracks": 20,
            "armijo_coefficient": 1.0e-4,
            "primal_penetration_max_m": 1.0e-10,
            "nonactive_contact_gap_strict_min_m": 1.0e-7,
            "validity_normalized_margin_min": 1.0e-5,
            "active_multiplier_candidate_min_N": 0.0,
            "audit_steps": (3.0e-6, 1.0e-6, 3.0e-7),
            "audit_finest_pair_relative_difference_max": 5.0e-4,
            "audit_block_to_full_relative_difference_max": 5.0e-3,
        }
        object.__setattr__(self, "audit_steps", tuple(float(item) for item in self.audit_steps))
        for name, frozen in expected.items():
            if getattr(self, name) != frozen:
                raise ValueError(f"P3R5 freezes {name}={frozen!r}.")


@dataclass(frozen=True)
class ReferenceJacobianAudit:
    passed: bool
    dimensionless_steps: np.ndarray
    full_jacobians: np.ndarray
    independent_block_jacobian: np.ndarray
    finest_pair_relative_difference: float
    block_to_full_relative_difference: float


@dataclass(frozen=True)
class ReferenceConstructionResult:
    executed: bool
    converged: bool
    status: str
    iterations: int
    total_backtracks: int
    declared_active_constraint_ids: tuple[str, ...]
    declared_active_indices: np.ndarray
    initial_coordinates: object
    coordinates: object
    initial_active_multipliers_N: np.ndarray
    active_multipliers_N: np.ndarray
    initial_composite_residual: np.ndarray
    final_composite_residual: np.ndarray
    accepted_step_lengths: np.ndarray
    linear_system_relative_singular_values: np.ndarray
    jacobian_audit: ReferenceJacobianAudit | None


@dataclass(frozen=True)
class _ReferenceState:
    coordinates: object
    evaluation: object
    active_multipliers_N: np.ndarray
    composite_residual: np.ndarray


def settings_from_manifest(manifest: dict[str, Any]) -> ReferenceSettings:
    source = manifest["reference_constructor"]
    audit = manifest["reference_jacobian_audit"]
    return ReferenceSettings(
        declared_active_count=int(source["declared_active_count"]),
        full_residual_jacobian_dimensionless_step=float(
            source["full_residual_jacobian_dimensionless_step"]
        ),
        linear_system_relative_singular_value_min=float(
            source["linear_system_relative_singular_value_min"]
        ),
        maximum_newton_iterations=int(source["maximum_newton_iterations"]),
        convergence_composite_infinity_max=float(source["convergence_composite_infinity_max"]),
        maximum_backtracks=int(source["maximum_backtracks"]),
        armijo_coefficient=float(source["armijo_coefficient"]),
        primal_penetration_max_m=float(source["primal_penetration_max_m"]),
        nonactive_contact_gap_strict_min_m=float(source["nonactive_contact_gap_strict_min_m"]),
        validity_normalized_margin_min=float(source["validity_normalized_margin_min"]),
        active_multiplier_candidate_min_N=float(source["active_multiplier_candidate_min_N"]),
        audit_steps=tuple(audit["full_residual_dimensionless_steps"]),
        audit_finest_pair_relative_difference_max=float(
            audit["finest_pair_relative_difference_max"]
        ),
        audit_block_to_full_relative_difference_max=float(
            audit["independent_block_to_full_relative_difference_max"]
        ),
    )


def _declared_indices(
    constraint_ids: tuple[str, ...],
    declared_ids: tuple[str, ...],
) -> np.ndarray:
    if len(declared_ids) != len(set(declared_ids)):
        raise ValueError("P3R5 declared active contact identities must be unique.")
    by_identity = {identity: index for index, identity in enumerate(constraint_ids)}
    if len(by_identity) != len(constraint_ids) or any(
        item not in by_identity for item in declared_ids
    ):
        raise ValueError("P3R5 declared active contact identity is absent or ambiguous.")
    return np.asarray([by_identity[item] for item in declared_ids], dtype=int)


def _active_full_multipliers(
    contact_count: int,
    active_indices: np.ndarray,
    active_multipliers_N: np.ndarray,
) -> np.ndarray:
    result = np.zeros(contact_count)
    result[active_indices] = active_multipliers_N
    return result


def _state(
    assembly: P3R5ContactAssembly,
    values: np.ndarray,
    active_indices: np.ndarray,
    active_multipliers_N: np.ndarray,
    scales: CharacteristicScales,
) -> _ReferenceState:
    coordinates = assembly.coordinates_from_values(values)
    evaluation = assembly.evaluate(coordinates)
    full = _active_full_multipliers(
        evaluation.contact.gaps_m.size,
        active_indices,
        active_multipliers_N,
    )
    stationarity = stationarity_vector(evaluation, full) / scales.stationarity_scales
    _, projection = gauge_direction_and_projection(assembly, values, scales)
    projected = projection.T @ stationarity
    active_gaps = evaluation.contact.gaps_m[active_indices] / scales.length_m
    residual = np.concatenate([projected, active_gaps, [gauge_coordinate(assembly, values)]])
    return _ReferenceState(
        coordinates=coordinates,
        evaluation=evaluation,
        active_multipliers_N=np.array(active_multipliers_N, copy=True),
        composite_residual=np.array(residual, copy=True),
    )


def _initial_multipliers(
    state: _ReferenceState,
    active_indices: np.ndarray,
    scales: CharacteristicScales,
) -> np.ndarray:
    jacobian = np.asarray(state.evaluation.contact.gap_jacobian, dtype=float)[active_indices]
    gradient = -np.asarray(state.evaluation.generalized_force, dtype=float)
    weighted_jacobian = jacobian.T / scales.stationarity_scales[:, None]
    weighted_gradient = gradient / scales.stationarity_scales
    active, _ = nnls(weighted_jacobian, weighted_gradient)
    return np.asarray(active, dtype=float)


def _full_jacobian(
    assembly: P3R5ContactAssembly,
    state: _ReferenceState,
    active_indices: np.ndarray,
    scales: CharacteristicScales,
    step: float,
) -> np.ndarray:
    coordinate_count = state.coordinates.values.size
    unknown_count = coordinate_count + active_indices.size
    matrix = np.empty((unknown_count, unknown_count))
    for column in range(unknown_count):
        plus_values = np.array(state.coordinates.values, copy=True)
        minus_values = np.array(state.coordinates.values, copy=True)
        plus_multipliers = np.array(state.active_multipliers_N, copy=True)
        minus_multipliers = np.array(state.active_multipliers_N, copy=True)
        if column < coordinate_count:
            physical_step = step * scales.coordinate_scales[column]
            plus_values[column] += physical_step
            minus_values[column] -= physical_step
        else:
            multiplier_index = column - coordinate_count
            physical_step = step * scales.force_N
            plus_multipliers[multiplier_index] += physical_step
            minus_multipliers[multiplier_index] -= physical_step
        plus = _state(
            assembly,
            plus_values,
            active_indices,
            plus_multipliers,
            scales,
        ).composite_residual
        minus = _state(
            assembly,
            minus_values,
            active_indices,
            minus_multipliers,
            scales,
        ).composite_residual
        matrix[:, column] = (plus - minus) / (2.0 * step)
    return matrix


def audit_reference_jacobian(
    assembly: P3R5ContactAssembly,
    state: _ReferenceState,
    active_indices: np.ndarray,
    scales: CharacteristicScales,
    settings: ReferenceSettings,
    manifest: dict[str, Any],
) -> ReferenceJacobianAudit:
    steps = np.asarray(settings.audit_steps, dtype=float)
    full = np.stack(
        [_full_jacobian(assembly, state, active_indices, scales, float(step)) for step in steps]
    )
    block = quasi_newton_matrix(
        assembly,
        state.coordinates,
        active_indices,
        state.active_multipliers_N,
        scales,
        qualification_settings(manifest).restoration,
    )
    denominator = max(float(np.linalg.norm(full[-1])), np.finfo(float).tiny)
    finest_pair = float(np.linalg.norm(full[-1] - full[-2]) / denominator)
    block_difference = float(np.linalg.norm(block - full[-1]) / denominator)
    passed = bool(
        np.all(np.isfinite(full))
        and np.all(np.isfinite(block))
        and finest_pair <= settings.audit_finest_pair_relative_difference_max
        and block_difference <= settings.audit_block_to_full_relative_difference_max
    )
    return ReferenceJacobianAudit(
        passed=passed,
        dimensionless_steps=np.array(steps, copy=True),
        full_jacobians=np.array(full, copy=True),
        independent_block_jacobian=np.array(block, copy=True),
        finest_pair_relative_difference=finest_pair,
        block_to_full_relative_difference=block_difference,
    )


def _feasible(
    state: _ReferenceState,
    nonactive_indices: np.ndarray,
    settings: ReferenceSettings,
) -> bool:
    gaps = np.asarray(state.evaluation.contact.gaps_m, dtype=float)
    validity = np.asarray(state.evaluation.validity.normalized_residuals, dtype=float)
    return bool(
        np.all(np.isfinite(state.coordinates.values))
        and np.all(np.isfinite(gaps))
        and np.all(np.isfinite(validity))
        and np.all(np.isfinite(state.active_multipliers_N))
        and np.all(np.isfinite(state.composite_residual))
        and float(np.min(state.active_multipliers_N)) >= settings.active_multiplier_candidate_min_N
        and float(np.min(gaps)) >= -settings.primal_penetration_max_m
        and float(np.min(gaps[nonactive_indices])) > settings.nonactive_contact_gap_strict_min_m
        and float(np.min(validity)) >= settings.validity_normalized_margin_min
    )


def _result(
    *,
    converged: bool,
    status: str,
    iterations: int,
    total_backtracks: int,
    declared_ids: tuple[str, ...],
    active_indices: np.ndarray,
    initial: _ReferenceState,
    final: _ReferenceState,
    accepted_steps: list[float],
    singular_values: list[float],
    jacobian_audit: ReferenceJacobianAudit | None,
) -> ReferenceConstructionResult:
    return ReferenceConstructionResult(
        executed=True,
        converged=converged,
        status=status,
        iterations=iterations,
        total_backtracks=total_backtracks,
        declared_active_constraint_ids=declared_ids,
        declared_active_indices=np.array(active_indices, copy=True),
        initial_coordinates=initial.coordinates,
        coordinates=final.coordinates,
        initial_active_multipliers_N=np.array(initial.active_multipliers_N, copy=True),
        active_multipliers_N=np.array(final.active_multipliers_N, copy=True),
        initial_composite_residual=np.array(initial.composite_residual, copy=True),
        final_composite_residual=np.array(final.composite_residual, copy=True),
        accepted_step_lengths=np.asarray(accepted_steps, dtype=float),
        linear_system_relative_singular_values=np.asarray(singular_values, dtype=float),
        jacobian_audit=jacobian_audit,
    )


def construct_reference(
    assembly: P3R5ContactAssembly,
    initial_coordinates: object,
    declared_active_constraint_ids: tuple[str, ...],
    settings: ReferenceSettings,
    manifest: dict[str, Any],
) -> ReferenceConstructionResult:
    """Run the single frozen reference constructor for one declared active pair."""

    scales = characteristic_scales(assembly)
    initial_evaluation = assembly.evaluate(initial_coordinates)
    active_indices = None
    with suppress(ValueError):
        active_indices = _declared_indices(
            initial_evaluation.contact.constraint_ids,
            declared_active_constraint_ids,
        )
    if active_indices is None:
        placeholder = _ReferenceState(
            coordinates=initial_coordinates,
            evaluation=initial_evaluation,
            active_multipliers_N=np.zeros(settings.declared_active_count),
            composite_residual=np.full(6 + settings.declared_active_count, np.inf),
        )
        return _result(
            converged=False,
            status="FAIL_CLOSED_DECLARED_ACTIVE_IDENTITY",
            iterations=0,
            total_backtracks=0,
            declared_ids=declared_active_constraint_ids,
            active_indices=np.empty(0, dtype=int),
            initial=placeholder,
            final=placeholder,
            accepted_steps=[],
            singular_values=[],
            jacobian_audit=None,
        )
    if active_indices.size != settings.declared_active_count:
        raise ValueError("P3R5 reference constructor requires exactly two declared contacts.")
    zero_state = _state(
        assembly,
        initial_coordinates.values,
        active_indices,
        np.zeros(active_indices.size),
        scales,
    )
    initial_multipliers = _initial_multipliers(zero_state, active_indices, scales)
    initial = _state(
        assembly,
        initial_coordinates.values,
        active_indices,
        initial_multipliers,
        scales,
    )
    all_indices = np.arange(initial.evaluation.contact.gaps_m.size)
    nonactive = np.setdiff1d(all_indices, active_indices, assume_unique=True)
    if nonactive.size == 0 or not _feasible(initial, nonactive, settings):
        return _result(
            converged=False,
            status="FAIL_CLOSED_INITIAL_DOMAIN",
            iterations=0,
            total_backtracks=0,
            declared_ids=declared_active_constraint_ids,
            active_indices=active_indices,
            initial=initial,
            final=initial,
            accepted_steps=[],
            singular_values=[],
            jacobian_audit=None,
        )
    current = initial
    accepted_steps: list[float] = []
    singular_values: list[float] = []
    total_backtracks = 0
    current_norm = float(np.linalg.norm(current.composite_residual, ord=np.inf))
    if current_norm <= settings.convergence_composite_infinity_max:
        audit = audit_reference_jacobian(
            assembly, current, active_indices, scales, settings, manifest
        )
        return _result(
            converged=True,
            status="CONVERGED_AT_ENTRY",
            iterations=0,
            total_backtracks=0,
            declared_ids=declared_active_constraint_ids,
            active_indices=active_indices,
            initial=initial,
            final=current,
            accepted_steps=accepted_steps,
            singular_values=singular_values,
            jacobian_audit=audit,
        )
    for iteration in range(1, settings.maximum_newton_iterations + 1):
        matrix = None
        singular = None
        with suppress(ContactGeometryError, ValueError, np.linalg.LinAlgError):
            matrix = _full_jacobian(
                assembly,
                current,
                active_indices,
                scales,
                settings.full_residual_jacobian_dimensionless_step,
            )
            singular = np.linalg.svd(matrix, compute_uv=False)
        if matrix is None or singular is None:
            return _result(
                converged=False,
                status="FAIL_CLOSED_UNDEFINED_GEOMETRY_OR_COORDINATE",
                iterations=iteration - 1,
                total_backtracks=total_backtracks,
                declared_ids=declared_active_constraint_ids,
                active_indices=active_indices,
                initial=initial,
                final=current,
                accepted_steps=accepted_steps,
                singular_values=singular_values,
                jacobian_audit=None,
            )
        relative = float(singular[-1] / singular[0]) if singular[0] > 0.0 else 0.0
        singular_values.append(relative)
        if relative < settings.linear_system_relative_singular_value_min:
            return _result(
                converged=False,
                status="FAIL_CLOSED_LINEAR_SYSTEM",
                iterations=iteration - 1,
                total_backtracks=total_backtracks,
                declared_ids=declared_active_constraint_ids,
                active_indices=active_indices,
                initial=initial,
                final=current,
                accepted_steps=accepted_steps,
                singular_values=singular_values,
                jacobian_audit=None,
            )
        direction = None
        with suppress(np.linalg.LinAlgError):
            direction = np.linalg.solve(matrix, -current.composite_residual)
        if direction is None:
            return _result(
                converged=False,
                status="FAIL_CLOSED_LINEAR_SYSTEM",
                iterations=iteration - 1,
                total_backtracks=total_backtracks,
                declared_ids=declared_active_constraint_ids,
                active_indices=active_indices,
                initial=initial,
                final=current,
                accepted_steps=accepted_steps,
                singular_values=singular_values,
                jacobian_audit=None,
            )
        coordinate_direction = scales.coordinate_scales * direction[:6]
        multiplier_direction = scales.force_N * direction[6:]
        accepted = False
        accepted_state = current
        accepted_alpha = 0.0
        nonnegative_candidate_seen = False
        for backtrack in range(settings.maximum_backtracks + 1):
            alpha = float(2.0 ** (-backtrack))
            candidate_multipliers = current.active_multipliers_N + alpha * multiplier_direction
            if float(np.min(candidate_multipliers)) < settings.active_multiplier_candidate_min_N:
                continue
            nonnegative_candidate_seen = True
            candidate = None
            with suppress(ContactGeometryError, ValueError, np.linalg.LinAlgError):
                candidate = _state(
                    assembly,
                    current.coordinates.values + alpha * coordinate_direction,
                    active_indices,
                    candidate_multipliers,
                    scales,
                )
            if candidate is None:
                continue
            candidate_norm = float(np.linalg.norm(candidate.composite_residual, ord=np.inf))
            required = (1.0 - settings.armijo_coefficient * alpha) * current_norm
            if _feasible(candidate, nonactive, settings) and candidate_norm <= required:
                accepted = True
                accepted_state = candidate
                accepted_alpha = alpha
                total_backtracks += backtrack
                break
        if not accepted:
            status = (
                "FAIL_CLOSED_NO_ACCEPTED_STEP"
                if nonnegative_candidate_seen
                else "FAIL_CLOSED_NEGATIVE_ACTIVE_MULTIPLIER"
            )
            return _result(
                converged=False,
                status=status,
                iterations=iteration - 1,
                total_backtracks=total_backtracks,
                declared_ids=declared_active_constraint_ids,
                active_indices=active_indices,
                initial=initial,
                final=current,
                accepted_steps=accepted_steps,
                singular_values=singular_values,
                jacobian_audit=None,
            )
        current = accepted_state
        current_norm = float(np.linalg.norm(current.composite_residual, ord=np.inf))
        accepted_steps.append(accepted_alpha)
        if current_norm <= settings.convergence_composite_infinity_max:
            audit = audit_reference_jacobian(
                assembly, current, active_indices, scales, settings, manifest
            )
            return _result(
                converged=True,
                status="CONVERGED",
                iterations=iteration,
                total_backtracks=total_backtracks,
                declared_ids=declared_active_constraint_ids,
                active_indices=active_indices,
                initial=initial,
                final=current,
                accepted_steps=accepted_steps,
                singular_values=singular_values,
                jacobian_audit=audit,
            )
    return _result(
        converged=False,
        status="FAIL_CLOSED_ITERATION_LIMIT",
        iterations=settings.maximum_newton_iterations,
        total_backtracks=total_backtracks,
        declared_ids=declared_active_constraint_ids,
        active_indices=active_indices,
        initial=initial,
        final=current,
        accepted_steps=accepted_steps,
        singular_values=singular_values,
        jacobian_audit=None,
    )


__all__ = [
    "ReferenceConstructionResult",
    "ReferenceJacobianAudit",
    "ReferenceSettings",
    "audit_reference_jacobian",
    "construct_reference",
    "settings_from_manifest",
]
