"""Deterministic active-contact manifold retraction and finite-neighborhood audit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ypendulum_hfv2_p3r.kkt import matrix_rank

from . import P3R4_MANIFOLD_RETRACTION_ID
from .assembly import P3R4ContactAssembly
from .certification import CharacteristicScales, gauge_coordinate, gauge_coordinate_row
from .second_order import tangent_directions


@dataclass(frozen=True)
class ManifoldRetractionSettings:
    linear_system_relative_singular_value_min: float
    maximum_newton_iterations: int
    convergence_infinity_max: float
    maximum_backtracks: int
    armijo_coefficient: float
    nonactive_contact_gap_strict_min_m: float
    validity_normalized_margin_min: float


@dataclass(frozen=True)
class ManifoldRetractionResult:
    converged: bool
    status: str
    iterations: int
    total_backtracks: int
    accepted_step_lengths: np.ndarray
    linear_system_relative_singular_values: np.ndarray
    target_tangent_coordinates: np.ndarray
    initial_residual: np.ndarray
    final_residual: np.ndarray
    coordinates: object
    evaluation: object


@dataclass(frozen=True)
class ManifoldNeighborhoodAudit:
    identity: str
    passed: bool
    dimensionless_radius: float
    tangent_basis: np.ndarray
    direction_count_unoriented: int
    endpoint_retraction_count: int
    records: tuple[dict[str, Any], ...]
    minimum_true_potential_increase_margin: float
    minimum_symmetric_true_potential_curvature: float


def settings_from_manifest(manifest: dict[str, Any]) -> ManifoldRetractionSettings:
    source = manifest["manifold_neighborhood"]
    return ManifoldRetractionSettings(
        linear_system_relative_singular_value_min=float(
            source["linear_system_relative_singular_value_min"]
        ),
        maximum_newton_iterations=int(source["maximum_newton_iterations"]),
        convergence_infinity_max=float(source["convergence_infinity_max"]),
        maximum_backtracks=int(source["maximum_backtracks"]),
        armijo_coefficient=float(source["armijo_coefficient"]),
        nonactive_contact_gap_strict_min_m=float(source["nonactive_contact_gap_strict_min_m"]),
        validity_normalized_margin_min=float(source["validity_normalized_margin_min"]),
    )


def _residual_and_jacobian(
    assembly: P3R4ContactAssembly,
    values: np.ndarray,
    reference_values: np.ndarray,
    active_indices: np.ndarray,
    tangent_basis: np.ndarray,
    target_tangent_coordinates: np.ndarray,
    scales: CharacteristicScales,
) -> tuple[object, object, np.ndarray, np.ndarray]:
    coordinates = assembly.coordinates_from_values(values)
    evaluation = assembly.evaluate(coordinates)
    dimensionless = (values - reference_values) / scales.coordinate_scales
    active_residual = evaluation.contact.gaps_m[active_indices] / scales.length_m
    gauge_residual = gauge_coordinate(assembly, values)
    tangent_residual = tangent_basis.T @ dimensionless - target_tangent_coordinates
    residual = np.concatenate([active_residual, [gauge_residual], tangent_residual])
    active_rows = (
        evaluation.contact.gap_jacobian[active_indices]
        * scales.coordinate_scales[None, :]
        / scales.length_m
    )
    gauge_row = (gauge_coordinate_row(assembly) * scales.coordinate_scales)[None, :]
    jacobian = np.vstack([active_rows, gauge_row, tangent_basis.T])
    if residual.shape != (6,) or jacobian.shape != (6, 6):
        raise ValueError("P3R4 manifold chart must close six equations in six coordinates.")
    if not np.all(np.isfinite(residual)) or not np.all(np.isfinite(jacobian)):
        raise ValueError("P3R4 manifold residual and Jacobian must be finite.")
    return coordinates, evaluation, residual, jacobian


def _domain_feasible(
    evaluation: object,
    nonactive_indices: np.ndarray,
    settings: ManifoldRetractionSettings,
) -> bool:
    gaps = np.asarray(evaluation.contact.gaps_m, dtype=float)
    validity = np.asarray(evaluation.validity.normalized_residuals, dtype=float)
    return bool(
        np.all(np.isfinite(gaps))
        and np.all(np.isfinite(validity))
        and (
            nonactive_indices.size == 0
            or float(np.min(gaps[nonactive_indices])) > settings.nonactive_contact_gap_strict_min_m
        )
        and float(np.min(validity)) >= settings.validity_normalized_margin_min
    )


def retract_to_manifold(
    assembly: P3R4ContactAssembly,
    reference_coordinates: object,
    active_indices: np.ndarray,
    tangent_basis: np.ndarray,
    target_tangent_coordinates: np.ndarray,
    scales: CharacteristicScales,
    settings: ManifoldRetractionSettings,
) -> ManifoldRetractionResult:
    """Solve active gaps, gauge and fixed tangent coordinates without fallback."""

    indices = np.asarray(active_indices, dtype=int)
    basis = np.asarray(tangent_basis, dtype=float)
    target = np.asarray(target_tangent_coordinates, dtype=float)
    reference_values = np.asarray(reference_coordinates.values, dtype=float)
    if indices.shape != (2,) or basis.shape != (6, 3) or target.shape != (3,):
        raise ValueError("P3R4 manifold retraction requires two constraints and three coordinates.")
    if not np.all(np.isfinite(reference_values)) or not np.all(np.isfinite(target)):
        raise ValueError("P3R4 manifold chart inputs must be finite.")
    values = reference_values + scales.coordinate_scales * (basis @ target)
    coordinates, evaluation, residual, jacobian = _residual_and_jacobian(
        assembly,
        values,
        reference_values,
        indices,
        basis,
        target,
        scales,
    )
    initial_residual = np.array(residual, copy=True)
    all_indices = np.arange(evaluation.contact.gaps_m.size)
    nonactive = np.setdiff1d(all_indices, indices, assume_unique=True)
    accepted_steps: list[float] = []
    relative_singular_values: list[float] = []
    total_backtracks = 0
    current_norm = float(np.linalg.norm(residual, ord=np.inf))
    if current_norm <= settings.convergence_infinity_max:
        return ManifoldRetractionResult(
            converged=True,
            status="CONVERGED_AT_ENTRY",
            iterations=0,
            total_backtracks=0,
            accepted_step_lengths=np.empty(0),
            linear_system_relative_singular_values=np.empty(0),
            target_tangent_coordinates=np.array(target, copy=True),
            initial_residual=initial_residual,
            final_residual=np.array(residual, copy=True),
            coordinates=coordinates,
            evaluation=evaluation,
        )
    for iteration in range(1, settings.maximum_newton_iterations + 1):
        singular = np.linalg.svd(jacobian, compute_uv=False)
        relative = float(singular[-1] / singular[0]) if singular[0] > 0.0 else 0.0
        relative_singular_values.append(relative)
        if relative < settings.linear_system_relative_singular_value_min:
            return ManifoldRetractionResult(
                converged=False,
                status="FAIL_CLOSED_LINEAR_SYSTEM",
                iterations=iteration - 1,
                total_backtracks=total_backtracks,
                accepted_step_lengths=np.asarray(accepted_steps),
                linear_system_relative_singular_values=np.asarray(relative_singular_values),
                target_tangent_coordinates=np.array(target, copy=True),
                initial_residual=initial_residual,
                final_residual=np.array(residual, copy=True),
                coordinates=coordinates,
                evaluation=evaluation,
            )
        direction = np.linalg.solve(jacobian, -residual)
        accepted = False
        for backtrack in range(settings.maximum_backtracks + 1):
            alpha = float(2.0 ** (-backtrack))
            candidate_values = values + alpha * scales.coordinate_scales * direction
            candidate = _residual_and_jacobian(
                assembly,
                candidate_values,
                reference_values,
                indices,
                basis,
                target,
                scales,
            )
            candidate_coordinates, candidate_evaluation, candidate_residual, candidate_jacobian = (
                candidate
            )
            candidate_norm = float(np.linalg.norm(candidate_residual, ord=np.inf))
            decrease = (1.0 - settings.armijo_coefficient * alpha) * current_norm
            if _domain_feasible(candidate_evaluation, nonactive, settings) and (
                candidate_norm <= decrease
            ):
                values = candidate_values
                coordinates = candidate_coordinates
                evaluation = candidate_evaluation
                residual = candidate_residual
                jacobian = candidate_jacobian
                current_norm = candidate_norm
                accepted_steps.append(alpha)
                total_backtracks += backtrack
                accepted = True
                break
        if not accepted:
            return ManifoldRetractionResult(
                converged=False,
                status="FAIL_CLOSED_NO_ACCEPTED_STEP",
                iterations=iteration - 1,
                total_backtracks=total_backtracks,
                accepted_step_lengths=np.asarray(accepted_steps),
                linear_system_relative_singular_values=np.asarray(relative_singular_values),
                target_tangent_coordinates=np.array(target, copy=True),
                initial_residual=initial_residual,
                final_residual=np.array(residual, copy=True),
                coordinates=coordinates,
                evaluation=evaluation,
            )
        if current_norm <= settings.convergence_infinity_max:
            return ManifoldRetractionResult(
                converged=True,
                status="CONVERGED",
                iterations=iteration,
                total_backtracks=total_backtracks,
                accepted_step_lengths=np.asarray(accepted_steps),
                linear_system_relative_singular_values=np.asarray(relative_singular_values),
                target_tangent_coordinates=np.array(target, copy=True),
                initial_residual=initial_residual,
                final_residual=np.array(residual, copy=True),
                coordinates=coordinates,
                evaluation=evaluation,
            )
    return ManifoldRetractionResult(
        converged=False,
        status="FAIL_CLOSED_ITERATION_LIMIT",
        iterations=settings.maximum_newton_iterations,
        total_backtracks=total_backtracks,
        accepted_step_lengths=np.asarray(accepted_steps),
        linear_system_relative_singular_values=np.asarray(relative_singular_values),
        target_tangent_coordinates=np.array(target, copy=True),
        initial_residual=initial_residual,
        final_residual=np.array(residual, copy=True),
        coordinates=coordinates,
        evaluation=evaluation,
    )


def _branch_correlations(
    reference_rows: np.ndarray,
    current_rows: np.ndarray,
    coordinate_scales: np.ndarray,
) -> np.ndarray:
    reference = reference_rows * coordinate_scales[None, :]
    current = current_rows * coordinate_scales[None, :]
    numerator = np.sum(reference * current, axis=1)
    denominator = np.linalg.norm(reference, axis=1) * np.linalg.norm(current, axis=1)
    return numerator / denominator


def _retraction_document(result: ManifoldRetractionResult) -> dict[str, Any]:
    return {
        "converged": result.converged,
        "status": result.status,
        "iterations": result.iterations,
        "total_backtracks": result.total_backtracks,
        "accepted_step_lengths": result.accepted_step_lengths,
        "linear_system_relative_singular_values": (result.linear_system_relative_singular_values),
        "target_tangent_coordinates": result.target_tangent_coordinates,
        "initial_residual": result.initial_residual,
        "final_residual": result.final_residual,
    }


def audit_manifold_neighborhood(
    assembly: P3R4ContactAssembly,
    reference_coordinates: object,
    reference_evaluation: object,
    supported_indices: np.ndarray,
    scales: CharacteristicScales,
    tangent_basis: np.ndarray,
    manifest: dict[str, Any],
) -> ManifoldNeighborhoodAudit:
    """Audit finite geometry and true potential only on retracted points."""

    source = manifest["manifold_neighborhood"]
    settings = settings_from_manifest(manifest)
    indices = np.asarray(supported_indices, dtype=int)
    basis = np.asarray(tangent_basis, dtype=float)
    if indices.shape != (2,) or basis.shape != (6, 3):
        raise ValueError("P3R4 manifold neighborhood requires two supports and three tangents.")
    radius = float(source["coordinate_radius_dimensionless"])
    fractions = tuple(float(value) for value in source["probe_radius_fractions"])
    directions = tangent_directions(basis)
    all_indices = np.arange(reference_evaluation.contact.gaps_m.size)
    nonactive = np.setdiff1d(all_indices, indices, assume_unique=True)
    reference_rows = reference_evaluation.contact.gap_jacobian[indices]
    reference_potential = float(reference_evaluation.total_potential)
    epsilon = float(np.finfo(float).eps)
    energy_safety = float(source["energy_roundoff_safety_factor"])
    records: list[dict[str, Any]] = []
    energy_margins: list[float] = []
    curvatures: list[float] = []
    for direction_id, direction in directions:
        tangent_direction = basis.T @ direction
        for fraction in fractions:
            layer_radius = radius * fraction
            endpoints: list[dict[str, Any]] = []
            endpoint_potentials: list[float] = []
            for sign in (-1.0, 1.0):
                target = sign * layer_radius * tangent_direction
                result = retract_to_manifold(
                    assembly,
                    reference_coordinates,
                    indices,
                    basis,
                    target,
                    scales,
                    settings,
                )
                evaluation = result.evaluation
                current_rows = evaluation.contact.gap_jacobian[indices]
                correlations = _branch_correlations(
                    reference_rows,
                    current_rows,
                    scales.coordinate_scales,
                )
                active_rank = matrix_rank(
                    current_rows,
                    float(manifest["kkt"]["rank_relative_tolerance"]),
                )
                nonactive_minimum = (
                    float(np.min(evaluation.contact.gaps_m[nonactive]))
                    if nonactive.size
                    else float("inf")
                )
                validity_minimum = float(np.min(evaluation.validity.normalized_residuals))
                active_gap_maximum = float(np.max(np.abs(evaluation.contact.gaps_m[indices])))
                energy_increase = float(evaluation.total_potential - reference_potential)
                normalized_increase = energy_increase / scales.energy_N_m
                roundoff = (
                    energy_safety
                    * epsilon
                    * (abs(float(evaluation.total_potential)) + abs(reference_potential))
                    / scales.energy_N_m
                )
                energy_margin = normalized_increase - roundoff
                energy_margins.append(energy_margin)
                endpoint_potentials.append(float(evaluation.total_potential))
                finite = bool(
                    np.all(np.isfinite(result.coordinates.values))
                    and np.all(np.isfinite(evaluation.contact.gaps_m))
                    and np.all(np.isfinite(evaluation.validity.normalized_residuals))
                    and np.all(np.isfinite(correlations))
                )
                passed = bool(
                    result.converged
                    and finite
                    and active_gap_maximum
                    <= float(source["active_gap_absolute_max_length_scale_fraction"])
                    * scales.length_m
                    and float(np.linalg.norm(result.final_residual[2:], ord=np.inf))
                    <= float(source["tangent_and_gauge_absolute_max"])
                    and active_rank == int(source["required_active_rank"])
                    and float(np.min(correlations))
                    > float(source["branch_orientation_correlation_strict_min"])
                    and nonactive_minimum > float(source["nonactive_contact_gap_strict_min_m"])
                    and validity_minimum >= float(source["validity_normalized_margin_min"])
                    and energy_margin
                    > float(source["true_potential_increase_minus_roundoff_strict_min"])
                )
                endpoints.append(
                    {
                        "sign": sign,
                        "probe_role": "constraint_manifold_geometry_probe",
                        "retraction": _retraction_document(result),
                        "coordinates": result.coordinates.values,
                        "finite": finite,
                        "active_gap_maximum_absolute_m": active_gap_maximum,
                        "supported_rank": active_rank,
                        "branch_orientation_correlations": correlations,
                        "minimum_nonactive_gap_m": nonactive_minimum,
                        "minimum_validity_normalized_residual": validity_minimum,
                        "true_potential_J": float(evaluation.total_potential),
                        "true_potential_increase_normalized": normalized_increase,
                        "true_potential_roundoff_bound": roundoff,
                        "true_potential_increase_margin": energy_margin,
                        "passed": passed,
                    }
                )
            curvature = (
                endpoint_potentials[1] - 2.0 * reference_potential + endpoint_potentials[0]
            ) / (layer_radius**2 * scales.energy_N_m)
            curvatures.append(float(curvature))
            curvature_passed = bool(
                curvature > float(source["symmetric_true_potential_curvature_strict_min"])
            )
            records.append(
                {
                    "direction_id": direction_id,
                    "radius_fraction": fraction,
                    "dimensionless_radius": layer_radius,
                    "endpoints": endpoints,
                    "symmetric_true_potential_curvature": float(curvature),
                    "curvature_passed": curvature_passed,
                    "passed": bool(
                        all(endpoint["passed"] for endpoint in endpoints) and curvature_passed
                    ),
                }
            )
    passed = all(record["passed"] for record in records)
    return ManifoldNeighborhoodAudit(
        identity=P3R4_MANIFOLD_RETRACTION_ID,
        passed=passed,
        dimensionless_radius=radius,
        tangent_basis=np.array(basis, copy=True),
        direction_count_unoriented=len(directions),
        endpoint_retraction_count=2 * len(directions) * len(fractions),
        records=tuple(records),
        minimum_true_potential_increase_margin=float(min(energy_margins)),
        minimum_symmetric_true_potential_curvature=float(min(curvatures)),
    )


__all__ = [
    "ManifoldNeighborhoodAudit",
    "ManifoldRetractionResult",
    "ManifoldRetractionSettings",
    "audit_manifold_neighborhood",
    "retract_to_manifold",
    "settings_from_manifest",
]
