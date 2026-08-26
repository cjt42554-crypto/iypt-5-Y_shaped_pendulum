"""Deterministic, manifest-driven G1R evidence construction."""

from __future__ import annotations

import hashlib
import inspect
import json
import platform
from pathlib import Path
from typing import Any

import numpy as np

from ypendulum_hfv2 import MODEL_ID
from ypendulum_hfv2.audit.architecture import (
    FORBIDDEN_IMPORT_PREFIXES,
    FORBIDDEN_SOLVER_IMPORT_PREFIXES,
    audit_physical_core,
)
from ypendulum_hfv2.audit.energy_gradient import (
    GradientSample,
    central_difference_gradient,
    force_gradient_samples,
)
from ypendulum_hfv2.audit.invariance import internal_balance, objectivity_audit
from ypendulum_hfv2.constitutive.axial import AxialMaterial, axial_segment_response
from ypendulum_hfv2.constitutive.bending import (
    BendingGeometryError,
    bending_energy,
    bending_energy_forces,
)
from ypendulum_hfv2.mass import MassProperties
from ypendulum_hfv2.rigid.rotation import (
    SO3_ROUNDOFF_TOLERANCE,
    advance_rotation_body,
    exp_so3,
    rotation_metrics,
)
from ypendulum_hfv2.state import HFV2State
from ypendulum_hfv2.topology import HFV2Topology, MaterialNode, MaterialSegment


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strict_decrease_interval(
    errors: list[float], minimum_decrease_steps: int
) -> tuple[int, int] | None:
    """Find a consecutive decreasing interval ending no later than the first minimum."""

    if minimum_decrease_steps < 1:
        raise ValueError("minimum_decrease_steps must be positive.")
    if not errors or not all(np.isfinite(errors)):
        raise ValueError("errors must be a non-empty finite sequence.")
    first_minimum = int(np.argmin(errors))
    run_start = 0
    decrease_steps = 0
    for index in range(1, first_minimum + 1):
        if errors[index] < errors[index - 1]:
            if decrease_steps == 0:
                run_start = index - 1
            decrease_steps += 1
            if decrease_steps >= minimum_decrease_steps:
                return run_start, index
        else:
            decrease_steps = 0
    return None


def _gradient_metrics(
    samples: tuple[GradientSample, ...], finite_difference: dict[str, Any]
) -> dict[str, Any]:
    errors = [sample.relative_error for sample in samples]
    interval = strict_decrease_interval(
        errors, int(finite_difference["minimum_strict_decrease_steps"])
    )
    final_threshold = float(finite_difference["final_relative_error_max"])
    passed = errors[-1] <= final_threshold and interval is not None
    return {
        "relative_steps": [sample.relative_step for sample in samples],
        "absolute_steps": [sample.absolute_step for sample in samples],
        "relative_errors": errors,
        "final_relative_error": errors[-1],
        "final_relative_error_max": final_threshold,
        "strict_decrease_interval_indices": list(interval) if interval is not None else None,
        "minimum_strict_decrease_steps": int(
            finite_difference["minimum_strict_decrease_steps"]
        ),
        "status": "PASS" if passed else "FAIL",
    }


def _axial_gradient_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    case = manifest["gradient_cases"]["axial"]
    finite_difference = manifest["finite_difference"]
    points = np.asarray(case["points_m"], dtype=float)
    material = AxialMaterial(
        rest_length=float(case["rest_length_m"]),
        axial_rigidity=float(case["axial_rigidity_N"]),
        axial_viscosity=0.0,
    )

    def response(coordinates: np.ndarray):
        return axial_segment_response(
            coordinates[0], coordinates[1], np.zeros(3), np.zeros(3), material
        )

    base = response(points)
    force = np.vstack([base.force_on_start, base.force_on_end])
    samples = force_gradient_samples(
        lambda coordinates: response(coordinates).stored_energy,
        points,
        force,
        finite_difference["relative_step_sequence"],
        coordinate_scale=float(case["coordinate_scale_m"]),
    )
    return _gradient_metrics(samples, finite_difference)


def _bending_gradient_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    finite_difference = manifest["finite_difference"]
    results: dict[str, Any] = {}
    for case_id, case in manifest["gradient_cases"]["bending"].items():
        points = np.asarray(case["points_m"], dtype=float)
        rest = np.asarray(case["segment_rest_length_m"], dtype=float)
        stiffness = float(case["bending_stiffness_N_m2"])
        response = bending_energy_forces(points, rest, stiffness)
        samples = force_gradient_samples(
            lambda coordinates, rest=rest, stiffness=stiffness: bending_energy(
                coordinates, rest, stiffness
            ),
            points,
            response.forces,
            finite_difference["relative_step_sequence"],
            coordinate_scale=float(case["coordinate_scale_m"]),
        )
        results[case_id] = _gradient_metrics(samples, finite_difference)
    return results


def _bending_equation_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    contract = manifest["bending_equation"]
    stiffness = 0.12
    rest = np.ones(2)
    turn_energies: list[float] = []
    for offset in contract["turn_to_pi_offsets_rad"]:
        angle = np.pi - float(offset)
        points = np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0 + np.cos(angle), np.sin(angle), 0.0]]
        )
        turn_energies.append(bending_energy(points, rest, stiffness))
    turn_ratios = [
        right / left for left, right in zip(turn_energies[:-1], turn_energies[1:], strict=True)
    ]
    minimum_ratio = float(contract["minimum_successive_energy_ratio"])

    antiparallel = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.2, 0.0, 0.0]])
    exact_antiparallel_failed_from_denominator = False
    try:
        bending_energy_forces(antiparallel, rest, stiffness)
    except BendingGeometryError as error:
        exact_antiparallel_failed_from_denominator = "denominator" in str(error)

    collapsed = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    zero_antiparallel = bending_energy_forces(antiparallel, rest, 0.0)
    zero_collapsed = bending_energy_forces(collapsed, rest, 0.0)
    zero_branch_exact = (
        zero_antiparallel.energy == float(contract["zero_stiffness_exact_energy"])
        and zero_collapsed.energy == float(contract["zero_stiffness_exact_energy"])
        and np.array_equal(zero_antiparallel.forces, np.zeros_like(antiparallel))
        and np.array_equal(zero_collapsed.forces, np.zeros_like(collapsed))
        and zero_antiparallel.minimum_turn_clearance is None
        and zero_collapsed.minimum_turn_clearance is None
    )

    straight_points = np.column_stack([np.linspace(0.0, 1.5, 4), np.zeros((4, 2))])
    straight_rest = np.full(3, 0.5)
    straight_response = bending_energy_forces(straight_points, straight_rest, 0.2)
    straight_gradient = central_difference_gradient(
        lambda coordinates: bending_energy(coordinates, straight_rest, 0.2),
        straight_points,
        5.0e-7,
    )
    straight_exact = (
        straight_response.energy == 0.0
        and np.array_equal(straight_response.forces, np.zeros_like(straight_points))
        and np.array_equal(straight_gradient, np.zeros_like(straight_points))
    )

    radius = float(contract["circular_arc_radius_m"])
    total_angle = float(contract["circular_arc_total_angle_rad"])
    arc_stiffness = float(contract["circular_arc_stiffness_N_m2"])
    continuum_energy = 0.5 * arc_stiffness * total_angle / radius
    arc_errors: list[float] = []
    for segment_count in contract["circular_arc_segment_counts"]:
        angles = np.linspace(0.0, total_angle, int(segment_count) + 1)
        points = np.column_stack(
            [radius * np.sin(angles), radius * (1.0 - np.cos(angles)), np.zeros_like(angles)]
        )
        segment_rest = np.full(int(segment_count), radius * total_angle / int(segment_count))
        arc_errors.append(
            abs(bending_energy(points, segment_rest, arc_stiffness) - continuum_energy)
        )
    arc_strictly_decreasing = all(
        right < left for left, right in zip(arc_errors[:-1], arc_errors[1:], strict=True)
    )
    turn_pass = all(ratio >= minimum_ratio for ratio in turn_ratios)
    passed = (
        turn_pass
        and exact_antiparallel_failed_from_denominator
        and zero_branch_exact
        and straight_exact
        and arc_strictly_decreasing
    )
    return {
        "turn_to_pi_offsets_rad": contract["turn_to_pi_offsets_rad"],
        "turn_to_pi_energies_J": turn_energies,
        "successive_energy_ratios": turn_ratios,
        "minimum_successive_energy_ratio": minimum_ratio,
        "exact_antiparallel_failed_from_equation_denominator": (
            exact_antiparallel_failed_from_denominator
        ),
        "zero_stiffness_antiparallel_and_collapsed_exact_zero": zero_branch_exact,
        "straight_energy_force_and_centered_gradient_exact_zero": straight_exact,
        "circular_arc_segment_counts": contract["circular_arc_segment_counts"],
        "circular_arc_errors_J": arc_errors,
        "circular_arc_errors_strictly_decrease": arc_strictly_decreasing,
        "status": "PASS" if passed else "FAIL",
    }


def _balance_and_objectivity_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    case = manifest["gradient_cases"]["bending"]["three_dimensional"]
    points = np.asarray(case["points_m"], dtype=float)
    rest = np.asarray(case["segment_rest_length_m"], dtype=float)
    stiffness = float(case["bending_stiffness_N_m2"])
    response = bending_energy_forces(points, rest, stiffness)
    force_scale = float(np.linalg.norm(response.forces))
    balance = internal_balance(
        points,
        response.forces,
        np.array([-0.8, 0.4, 1.2]),
        force_scale=force_scale,
        length_scale=float(np.sum(rest)),
    )
    balance_contract = manifest["balance"]
    balance_pass = (
        balance.scaled_force_resultant
        <= float(balance_contract["scaled_force_resultant_max"])
        and balance.scaled_moment_resultant
        <= float(balance_contract["scaled_moment_resultant_max"])
    )

    def energy_and_force(coordinates: np.ndarray) -> tuple[float, np.ndarray]:
        candidate = bending_energy_forces(coordinates, rest, stiffness)
        return candidate.energy, candidate.forces

    objectivity_contract = manifest["objectivity"]
    objectivity = objectivity_audit(
        energy_and_force,
        points,
        exp_so3(np.asarray(objectivity_contract["rotation_vector_rad"], dtype=float)),
        np.asarray(objectivity_contract["translation_m"], dtype=float),
        energy_scale=response.energy,
        force_scale=force_scale,
    )
    objectivity_pass = (
        objectivity.relative_energy_change
        <= float(objectivity_contract["relative_energy_change_max"])
        and objectivity.relative_force_covariance_error
        <= float(objectivity_contract["relative_force_covariance_error_max"])
    )
    return {
        "internal_balance": {
            "scaled_force_resultant": balance.scaled_force_resultant,
            "scaled_force_resultant_max": balance_contract["scaled_force_resultant_max"],
            "scaled_moment_resultant": balance.scaled_moment_resultant,
            "scaled_moment_resultant_max": balance_contract["scaled_moment_resultant_max"],
            "status": "PASS" if balance_pass else "FAIL",
        },
        "objectivity": {
            "relative_energy_change": objectivity.relative_energy_change,
            "relative_energy_change_max": objectivity_contract["relative_energy_change_max"],
            "relative_force_covariance_error": objectivity.relative_force_covariance_error,
            "relative_force_covariance_error_max": objectivity_contract[
                "relative_force_covariance_error_max"
            ],
            "status": "PASS" if objectivity_pass else "FAIL",
        },
    }


def _material_reference_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    coarse = (
        MaterialSegment("coarse", "branch", "support", "bob", 0.0, 1.0),
    )
    refined = (
        MaterialSegment("left", "branch", "support", "mid", 0.0, 0.4),
        MaterialSegment("right", "branch", "mid", "bob", 0.4, 1.0),
    )
    coarse_topology = HFV2Topology(
        nodes=(MaterialNode("support", "prescribed"), MaterialNode("bob", "bob_attachment")),
        segments=coarse,
    )
    refined_topology = HFV2Topology(
        nodes=(
            MaterialNode("support", "prescribed"),
            MaterialNode("mid", "free"),
            MaterialNode("bob", "bob_attachment"),
        ),
        segments=refined,
    )
    independent_rest_length_absent = (
        "rest_length" not in MaterialSegment.__dataclass_fields__
        and "rest_length" not in inspect.signature(MaterialSegment).parameters
    )
    inconsistent_constructor_rejected = False
    try:
        MaterialSegment(
            "bad", "branch", "support", "bob", 0.0, 1.0, rest_length=0.7
        )
    except TypeError:
        inconsistent_constructor_rejected = True

    density_per_length = 0.23
    axial_rigidity = 120.0
    coarse_mass = sum(density_per_length * segment.rest_length for segment in coarse)
    refined_mass = sum(density_per_length * segment.rest_length for segment in refined)
    coarse_series_stiffness = 1.0 / sum(
        segment.rest_length / axial_rigidity for segment in coarse
    )
    refined_series_stiffness = 1.0 / sum(
        segment.rest_length / axial_rigidity for segment in refined
    )
    tolerance = float(manifest["material_reference"]["subdivision_tolerance"])
    branch_span_consistent = (
        abs(sum(segment.rest_length for segment in refined) - 1.0) <= tolerance
        and abs(refined_topology.branch_rest_length("branch") - 1.0) <= tolerance
    )
    subdivision_consistent = (
        abs(coarse_topology.branch_rest_length("branch") - 1.0) <= tolerance
        and abs(coarse_mass - refined_mass) <= tolerance
        and abs(coarse_series_stiffness - refined_series_stiffness) <= tolerance
    )
    passed = (
        independent_rest_length_absent
        and inconsistent_constructor_rejected
        and branch_span_consistent
        and subdivision_consistent
    )
    return {
        "independent_rest_length_field_absent": independent_rest_length_absent,
        "inconsistent_rest_length_constructor_rejected": inconsistent_constructor_rejected,
        "refined_branch_rest_length_m": sum(segment.rest_length for segment in refined),
        "refined_branch_material_span_m": refined_topology.branch_rest_length("branch"),
        "coarse_mass_allocation_kg": coarse_mass,
        "refined_mass_allocation_kg": refined_mass,
        "coarse_equivalent_axial_stiffness_N_per_m": coarse_series_stiffness,
        "refined_equivalent_axial_stiffness_N_per_m": refined_series_stiffness,
        "status": "PASS" if passed else "FAIL",
    }


def _layout_and_mass_metrics() -> dict[str, Any]:
    nodes = (
        MaterialNode("support", "prescribed"),
        MaterialNode("free_a", "free"),
        MaterialNode("free_b", "free"),
        MaterialNode("bob", "bob_attachment"),
    )
    segments = (
        MaterialSegment("s0", "branch", "support", "free_a", 0.0, 0.3),
        MaterialSegment("s1", "branch", "free_a", "free_b", 0.3, 0.7),
        MaterialSegment("s2", "branch", "free_b", "bob", 0.7, 1.0),
    )
    topology = HFV2Topology(nodes=nodes, segments=segments)
    permuted_topology = HFV2Topology(
        nodes=(nodes[0], nodes[2], nodes[1], nodes[3]), segments=segments
    )
    state = HFV2State(
        free_node_ids=topology.free_node_ids,
        free_node_positions=np.zeros((2, 3)),
        free_node_velocities=np.zeros((2, 3)),
        bob_position=np.zeros(3),
        bob_velocity=np.zeros(3),
        bob_rotation=np.eye(3),
        bob_angular_velocity_body=np.zeros(3),
    )
    mass = MassProperties(
        free_node_ids=topology.free_node_ids,
        free_node_mass=np.array([0.1, 0.2]),
        bob_mass=0.5,
        bob_inertia_body=np.diag([0.02, 0.025, 0.03]),
    )
    state.validate_topology(topology)
    mass.validate_topology(topology)
    mass.validate_state(state)

    state_permutation_rejected = False
    mass_permutation_rejected = False
    try:
        state.validate_topology(permuted_topology)
    except ValueError:
        state_permutation_rejected = True
    try:
        mass.validate_topology(permuted_topology)
    except ValueError:
        mass_permutation_rejected = True

    unrealizable_inertia_rejected = False
    try:
        MassProperties(("node",), np.ones(1), 1.0, np.diag([1.0, 1.0, 3.0]))
    except ValueError:
        unrealizable_inertia_rejected = True

    nonfinite_momentum_rejected = False
    try:
        mass.total_linear_momentum(np.array([[np.nan, 0.0, 0.0], [0.0, 0.0, 0.0]]), np.zeros(3))
    except ValueError:
        nonfinite_momentum_rejected = True

    passed = (
        state_permutation_rejected
        and mass_permutation_rejected
        and unrealizable_inertia_rejected
        and nonfinite_momentum_rejected
    )
    return {
        "bound_free_node_ids": list(topology.free_node_ids),
        "permuted_free_node_ids": list(permuted_topology.free_node_ids),
        "state_permutation_rejected": state_permutation_rejected,
        "mass_permutation_rejected": mass_permutation_rejected,
        "unrealizable_positive_definite_inertia_rejected": unrealizable_inertia_rejected,
        "nonfinite_momentum_input_rejected": nonfinite_momentum_rejected,
        "status": "PASS" if passed else "FAIL",
    }


def _rotation_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    contract = manifest["rotation"]
    tolerance = float(contract["shared_roundoff_tolerance"])
    cases: list[dict[str, Any]] = []
    for case in contract["sequences"]:
        rotation = np.eye(3)
        angular_velocity = np.asarray(case["angular_velocity_body_rad_per_s"], dtype=float)
        for _ in range(int(case["update_count"])):
            rotation = advance_rotation_body(rotation, angular_velocity, float(case["time_step_s"]))
        metrics = rotation_metrics(rotation)
        passed = (
            metrics.orthogonality_error <= tolerance
            and metrics.determinant_error <= tolerance
        )
        cases.append(
            {
                "case_id": case["case_id"],
                "time_step_s": case["time_step_s"],
                "update_count": case["update_count"],
                "orthogonality_error": metrics.orthogonality_error,
                "determinant_error": metrics.determinant_error,
                "status": "PASS" if passed else "FAIL",
            }
        )
    contract_matches_source = tolerance == SO3_ROUNDOFF_TOLERANCE
    passed = contract_matches_source and all(case["status"] == "PASS" for case in cases)
    return {
        "shared_roundoff_tolerance": tolerance,
        "source_contract_matches_manifest": contract_matches_source,
        "normalization_or_projection_allowed": contract[
            "normalization_or_projection_allowed"
        ],
        "sequences": cases,
        "status": "PASS" if passed else "FAIL",
    }


def _architecture_metrics(candidate_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    package_root = candidate_root / "src" / "ypendulum_hfv2"
    module_manifest_path = candidate_root / manifest["module_manifest"]
    audit = audit_physical_core(package_root, module_manifest_path)
    contract = manifest["architecture"]
    contract_matches_source = (
        set(contract["forbidden_import_prefixes"]) == set(FORBIDDEN_IMPORT_PREFIXES)
        and set(contract["forbidden_solver_import_prefixes"])
        == set(FORBIDDEN_SOLVER_IMPORT_PREFIXES)
    )
    passed = (
        audit.passed
        and contract_matches_source
        and len(audit.unclassified_files) <= int(contract["unclassified_file_count_max"])
        and len(audit.missing_manifest_files)
        <= int(contract["missing_manifest_file_count_max"])
        and audit.try_statement_count
        <= int(contract["scanned_core_try_statement_count_max"])
        and audit.random_call_count <= int(contract["scanned_core_random_call_count_max"])
    )
    return {
        "auto_discovered_files": list(audit.discovered_files),
        "classified_files": list(audit.classified_files),
        "scanned_dependency_clean_core_files": list(audit.files),
        "unclassified_files": list(audit.unclassified_files),
        "missing_manifest_files": list(audit.missing_manifest_files),
        "forbidden_imports": list(audit.forbidden_imports),
        "solver_imports": list(audit.solver_imports),
        "scanned_core_try_statement_count": audit.try_statement_count,
        "scanned_core_random_call_count": audit.random_call_count,
        "manifest_forbidden_prefixes_match_auditor": contract_matches_source,
        "claim_scope": (
            "The classified dependency-clean production files contain no forbidden imports, "
            "SciPy solver imports, try statements, or random calls; this is not a proof that "
            "arbitrary fallback behavior is impossible."
        ),
        "status": "PASS" if passed else "FAIL",
    }


def build_g1r_evidence(candidate_root: str | Path) -> dict[str, Any]:
    """Recompute all manifest-bound G1R local evidence from the current source."""

    root = Path(candidate_root).resolve()
    acceptance_path = root / "contracts" / "g1r_acceptance_manifest.json"
    model_identity_path = root / "contracts" / "model_identity_0_2.json"
    manifest = _load_json(acceptance_path)
    model_identity = _load_json(model_identity_path)
    if manifest["model_id"] != MODEL_ID or model_identity["model_id"] != MODEL_ID:
        raise ValueError("G1R manifest, model identity and package MODEL_ID must match exactly.")

    axial_gradient = _axial_gradient_metrics(manifest)
    bending_gradient = _bending_gradient_metrics(manifest)
    bending_equation = _bending_equation_metrics(manifest)
    balance_objectivity = _balance_and_objectivity_metrics(manifest)
    material_reference = _material_reference_metrics(manifest)
    layout_and_mass = _layout_and_mass_metrics()
    rotation = _rotation_metrics(manifest)
    architecture = _architecture_metrics(root, manifest)

    component_statuses = [
        axial_gradient["status"],
        *(case["status"] for case in bending_gradient.values()),
        bending_equation["status"],
        balance_objectivity["internal_balance"]["status"],
        balance_objectivity["objectivity"]["status"],
        material_reference["status"],
        layout_and_mass["status"],
        rotation["status"],
        architecture["status"],
    ]
    passed = all(status == "PASS" for status in component_statuses)

    source_paths = tuple(
        sorted((root / "src" / "ypendulum_hfv2").rglob("*.py"))
    )
    source_hashes = {
        path.relative_to(root).as_posix(): _sha256(path) for path in source_paths
    }
    historical_paths = (
        root / "reports" / "G1_REPORT.md",
        root / "reports" / "g1_metrics.json",
        root / "contracts" / "acceptance_manifest.json",
        root / "contracts" / "model_identity.json",
        root / "contracts" / "baseline_sources.json",
    )
    tool_path = root / "tools" / "generate_g1r_evidence.py"
    return {
        "schema": "YPS-HFV2-G1R-METRICS-1.0",
        "model_id": MODEL_ID,
        "status": (
            "PASS_G1R_LOCAL_MODEL_CONTRACT_ONLY"
            if passed
            else "FAIL_G1R_LOCAL_MODEL_CONTRACT"
        ),
        "allowed_claim": manifest["allowed_claim"] if passed else "G1R_LOCAL_GATE_FAILED",
        "evidence_binding": {
            "command": "python tools/generate_g1r_evidence.py --check",
            "acceptance_manifest": "contracts/g1r_acceptance_manifest.json",
            "acceptance_manifest_sha256": _sha256(acceptance_path),
            "module_manifest": manifest["module_manifest"],
            "module_manifest_sha256": _sha256(root / manifest["module_manifest"]),
            "model_identity": "contracts/model_identity_0_2.json",
            "model_identity_sha256": _sha256(model_identity_path),
            "evidence_generator": "tools/generate_g1r_evidence.py",
            "evidence_generator_sha256": _sha256(tool_path),
            "source_sha256": source_hashes,
            "historical_g1_artifact_sha256": {
                path.relative_to(root).as_posix(): _sha256(path) for path in historical_paths
            },
        },
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
        },
        "axial_gradient": axial_gradient,
        "bending_gradient": bending_gradient,
        "bending_equation": bending_equation,
        **balance_objectivity,
        "material_reference": material_reference,
        "layout_and_mass": layout_and_mass,
        "rotation_group": rotation,
        "architecture": architecture,
        "evidence_level": "local_formula_contract_and_static_source_checks",
        "formal_numerical_qualification": "HF_NUMERICAL_QUALIFICATION_NO_GO",
        "dynamic_contact": "CLOSED_PENDING_PRO_REVIEW",
    }


def canonical_evidence_text(evidence: dict[str, Any]) -> str:
    return json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
