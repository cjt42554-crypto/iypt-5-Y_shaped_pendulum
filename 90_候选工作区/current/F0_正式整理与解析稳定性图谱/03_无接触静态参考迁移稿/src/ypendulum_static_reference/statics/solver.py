"""Single-algorithm deterministic solver for the gated no-contact static phase."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from scipy.optimize import OptimizeWarning, minimize

from .assembly import StaticAssembly, StaticEvaluation
from .contracts import StaticCoordinates, StaticSeed


@dataclass(frozen=True)
class StaticSolverSettings:
    method: str
    gradient_infinity_tolerance: float
    maximum_iterations: int
    x_relative_tolerance: float
    armijo_c1: float
    curvature_c2: float

    def __post_init__(self) -> None:
        if self.method != "BFGS":
            raise ValueError("P2 freezes BFGS as the only static solver.")
        values = np.asarray(
            [
                self.gradient_infinity_tolerance,
                self.x_relative_tolerance,
                self.armijo_c1,
                self.curvature_c2,
            ],
            dtype=float,
        )
        if not np.all(np.isfinite(values)):
            raise ValueError("Static solver tolerances must be finite.")
        if self.gradient_infinity_tolerance <= 0.0 or self.x_relative_tolerance < 0.0:
            raise ValueError("Static gradient tolerance must be positive and xrtol non-negative.")
        if not 0.0 < self.armijo_c1 < self.curvature_c2 < 1.0:
            raise ValueError("BFGS line-search constants must satisfy 0 < c1 < c2 < 1.")
        if self.armijo_c1 != 1.0e-4 or self.curvature_c2 != 0.9:
            raise ValueError("P2 freezes the SciPy BFGS default c1=1e-4 and c2=0.9.")
        if self.maximum_iterations <= 0:
            raise ValueError("maximum_iterations must be positive.")


@dataclass(frozen=True)
class StaticSolveResult:
    seed_id: str
    initial_coordinates: StaticCoordinates
    coordinates: StaticCoordinates
    evaluation: StaticEvaluation
    optimizer_success: bool
    optimizer_status: int
    optimizer_message: str
    iterations: int
    function_evaluations: int
    gradient_evaluations: int


def bfgs_minimize_options(settings: StaticSolverSettings) -> dict[str, object]:
    """Return every frozen SciPy BFGS option as the actual call mapping."""

    return {
        "gtol": settings.gradient_infinity_tolerance,
        "maxiter": settings.maximum_iterations,
        "xrtol": settings.x_relative_tolerance,
        "norm": np.inf,
        "disp": False,
        "c1": settings.armijo_c1,
        "c2": settings.curvature_c2,
    }


def solve_static_seed(
    assembly: StaticAssembly,
    seed: StaticSeed,
    settings: StaticSolverSettings,
) -> StaticSolveResult:
    """Run exactly one BFGS solve without fallback or tolerance mutation."""

    initial = assembly.coordinates_from_seed(seed)

    def objective(values: np.ndarray) -> tuple[float, np.ndarray]:
        evaluation = assembly.evaluate(assembly.coordinates_from_values(values))
        return evaluation.total_potential, -evaluation.generalized_force

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "error",
            message=r"Unknown solver options.*",
            category=OptimizeWarning,
        )
        result = minimize(
            objective,
            initial.values,
            method=settings.method,
            jac=True,
            options=bfgs_minimize_options(settings),
        )
    coordinates = assembly.coordinates_from_values(np.asarray(result.x, dtype=float))
    evaluation = assembly.evaluate(coordinates)
    return StaticSolveResult(
        seed_id=seed.seed_id,
        initial_coordinates=initial,
        coordinates=coordinates,
        evaluation=evaluation,
        optimizer_success=bool(result.success),
        optimizer_status=int(result.status),
        optimizer_message=str(result.message),
        iterations=int(result.nit),
        function_evaluations=int(result.nfev),
        gradient_evaluations=int(result.njev),
    )


def solve_deterministic_seeds(
    assembly: StaticAssembly,
    seeds: tuple[StaticSeed, ...],
    settings: StaticSolverSettings,
) -> tuple[StaticSolveResult, ...]:
    """Run the frozen seed list in supplied order using the one solver."""

    frozen_seeds = tuple(seeds)
    if not frozen_seeds:
        raise ValueError("At least one deterministic seed is required.")
    seed_ids = tuple(seed.seed_id for seed in frozen_seeds)
    if len(seed_ids) != len(set(seed_ids)):
        raise ValueError("Deterministic seed identities must be unique.")
    return tuple(solve_static_seed(assembly, seed, settings) for seed in frozen_seeds)
