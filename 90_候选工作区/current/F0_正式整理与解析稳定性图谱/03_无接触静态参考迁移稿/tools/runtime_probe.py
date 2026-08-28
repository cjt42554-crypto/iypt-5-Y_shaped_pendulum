"""Run the bound status-2 reference probe for one supported dependency cell."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import sys
from pathlib import Path

from ypendulum_static_reference.audit.g2_cases import build_y_anchor_case
from ypendulum_static_reference.interface import (
    StaticReferenceAuditThresholds,
    solve_no_contact_static_reference,
)
from ypendulum_static_reference.statics.solver import StaticSolverSettings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    arguments = parser.parse_args()
    project = arguments.project_root.resolve()
    manifest = json.loads(
        (project / "contracts/g2_acceptance_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    case = build_y_anchor_case(manifest, 2)
    solver = manifest["primary_solver"]
    finite = manifest["finite_difference"]
    y_case = manifest["y_anchor"]
    settings = StaticSolverSettings(
        method=solver["method"],
        gradient_infinity_tolerance=solver["gradient_infinity_tolerance"],
        maximum_iterations=solver["maximum_iterations"],
        x_relative_tolerance=solver["x_relative_tolerance"],
        armijo_c1=solver["armijo_c1"],
        curvature_c2=solver["curvature_c2"],
    )
    thresholds = StaticReferenceAuditThresholds(
        finite_difference_relative_steps=tuple(finite["relative_step_sequence"]),
        finite_difference_final_relative_error_max=finite[
            "final_relative_error_max"
        ],
        finite_difference_minimum_strict_decrease_steps=finite[
            "minimum_strict_decrease_steps"
        ],
        scaled_generalized_force_residual_max=y_case[
            "scaled_generalized_force_residual_max"
        ],
        scaled_global_force_balance_max=y_case["scaled_global_force_balance_max"],
        scaled_global_moment_balance_max=y_case[
            "scaled_global_moment_balance_max"
        ],
    )
    result = solve_no_contact_static_reference(
        case.assembly, (case.seeds[0],), settings, thresholds
    )
    solve = result.solve_results[0]
    audit = result.post_audits[0]
    payload = {
        "schema": "YPS-NO-CONTACT-STATIC-RUNTIME-PROBE-1.0",
        "runtime": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "numpy": importlib.metadata.version("numpy"),
            "scipy": importlib.metadata.version("scipy"),
            "pytest": importlib.metadata.version("pytest"),
            "executable": Path(sys.executable).name,
        },
        "case": {
            "mesh_segments_per_branch": 2,
            "seed_id": solve.seed_id,
            "optimizer_success_record_only": solve.optimizer_success,
            "optimizer_status_record_only": solve.optimizer_status,
            "optimizer_message_record_only": solve.optimizer_message,
            "implementation_diagnostics_passed": audit.implementation_diagnostics_passed,
            "independent_checks": audit.independent_checks,
            "scaled_generalized_force_residual": audit.scaled_generalized_force_residual,
            "scaled_global_force_balance": audit.scaled_global_force_balance,
            "scaled_global_moment_balance": audit.scaled_global_moment_balance,
            "finite_difference_final_relative_error": (
                audit.finite_difference_relative_errors[-1]
            ),
        },
        "interpretation": (
            "optimizer status is record-only; implementation diagnostics are not "
            "formal numerical qualification or contact capability"
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
