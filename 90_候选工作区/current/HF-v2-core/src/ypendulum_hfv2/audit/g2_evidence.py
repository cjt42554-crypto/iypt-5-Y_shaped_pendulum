"""Deterministic manifest-driven evidence for the HF-v2 P2 / G2 stop gate."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import scipy

from ypendulum_hfv2 import MODEL_ID
from ypendulum_hfv2.audit.clearance import audit_clearance
from ypendulum_hfv2.audit.dependency import audit_g2_dependencies
from ypendulum_hfv2.audit.g2_cases import (
    YAnchorCase,
    build_vertical_case,
    build_y_anchor_case,
)
from ypendulum_hfv2.audit.statics import (
    balance_audit,
    energy_force_samples,
    force_scale,
    independent_hessian_audit,
    strict_decrease_interval,
)
from ypendulum_hfv2.statics.assembly import StaticAssembly
from ypendulum_hfv2.statics.solver import (
    StaticSolveResult,
    StaticSolverSettings,
    solve_deterministic_seeds,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _solver_settings(manifest: dict[str, Any]) -> StaticSolverSettings:
    contract = manifest["primary_solver"]
    return StaticSolverSettings(
        method=str(contract["method"]),
        gradient_infinity_tolerance=float(
            contract["gradient_infinity_tolerance"]
        ),
        maximum_iterations=int(contract["maximum_iterations"]),
        x_relative_tolerance=float(contract["x_relative_tolerance"]),
        armijo_c1=float(contract["armijo_c1"]),
        curvature_c2=float(contract["curvature_c2"]),
    )


def _architecture_metrics(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    package_root = root / "src" / "ypendulum_hfv2"
    module_manifest = root / str(manifest["module_manifest"])
    audit = audit_g2_dependencies(package_root, module_manifest)
    line_counts = {
        relative: len((package_root / relative).read_text(encoding="utf-8").splitlines())
        for relative in audit.discovered_files
    }
    line_limit = int(manifest["architecture"]["source_lines_per_module_max_exclusive"])
    line_count_pass = all(value < line_limit for value in line_counts.values())
    passed = audit.passed and line_count_pass
    return {
        "discovered_files": list(audit.discovered_files),
        "classified_files": list(audit.classified_files),
        "unclassified_files": list(audit.unclassified_files),
        "missing_manifest_files": list(audit.missing_manifest_files),
        "canonical_imports": {
            relative: list(imports) for relative, imports in audit.canonical_imports
        },
        "dependency_violations": [
            {
                "source_path": violation.source_path,
                "source_classification": violation.source_classification,
                "imported_name": violation.imported_name,
                "target_classification": violation.target_classification,
                "reason": violation.reason,
            }
            for violation in audit.dependency_violations
        ],
        "path_classification_violations": list(
            audit.path_classification_violations
        ),
        "production_try_statement_count": audit.production_try_statement_count,
        "production_random_call_count": audit.production_random_call_count,
        "source_line_counts": line_counts,
        "source_lines_per_module_max_exclusive": line_limit,
        "line_count_status": "PASS" if line_count_pass else "FAIL",
        "status": "PASS" if passed else "FAIL",
    }


def _layout_metrics(assembly: StaticAssembly, manifest: dict[str, Any]) -> dict[str, Any]:
    rest_errors = assembly.rest_binding_errors()
    mass_error = abs(
        assembly.total_reference_material_mass()
        - assembly.expected_reference_material_mass()
    )
    volume_error = abs(
        assembly.total_reference_displaced_volume()
        - assembly.expected_reference_displaced_volume()
    )
    rest_max = float(np.max(np.abs(rest_errors), initial=0.0))
    expected_slices = {
        node_id: [assembly.layout.free_slice(node_id).start, assembly.layout.free_slice(node_id).stop]
        for node_id in assembly.layout.free_node_ids
    }
    expected_slices["bob_position"] = [
        assembly.layout.bob_position_slice.start,
        assembly.layout.bob_position_slice.stop,
    ]
    expected_slices["bob_rotation_body"] = [
        assembly.layout.bob_rotation_slice.start,
        assembly.layout.bob_rotation_slice.stop,
    ]
    passed = (
        rest_max
        <= float(manifest["material_reference"]["exact_binding_absolute_error_max_m"])
        and mass_error
        <= float(manifest["mass_lumping"]["total_mass_absolute_error_max_kg"])
        and volume_error
        <= float(
            manifest["mass_lumping"]["total_displaced_volume_absolute_error_max_m3"]
        )
        and assembly.mass_properties.free_node_ids == assembly.topology.free_node_ids
        and assembly.reference_state.free_node_ids == assembly.topology.free_node_ids
        and assembly.layout.segment_ids
        == tuple(segment.segment_id for segment in assembly.topology.segments)
        and assembly.layout.generalized_size
        == assembly.topology.generalized_position_tangent_size
    )
    return {
        "layout_token": assembly.layout.layout_token,
        "node_ids": list(assembly.layout.node_ids),
        "free_node_ids": list(assembly.layout.free_node_ids),
        "segment_ids": list(assembly.layout.segment_ids),
        "segment_rest_lengths_m": assembly.layout.segment_rest_lengths.tolist(),
        "coordinate_slices": expected_slices,
        "generalized_size": assembly.layout.generalized_size,
        "node_lumped_mass_kg": assembly.node_mass.tolist(),
        "node_lumped_displaced_volume_m3": assembly.node_displaced_volume.tolist(),
        "rest_binding_max_absolute_error_m": rest_max,
        "material_mass_total_kg": assembly.total_reference_material_mass(),
        "material_mass_expected_kg": assembly.expected_reference_material_mass(),
        "material_mass_absolute_error_kg": mass_error,
        "material_volume_total_m3": assembly.total_reference_displaced_volume(),
        "material_volume_expected_m3": assembly.expected_reference_displaced_volume(),
        "material_volume_absolute_error_m3": volume_error,
        "status": "PASS" if passed else "FAIL",
    }


def _energy_force_metrics(
    case: YAnchorCase,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    contract = manifest["finite_difference"]
    probe = case.assembly.coordinates_from_seed(case.seeds[1])
    samples = energy_force_samples(
        case.assembly,
        probe,
        tuple(float(value) for value in contract["relative_step_sequence"]),
    )
    errors = tuple(sample.relative_error for sample in samples)
    interval = strict_decrease_interval(
        errors,
        int(contract["minimum_strict_decrease_steps"]),
    )
    passed = (
        errors[-1] <= float(contract["final_relative_error_max"])
        and interval is not None
    )
    return {
        "case_id": manifest["y_anchor"]["case_id"],
        "probe_seed_id": case.seeds[1].seed_id,
        "probe_rotation_vector_rad": case.seeds[1].bob_rotation_vector.tolist(),
        "relative_steps": [sample.relative_step for sample in samples],
        "relative_errors": list(errors),
        "final_relative_error": errors[-1],
        "final_relative_error_max": contract["final_relative_error_max"],
        "strict_decrease_interval_indices": list(interval) if interval else None,
        "minimum_strict_decrease_steps": contract["minimum_strict_decrease_steps"],
        "status": "PASS" if passed else "FAIL",
    }


def _hessian_metrics(
    assembly: StaticAssembly,
    result: StaticSolveResult,
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    contract = manifest["second_order_audit"]
    audit = independent_hessian_audit(
        assembly,
        result.coordinates,
        normalized_step=float(contract["normalized_step"]),
        directional_energy_step=float(contract["directional_energy_step"]),
        direction_count=int(contract["direction_count"]),
    )
    max_gauge = float(np.max(np.abs(audit.gauge_curvatures), initial=0.0))
    min_nongauge = float(np.min(audit.nongauge_eigenvalues))
    min_directional = float(np.min(audit.directional_curvatures))
    passed = (
        audit.unsymmetrized_relative_asymmetry
        <= float(contract["unsymmetrized_relative_asymmetry_max"])
        and max_gauge <= float(contract["gauge_eigenvalue_absolute_max"])
        and min_nongauge
        >= float(contract["minimum_nongauge_normalized_eigenvalue"])
        and min_directional
        >= float(contract["minimum_normalized_directional_curvature"])
    )
    return (
        {
            "normalization_energy_J": force_scale(assembly),
            "unsymmetrized_relative_asymmetry": audit.unsymmetrized_relative_asymmetry,
            "unsymmetrized_relative_asymmetry_max": contract[
                "unsymmetrized_relative_asymmetry_max"
            ],
            "gauge_curvatures": audit.gauge_curvatures.tolist(),
            "maximum_absolute_gauge_curvature": max_gauge,
            "gauge_eigenvalue_absolute_max": contract[
                "gauge_eigenvalue_absolute_max"
            ],
            "nongauge_eigenvalues": audit.nongauge_eigenvalues.tolist(),
            "minimum_nongauge_normalized_eigenvalue": min_nongauge,
            "minimum_nongauge_normalized_eigenvalue_required": contract[
                "minimum_nongauge_normalized_eigenvalue"
            ],
            "directional_curvatures": audit.directional_curvatures.tolist(),
            "minimum_normalized_directional_curvature": min_directional,
            "minimum_normalized_directional_curvature_required": contract[
                "minimum_normalized_directional_curvature"
            ],
            "status": "PASS" if passed else "FAIL",
        },
        passed,
    )


def _vertical_metrics(
    root: Path,
    manifest: dict[str, Any],
    settings: StaticSolverSettings,
) -> dict[str, Any]:
    del root
    case = build_vertical_case(manifest)
    result = solve_deterministic_seeds(case.assembly, case.seeds, settings)[0]
    evaluation = result.evaluation
    expectation = case.expectation
    contract = manifest["analytic_vertical_case"]
    position_error = float(np.linalg.norm(evaluation.bob_position - expectation.bob_position_m))
    reaction_error = float(
        np.linalg.norm(evaluation.support_reactions[0] - expectation.support_reaction_N)
    )
    tension_error = abs(float(evaluation.segment_tensions[0]) - expectation.tension_N)
    balance = balance_audit(case.assembly, evaluation)
    hessian, hessian_pass = _hessian_metrics(case.assembly, result, manifest)
    normalized_expected = (
        expectation.physical_translation_hessian_eigenvalues / force_scale(case.assembly)
    )
    actual = np.asarray(hessian["nongauge_eigenvalues"], dtype=float)
    hessian_relative_error = float(
        np.linalg.norm(actual - normalized_expected)
        / np.linalg.norm(normalized_expected)
    )
    passed = (
        position_error <= float(contract["position_absolute_error_max_m"])
        and reaction_error <= float(contract["reaction_absolute_error_max_N"])
        and balance.scaled_generalized_force_residual * balance.force_scale_N
        <= float(contract["force_residual_max_N"])
        and hessian_relative_error
        <= float(contract["physical_hessian_relative_error_max"])
        and len(hessian["gauge_curvatures"])
        == int(contract["expected_rotation_gauge_nullity"])
        and hessian_pass
    )
    return {
        "case_id": contract["case_id"],
        "optimizer": {
            "success_record_only": result.optimizer_success,
            "status": result.optimizer_status,
            "message": result.optimizer_message,
            "iterations": result.iterations,
            "function_evaluations": result.function_evaluations,
            "gradient_evaluations": result.gradient_evaluations,
        },
        "expected_bob_position_m": expectation.bob_position_m.tolist(),
        "computed_bob_position_m": evaluation.bob_position.tolist(),
        "position_absolute_error_m": position_error,
        "position_absolute_error_max_m": contract["position_absolute_error_max_m"],
        "expected_support_reaction_N": expectation.support_reaction_N.tolist(),
        "computed_support_reaction_N": evaluation.support_reactions[0].tolist(),
        "reaction_absolute_error_N": reaction_error,
        "reaction_absolute_error_max_N": contract["reaction_absolute_error_max_N"],
        "expected_tension_N": expectation.tension_N,
        "computed_tension_N": float(evaluation.segment_tensions[0]),
        "tension_absolute_error_N": tension_error,
        "generalized_force_residual_N": float(
            np.linalg.norm(evaluation.generalized_force, ord=np.inf)
        ),
        "generalized_force_residual_max_N": contract["force_residual_max_N"],
        "global_force_closure_residual_N": balance.global_force_closure_residual_N.tolist(),
        "global_moment_closure_residual_N_m": balance.global_moment_closure_residual_N_m.tolist(),
        "raw_equilibrium_force_residual_N": balance.raw_equilibrium_force_residual_N.tolist(),
        "raw_equilibrium_moment_residual_N_m": balance.raw_equilibrium_moment_residual_N_m.tolist(),
        "expected_normalized_physical_hessian_eigenvalues": normalized_expected.tolist(),
        "physical_hessian_relative_error": hessian_relative_error,
        "physical_hessian_relative_error_max": contract[
            "physical_hessian_relative_error_max"
        ],
        "layout_mass_and_rest_binding": _layout_metrics(case.assembly, manifest),
        "second_order": hessian,
        "status": "PASS" if passed else "FAIL",
    }


def _candidate_metrics(
    case: YAnchorCase,
    result: StaticSolveResult,
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    evaluation = result.evaluation
    y_contract = manifest["y_anchor"]
    clearance_contract = manifest["clearance_audit"]
    clearance = audit_clearance(
        case.assembly,
        evaluation,
        cable_radius_m=float(clearance_contract["cable_radius_m"]),
        bob_radius_m=float(y_contract["bob_radius_m"]),
        same_branch_material_exclusion_m=float(
            clearance_contract["same_branch_material_exclusion_m"]
        ),
        junction_socket_material_exclusion_m=float(
            clearance_contract["junction_socket_material_exclusion_m"]
        ),
        bob_socket_material_exclusion_m=float(
            clearance_contract["bob_socket_material_exclusion_m"]
        ),
    )
    balance = balance_audit(case.assembly, evaluation)
    hessian, hessian_pass = _hessian_metrics(case.assembly, result, manifest)
    min_extension = float(np.min(evaluation.segment_extensions))
    min_tension = float(np.min(evaluation.segment_tensions))
    min_length = float(np.min(evaluation.segment_current_lengths))
    min_curvature = float(
        min(value for _, value in evaluation.branch_minimum_curvature_denominators)
    )
    rest_lengths = case.assembly.layout.segment_rest_lengths
    engineering_strain = evaluation.segment_extensions / rest_lengths
    extension_fraction = evaluation.segment_extensions / evaluation.segment_current_lengths
    current_to_rest = evaluation.segment_current_lengths / rest_lengths
    extension_fraction_identity_error = float(
        np.max(
            np.abs(
                extension_fraction
                - engineering_strain / (1.0 + engineering_strain)
            ),
            initial=0.0,
        )
    )
    stretch_identity_error = float(
        np.max(np.abs(current_to_rest - (1.0 + engineering_strain)), initial=0.0)
    )
    passed = (
        balance.scaled_generalized_force_residual
        <= float(y_contract["scaled_generalized_force_residual_max"])
        and balance.scaled_global_force_balance
        <= float(y_contract["scaled_global_force_balance_max"])
        and balance.scaled_global_moment_balance
        <= float(y_contract["scaled_global_moment_balance_max"])
        and min_extension >= float(y_contract["minimum_extension_m"])
        and min_tension >= float(y_contract["minimum_tension_N"])
        and min_length >= float(y_contract["minimum_segment_length_m"])
        and min_curvature >= float(y_contract["minimum_curvature_denominator"])
        and clearance.minimum_net_clearance_m
        >= float(clearance_contract["minimum_net_clearance_m"])
        and len(hessian["gauge_curvatures"])
        == int(manifest["coordinate_chart"]["expected_y_anchor_gauge_nullity"])
        and hessian_pass
    )
    junction_position = evaluation.node_positions[
        case.assembly.topology.node_index(case.junction_id)
    ]
    shape = np.concatenate(
        [junction_position, evaluation.attachment_position, evaluation.bob_position]
    )
    return (
        {
            "seed_id": result.seed_id,
            "optimizer": {
                "success_record_only": result.optimizer_success,
                "status": result.optimizer_status,
                "message": result.optimizer_message,
                "iterations": result.iterations,
                "function_evaluations": result.function_evaluations,
                "gradient_evaluations": result.gradient_evaluations,
            },
            "total_potential_J": evaluation.total_potential,
            "energy_components_J": dict(evaluation.energy_components),
            "scaled_generalized_force_residual": balance.scaled_generalized_force_residual,
            "scaled_generalized_force_residual_max": y_contract[
                "scaled_generalized_force_residual_max"
            ],
            "scaled_global_force_balance": balance.scaled_global_force_balance,
            "scaled_global_force_balance_max": y_contract[
                "scaled_global_force_balance_max"
            ],
            "scaled_global_moment_balance": balance.scaled_global_moment_balance,
            "scaled_global_moment_balance_max": y_contract[
                "scaled_global_moment_balance_max"
            ],
            "global_force_closure_residual_N": balance.global_force_closure_residual_N.tolist(),
            "global_moment_closure_residual_N_m": balance.global_moment_closure_residual_N_m.tolist(),
            "raw_equilibrium_force_residual_N": balance.raw_equilibrium_force_residual_N.tolist(),
            "raw_equilibrium_moment_residual_N_m": balance.raw_equilibrium_moment_residual_N_m.tolist(),
            "minimum_extension_m": min_extension,
            "minimum_extension_required_m": y_contract["minimum_extension_m"],
            "minimum_tension_N": min_tension,
            "minimum_tension_required_N": y_contract["minimum_tension_N"],
            "minimum_segment_length_m": min_length,
            "minimum_segment_length_required_m": y_contract[
                "minimum_segment_length_m"
            ],
            "minimum_curvature_denominator": min_curvature,
            "minimum_curvature_denominator_required": y_contract[
                "minimum_curvature_denominator"
            ],
            "clearance": {
                "role": clearance_contract["role"],
                "rod_rod_centerline_distance_m": clearance.rod_rod_centerline_distance_m,
                "rod_rod_net_clearance_m": clearance.rod_rod_net_clearance_m,
                "bob_rod_centerline_distance_m": clearance.bob_rod_centerline_distance_m,
                "bob_rod_net_clearance_m": clearance.bob_rod_net_clearance_m,
                "minimum_net_clearance_m": clearance.minimum_net_clearance_m,
                "minimum_net_clearance_required_m": clearance_contract[
                    "minimum_net_clearance_m"
                ],
                "evaluated_rod_pair_domains": clearance.evaluated_rod_pair_domains,
                "evaluated_bob_segment_domains": clearance.evaluated_bob_segment_domains,
            },
            "junction_attachment_bob_shape_m": shape.tolist(),
            "two_support_reactions_N": evaluation.support_reactions.reshape(-1).tolist(),
            "segment_extensions_m": evaluation.segment_extensions.tolist(),
            "segment_tensions_N": evaluation.segment_tensions.tolist(),
            "segment_current_lengths_m": evaluation.segment_current_lengths.tolist(),
            "dimensionless_segment_diagnostics": {
                "engineering_strain": engineering_strain.tolist(),
                "engineering_strain_minimum": float(np.min(engineering_strain)),
                "engineering_strain_maximum": float(np.max(engineering_strain)),
                "extension_fraction_of_current_length": extension_fraction.tolist(),
                "extension_fraction_of_current_length_minimum": float(
                    np.min(extension_fraction)
                ),
                "extension_fraction_of_current_length_maximum": float(
                    np.max(extension_fraction)
                ),
                "current_to_rest_length_ratio": current_to_rest.tolist(),
                "current_to_rest_length_ratio_minimum": float(np.min(current_to_rest)),
                "current_to_rest_length_ratio_maximum": float(np.max(current_to_rest)),
                "extension_fraction_identity_max_absolute_error": (
                    extension_fraction_identity_error
                ),
                "stretch_identity_max_absolute_error": stretch_identity_error,
            },
            "branch_minimum_curvature_denominators": dict(
                evaluation.branch_minimum_curvature_denominators
            ),
            "second_order": hessian,
            "independent_gate_status": "PASS" if passed else "FAIL",
        },
        passed,
    )


def _maximum_pairwise_distance(vectors: list[np.ndarray]) -> float:
    if len(vectors) < 2:
        return 0.0
    return float(max(np.linalg.norm(left - right) for left, right in combinations(vectors, 2)))


def _mesh_metrics(
    case: YAnchorCase,
    manifest: dict[str, Any],
    settings: StaticSolverSettings,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    results = solve_deterministic_seeds(case.assembly, case.seeds, settings)
    candidate_documents: list[dict[str, Any]] = []
    candidate_pass: list[bool] = []
    for result in results:
        document, passed = _candidate_metrics(case, result, manifest)
        candidate_documents.append(document)
        candidate_pass.append(passed)
    qualified = [
        (result, document)
        for result, document, passed in zip(
            results,
            candidate_documents,
            candidate_pass,
            strict=True,
        )
        if passed
    ]
    selected_pair = (
        min(
            qualified,
            key=lambda pair: (pair[0].evaluation.total_potential, pair[0].seed_id),
        )
        if qualified
        else None
    )
    shapes = [
        np.asarray(document["junction_attachment_bob_shape_m"], dtype=float)
        for document in candidate_documents
    ]
    energies = [float(document["total_potential_J"]) for document in candidate_documents]
    shape_spread = _maximum_pairwise_distance(shapes)
    energy_spread = float(max(energies) - min(energies))
    y_contract = manifest["y_anchor"]
    multiseed_pass = (
        shape_spread
        <= float(y_contract["gauge_invariant_multiseed_shape_spread_max_m"])
        and energy_spread <= float(y_contract["multiseed_energy_spread_max_J"])
        and all(candidate_pass)
        and selected_pair is not None
    )
    layout = _layout_metrics(case.assembly, manifest)
    passed = multiseed_pass and layout["status"] == "PASS"
    selected_document = selected_pair[1] if selected_pair is not None else None
    observables: dict[str, Any] = {}
    if selected_document is not None:
        selected_result = selected_pair[0]
        branch_polylines: dict[str, dict[str, np.ndarray]] = {}
        for material in case.assembly.branch_materials:
            segments = case.assembly.topology.branch_segments(material.branch_id)
            node_ids = case.assembly.branch_node_ids(material.branch_id)
            material_coordinates = np.array(
                [segments[0].material_start]
                + [segment.material_end for segment in segments],
                dtype=float,
            )
            node_positions = np.vstack(
                [
                    selected_result.evaluation.node_positions[
                        case.assembly.topology.node_index(node_id)
                    ]
                    for node_id in node_ids
                ]
            )
            branch_polylines[material.branch_id] = {
                "material_coordinates_m": material_coordinates,
                "node_positions_m": node_positions,
            }
        observables = {
            "shape": np.asarray(
                selected_document["junction_attachment_bob_shape_m"], dtype=float
            ),
            "reactions": np.asarray(
                selected_document["two_support_reactions_N"], dtype=float
            ),
            "potential": float(selected_document["total_potential_J"]),
            "selected_candidate": selected_document,
            "branch_polylines": branch_polylines,
        }
    return (
        {
            "mesh_segments_per_branch": case.mesh_segments_per_branch,
            "generalized_size": case.assembly.layout.generalized_size,
            "layout_mass_and_rest_binding": layout,
            "candidates": candidate_documents,
            "all_candidates_independently_pass": all(candidate_pass),
            "selected_seed_id": selected_pair[0].seed_id if selected_pair else None,
            "selection_rule": manifest["primary_solver"]["selection_rule"],
            "gauge_invariant_multiseed_shape_spread_m": shape_spread,
            "gauge_invariant_multiseed_shape_spread_max_m": y_contract[
                "gauge_invariant_multiseed_shape_spread_max_m"
            ],
            "multiseed_energy_spread_J": energy_spread,
            "multiseed_energy_spread_max_J": y_contract[
                "multiseed_energy_spread_max_J"
            ],
            "status": "PASS" if passed else "FAIL",
        },
        observables,
        passed,
    )


def _trend_ratio(coarse: float, fine: float, floor: float) -> float:
    if coarse <= floor:
        return 0.0 if fine <= floor else float("inf")
    return fine / coarse


def _mesh_trend_metrics(
    observables: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    contract = manifest["mesh_trend"]
    shape_01 = float(np.linalg.norm(observables[1]["shape"] - observables[0]["shape"]))
    shape_12 = float(np.linalg.norm(observables[2]["shape"] - observables[1]["shape"]))
    reaction_01 = float(
        np.linalg.norm(observables[1]["reactions"] - observables[0]["reactions"])
    )
    reaction_12 = float(
        np.linalg.norm(observables[2]["reactions"] - observables[1]["reactions"])
    )
    potential_01 = abs(float(observables[1]["potential"]) - float(observables[0]["potential"]))
    potential_12 = abs(float(observables[2]["potential"]) - float(observables[1]["potential"]))
    ratios = {
        "shape": _trend_ratio(
            shape_01,
            shape_12,
            float(contract["shape_absolute_floor_m"]),
        ),
        "reactions": _trend_ratio(
            reaction_01,
            reaction_12,
            float(contract["reaction_absolute_floor_N"]),
        ),
        "potential": _trend_ratio(
            potential_01,
            potential_12,
            float(contract["potential_absolute_floor_J"]),
        ),
    }
    threshold = float(contract["successive_difference_ratio_max"])
    passed = all(value <= threshold for value in ratios.values())
    return {
        "levels": contract["levels"],
        "successive_differences": {
            "shape_m": [shape_01, shape_12],
            "reactions_N": [reaction_01, reaction_12],
            "potential_J": [potential_01, potential_12],
        },
        "successive_difference_ratios": ratios,
        "successive_difference_ratio_max": threshold,
        "status": "PASS" if passed else "FAIL",
    }


def _evidence_binding(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    acceptance_relative = "contracts/g2_acceptance_manifest.json"
    module_relative = str(manifest["module_manifest"])
    protocol_relative = "contracts/G2_FROZEN_PROTOCOL.md"
    identity_relative = "contracts/model_identity_0_2.json"
    generator_relative = "tools/generate_g2_evidence.py"
    pyproject_relative = "pyproject.toml"
    readme_relative = "README.md"
    source_root = root / "src" / "ypendulum_hfv2"
    source_hashes = {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(source_root.rglob("*.py"))
    }
    test_hashes = {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted((root / "tests").rglob("*.py"))
    }
    return {
        "acceptance_manifest": acceptance_relative,
        "acceptance_manifest_sha256": _sha256(root / acceptance_relative),
        "module_manifest": module_relative,
        "module_manifest_sha256": _sha256(root / module_relative),
        "frozen_protocol": protocol_relative,
        "frozen_protocol_sha256": _sha256(root / protocol_relative),
        "model_identity": identity_relative,
        "model_identity_sha256": _sha256(root / identity_relative),
        "evidence_generator": generator_relative,
        "evidence_generator_sha256": _sha256(root / generator_relative),
        "pyproject": pyproject_relative,
        "pyproject_sha256": _sha256(root / pyproject_relative),
        "readme": readme_relative,
        "readme_sha256": _sha256(root / readme_relative),
        "source_sha256": source_hashes,
        "test_sha256": test_hashes,
        "historical_g1r_metrics_sha256": _sha256(
            root / manifest["historical_g1r"]["metrics_path"]
        ),
        "historical_g1r_report_sha256": _sha256(
            root / manifest["historical_g1r"]["report_path"]
        ),
    }


def build_g2_evidence(candidate_root: str | Path) -> dict[str, Any]:
    root = Path(candidate_root)
    manifest = _load_json(root / "contracts" / "g2_acceptance_manifest.json")
    if manifest["model_id"] != MODEL_ID:
        raise ValueError("G2 manifest model identity differs from the candidate package.")
    settings = _solver_settings(manifest)
    architecture = _architecture_metrics(root, manifest)
    mesh_levels = tuple(int(value) for value in manifest["mesh_trend"]["levels"])
    cases = [build_y_anchor_case(manifest, level) for level in mesh_levels]
    energy_force = _energy_force_metrics(cases[0], manifest)
    vertical = _vertical_metrics(root, manifest, settings)
    mesh_documents: list[dict[str, Any]] = []
    observables: list[dict[str, Any]] = []
    mesh_passes: list[bool] = []
    for case in cases:
        document, selected_observables, passed = _mesh_metrics(
            case,
            manifest,
            settings,
        )
        mesh_documents.append(document)
        observables.append(selected_observables)
        mesh_passes.append(passed)
    trend = (
        _mesh_trend_metrics(observables, manifest)
        if all(observables)
        else {"status": "FAIL", "reason": "one_or_more_meshes_have_no_qualified_solution"}
    )
    historical = manifest["historical_g1r"]
    historical_pass = (
        _sha256(root / historical["metrics_path"]) == historical["metrics_sha256"]
        and _sha256(root / historical["report_path"]) == historical["report_sha256"]
    )
    gates = {
        "historical_g1r_immutability": historical_pass,
        "architecture": architecture["status"] == "PASS",
        "assembly_energy_force": energy_force["status"] == "PASS",
        "analytic_vertical_system": vertical["status"] == "PASS",
        "all_y_meshes": all(mesh_passes),
        "three_mesh_trend": trend["status"] == "PASS",
    }
    passed = all(gates.values())
    evidence = {
        "schema": "YPS-HFV2-G2-EVIDENCE-1.0",
        "model_id": MODEL_ID,
        "phase": manifest["phase"],
        "stop_gate": manifest["stop_gate"],
        "status": manifest["pass_status"] if passed else manifest["fail_status"],
        "allowed_claim": manifest["allowed_claim_on_pass"] if passed else "NO_GO",
        "claim_ceiling": manifest["claim_ceiling"],
        "optimizer_success_used_as_gate": False,
        "runtime": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "platform": platform.platform(),
            "byteorder": sys.byteorder,
        },
        "gate_summary": gates,
        "historical_g1r": {
            "treatment": historical["treatment"],
            "metrics_sha256_matches": _sha256(root / historical["metrics_path"])
            == historical["metrics_sha256"],
            "report_sha256_matches": _sha256(root / historical["report_path"])
            == historical["report_sha256"],
            "status": "PASS" if historical_pass else "FAIL",
        },
        "architecture": architecture,
        "assembly_energy_force": energy_force,
        "analytic_vertical_system": vertical,
        "y_anchor_meshes": mesh_documents,
        "mesh_trend": trend,
        "not_executed": [
            "static_contact",
            "dynamic_integrator",
            "dynamic_contact",
            "active_set",
            "formal_program_adapter",
            "ui",
            "hdf5",
            "physical_apparatus_validation",
            "experimental_validation",
        ],
        "evidence_binding": _evidence_binding(root, manifest),
    }
    return evidence


def canonical_evidence_text(evidence: dict[str, Any]) -> str:
    return json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n"
