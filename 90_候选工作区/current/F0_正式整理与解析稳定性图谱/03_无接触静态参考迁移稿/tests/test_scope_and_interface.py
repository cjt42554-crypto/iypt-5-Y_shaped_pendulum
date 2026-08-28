from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import numpy as np
import pytest

import ypendulum_static_reference as reference
from tests.fixtures.static_cases import build_y_anchor_case
from ypendulum_static_reference.interface import (
    StaticReferenceAuditThresholds,
    solve_no_contact_static_reference,
)
from ypendulum_static_reference.statics.solver import StaticSolverSettings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "ypendulum_static_reference"
IDENTITY = json.loads((PROJECT_ROOT / "model_identity.json").read_text(encoding="utf-8"))
CANONICAL = json.loads(
    (PROJECT_ROOT / "contracts/static_reference_run_contract.json").read_text(
        encoding="utf-8"
    )
)


def _thresholds(contract: dict) -> StaticReferenceAuditThresholds:
    finite = contract["finite_difference"]
    case = contract["y_anchor"]
    return StaticReferenceAuditThresholds(
        finite_difference_relative_steps=tuple(finite["relative_step_sequence"]),
        finite_difference_final_relative_error_max=finite[
            "final_relative_error_max"
        ],
        finite_difference_minimum_strict_decrease_steps=finite[
            "minimum_strict_decrease_steps"
        ],
        scaled_generalized_force_residual_max=case[
            "scaled_generalized_force_residual_max"
        ],
        scaled_global_force_balance_max=case["scaled_global_force_balance_max"],
        scaled_global_moment_balance_max=case["scaled_global_moment_balance_max"],
    )


def test_identity_carries_no_historical_numerical_qualification() -> None:
    assert reference.MODEL_ID == IDENTITY["model_id"]
    assert reference.MODEL_ID == "YPS-NO-CONTACT-STATIC-REFERENCE-DRAFT-1.1"
    assert reference.CLAIM_CEILING == (
        "CANDIDATE_STATIC_IMPLEMENTATION_AND_RUNTIME_EVIDENCE_ONLY"
    )
    assert reference.QUALIFICATION_STATUS == "NO_FORMAL_NUMERICAL_QUALIFICATION_CARRIED"
    assert IDENTITY["status"] == "CANDIDATE_MIGRATION_DRAFT_NOT_FORMALLY_PROMOTED"
    assert IDENTITY["qualification_carried_by_migration"] is False


def test_production_tree_and_ast_are_static_only() -> None:
    relative_files = {
        path.relative_to(PACKAGE_ROOT).as_posix() for path in PACKAGE_ROOT.rglob("*.py")
    }
    assert not any("contact" in path for path in relative_files)
    assert not any("dynamic" in path for path in relative_files)
    assert not any(path.endswith(("g2_cases.py", "passivity.py", "invariance.py")) for path in relative_files)

    forbidden_identifier_fragments = (
        "hfv2",
        "velocity",
        "kinetic",
        "momentum",
        "drag",
        "dissipation",
        "power",
        "time_step",
        "advance_rotation",
    )
    for path in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        identifiers: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                identifiers.append(node.name)
            elif isinstance(node, ast.arg):
                identifiers.append(node.arg)
            elif isinstance(node, ast.Name):
                identifiers.append(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.append(node.attr)
            elif isinstance(node, ast.Import):
                identifiers.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                identifiers.append(node.module or "")
        assert all(
            fragment not in identifier.lower()
            for identifier in identifiers
            for fragment in forbidden_identifier_fragments
        ), path


def test_root_exports_are_closed_and_static_only() -> None:
    expected = {
        "CAPABILITY",
        "CLAIM_CEILING",
        "EXPLICIT_EXCLUSIONS",
        "MODEL_ID",
        "QUALIFICATION_STATUS",
        "AxialMaterial",
        "AxialResponse",
        "BendingGeometryError",
        "BendingResponse",
        "MaterialNode",
        "MaterialSegment",
        "StaticMassDistribution",
        "StaticPointLoadResponse",
        "StaticReferenceAuditThresholds",
        "StaticReferenceBatchResult",
        "StaticReferencePostAudit",
        "StaticReferenceState",
        "StaticReferenceTopology",
        "attachment_action_reaction",
        "attachment_geometry",
        "axial_segment_response",
        "bending_energy",
        "bending_energy_forces",
        "exp_so3",
        "point_static_load",
        "solve_no_contact_static_reference",
    }
    assert set(reference.__all__) == expected
    assert all(hasattr(reference, name) for name in expected)


def test_bound_canonical_case_runs_with_optimizer_status_as_record_only() -> None:
    case = build_y_anchor_case(CANONICAL, 2)
    solver = CANONICAL["primary_solver"]
    settings = StaticSolverSettings(
        method=solver["method"],
        gradient_infinity_tolerance=solver["gradient_infinity_tolerance"],
        maximum_iterations=solver["maximum_iterations"],
        x_relative_tolerance=solver["x_relative_tolerance"],
        armijo_c1=solver["armijo_c1"],
        curvature_c2=solver["curvature_c2"],
    )
    result = solve_no_contact_static_reference(
        case.assembly,
        (case.seeds[0],),
        settings,
        _thresholds(CANONICAL),
    )
    assert result.model_id == reference.MODEL_ID
    assert result.capability == (
        "position_orientation_conservative_no_contact_static_reference_only"
    )
    assert result.qualification_status == "NO_FORMAL_NUMERICAL_QUALIFICATION_CARRIED"
    audit = result.post_audits[0]
    assert audit.optimizer_status_record_only in {0, 2}
    assert isinstance(audit.optimizer_success_record_only, bool)
    assert audit.implementation_diagnostics_passed
    assert all(audit.independent_checks.values())
    assert np.isfinite(audit.scaled_generalized_force_residual)


@pytest.mark.parametrize(
    "mutation",
    (
        "empty_steps",
        "nondecreasing_steps",
        "nonfinite_threshold",
        "negative_threshold",
        "invalid_minimum_steps",
    ),
)
def test_audit_thresholds_fail_closed_on_invalid_values(mutation: str) -> None:
    kwargs = {
        "finite_difference_relative_steps": (1.0e-4, 3.0e-5, 1.0e-5),
        "finite_difference_final_relative_error_max": 2.0e-6,
        "finite_difference_minimum_strict_decrease_steps": 2,
        "scaled_generalized_force_residual_max": 2.0e-7,
        "scaled_global_force_balance_max": 2.0e-10,
        "scaled_global_moment_balance_max": 2.0e-9,
    }
    invalid = copy.deepcopy(kwargs)
    if mutation == "empty_steps":
        invalid["finite_difference_relative_steps"] = ()
    elif mutation == "nondecreasing_steps":
        invalid["finite_difference_relative_steps"] = (1.0e-4, 2.0e-4)
    elif mutation == "nonfinite_threshold":
        invalid["scaled_global_force_balance_max"] = float("nan")
    elif mutation == "negative_threshold":
        invalid["scaled_global_moment_balance_max"] = -1.0
    else:
        invalid["finite_difference_minimum_strict_decrease_steps"] = 3
    with pytest.raises(ValueError):
        StaticReferenceAuditThresholds(**invalid)
