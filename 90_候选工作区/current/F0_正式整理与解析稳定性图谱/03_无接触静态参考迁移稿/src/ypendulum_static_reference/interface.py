"""Narrow public interface for a no-contact conservative static reference solve."""

from __future__ import annotations

from dataclasses import dataclass

from .audit.statics import balance_audit, energy_force_samples, strict_decrease_interval
from .identity import CAPABILITY, CLAIM_CEILING, MODEL_ID, QUALIFICATION_STATUS
from .statics.assembly import StaticAssembly
from .statics.contracts import StaticSeed
from .statics.solver import (
    StaticSolveResult,
    StaticSolverSettings,
    solve_deterministic_seeds,
)


@dataclass(frozen=True)
class StaticReferenceAuditThresholds:
    finite_difference_relative_steps: tuple[float, ...]
    finite_difference_final_relative_error_max: float
    finite_difference_minimum_strict_decrease_steps: int
    scaled_generalized_force_residual_max: float
    scaled_global_force_balance_max: float
    scaled_global_moment_balance_max: float


@dataclass(frozen=True)
class StaticReferencePostAudit:
    seed_id: str
    optimizer_success_record_only: bool
    optimizer_status_record_only: int
    finite_difference_probe: str
    finite_difference_relative_errors: tuple[float, ...]
    scaled_generalized_force_residual: float
    scaled_global_force_balance: float
    scaled_global_moment_balance: float
    independent_checks: dict[str, bool]
    implementation_diagnostics_passed: bool


@dataclass(frozen=True)
class StaticReferenceBatchResult:
    model_id: str
    capability: str
    claim_ceiling: str
    qualification_status: str
    solve_results: tuple[StaticSolveResult, ...]
    post_audits: tuple[StaticReferencePostAudit, ...]


def _post_audit(
    assembly: StaticAssembly,
    result: StaticSolveResult,
    thresholds: StaticReferenceAuditThresholds,
) -> StaticReferencePostAudit:
    samples = energy_force_samples(
        assembly,
        result.initial_coordinates,
        thresholds.finite_difference_relative_steps,
    )
    errors = tuple(sample.relative_error for sample in samples)
    balance = balance_audit(assembly, result.evaluation)
    checks = {
        "finite_difference_decrease": strict_decrease_interval(
            errors,
            thresholds.finite_difference_minimum_strict_decrease_steps,
        )
        is not None,
        "finite_difference_final": errors[-1]
        <= thresholds.finite_difference_final_relative_error_max,
        "generalized_force": balance.scaled_generalized_force_residual
        <= thresholds.scaled_generalized_force_residual_max,
        "global_force_balance": balance.scaled_global_force_balance
        <= thresholds.scaled_global_force_balance_max,
        "global_moment_balance": balance.scaled_global_moment_balance
        <= thresholds.scaled_global_moment_balance_max,
    }
    return StaticReferencePostAudit(
        seed_id=result.seed_id,
        optimizer_success_record_only=result.optimizer_success,
        optimizer_status_record_only=result.optimizer_status,
        finite_difference_probe="initial_coordinates_before_optimization",
        finite_difference_relative_errors=errors,
        scaled_generalized_force_residual=balance.scaled_generalized_force_residual,
        scaled_global_force_balance=balance.scaled_global_force_balance,
        scaled_global_moment_balance=balance.scaled_global_moment_balance,
        independent_checks=checks,
        implementation_diagnostics_passed=all(checks.values()),
    )


def solve_no_contact_static_reference(
    assembly: StaticAssembly,
    seeds: tuple[StaticSeed, ...],
    settings: StaticSolverSettings,
    thresholds: StaticReferenceAuditThresholds,
) -> StaticReferenceBatchResult:
    """Solve deterministic seeds and report independent implementation diagnostics.

    ``optimizer_success`` is retained only as a record.  The returned
    ``implementation_diagnostics_passed`` flag is not a numerical qualification,
    contact capability, device validation or experimental validation.
    """

    results = solve_deterministic_seeds(assembly, seeds, settings)
    audits = tuple(_post_audit(assembly, result, thresholds) for result in results)
    return StaticReferenceBatchResult(
        model_id=MODEL_ID,
        capability=CAPABILITY,
        claim_ceiling=CLAIM_CEILING,
        qualification_status=QUALIFICATION_STATUS,
        solve_results=results,
        post_audits=audits,
    )
