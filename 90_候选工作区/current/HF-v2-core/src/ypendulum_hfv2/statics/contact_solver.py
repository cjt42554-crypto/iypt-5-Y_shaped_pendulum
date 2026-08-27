"""Single-algorithm deterministic SLSQP solver for P3 static contact."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from scipy.optimize import OptimizeWarning, minimize

from ypendulum_hfv2.statics.contact_assembly import (
    ContactCoordinates,
    ContactStaticAssembly,
    ContactStaticEvaluation,
)
from ypendulum_hfv2.statics.contracts import StaticSeed


@dataclass(frozen=True)
class ContactSolverSettings:
    method: str
    function_tolerance: float
    maximum_iterations: int

    def __post_init__(self) -> None:
        if self.method != "SLSQP":
            raise ValueError("P3 freezes SLSQP as the only static contact solver.")
        tolerance = float(self.function_tolerance)
        if not np.isfinite(tolerance) or tolerance <= 0.0:
            raise ValueError("SLSQP function tolerance must be finite and positive.")
        if tolerance != 1.0e-12:
            raise ValueError("P3 freezes SLSQP ftol=1e-12.")
        if self.maximum_iterations != 3000:
            raise ValueError("P3 freezes SLSQP maximum_iterations=3000.")
        object.__setattr__(self, "function_tolerance", tolerance)


@dataclass(frozen=True)
class ContactStaticSolveResult:
    seed_id: str
    initial_coordinates: ContactCoordinates
    coordinates: ContactCoordinates
    evaluation: ContactStaticEvaluation
    optimizer_success: bool
    optimizer_status: int
    optimizer_message: str
    iterations: int
    function_evaluations: int
    gradient_evaluations: int


def slsqp_minimize_options(settings: ContactSolverSettings) -> dict[str, object]:
    return {
        "ftol": settings.function_tolerance,
        "maxiter": settings.maximum_iterations,
        "disp": False,
    }


def solve_contact_seed(
    assembly: ContactStaticAssembly,
    seed: StaticSeed,
    settings: ContactSolverSettings,
) -> ContactStaticSolveResult:
    """Run exactly one analytic SLSQP solve without fallback or mutation."""

    initial = assembly.coordinates_from_seed(seed)
    cache_values: np.ndarray | None = None
    cache_evaluation: ContactStaticEvaluation | None = None

    def evaluate(values: np.ndarray) -> ContactStaticEvaluation:
        nonlocal cache_values, cache_evaluation
        vector = np.asarray(values, dtype=float)
        if cache_values is None or not np.array_equal(vector, cache_values):
            cache_values = np.array(vector, copy=True)
            cache_evaluation = assembly.evaluate(assembly.coordinates_from_values(vector))
        if cache_evaluation is None:
            raise AssertionError("Contact evaluation cache was not populated.")
        return cache_evaluation

    def objective(values: np.ndarray) -> tuple[float, np.ndarray]:
        current = evaluate(values)
        return current.total_potential, -current.generalized_force

    def gaps(values: np.ndarray) -> np.ndarray:
        return evaluate(values).gaps_m

    def gap_jacobian(values: np.ndarray) -> np.ndarray:
        return evaluate(values).gap_jacobian

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
            constraints={"type": "ineq", "fun": gaps, "jac": gap_jacobian},
            options=slsqp_minimize_options(settings),
        )
    coordinates = assembly.coordinates_from_values(np.asarray(result.x, dtype=float))
    evaluation = assembly.evaluate(coordinates)
    return ContactStaticSolveResult(
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
    assembly: ContactStaticAssembly,
    seeds: tuple[StaticSeed, ...],
    settings: ContactSolverSettings,
) -> tuple[ContactStaticSolveResult, ...]:
    frozen = tuple(seeds)
    if not frozen:
        raise ValueError("At least one deterministic contact seed is required.")
    identities = tuple(seed.seed_id for seed in frozen)
    if len(identities) != len(set(identities)):
        raise ValueError("Deterministic contact seed identities must be unique.")
    return tuple(solve_contact_seed(assembly, seed, settings) for seed in frozen)
