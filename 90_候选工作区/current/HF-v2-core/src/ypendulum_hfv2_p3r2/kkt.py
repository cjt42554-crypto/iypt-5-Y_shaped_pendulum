"""Component-scaled P3R2 KKT, NNLS and dual-interval certification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import linprog

from ypendulum_hfv2_p3r.kkt import matrix_rank

from .assembly import P3R2ContactAssembly
from .certification import (
    COORDINATE_IDS,
    STATIONARITY_UNITS,
    CharacteristicScales,
    characteristic_scales,
    scaled_canonical_multipliers,
)


@dataclass(frozen=True)
class P3R2KKTThresholds:
    near_active_gap_max_m: float
    primal_penetration_max_m: float
    dual_negative_max_N: float
    supported_multiplier_min_N: float
    rank_relative_tolerance: float
    complementarity_absolute_max_N_m: float
    complementarity_energy_scale_factor_max: float
    dual_interval_nonunique_width_N: float
    legacy_mixed_infinity_max: float
    translation_absolute_max_N: float
    rotation_absolute_force_times_length_factor: float
    dimensionless_component_max: float

    def __post_init__(self) -> None:
        values = np.asarray(list(self.__dict__.values()), dtype=float)
        if not np.all(np.isfinite(values)) or np.any(values < 0.0):
            raise ValueError("P3R2 KKT thresholds must be finite and non-negative.")
        if self.near_active_gap_max_m <= 0.0 or self.rank_relative_tolerance <= 0.0:
            raise ValueError("P3R2 activity and rank thresholds must be positive.")


@dataclass(frozen=True)
class P3R2KKTAudit:
    passed: bool
    finite: bool
    scales: CharacteristicScales
    coordinate_ids: tuple[str, ...]
    stationarity_units: tuple[str, ...]
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
    translation_force_residual_N: np.ndarray
    rotation_torque_residual_N_m: np.ndarray
    dimensionless_stationarity: np.ndarray
    component_allowed_raw: np.ndarray
    primal_violation_m: float
    dual_violation_N: float
    stationarity_residual_N: float
    stationarity_limit_N: float
    translation_force_infinity_N: float
    rotation_torque_infinity_N_m: float
    dimensionless_stationarity_infinity: float
    legacy_stationarity_passed: bool
    translation_stationarity_passed: bool
    rotation_stationarity_passed: bool
    dimensionless_stationarity_passed: bool
    complementarity_residual_N_m: float
    complementarity_limit_N_m: float


def thresholds_from_manifest(manifest: dict[str, Any]) -> P3R2KKTThresholds:
    kkt = manifest["kkt"]
    component = manifest["component_scale_contract"]
    return P3R2KKTThresholds(
        near_active_gap_max_m=float(kkt["near_active_gap_max_m"]),
        primal_penetration_max_m=float(kkt["primal_penetration_max_m"]),
        dual_negative_max_N=float(kkt["dual_negative_max_N"]),
        supported_multiplier_min_N=float(kkt["supported_multiplier_min_N"]),
        rank_relative_tolerance=float(kkt["rank_relative_tolerance"]),
        complementarity_absolute_max_N_m=float(
            kkt["complementarity_absolute_max_N_m"]
        ),
        complementarity_energy_scale_factor_max=float(
            kkt["complementarity_energy_scale_factor_max"]
        ),
        dual_interval_nonunique_width_N=float(
            kkt["dual_interval_nonunique_width_N"]
        ),
        legacy_mixed_infinity_max=float(component["legacy_mixed_infinity_max"]),
        translation_absolute_max_N=float(
            component["translation_absolute_max_N"]
        ),
        rotation_absolute_force_times_length_factor=float(
            component["rotation_absolute_force_times_length_factor"]
        ),
        dimensionless_component_max=float(
            component["dimensionless_component_max"]
        ),
    )


def component_allowed_raw(
    scales: CharacteristicScales,
    thresholds: P3R2KKTThresholds,
) -> np.ndarray:
    absolute = np.array(
        [
            thresholds.translation_absolute_max_N,
            thresholds.translation_absolute_max_N,
            thresholds.translation_absolute_max_N,
            thresholds.rotation_absolute_force_times_length_factor * scales.length_m,
            thresholds.rotation_absolute_force_times_length_factor * scales.length_m,
            thresholds.rotation_absolute_force_times_length_factor * scales.length_m,
        ]
    )
    dimensionless = (
        thresholds.dimensionless_component_max * scales.stationarity_scales
    )
    return np.minimum(absolute, dimensionless)


def _dual_intervals(
    gradient: np.ndarray,
    active_jacobian: np.ndarray,
    allowed_raw: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, bool]:
    count = active_jacobian.shape[0]
    if count == 0:
        return np.empty(0), np.empty(0), True
    transpose = active_jacobian.T
    upper_matrix = np.vstack([transpose, -transpose])
    upper_vector = np.concatenate(
        [gradient + allowed_raw, -gradient + allowed_raw]
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
    feasible = bool(np.all(np.isfinite(lower)) and np.all(~np.isnan(upper)))
    return lower, upper, feasible


def audit_kkt_arrays(
    *,
    gradient: np.ndarray,
    gaps_m: np.ndarray,
    gap_jacobian: np.ndarray,
    scales: CharacteristicScales,
    thresholds: P3R2KKTThresholds,
) -> P3R2KKTAudit:
    gradient_array = np.asarray(gradient, dtype=float)
    gaps = np.asarray(gaps_m, dtype=float)
    jacobian = np.asarray(gap_jacobian, dtype=float)
    if (
        gradient_array.shape != (6,)
        or gaps.ndim != 1
        or jacobian.shape != (gaps.size, 6)
    ):
        raise ValueError("P3R2 KKT arrays have incompatible dimensions.")
    near = np.flatnonzero(gaps <= thresholds.near_active_gap_max_m)

    class _Contact:
        gaps_m = gaps
        gap_jacobian = jacobian

    class _Evaluation:
        contact = _Contact()
        generalized_force = -gradient_array

    multipliers = scaled_canonical_multipliers(_Evaluation(), near, scales)
    supported = near[multipliers[near] > thresholds.supported_multiplier_min_N]
    weak = np.setdiff1d(near, supported, assume_unique=True)
    stationarity = gradient_array - jacobian.T @ multipliers
    allowed = component_allowed_raw(scales, thresholds)
    active_lower, active_upper, intervals_feasible = _dual_intervals(
        gradient_array,
        jacobian[near],
        allowed,
    )
    lower = np.zeros(gaps.size)
    upper = np.zeros(gaps.size)
    lower[near] = active_lower
    upper[near] = active_upper
    possible = near[active_upper > thresholds.supported_multiplier_min_N]
    mandatory = near[active_lower > thresholds.supported_multiplier_min_N]
    primal = max(0.0, -float(np.min(gaps))) if gaps.size else 0.0
    dual = max(0.0, -float(np.min(multipliers))) if multipliers.size else 0.0
    legacy = float(np.linalg.norm(stationarity, ord=np.inf))
    translation = np.array(stationarity[:3], copy=True)
    rotation = np.array(stationarity[3:], copy=True)
    dimensionless = stationarity / scales.stationarity_scales
    translation_infinity = float(np.linalg.norm(translation, ord=np.inf))
    rotation_infinity = float(np.linalg.norm(rotation, ord=np.inf))
    dimensionless_infinity = float(np.linalg.norm(dimensionless, ord=np.inf))
    complementarity = float(np.max(np.abs(multipliers * gaps))) if gaps.size else 0.0
    complementarity_limit = max(
        thresholds.complementarity_absolute_max_N_m,
        thresholds.complementarity_energy_scale_factor_max * scales.energy_N_m,
    )
    near_rank = matrix_rank(jacobian[near], thresholds.rank_relative_tolerance)
    supported_rank = matrix_rank(
        jacobian[supported],
        thresholds.rank_relative_tolerance,
    )
    widths = active_upper - active_lower
    nonunique = bool(
        np.any(~np.isfinite(widths))
        or np.any(widths > thresholds.dual_interval_nonunique_width_N)
    )
    finite = bool(
        np.all(np.isfinite(gradient_array))
        and np.all(np.isfinite(gaps))
        and np.all(np.isfinite(jacobian))
        and np.all(np.isfinite(multipliers))
        and np.all(np.isfinite(stationarity))
        and np.all(np.isfinite(lower))
        and np.all(~np.isnan(upper))
    )
    legacy_passed = legacy <= thresholds.legacy_mixed_infinity_max
    translation_passed = (
        translation_infinity <= thresholds.translation_absolute_max_N
    )
    rotation_passed = rotation_infinity <= (
        thresholds.rotation_absolute_force_times_length_factor * scales.length_m
    )
    dimensionless_passed = (
        dimensionless_infinity <= thresholds.dimensionless_component_max
    )
    passed = bool(
        finite
        and intervals_feasible
        and primal <= thresholds.primal_penetration_max_m
        and dual <= thresholds.dual_negative_max_N
        and legacy_passed
        and translation_passed
        and rotation_passed
        and dimensionless_passed
        and complementarity <= complementarity_limit
        and supported_rank == supported.size
    )
    return P3R2KKTAudit(
        passed=passed,
        finite=finite,
        scales=scales,
        coordinate_ids=COORDINATE_IDS,
        stationarity_units=STATIONARITY_UNITS,
        near_active_indices=np.array(near, copy=True),
        supported_indices=np.array(supported, copy=True),
        weak_active_indices=np.array(weak, copy=True),
        possible_supported_indices=np.array(possible, copy=True),
        mandatory_supported_indices=np.array(mandatory, copy=True),
        near_active_rank=near_rank,
        supported_rank=supported_rank,
        canonical_multipliers_N=np.array(multipliers, copy=True),
        dual_interval_lower_N=np.array(lower, copy=True),
        dual_interval_upper_N=np.array(upper, copy=True),
        dual_interval_feasible=intervals_feasible,
        dual_nonunique=nonunique,
        stationarity_vector_N=np.array(stationarity, copy=True),
        translation_force_residual_N=translation,
        rotation_torque_residual_N_m=rotation,
        dimensionless_stationarity=np.array(dimensionless, copy=True),
        component_allowed_raw=np.array(allowed, copy=True),
        primal_violation_m=primal,
        dual_violation_N=dual,
        stationarity_residual_N=legacy,
        stationarity_limit_N=thresholds.legacy_mixed_infinity_max,
        translation_force_infinity_N=translation_infinity,
        rotation_torque_infinity_N_m=rotation_infinity,
        dimensionless_stationarity_infinity=dimensionless_infinity,
        legacy_stationarity_passed=legacy_passed,
        translation_stationarity_passed=translation_passed,
        rotation_stationarity_passed=rotation_passed,
        dimensionless_stationarity_passed=dimensionless_passed,
        complementarity_residual_N_m=complementarity,
        complementarity_limit_N_m=complementarity_limit,
    )


def audit_contact_kkt(
    assembly: P3R2ContactAssembly,
    evaluation: object,
    thresholds: P3R2KKTThresholds,
    scales: CharacteristicScales | None = None,
) -> P3R2KKTAudit:
    contract_scales = scales or characteristic_scales(assembly)
    return audit_kkt_arrays(
        gradient=-np.asarray(evaluation.generalized_force, dtype=float),
        gaps_m=evaluation.contact.gaps_m,
        gap_jacobian=evaluation.contact.gap_jacobian,
        scales=contract_scales,
        thresholds=thresholds,
    )
