"""P3R4 wrapper over the fixed P3R3 composite numerical behavior."""

from __future__ import annotations

from typing import Any

from ypendulum_hfv2.statics.contracts import StaticSeed
from ypendulum_hfv2_p3r3.solver import (
    P3R3ContactSolveResult,
    P3R3SolverSettings,
)
from ypendulum_hfv2_p3r3.solver import (
    settings_from_manifest as _settings_from_manifest,
)
from ypendulum_hfv2_p3r3.solver import (
    solve_contact_seed as _solve_contact_seed,
)
from ypendulum_hfv2_p3r3.solver import (
    solve_contact_seeds as _solve_contact_seeds,
)

from .assembly import P3R4ContactAssembly

P3R4ContactSolveResult = P3R3ContactSolveResult
P3R4SolverSettings = P3R3SolverSettings


def settings_from_manifest(manifest: dict[str, Any]) -> P3R4SolverSettings:
    """Build the frozen behavior settings under the P3R4 identity."""

    return _settings_from_manifest(manifest)


def solve_contact_seed(
    assembly: P3R4ContactAssembly,
    seed: StaticSeed,
    settings: P3R4SolverSettings,
) -> P3R4ContactSolveResult:
    """Execute the fixed two-stage solver for one P3R4-identity assembly."""

    return _solve_contact_seed(assembly, seed, settings)


def solve_contact_seeds(
    assembly: P3R4ContactAssembly,
    seeds: tuple[StaticSeed, ...],
    settings: P3R4SolverSettings,
) -> tuple[P3R4ContactSolveResult, ...]:
    """Execute the fixed solver once for each unique deterministic seed."""

    return _solve_contact_seeds(assembly, seeds, settings)


__all__ = [
    "P3R4ContactSolveResult",
    "P3R4SolverSettings",
    "settings_from_manifest",
    "solve_contact_seed",
    "solve_contact_seeds",
]
