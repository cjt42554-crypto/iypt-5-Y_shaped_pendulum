"""Fixed SLSQP plus always-executed projected KKT restoration for P3R2."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import OptimizeWarning, minimize

from ypendulum_hfv2.statics.contact_assembly import ContactCoordinates
from ypendulum_hfv2.statics.contracts import StaticSeed

from .assembly import P3R2ContactAssembly
from .certification import CharacteristicScales, characteristic_scales
from .restoration import (
    P3R2RestorationResult,
    P3R2RestorationSettings,
    restore_contact_kkt,
)


@dataclass(frozen=True)
class P3R2SolverSettings:
    method: str
    function_tolerance: float
    maximum_iterations: int
    restoration: P3R2RestorationSettings

    def __post_init__(self) -> None:
        if self.method != "SLSQP":
            raise ValueError("P3R2 freezes SLSQP as the composite primary stage.")
        if float(self.function_tolerance) != 1.0e-12:
            raise ValueError("P3R2 freezes SLSQP ftol=1e-12.")
        if self.maximum_iterations != 3000:
            raise ValueError("P3R2 freezes SLSQP maximum_iterations=3000.")


@dataclass(frozen=True)
class P3R2ContactSolveResult:
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
    restoration: P3R2RestorationResult


def slsqp_options(settings: P3R2SolverSettings) -> dict[str, object]:
    return {
        "ftol": settings.function_tolerance,
        "maxiter": settings.maximum_iterations,
        "disp": False,
    }


def settings_from_manifest(manifest: dict[str, Any]) -> P3R2SolverSettings:
    composite = manifest["composite_solver"]
    primary = composite["primary"]
    restore = composite["restoration"]
    restoration = P3R2RestorationSettings(
        near_active_gap_max_m=float(restore["near_active_gap_max_m"]),
        supported_multiplier_min_N=float(
            restore["canonical_support_multiplier_min_N"]
        ),
        required_active_count=int(restore["required_active_count"]),
        rank_relative_tolerance=float(restore["rank_relative_tolerance"]),
        initial_non_near_gap_strict_min_m=float(
            restore["initial_non_near_gap_strict_min_m"]
        ),
        primal_penetration_max_m=float(restore["primal_penetration_max_m"]),
        validity_normalized_margin_min=float(
            restore["validity_normalized_margin_min"]
        ),
        translation_hessian_step_m=float(restore["translation_hessian_step_m"]),
        rotation_hessian_step_rad=float(restore["rotation_hessian_step_rad"]),
        linear_system_relative_singular_value_min=float(
            restore["linear_system_relative_singular_value_min"]
        ),
        maximum_newton_iterations=int(restore["maximum_newton_iterations"]),
        convergence_composite_infinity_max=float(
            restore["convergence_composite_infinity_max"]
        ),
        maximum_backtracks=int(restore["maximum_backtracks"]),
        armijo_coefficient=float(restore["armijo_coefficient"]),
    )
    return P3R2SolverSettings(
        method=str(primary["method"]),
        function_tolerance=float(primary["ftol"]),
        maximum_iterations=int(primary["maximum_iterations"]),
        restoration=restoration,
    )


def solve_contact_seed(
    assembly: P3R2ContactAssembly,
    seed: StaticSeed,
    settings: P3R2SolverSettings,
) -> P3R2ContactSolveResult:
    """Execute both frozen stages for one deterministic seed."""

    initial = assembly.coordinates_from_seed(seed)
    cache_values: np.ndarray | None = None
    cache_evaluation: object | None = None

    def evaluate(values: np.ndarray) -> object:
        nonlocal cache_values, cache_evaluation
        vector = np.asarray(values, dtype=float)
        if cache_values is None or not np.array_equal(vector, cache_values):
            cache_values = np.array(vector, copy=True)
            cache_evaluation = assembly.evaluate(
                assembly.coordinates_from_values(vector)
            )
        if cache_evaluation is None:
            raise AssertionError("P3R2 contact evaluation cache was not populated.")
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
    slsqp_coordinates = assembly.coordinates_from_values(
        np.asarray(primary.x, dtype=float)
    )
    slsqp_evaluation = assembly.evaluate(slsqp_coordinates)
    scales = characteristic_scales(assembly)
    restoration = restore_contact_kkt(
        assembly,
        slsqp_coordinates,
        scales,
        settings.restoration,
    )
    return P3R2ContactSolveResult(
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
    assembly: P3R2ContactAssembly,
    seeds: tuple[StaticSeed, ...],
    settings: P3R2SolverSettings,
) -> tuple[P3R2ContactSolveResult, ...]:
    frozen = tuple(seeds)
    if not frozen:
        raise ValueError("At least one deterministic P3R2 seed is required.")
    identities = tuple(seed.seed_id for seed in frozen)
    if len(identities) != len(set(identities)):
        raise ValueError("P3R2 deterministic seed identities must be unique.")
    return tuple(solve_contact_seed(assembly, seed, settings) for seed in frozen)
