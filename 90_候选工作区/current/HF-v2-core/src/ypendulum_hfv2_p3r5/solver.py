"""P3R5 wrapper over the fixed P3R4 qualification-algorithm behavior."""

from __future__ import annotations

from typing import Any

from ypendulum_hfv2.statics.contracts import StaticSeed
from ypendulum_hfv2_p3r4.solver import (
    P3R4ContactSolveResult,
    P3R4SolverSettings,
)
from ypendulum_hfv2_p3r4.solver import settings_from_manifest as _settings_from_manifest
from ypendulum_hfv2_p3r4.solver import solve_contact_seed as _solve_contact_seed
from ypendulum_hfv2_p3r4.solver import solve_contact_seeds as _solve_contact_seeds

from .assembly import P3R5ContactAssembly

P3R5ContactSolveResult = P3R4ContactSolveResult
P3R5SolverSettings = P3R4SolverSettings


def settings_from_manifest(manifest: dict[str, Any]) -> P3R5SolverSettings:
    """Build unchanged P3R4 numerical behavior under the P3R5 identity."""

    return _settings_from_manifest(manifest)


def solve_contact_seed(
    assembly: P3R5ContactAssembly,
    seed: StaticSeed,
    settings: P3R5SolverSettings,
) -> P3R5ContactSolveResult:
    return _solve_contact_seed(assembly, seed, settings)


def solve_contact_seeds(
    assembly: P3R5ContactAssembly,
    seeds: tuple[StaticSeed, ...],
    settings: P3R5SolverSettings,
) -> tuple[P3R5ContactSolveResult, ...]:
    return _solve_contact_seeds(assembly, seeds, settings)


__all__ = [
    "P3R5ContactSolveResult",
    "P3R5SolverSettings",
    "settings_from_manifest",
    "solve_contact_seed",
    "solve_contact_seeds",
]
