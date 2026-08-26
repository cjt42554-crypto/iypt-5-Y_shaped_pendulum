"""Data contracts for the candidate rigid-contact static gate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.optimize import OptimizeResult

Array = np.ndarray
EnergyWithGradient = Callable[[Array], tuple[float, Array]]
GapsWithJacobian = Callable[[Array], tuple[Array, Array]]

class DegenerateContactGeometry(ValueError):
    """Raised when a unique differentiable closest-point witness is unavailable."""


@dataclass(frozen=True)
class ContactWitness:
    """Closest-point evidence for one segment-pair unilateral gap."""

    first_parameter: float
    second_parameter: float
    first_point_m: Array
    second_point_m: Array
    distance_m: float
    required_center_distance_m: float
    gap_m: float
    normal_second_to_first: Array
    endpoint_gap_gradient: Array
    unique: bool
    differentiable: bool
    active_feature: str
    competing_minimizer_count: int


@dataclass(frozen=True)
class ContactConstraint:
    """One individually identified contact gap over four endpoint nodes."""

    label: str
    first_start_node: int
    first_end_node: int
    second_start_node: int
    second_end_node: int
    required_center_distance_m: float
    parameter_polygon: Array | None = None

    def endpoint_nodes(self) -> tuple[int, int, int, int]:
        return (
            self.first_start_node,
            self.first_end_node,
            self.second_start_node,
            self.second_end_node,
        )


@dataclass(frozen=True)
class KKTThresholds:
    """Dimensional static-contact acceptance thresholds."""

    primal_gap_m: float = 1.0e-10
    stationarity_N: float = 1.0e-8
    dual_force_N: float = 1.0e-10
    complementarity_Nm: float = 1.0e-12
    active_gap_m: float = 1.0e-8

    def __post_init__(self) -> None:
        values = (
            self.primal_gap_m,
            self.stationarity_N,
            self.dual_force_N,
            self.complementarity_Nm,
            self.active_gap_m,
        )
        if any(not np.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("KKT thresholds must be finite and non-negative.")


@dataclass(frozen=True)
class KKTAudit:
    """Static unilateral-contact KKT residuals and pass/fail decision."""

    passed: bool
    finite: bool
    primal_violation_m: float
    stationarity_residual_N: float
    dual_violation_N: float
    complementarity_residual_Nm: float
    minimum_gap_m: float
    minimum_multiplier_N: float
    active_contact_count: int
    multiplier_supported_contact_count: int
    stationarity_vector_N: Array


@dataclass(frozen=True)
class ProjectedHessianAudit:
    """Sufficient PSD check on the tangent space of the selected active set."""

    passed: bool
    finite: bool
    tangent_dimension: int
    active_constraint_rank: int
    minimum_projected_eigenvalue_N_per_m: float | None
    tolerance_N_per_m: float
    interpretation: str


@dataclass(frozen=True)
class StaticContactResult:
    """Generic constrained-energy result with independently reconstructed KKT data."""

    state: Array
    energy_J: float
    gradient_N: Array
    gaps_m: Array
    gap_jacobian: Array
    multipliers_N: Array
    optimizer_success: bool
    optimizer_status: int
    optimizer_message: str
    optimizer_iterations: int
    kkt: KKTAudit
    raw_result: OptimizeResult


