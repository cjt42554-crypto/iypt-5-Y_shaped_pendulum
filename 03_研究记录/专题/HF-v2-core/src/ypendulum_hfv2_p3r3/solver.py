"""Fixed SLSQP plus always-executed P3R3 quasi-Newton restoration."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import OptimizeWarning, minimize

from ypendulum_hfv2.statics.contact_assembly import ContactCoordinates
from ypendulum_hfv2.statics.contracts import StaticSeed

from .assembly import P3R3ContactAssembly
from .certification import CharacteristicScales, characteristic_scales
from .restoration import (
    P3R3RestorationResult,
    P3R3RestorationSettings,
    restore_contact_kkt,
)


@dataclass(frozen=True)
class P3R3SolverSettings:
    method: str
    function_tolerance: float
    maximum_iterations: int
    restoration: P3R3RestorationSettings

    def __post_init__(self) -> None:
        if self.method != "SLSQP":
            raise ValueError("P3R3 freezes SLSQP as the composite primary stage.")
        if float(self.function_tolerance) != 1.0e-12:
            raise ValueError("P3R3 freezes SLSQP ftol=1e-12.")
        if self.maximum_iterations != 3000:
            raise ValueError("P3R3 freezes SLSQP maximum_iterations=3000.")


@dataclass(frozen=True)
class P3R3ContactSolveResult:
    seed_id: str
    initial_coordinates: ContactCoordinates
    slsqp_coordinates: ContactCoordinates
    slsqp_evaluation: object
    coordinates: ContactCoordinates
    evaluation: object
    scales: CharacteristicScales
    optimizer_success: bool
    optimizer_status: int
    optimizer_message: str
    optimizer_iterations: int
    function_evaluations: int
    gradient_evaluations: int
    restoration: P3R3RestorationResult


def slsqp_options(settings: P3R3SolverSettings) -> dict[str, object]:
    return {
        "ftol": settings.function_tolerance,
        "maxiter": settings.maximum_iterations,
        "disp": False,
    }


def settings_from_manifest(manifest: dict[str, Any]) -> P3R3SolverSettings:
    composite = manifest["composite_solver"]
    primary = composite["primary"]
    restore = composite["restoration"]
    restoration = P3R3RestorationSettings(
        near_active_gap_max_m=float(restore["near_active_gap_max_m"]),
        supported_multiplier_min_N=float(restore["canonical_support_multiplier_min_N"]),
        required_active_count=int(restore["required_active_count"]),
        rank_relative_tolerance=float(restore["rank_relative_tolerance"]),
        initial_non_near_gap_strict_min_m=float(restore["initial_non_near_gap_strict_min_m"]),
        primal_penetration_max_m=float(restore["primal_penetration_max_m"]),
        validity_normalized_margin_min=float(restore["validity_normalized_margin_min"]),
        translation_hessian_step_m=float(restore["translation_hessian_step_m"]),
        rotation_hessian_step_rad=float(restore["rotation_hessian_step_rad"]),
        linear_system_relative_singular_value_min=float(
            restore["linear_system_relative_singular_value_min"]
        ),
        maximum_newton_iterations=int(restore["maximum_newton_iterations"]),
        convergence_composite_infinity_max=float(restore["convergence_composite_infinity_max"]),
        maximum_backtracks=int(restore["maximum_backtracks"]),
        armijo_coefficient=float(restore["armijo_coefficient"]),
        full_composite_jacobian_dimensionless_steps=tuple(
            float(item) for item in restore["full_composite_jacobian_dimensionless_steps"]
        ),
        full_jacobian_finest_pair_relative_difference_max=float(
            restore["full_jacobian_finest_pair_relative_difference_max"]
        ),
        quasi_to_full_jacobian_relative_difference_max=float(
            restore["quasi_to_full_jacobian_relative_difference_max"]
        ),
    )
    return P3R3SolverSettings(
        method=str(primary["method"]),
        function_tolerance=float(primary["ftol"]),
        maximum_iterations=int(primary["maximum_iterations"]),
        restoration=restoration,
    )


def solve_contact_seed(
    assembly: P3R3ContactAssembly,
    seed: StaticSeed,
    settings: P3R3SolverSettings,
) -> P3R3ContactSolveResult:
    """Execute both frozen stages for one deterministic seed."""

    initial = assembly.coordinates_from_seed(seed)
    cache_values: np.ndarray | None = None
    cache_evaluation: object | None = None

    def evaluate(values: np.ndarray) -> object:
        nonlocal cache_values, cache_evaluation
        vector = np.asarray(values, dtype=float)
        if cache_values is None or not np.array_equal(vector, cache_values):
            cache_values = np.array(vector, copy=True)
            cache_evaluation = assembly.evaluate(assembly.coordinates_from_values(vector))
        if cache_evaluation is None:
            raise AssertionError("P3R3 contact evaluation cache was not populated.")
        return cache_evaluation

    def objective(values: np.ndarray) -> tuple[float, np.ndarray]:
        current = evaluate(values)
        return current.total_potential, -current.generalized_force

    def inequalities(values: np.ndarray) -> np.ndarray:
        return evaluate(values).solver_inequality_residuals

    def inequality_jacobian(values: np.ndarray) -> np.ndarray:
        return evaluate(values).solver_inequality_jacobian

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "error",
            message=r"Unknown solver options.*",
            category=OptimizeWarning,
        )
        primary = minimize(
            objective,
            initial.values,
            method=settings.method,
            jac=True,
            constraints={
                "type": "ineq",
                "fun": inequalities,
                "jac": inequality_jacobian,
            },
            options=slsqp_options(settings),
        )
    slsqp_coordinates = assembly.coordinates_from_values(np.asarray(primary.x, dtype=float))
    slsqp_evaluation = assembly.evaluate(slsqp_coordinates)
    scales = characteristic_scales(assembly)
    restoration = restore_contact_kkt(
        assembly,
        slsqp_coordinates,
        scales,
        settings.restoration,
    )
    return P3R3ContactSolveResult(
        seed_id=seed.seed_id,
        initial_coordinates=initial,
        slsqp_coordinates=slsqp_coordinates,
        slsqp_evaluation=slsqp_evaluation,
        coordinates=restoration.coordinates,
        evaluation=restoration.evaluation,
        scales=scales,
        optimizer_success=bool(primary.success),
        optimizer_status=int(primary.status),
        optimizer_message=str(primary.message),
        optimizer_iterations=int(primary.nit),
        function_evaluations=int(primary.nfev),
        gradient_evaluations=int(primary.njev),
        restoration=restoration,
    )


def solve_contact_seeds(
    assembly: P3R3ContactAssembly,
    seeds: tuple[StaticSeed, ...],
    settings: P3R3SolverSettings,
) -> tuple[P3R3ContactSolveResult, ...]:
    frozen = tuple(seeds)
    if not frozen:
        raise ValueError("At least one deterministic P3R3 seed is required.")
    identities = tuple(seed.seed_id for seed in frozen)
    if len(identities) != len(set(identities)):
        raise ValueError("P3R3 deterministic seed identities must be unique.")
    return tuple(solve_contact_seed(assembly, seed, settings) for seed in frozen)
