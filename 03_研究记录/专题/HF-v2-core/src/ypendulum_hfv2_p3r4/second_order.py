"""Three-level Richardson audit for the reference Lagrangian Hessian."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from . import P3R4_SECOND_ORDER_ID
from .assembly import P3R4ContactAssembly
from .certification import CharacteristicScales


@dataclass(frozen=True)
class RichardsonDirectionAudit:
    direction_id: str
    dimensionless_steps: np.ndarray
    normalized_curvatures: np.ndarray
    curvature_roundoff_bounds: np.ndarray
    coarse_richardson_curvature: float
    fine_richardson_curvature: float
    truncation_uncertainty: float
    richardson_roundoff_uncertainty: float
    total_uncertainty: float
    curvature_lower_bound: float
    coarse_difference: float
    fine_difference: float
    coarse_difference_resolution_bound: float
    fine_difference_resolution_bound: float
    order_status: str
    observed_order: float | None
    passed: bool


@dataclass(frozen=True)
class SecondOrderAudit:
    identity: str
    passed: bool
    theoretical_order: int
    tangent_basis: np.ndarray
    direction_audits: tuple[RichardsonDirectionAudit, ...]
    minimum_curvature_lower_bound: float


def tangent_directions(basis: np.ndarray) -> tuple[tuple[str, np.ndarray], ...]:
    """Return the frozen nine unoriented directions in deterministic order."""

    array = np.asarray(basis, dtype=float)
    if array.shape != (6, 3) or not np.all(np.isfinite(array)):
        raise ValueError("P3R4 requires one finite 6-by-3 tangent basis.")
    if not np.allclose(array.T @ array, np.eye(3), rtol=0.0, atol=1.0e-10):
        raise ValueError("P3R4 tangent directions require an orthonormal basis.")
    directions: list[tuple[str, np.ndarray]] = [
        (f"basis_{index}", np.array(array[:, index], copy=True)) for index in range(3)
    ]
    for first in range(3):
        for second in range(first + 1, 3):
            for operation, sign in (("sum", 1.0), ("difference", -1.0)):
                vector = array[:, first] + sign * array[:, second]
                vector /= np.linalg.norm(vector)
                directions.append((f"basis_{first}_{operation}_{second}", vector))
    return tuple(directions)


def richardson_direction_audit(
    direction_id: str,
    steps: np.ndarray,
    curvatures: np.ndarray,
    roundoff_bounds: np.ndarray,
    contract: dict[str, Any],
) -> RichardsonDirectionAudit:
    """Apply the pre-frozen order, resolution and uncertainty model to samples."""

    step_values = np.asarray(steps, dtype=float)
    values = np.asarray(curvatures, dtype=float)
    rounding = np.asarray(roundoff_bounds, dtype=float)
    if step_values.shape != (3,) or values.shape != (3,) or rounding.shape != (3,):
        raise ValueError("P3R4 Richardson audit requires exactly three levels.")
    if not (
        np.all(np.isfinite(step_values))
        and np.all(np.isfinite(values))
        and np.all(np.isfinite(rounding))
        and np.all(step_values > 0.0)
        and np.all(rounding >= 0.0)
    ):
        raise ValueError("P3R4 Richardson inputs must be finite with positive steps.")
    if not np.allclose(step_values[:-1] / step_values[1:], 2.0, rtol=0.0, atol=1.0e-14):
        raise ValueError("P3R4 freezes nested step ratios of exactly two.")
    denominator = float(contract["richardson_denominator"])
    coarse_richardson = float((4.0 * values[1] - values[0]) / denominator)
    fine_richardson = float((4.0 * values[2] - values[1]) / denominator)
    truncation = abs(fine_richardson - coarse_richardson)
    richardson_roundoff = float((4.0 * rounding[2] + rounding[1]) / denominator)
    total_uncertainty = truncation + richardson_roundoff
    lower_bound = fine_richardson - total_uncertainty

    coarse_difference = float(values[0] - values[1])
    fine_difference = float(values[1] - values[2])
    resolution_factor = float(contract["resolved_difference_roundoff_factor"])
    coarse_resolution = resolution_factor * float(rounding[0] + rounding[1])
    fine_resolution = resolution_factor * float(rounding[1] + rounding[2])
    coarse_resolved = abs(coarse_difference) > coarse_resolution
    fine_resolved = abs(fine_difference) > fine_resolution
    observed_order: float | None = None
    if coarse_resolved and fine_resolved:
        same_sign = coarse_difference * fine_difference > 0.0
        observed_order = float(np.log2(abs(coarse_difference / fine_difference)))
        order_passed = bool(
            same_sign
            and float(contract["resolved_observed_order_min"])
            <= observed_order
            <= float(contract["resolved_observed_order_max"])
        )
        order_status = "RESOLVED_ORDER_PASS" if order_passed else "RESOLVED_ORDER_FAIL"
    elif not coarse_resolved and not fine_resolved:
        order_passed = True
        order_status = "ROUNDING_LIMITED_CONSISTENT"
    else:
        order_passed = False
        order_status = "MIXED_RESOLUTION_FAIL"
    passed = bool(
        order_passed
        and lower_bound > float(contract["extrapolated_curvature_minus_uncertainty_strict_min"])
    )
    return RichardsonDirectionAudit(
        direction_id=direction_id,
        dimensionless_steps=np.array(step_values, copy=True),
        normalized_curvatures=np.array(values, copy=True),
        curvature_roundoff_bounds=np.array(rounding, copy=True),
        coarse_richardson_curvature=coarse_richardson,
        fine_richardson_curvature=fine_richardson,
        truncation_uncertainty=float(truncation),
        richardson_roundoff_uncertainty=richardson_roundoff,
        total_uncertainty=float(total_uncertainty),
        curvature_lower_bound=float(lower_bound),
        coarse_difference=coarse_difference,
        fine_difference=fine_difference,
        coarse_difference_resolution_bound=coarse_resolution,
        fine_difference_resolution_bound=fine_resolution,
        order_status=order_status,
        observed_order=observed_order,
        passed=passed,
    )


def audit_reference_second_order(
    assembly: P3R4ContactAssembly,
    coordinates: object,
    evaluation: object,
    supported_indices: np.ndarray,
    active_multipliers_N: np.ndarray,
    scales: CharacteristicScales,
    tangent_basis: np.ndarray,
    manifest: dict[str, Any],
) -> SecondOrderAudit:
    """Audit the fixed-reference-multiplier Lagrangian in nine directions."""

    indices = np.asarray(supported_indices, dtype=int)
    multipliers = np.asarray(active_multipliers_N, dtype=float)
    if indices.shape != (2,) or multipliers.shape != (2,):
        raise ValueError("P3R4 second-order audit requires two supported contacts.")
    contract = manifest["second_order_numerics"]
    steps = np.asarray(contract["dimensionless_steps"], dtype=float)
    reference_value = float(
        evaluation.total_potential - multipliers @ evaluation.contact.gaps_m[indices]
    )
    epsilon = float(np.finfo(float).eps)
    safety = float(contract["roundoff_safety_factor"])
    audits: list[RichardsonDirectionAudit] = []
    for direction_id, direction in tangent_directions(tangent_basis):
        curvatures = []
        roundoff_bounds = []
        for step in steps:
            lagrangian_values = []
            for sign in (-1.0, 1.0):
                values = coordinates.values + (sign * step * scales.coordinate_scales * direction)
                current = assembly.evaluate(assembly.coordinates_from_values(values))
                lagrangian_values.append(
                    float(current.total_potential - multipliers @ current.contact.gaps_m[indices])
                )
            curvature = (lagrangian_values[1] - 2.0 * reference_value + lagrangian_values[0]) / (
                step**2 * scales.energy_N_m
            )
            roundoff = (
                safety
                * epsilon
                * (
                    abs(lagrangian_values[1])
                    + 2.0 * abs(reference_value)
                    + abs(lagrangian_values[0])
                )
                / (step**2 * scales.energy_N_m)
            )
            curvatures.append(float(curvature))
            roundoff_bounds.append(float(roundoff))
        audits.append(
            richardson_direction_audit(
                direction_id,
                steps,
                np.asarray(curvatures),
                np.asarray(roundoff_bounds),
                contract,
            )
        )
    lower_bound = min(item.curvature_lower_bound for item in audits)
    return SecondOrderAudit(
        identity=P3R4_SECOND_ORDER_ID,
        passed=all(item.passed for item in audits),
        theoretical_order=int(contract["theoretical_truncation_order"]),
        tangent_basis=np.array(tangent_basis, copy=True),
        direction_audits=tuple(audits),
        minimum_curvature_lower_bound=float(lower_bound),
    )


__all__ = [
    "RichardsonDirectionAudit",
    "SecondOrderAudit",
    "audit_reference_second_order",
    "richardson_direction_audit",
    "tangent_directions",
]
