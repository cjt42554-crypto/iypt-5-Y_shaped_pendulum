from __future__ import annotations

import ast
import copy
import hashlib
import json
import tomllib
from pathlib import Path

import numpy as np
import pytest

import ypendulum_static_reference as reference
from tests.fixtures.static_cases import build_y_anchor_case
from ypendulum_static_reference import identity as reference_identity
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
BUILD_METADATA = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
EXPECTED_PRODUCTION_FILES = {
    "__init__.py",
    "audit/__init__.py",
    "audit/energy_gradient.py",
    "audit/statics.py",
    "constitutive/__init__.py",
    "constitutive/axial.py",
    "constitutive/bending.py",
    "identity.py",
    "interface.py",
    "loads.py",
    "mass.py",
    "rigid/__init__.py",
    "rigid/attachment.py",
    "rigid/rotation.py",
    "state.py",
    "statics/__init__.py",
    "statics/assembly.py",
    "statics/contracts.py",
    "statics/solver.py",
    "topology.py",
}


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
    assert reference.MODEL_ID == "YPS-NO-CONTACT-STATIC-REFERENCE-1.1"
    assert reference_identity.RELEASE_STATUS == "FORMAL_RELEASE_STATIC_REFERENCE_ONLY"
    assert reference.CLAIM_CEILING == (
        "FORMAL_STATIC_REFERENCE_IMPLEMENTATION_AND_RUNTIME_EVIDENCE_ONLY"
    )
    assert reference.QUALIFICATION_STATUS == "NO_FORMAL_NUMERICAL_QUALIFICATION_CARRIED"
    assert IDENTITY["status"] == "FORMAL_RELEASE_STATIC_REFERENCE_ONLY"
    assert IDENTITY["qualification_carried_by_release"] is False
    assert CANONICAL["model_id"] == reference.MODEL_ID
    assert CANONICAL["release_status"] == reference_identity.RELEASE_STATUS
    assert CANONICAL["capability"] == reference.CAPABILITY
    assert CANONICAL["claim_ceiling"] == reference.CLAIM_CEILING
    assert CANONICAL["qualification_status"] == reference.QUALIFICATION_STATUS
    assert BUILD_METADATA["project"]["name"] == "y-pendulum-no-contact-static-reference"
    assert BUILD_METADATA["project"]["version"] == "1.1.0"


def test_production_tree_and_ast_are_static_only() -> None:
    production_files = sorted(PACKAGE_ROOT.rglob("*.py"))
    relative_files = {path.relative_to(PACKAGE_ROOT).as_posix() for path in production_files}
    assert relative_files == EXPECTED_PRODUCTION_FILES
    assert all(not path.is_symlink() for path in production_files)
    forbidden_path_fragments = (
        "contact",
        "dynamic",
        "g2_cases",
        "passivity",
        "invariance",
        "p3",
        "rc1",
    )
    assert all(
        fragment not in relative_path.lower()
        for relative_path in relative_files
        for fragment in forbidden_path_fragments
    )

    forbidden_identifier_fragments = (
        "hfv2",
        "velocity",
        "angular_velocity",
        "acceleration",
        "kinetic",
        "momentum",
        "drag",
        "damp",
        "dissipat",
        "power",
        "time_step",
        "timestep",
        "advance_rotation",
        "integrator",
        "contact_force",
        "contact_energy",
        "contact_solver",
        "friction",
        "collision",
        "restitution",
        "impact",
        "passivity",
    )
    forbidden_import_fragments = (
        "hfv2",
        "contact_assembly",
        "contact_solver",
        "friction",
        "collision",
        "dynamic",
        "p3r",
        "rc1",
        "passivity",
        "invariance",
    )
    for path in production_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        identifiers: list[str] = []
        imported_modules: list[str] = []
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
                imported_modules.extend(alias.name for alias in node.names)
                identifiers.extend(alias.asname or "" for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_modules.append(node.module or "")
                identifiers.extend(alias.name for alias in node.names)
                identifiers.extend(alias.asname or "" for alias in node.names)
            elif isinstance(node, ast.keyword) and node.arg is not None:
                identifiers.append(node.arg)
        assert all(
            fragment not in identifier.lower()
            for identifier in identifiers
            for fragment in forbidden_identifier_fragments
        ), path
        assert all(
            fragment not in module.lower()
            for module in imported_modules
            for fragment in forbidden_import_fragments
        ), path


def test_candidate_only_artifacts_are_excluded_and_historical_bytes_are_frozen() -> None:
    excluded = (
        PROJECT_ROOT / "outputs",
        PROJECT_ROOT / "runtime_matrix.json",
        PROJECT_ROOT / "migration_provenance.json",
        PROJECT_ROOT / "tools/generate_migration_provenance.py",
    )
    assert all(not path.exists() for path in excluded)
    historical = {
        "tests/fixtures/historical/g1r_acceptance_manifest.json": (
            "591a1950d7e40ebaf277950883152f5a11d6b0bf301a1ae82365541f7c2b5cfc"
        ),
        "tests/fixtures/historical/g2_acceptance_manifest.json": (
            "ba59e5ef8fb6b9f6a70ea3eefcb4536e192b6d6aff57185b2bcba38a64687a08"
        ),
    }
    for relative_path, expected_hash in historical.items():
        assert hashlib.sha256((PROJECT_ROOT / relative_path).read_bytes()).hexdigest() == (
            expected_hash
        )


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
