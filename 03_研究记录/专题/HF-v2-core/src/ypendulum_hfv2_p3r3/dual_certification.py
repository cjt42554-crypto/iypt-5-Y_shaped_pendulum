"""Centered dimensionless dual witness and independent interval certification."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np
from scipy.optimize import linprog

from ypendulum_hfv2_p3r2.kkt import (
    P3R2KKTAudit as P3R3KKTAudit,
)
from ypendulum_hfv2_p3r2.kkt import (
    P3R2KKTThresholds as P3R3KKTThresholds,
)
from ypendulum_hfv2_p3r2.kkt import (
    audit_contact_kkt as _audit_contact_kkt,
)
from ypendulum_hfv2_p3r2.kkt import (
    component_allowed_raw,
    thresholds_from_manifest,
)

from .assembly import P3R3ContactAssembly
from .certification import CharacteristicScales


@dataclass(frozen=True)
class DualBackendCall:
    purpose: str
    success: bool
    status: int
    message: str
    iterations: int
    objective_value: float
    centered_solution: np.ndarray
    minimum_backend_slack: float


@dataclass(frozen=True)
class P3R3DualCertificate:
    passed: bool
    status: str
    active_indices: np.ndarray
    canonical_active_multipliers_N: np.ndarray
    centered_matrix: np.ndarray
    scaled_gradient: np.ndarray
    scaled_allowed: np.ndarray
    witness_eta: np.ndarray
    witness_scaled_residual: np.ndarray
    witness_upper_slack: np.ndarray
    witness_lower_slack: np.ndarray
    witness_multiplier_slack: np.ndarray
    witness_minimum_slack: float
    backend_feasibility: DualBackendCall
    backend_endpoint_calls: tuple[DualBackendCall, ...]
    backend_lower_N: np.ndarray
    backend_upper_N: np.ndarray
    independent_vertex_count: int
    independent_lower_N: np.ndarray
    independent_upper_N: np.ndarray
    endpoint_crosscheck_max_N: float
    endpoint_minimum_slack: float
    interval_maximum_width_N: float
    interval_width_passed: bool


def audit_contact_kkt(
    assembly: P3R3ContactAssembly,
    evaluation: object,
    thresholds: P3R3KKTThresholds,
    scales: CharacteristicScales | None = None,
) -> P3R3KKTAudit:
    """Apply the inherited component-scaled KKT audit to the P3R3 identity."""

    return _audit_contact_kkt(assembly, evaluation, thresholds, scales)


def _backend_call(
    purpose: str,
    objective: np.ndarray,
    upper_matrix: np.ndarray,
    upper_vector: np.ndarray,
    *,
    primal_tolerance: float,
    dual_tolerance: float,
) -> tuple[DualBackendCall, object]:
    result = linprog(
        objective,
        A_ub=upper_matrix,
        b_ub=upper_vector,
        bounds=[(None, None)] * objective.size,
        method="highs-ds",
        options={
            "presolve": True,
            "primal_feasibility_tolerance": primal_tolerance,
            "dual_feasibility_tolerance": dual_tolerance,
        },
    )
    solution = (
        np.asarray(result.x, dtype=float)
        if result.x is not None
        else np.full(objective.size, np.nan)
    )
    slack = (
        upper_vector - upper_matrix @ solution
        if np.all(np.isfinite(solution))
        else np.full(upper_vector.size, np.nan)
    )
    minimum_slack = float(np.min(slack)) if np.all(np.isfinite(slack)) else float("nan")
    call = DualBackendCall(
        purpose=purpose,
        success=bool(result.success),
        status=int(result.status),
        message=str(result.message),
        iterations=int(result.nit),
        objective_value=(float(result.fun) if result.fun is not None else float("nan")),
        centered_solution=np.array(solution, copy=True),
        minimum_backend_slack=minimum_slack,
    )
    return call, result


def _independent_vertices(
    matrix: np.ndarray,
    gradient: np.ndarray,
    allowed: np.ndarray,
    *,
    feasibility_tolerance: float,
) -> np.ndarray:
    count = matrix.shape[1]
    if count != 2:
        raise ValueError("Independent P3R3 endpoint enumeration requires two multipliers.")
    halfspace_matrix = np.vstack([-matrix, matrix, -np.eye(count)])
    halfspace_vector = np.concatenate([allowed - gradient, allowed + gradient, np.zeros(count)])
    vertices: list[np.ndarray] = []
    for first, second in combinations(range(halfspace_matrix.shape[0]), 2):
        rows = halfspace_matrix[[first, second]]
        determinant = float(np.linalg.det(rows))
        scale = max(float(np.linalg.norm(rows[0]) * np.linalg.norm(rows[1])), 1.0)
        if abs(determinant) <= 128.0 * np.finfo(float).eps * scale:
            continue
        candidate = np.linalg.solve(rows, halfspace_vector[[first, second]])
        if not np.all(np.isfinite(candidate)):
            continue
        if float(np.max(halfspace_matrix @ candidate - halfspace_vector)) > (feasibility_tolerance):
            continue
        if any(float(np.linalg.norm(candidate - item, ord=np.inf)) <= 1.0e-11 for item in vertices):
            continue
        vertices.append(candidate)
    return np.vstack(vertices) if vertices else np.empty((0, count))


def _minimum_original_slack(
    matrix: np.ndarray,
    gradient: np.ndarray,
    allowed: np.ndarray,
    eta: np.ndarray,
) -> float:
    residual = gradient - matrix @ eta
    slacks = np.concatenate([allowed - residual, allowed + residual, eta])
    return float(np.min(slacks))


def certify_centered_dual(
    evaluation: object,
    active_indices: np.ndarray,
    canonical_multipliers_N: np.ndarray,
    scales: CharacteristicScales,
    allowed_raw: np.ndarray,
    manifest: dict[str, Any],
) -> P3R3DualCertificate:
    """Certify one explicit witness and all two-contact interval endpoints."""

    indices = np.asarray(active_indices, dtype=int)
    canonical = np.asarray(canonical_multipliers_N, dtype=float)
    allowed_raw_array = np.asarray(allowed_raw, dtype=float)
    gaps = np.asarray(evaluation.contact.gaps_m, dtype=float)
    jacobian = np.asarray(evaluation.contact.gap_jacobian, dtype=float)
    gradient_raw = -np.asarray(evaluation.generalized_force, dtype=float)
    if indices.shape != (2,):
        raise ValueError("The P3R3 dual certifier requires exactly two active contacts.")
    if canonical.shape != gaps.shape:
        raise ValueError("Canonical multipliers must match all physical contacts.")
    if allowed_raw_array.shape != gradient_raw.shape:
        raise ValueError("The component allowed band must match stationarity.")
    if not (
        np.all(np.isfinite(jacobian))
        and np.all(np.isfinite(gradient_raw))
        and np.all(np.isfinite(canonical))
        and np.all(np.isfinite(allowed_raw_array))
    ):
        raise ValueError("The P3R3 dual inputs must all be finite.")
    source = manifest["dual_certification"]
    witness_tolerance = float(source["canonical_witness_minimum_slack_dimensionless"])
    endpoint_tolerance = float(source["endpoint_minimum_slack_dimensionless"])
    crosscheck_tolerance_N = float(source["endpoint_crosscheck_absolute_max_N"])
    primal_tolerance = float(source["primal_feasibility_tolerance"])
    dual_tolerance = float(source["dual_feasibility_tolerance"])

    matrix = (jacobian[indices].T * scales.force_N) / scales.stationarity_scales[:, None]
    gradient = gradient_raw / scales.stationarity_scales
    allowed = allowed_raw_array / scales.stationarity_scales
    eta_zero = canonical[indices] / scales.force_N
    residual_zero = gradient - matrix @ eta_zero
    upper_slack = allowed - residual_zero
    lower_slack = allowed + residual_zero
    multiplier_slack = np.array(eta_zero, copy=True)
    witness_minimum = float(np.min(np.concatenate([upper_slack, lower_slack, multiplier_slack])))
    upper_matrix = np.vstack([-matrix, matrix, -np.eye(indices.size)])
    upper_vector = np.concatenate([upper_slack, lower_slack, eta_zero])
    feasibility_call, _ = _backend_call(
        "feasibility",
        np.zeros(indices.size),
        upper_matrix,
        upper_vector,
        primal_tolerance=primal_tolerance,
        dual_tolerance=dual_tolerance,
    )

    endpoint_calls: list[DualBackendCall] = []
    lower_eta = np.full(indices.size, np.nan)
    upper_eta = np.full(indices.size, np.nan)
    endpoint_eta: list[np.ndarray] = []
    if feasibility_call.success:
        for index in range(indices.size):
            objective = np.zeros(indices.size)
            objective[index] = 1.0
            minimum_call, minimum = _backend_call(
                f"minimum_eta_{index}",
                objective,
                upper_matrix,
                upper_vector,
                primal_tolerance=primal_tolerance,
                dual_tolerance=dual_tolerance,
            )
            endpoint_calls.append(minimum_call)
            if minimum_call.success:
                eta = eta_zero + np.asarray(minimum.x, dtype=float)
                lower_eta[index] = eta[index]
                endpoint_eta.append(eta)
            maximum_call, maximum = _backend_call(
                f"maximum_eta_{index}",
                -objective,
                upper_matrix,
                upper_vector,
                primal_tolerance=primal_tolerance,
                dual_tolerance=dual_tolerance,
            )
            endpoint_calls.append(maximum_call)
            if maximum_call.success:
                eta = eta_zero + np.asarray(maximum.x, dtype=float)
                upper_eta[index] = eta[index]
                endpoint_eta.append(eta)

    vertices = _independent_vertices(
        matrix,
        gradient,
        allowed,
        feasibility_tolerance=max(abs(endpoint_tolerance), primal_tolerance),
    )
    if vertices.size:
        independent_lower_eta = np.min(vertices, axis=0)
        independent_upper_eta = np.max(vertices, axis=0)
    else:
        independent_lower_eta = np.full(indices.size, np.nan)
        independent_upper_eta = np.full(indices.size, np.nan)
    backend_lower_N = lower_eta * scales.force_N
    backend_upper_N = upper_eta * scales.force_N
    independent_lower_N = independent_lower_eta * scales.force_N
    independent_upper_N = independent_upper_eta * scales.force_N
    endpoint_arrays = (
        backend_lower_N,
        backend_upper_N,
        independent_lower_N,
        independent_upper_N,
    )
    endpoints_finite = all(np.all(np.isfinite(item)) for item in endpoint_arrays)
    if endpoints_finite:
        crosscheck = float(
            max(
                np.max(np.abs(backend_lower_N - independent_lower_N)),
                np.max(np.abs(backend_upper_N - independent_upper_N)),
            )
        )
        widths = backend_upper_N - backend_lower_N
        interval_width = float(np.max(widths))
    else:
        crosscheck = float("inf")
        interval_width = float("inf")
    independent_endpoint_eta = []
    if vertices.size:
        for index in range(indices.size):
            independent_endpoint_eta.append(vertices[int(np.argmin(vertices[:, index]))])
            independent_endpoint_eta.append(vertices[int(np.argmax(vertices[:, index]))])
    all_endpoints = endpoint_eta + independent_endpoint_eta
    endpoint_minimum = (
        min(_minimum_original_slack(matrix, gradient, allowed, eta) for eta in all_endpoints)
        if all_endpoints
        else float("-inf")
    )
    endpoint_calls_pass = bool(
        len(endpoint_calls) == 2 * indices.size and all(call.success for call in endpoint_calls)
    )
    interval_width_passed = bool(
        interval_width <= float(manifest["kkt"]["qualification_dual_interval_width_max_N"])
    )
    explicit_witness_feasible = witness_minimum >= witness_tolerance
    if explicit_witness_feasible and not feasibility_call.success:
        status = "CERTIFIER_INTERNAL_INCONSISTENCY"
    elif not explicit_witness_feasible:
        status = "DUAL_WITNESS_INVALID"
    elif not feasibility_call.success or not endpoint_calls_pass or not vertices.size:
        status = "DUAL_ENDPOINT_FAILURE"
    elif crosscheck > crosscheck_tolerance_N or endpoint_minimum < endpoint_tolerance:
        status = "CERTIFIER_INTERNAL_INCONSISTENCY"
    elif not interval_width_passed:
        status = "DUAL_INTERVAL_TOO_WIDE"
    else:
        status = "PASS"
    return P3R3DualCertificate(
        passed=status == "PASS",
        status=status,
        active_indices=np.array(indices, copy=True),
        canonical_active_multipliers_N=np.array(canonical[indices], copy=True),
        centered_matrix=np.array(matrix, copy=True),
        scaled_gradient=np.array(gradient, copy=True),
        scaled_allowed=np.array(allowed, copy=True),
        witness_eta=np.array(eta_zero, copy=True),
        witness_scaled_residual=np.array(residual_zero, copy=True),
        witness_upper_slack=np.array(upper_slack, copy=True),
        witness_lower_slack=np.array(lower_slack, copy=True),
        witness_multiplier_slack=np.array(multiplier_slack, copy=True),
        witness_minimum_slack=witness_minimum,
        backend_feasibility=feasibility_call,
        backend_endpoint_calls=tuple(endpoint_calls),
        backend_lower_N=np.array(backend_lower_N, copy=True),
        backend_upper_N=np.array(backend_upper_N, copy=True),
        independent_vertex_count=int(vertices.shape[0]),
        independent_lower_N=np.array(independent_lower_N, copy=True),
        independent_upper_N=np.array(independent_upper_N, copy=True),
        endpoint_crosscheck_max_N=crosscheck,
        endpoint_minimum_slack=float(endpoint_minimum),
        interval_maximum_width_N=interval_width,
        interval_width_passed=interval_width_passed,
    )


__all__ = [
    "DualBackendCall",
    "P3R3DualCertificate",
    "P3R3KKTAudit",
    "P3R3KKTThresholds",
    "audit_contact_kkt",
    "certify_centered_dual",
    "component_allowed_raw",
    "thresholds_from_manifest",
]
