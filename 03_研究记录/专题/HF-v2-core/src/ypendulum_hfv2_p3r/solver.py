"""Single-algorithm deterministic SLSQP solver for P3R static contact."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from scipy.optimize import OptimizeWarning, minimize

from ypendulum_hfv2.statics.contact_assembly import ContactCoordinates
from ypendulum_hfv2.statics.contracts import StaticSeed

from .assembly import P3RContactAssembly, P3RContactEvaluation


@dataclass(frozen=True)
class P3RSolverSettings:
    method: str
    function_tolerance: float
    maximum_iterations: int

    def __post_init__(self) -> None:
        if self.method != "SLSQP":
            raise ValueError("P3R freezes SLSQP as the only static contact solver.")
        tolerance = float(self.function_tolerance)
        if not np.isfinite(tolerance) or tolerance != 1.0e-12:
            raise ValueError("P3R freezes SLSQP ftol=1e-12.")
        if self.maximum_iterations != 3000:
            raise ValueError("P3R freezes SLSQP maximum_iterations=3000.")
        object.__setattr__(self, "function_tolerance", tolerance)


@dataclass(frozen=True)
class P3RContactSolveResult:
    seed_id: str
    initial_coordinates: ContactCoordinates
    coordinates: ContactCoordinates
    evaluation: P3RContactEvaluation
    optimizer_success: bool
    optimizer_status: int
    optimizer_message: str
    iterations: int
    function_evaluations: int
    gradient_evaluations: int


def slsqp_options(settings: P3RSolverSettings) -> dict[str, object]:
    return {
        "ftol": settings.function_tolerance,
        "maxiter": settings.maximum_iterations,
        "disp": False,
    }


def solve_contact_seed(
    assembly: P3RContactAssembly,
    seed: StaticSeed,
    settings: P3RSolverSettings,
) -> P3RContactSolveResult:
    """Run exactly one SLSQP solve with all finite domain residuals exposed."""

    initial = assembly.coordinates_from_seed(seed)
    cache_values: np.ndarray | None = None
    cache_evaluation: P3RContactEvaluation | None = None

    def evaluate(values: np.ndarray) -> P3RContactEvaluation:
        nonlocal cache_values, cache_evaluation
        vector = np.asarray(values, dtype=float)
        if cache_values is None or not np.array_equal(vector, cache_values):
            cache_values = np.array(vector, copy=True)
            coordinates = assembly.coordinates_from_values(vector)
            cache_evaluation = assembly.evaluate(coordinates)
        if cache_evaluation is None:
            raise AssertionError("P3R contact evaluation cache was not populated.")
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
        result = minimize(
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
    coordinates = assembly.coordinates_from_values(np.asarray(result.x, dtype=float))
    evaluation = assembly.evaluate(coordinates)
    return P3RContactSolveResult(
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


def solve_contact_seeds(
    assembly: P3RContactAssembly,
    seeds: tuple[StaticSeed, ...],
    settings: P3RSolverSettings,
) -> tuple[P3RContactSolveResult, ...]:
    frozen = tuple(seeds)
    if not frozen:
        raise ValueError("At least one deterministic P3R seed is required.")
    identities = tuple(seed.seed_id for seed in frozen)
    if len(identities) != len(set(identities)):
        raise ValueError("P3R deterministic seed identities must be unique.")
    return tuple(solve_contact_seed(assembly, seed, settings) for seed in frozen)
