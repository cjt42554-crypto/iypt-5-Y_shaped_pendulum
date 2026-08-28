from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np

import ypendulum_static_reference as reference
from ypendulum_static_reference.audit.g2_cases import build_y_anchor_case
from ypendulum_static_reference.interface import (
    StaticReferenceAuditThresholds,
    solve_no_contact_static_reference,
)
from ypendulum_static_reference.statics.solver import StaticSolverSettings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "ypendulum_static_reference"
IDENTITY = json.loads((PROJECT_ROOT / "model_identity.json").read_text(encoding="utf-8"))
G2 = json.loads(
    (PROJECT_ROOT / "contracts" / "g2_acceptance_manifest.json").read_text(encoding="utf-8")
)


def test_new_identity_is_not_the_hfv2_candidate_identity() -> None:
    assert reference.MODEL_ID == IDENTITY["model_id"]
    assert reference.MODEL_ID.startswith(
        "YPS-DISCRETE-ROD-RIGID-BOB-NO-CONTACT-STATIC-REFERENCE-DRAFT"
    )
    assert "HFV2-DISCRETE-CORD" not in reference.MODEL_ID
    assert reference.QUALIFICATION_STATUS == "NOT_CARRIED_BY_MIGRATION"
    assert IDENTITY["status"] == "CANDIDATE_MIGRATION_DRAFT_NOT_FORMALLY_PROMOTED"
    assert IDENTITY["qualification_carried_by_migration"] is False


def test_distribution_tree_excludes_contact_p3r_and_dynamics_modules() -> None:
    relative_files = {
        path.relative_to(PACKAGE_ROOT).as_posix() for path in PACKAGE_ROOT.rglob("*.py")
    }
    assert not any("contact" in path for path in relative_files)
    assert not any("p3r" in path for path in relative_files)
    assert not any("dynamic" in path for path in relative_files)
    for path in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert all("ypendulum_hfv2" not in name for name in names)
            assert all("contact" not in name for name in names)
            assert all("p3r" not in name for name in names)


def test_bound_y_case_runs_with_optimizer_status_as_record_only() -> None:
    case = build_y_anchor_case(G2, 2)
    solver = G2["primary_solver"]
    settings = StaticSolverSettings(
        method=solver["method"],
        gradient_infinity_tolerance=solver["gradient_infinity_tolerance"],
        maximum_iterations=solver["maximum_iterations"],
        x_relative_tolerance=solver["x_relative_tolerance"],
        armijo_c1=solver["armijo_c1"],
        curvature_c2=solver["curvature_c2"],
    )
    finite = G2["finite_difference"]
    y_case = G2["y_anchor"]
    thresholds = StaticReferenceAuditThresholds(
        finite_difference_relative_steps=tuple(finite["relative_step_sequence"]),
        finite_difference_final_relative_error_max=finite["final_relative_error_max"],
        finite_difference_minimum_strict_decrease_steps=finite["minimum_strict_decrease_steps"],
        scaled_generalized_force_residual_max=y_case["scaled_generalized_force_residual_max"],
        scaled_global_force_balance_max=y_case["scaled_global_force_balance_max"],
        scaled_global_moment_balance_max=y_case["scaled_global_moment_balance_max"],
    )
    result = solve_no_contact_static_reference(
        case.assembly,
        (case.seeds[0],),
        settings,
        thresholds,
    )
    assert result.model_id == reference.MODEL_ID
    assert result.capability == "conservative_no_contact_static_reference_only"
    assert result.qualification_status == "NOT_CARRIED_BY_MIGRATION"
    audit = result.post_audits[0]
    assert audit.optimizer_status_record_only in {0, 2}
    assert isinstance(audit.optimizer_success_record_only, bool)
    assert audit.implementation_diagnostics_passed
    assert all(audit.independent_checks.values())
    assert np.isfinite(audit.scaled_generalized_force_residual)
