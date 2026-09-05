"""P3R contact KKT audit with weak activity and dual-force intervals."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog, nnls

from ypendulum_hfv2.audit.statics import force_scale

from .assembly import P3RContactAssembly, P3RContactEvaluation


def matrix_rank(matrix: np.ndarray, relative_tolerance: float) -> int:
    values = np.asarray(matrix, dtype=float)
    if values.size == 0:
        return 0
    singular = np.linalg.svd(values, compute_uv=False)
    if singular.size == 0 or singular[0] == 0.0:
        return 0
    return int(np.count_nonzero(singular > relative_tolerance * singular[0]))


@dataclass(frozen=True)
class P3RKKTThresholds:
    near_active_gap_max_m: float
    primal_penetration_max_m: float
    dual_negative_max_N: float
    stationarity_absolute_max_N: float
    stationarity_force_scale_factor_max: float
    complementarity_absolute_max_N_m: float
    complementarity_energy_scale_factor_max: float
    supported_multiplier_min_N: float
    rank_relative_tolerance: float
    dual_interval_nonunique_width_N: float

    def __post_init__(self) -> None:
        values = np.asarray(list(self.__dict__.values()), dtype=float)
        if not np.all(np.isfinite(values)) or np.any(values < 0.0):
            raise ValueError("P3R KKT thresholds must be finite and non-negative.")
        if self.near_active_gap_max_m <= 0.0 or self.rank_relative_tolerance <= 0.0:
            raise ValueError("Near-active gap and rank tolerances must be strictly positive.")


@dataclass(frozen=True)
class P3RKKTAudit:
    passed: bool
    finite: bool
    force_scale_N: float
    energy_scale_N_m: float
    near_active_indices: np.ndarray
    supported_indices: np.ndarray
    weak_active_indices: np.ndarray
    possible_supported_indices: np.ndarray
    mandatory_supported_indices: np.ndarray
    near_active_rank: int
    supported_rank: int
    canonical_multipliers_N: np.ndarray
    dual_interval_lower_N: np.ndarray
    dual_interval_upper_N: np.ndarray
    dual_interval_feasible: bool
    dual_nonunique: bool
    stationarity_vector_N: np.ndarray
    primal_violation_m: float
    dual_violation_N: float
    stationarity_residual_N: float
    stationarity_limit_N: float
    complementarity_residual_N_m: float
    complementarity_limit_N_m: float


def _dual_intervals(
    gradient: np.ndarray,
    active_jacobian: np.ndarray,
    stationarity_limit: float,
) -> tuple[np.ndarray, np.ndarray, bool]:
    count = active_jacobian.shape[0]
    if count == 0:
        return np.empty(0), np.empty(0), True
    transpose = active_jacobian.T
    upper_matrix = np.vstack([transpose, -transpose])
    upper_vector = np.concatenate(
        [gradient + stationarity_limit, -gradient + stationarity_limit]
    )
    bounds = [(0.0, None)] * count
    feasibility = linprog(
        np.zeros(count),
        A_ub=upper_matrix,
        b_ub=upper_vector,
        bounds=bounds,
        method="highs",
    )
    if not feasibility.success:
        return np.full(count, np.nan), np.full(count, np.nan), False
    lower = np.empty(count)
    upper = np.empty(count)
    for index in range(count):
        objective = np.zeros(count)
        objective[index] = 1.0
        minimum = linprog(
            objective,
            A_ub=upper_matrix,
            b_ub=upper_vector,
            bounds=bounds,
            method="highs",
        )
        lower[index] = float(minimum.fun) if minimum.success else np.nan
        maximum = linprog(
            -objective,
            A_ub=upper_matrix,
            b_ub=upper_vector,
            bounds=bounds,
            method="highs",
        )
        if maximum.status == 3:
            upper[index] = float("inf")
        else:
            upper[index] = float(-maximum.fun) if maximum.success else np.nan
    return lower, upper, bool(np.all(np.isfinite(lower)) and np.all(~np.isnan(upper)))


def audit_kkt_arrays(
    *,
    gradient_N: np.ndarray,
    gaps_m: np.ndarray,
    gap_jacobian: np.ndarray,
    force_scale_N: float,
    energy_scale_N_m: float,
    thresholds: P3RKKTThresholds,
) -> P3RKKTAudit:
    gradient = np.asarray(gradient_N, dtype=float)
    gaps = np.asarray(gaps_m, dtype=float)
    jacobian = np.asarray(gap_jacobian, dtype=float)
    if gradient.ndim != 1 or gaps.ndim != 1 or jacobian.shape != (gaps.size, gradient.size):
        raise ValueError("P3R KKT arrays have incompatible dimensions.")
    near_active = np.flatnonzero(gaps <= thresholds.near_active_gap_max_m)
    multipliers = np.zeros(gaps.size)
    if near_active.size:
        active_multipliers, _ = nnls(jacobian[near_active].T, gradient)
        multipliers[near_active] = active_multipliers
    supported = near_active[
        multipliers[near_active] > thresholds.supported_multiplier_min_N
    ]
    weak = np.setdiff1d(near_active, supported, assume_unique=True)
    stationarity = gradient - jacobian.T @ multipliers
    stationarity_limit = max(
        thresholds.stationarity_absolute_max_N,
        thresholds.stationarity_force_scale_factor_max * float(force_scale_N),
    )
    complementarity_limit = max(
        thresholds.complementarity_absolute_max_N_m,
        thresholds.complementarity_energy_scale_factor_max * float(energy_scale_N_m),
    )
    active_lower, active_upper, intervals_feasible = _dual_intervals(
        gradient,
        jacobian[near_active],
        stationarity_limit,
    )
    lower = np.zeros(gaps.size)
    upper = np.zeros(gaps.size)
    lower[near_active] = active_lower
    upper[near_active] = active_upper
    possible = near_active[active_upper > thresholds.supported_multiplier_min_N]
    mandatory = near_active[active_lower > thresholds.supported_multiplier_min_N]
    finite = bool(
        np.all(np.isfinite(gradient))
        and np.all(np.isfinite(gaps))
        and np.all(np.isfinite(jacobian))
        and np.all(np.isfinite(multipliers))
        and np.all(np.isfinite(stationarity))
        and np.all(np.isfinite(lower))
        and np.all(~np.isnan(upper))
    )
    primal = max(0.0, -float(np.min(gaps))) if gaps.size else 0.0
    dual = max(0.0, -float(np.min(multipliers))) if multipliers.size else 0.0
    stationarity_residual = float(np.linalg.norm(stationarity, ord=np.inf))
    complementarity = float(np.max(np.abs(multipliers * gaps))) if gaps.size else 0.0
    active_rank = matrix_rank(jacobian[near_active], thresholds.rank_relative_tolerance)
    supported_rank = matrix_rank(jacobian[supported], thresholds.rank_relative_tolerance)
    widths = active_upper - active_lower
    nonunique = bool(
        np.any(~np.isfinite(widths))
        or np.any(widths > thresholds.dual_interval_nonunique_width_N)
    )
    passed = bool(
        finite
        and intervals_feasible
        and primal <= thresholds.primal_penetration_max_m
        and dual <= thresholds.dual_negative_max_N
        and stationarity_residual <= stationarity_limit
        and complementarity <= complementarity_limit
        and supported_rank == supported.size
    )
    return P3RKKTAudit(
        passed=passed,
        finite=finite,
        force_scale_N=float(force_scale_N),
        energy_scale_N_m=float(energy_scale_N_m),
        near_active_indices=np.array(near_active, copy=True),
        supported_indices=np.array(supported, copy=True),
        weak_active_indices=np.array(weak, copy=True),
        possible_supported_indices=np.array(possible, copy=True),
        mandatory_supported_indices=np.array(mandatory, copy=True),
        near_active_rank=active_rank,
        supported_rank=supported_rank,
        canonical_multipliers_N=np.array(multipliers, copy=True),
        dual_interval_lower_N=np.array(lower, copy=True),
        dual_interval_upper_N=np.array(upper, copy=True),
        dual_interval_feasible=intervals_feasible,
        dual_nonunique=nonunique,
        stationarity_vector_N=np.array(stationarity, copy=True),
        primal_violation_m=primal,
        dual_violation_N=dual,
        stationarity_residual_N=stationarity_residual,
        stationarity_limit_N=stationarity_limit,
        complementarity_residual_N_m=complementarity,
        complementarity_limit_N_m=complementarity_limit,
    )


def audit_contact_kkt(
    assembly: P3RContactAssembly,
    evaluation: P3RContactEvaluation,
    thresholds: P3RKKTThresholds,
) -> P3RKKTAudit:
    scale = force_scale(assembly.base_assembly)
    return audit_kkt_arrays(
        gradient_N=-evaluation.generalized_force,
        gaps_m=evaluation.contact.gaps_m,
        gap_jacobian=evaluation.contact.gap_jacobian,
        force_scale_N=scale,
        energy_scale_N_m=scale,
        thresholds=thresholds,
    )
