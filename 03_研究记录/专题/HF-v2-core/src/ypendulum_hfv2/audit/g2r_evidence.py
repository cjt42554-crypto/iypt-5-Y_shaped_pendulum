"""Deterministic correction and equivalence evidence for the HF-v2 G2R gate."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import scipy
from scipy.optimize import _optimize

from ypendulum_hfv2 import MODEL_ID
from ypendulum_hfv2.audit.g2_cases import build_y_anchor_case
from ypendulum_hfv2.audit.g2_evidence import (
    _architecture_metrics,
    _energy_force_metrics,
    _mesh_metrics,
    _mesh_trend_metrics,
    _solver_settings,
    _vertical_metrics,
)
from ypendulum_hfv2.rigid.rotation import exp_so3
from ypendulum_hfv2.state import HFV2State
from ypendulum_hfv2.statics.assembly import StaticAssembly
from ypendulum_hfv2.statics.solver import bfgs_minimize_options
from ypendulum_hfv2.topology import HFV2Topology, MaterialNode


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _historical_immutability(root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    historical = contract["historical_g2"]
    checks = {
        "report": _sha256(root / historical["report_path"])
        == historical["report_sha256"],
        "metrics": _sha256(root / historical["metrics_path"])
        == historical["metrics_sha256"],
        "frozen_protocol": _sha256(root / historical["frozen_protocol_path"])
        == historical["frozen_protocol_sha256"],
        "acceptance_manifest": _sha256(root / historical["acceptance_manifest_path"])
        == historical["acceptance_manifest_sha256"],
    }
    return {
        "treatment": historical["treatment"],
        "sha256_matches": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def _swapped_attachment_assembly(base: StaticAssembly) -> StaticAssembly:
    nodes = tuple(
        MaterialNode(
            node.node_id,
            "bob_attachment"
            if node.node_id == "support_left"
            else "prescribed"
            if node.node_id == "attachment"
            else node.kind,
        )
        for node in base.topology.nodes
    )
    topology = HFV2Topology(nodes=nodes, segments=base.topology.segments)
    state = HFV2State(
        free_node_ids=base.reference_state.free_node_ids,
        free_node_positions=base.reference_state.free_node_positions,
        free_node_velocities=base.reference_state.free_node_velocities,
        bob_position=base.reference_state.bob_position,
        bob_velocity=base.reference_state.bob_velocity,
        bob_rotation=base.reference_state.bob_rotation,
        bob_angular_velocity_body=base.reference_state.bob_angular_velocity_body,
    )
    return StaticAssembly(
        topology=topology,
        reference_state=state,
        branch_materials=base.branch_materials,
        prescribed_node_positions={
            "support_right": base.prescribed_node_positions["support_right"],
            "attachment": base.prescribed_node_positions["support_left"],
        },
        environment=base.environment,
        bob=base.bob,
        explicit_node_mass=base.explicit_node_mass,
        explicit_node_displaced_volume=base.explicit_node_displaced_volume,
        rotation_chart_norm_max=base.rotation_chart_norm_max,
    )


def _identity_metrics(
    base_manifest: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    base_case = build_y_anchor_case(base_manifest, 2)
    source = base_case.assembly
    source_coordinates = source.coordinates_from_seed(base_case.seeds[0])

    rotated_manifest = copy.deepcopy(base_manifest)
    rotated_manifest["y_anchor"]["base_geometry"]["reference_rotation"] = exp_so3(
        np.array([0.0, 0.0, 0.1])
    ).tolist()
    shifted_manifest = copy.deepcopy(base_manifest)
    shifted_manifest["y_anchor"]["support_left_position_m"][1] = 0.01
    gravity_manifest = copy.deepcopy(base_manifest)
    gravity_manifest["y_anchor"]["gravity_m_per_s2"][2] = -9.8
    variants = {
        "reference_bob_rotation": build_y_anchor_case(rotated_manifest, 2).assembly,
        "bob_attachment_and_prescribed_node_identity": _swapped_attachment_assembly(
            source
        ),
        "prescribed_support_position": build_y_anchor_case(
            shifted_manifest, 2
        ).assembly,
        "gravity": build_y_anchor_case(gravity_manifest, 2).assembly,
    }
    documents: dict[str, dict[str, Any]] = {}
    for identity, variant in variants.items():
        rejected = False
        rejection_type: str | None = None
        try:
            variant.evaluate(source_coordinates)
        except ValueError as error:
            rejected = True
            rejection_type = type(error).__name__
        token_differs = variant.layout.layout_token != source.layout.layout_token
        documents[identity] = {
            "source_token": source.layout.layout_token,
            "variant_token": variant.layout.layout_token,
            "token_differs": token_differs,
            "foreign_coordinates_rejected": rejected,
            "rejection_type": rejection_type,
            "status": "PASS" if token_differs and rejected else "FAIL",
        }
    required = tuple(contract["assembly_identity"]["required_counterexamples"])
    passed = (
        source.layout.identity_schema == "YPS-HFV2-STATIC-ASSEMBLY-IDENTITY-1.0"
        and contract["assembly_identity"]["coordinate_rebinding_allowed"] is False
        and set(documents) == set(required)
        and all(document["status"] == "PASS" for document in documents.values())
    )
    return {
        "design": contract["assembly_identity"]["design"],
        "identity_schema": source.layout.identity_schema,
        "legacy_field_name": "layout_token",
        "semantics": "complete_coordinate_and_physical_static_assembly_identity",
        "coordinate_rebinding_allowed": False,
        "bound_field_groups": [
            "node_ids_kinds_attachment_and_free_order",
            "segments_material_coordinates_and_order",
            "coordinate_slices_and_generalized_size",
            "reference_bob_rotation_and_rotation_chart",
            "prescribed_node_ids_and_positions",
            "branch_materials_explicit_and_lumped_node_properties",
            "bob_mass_volume_inertia_and_attachment_arm",
            "gravity_fluid_density_and_buoyancy_switch",
        ],
        "counterexamples": documents,
        "status": "PASS" if passed else "FAIL",
    }


def _bfgs_metrics(
    base_manifest: dict[str, Any],
    contract: dict[str, Any],
    runtime_amendment: dict[str, Any],
) -> dict[str, Any]:
    settings = _solver_settings(base_manifest)
    actual = bfgs_minimize_options(settings)
    serializable_actual = {
        key: "inf" if key == "norm" and value == np.inf else value
        for key, value in actual.items()
    }
    expected = contract["bfgs_forwarded_options"]
    expected_options = {key: value for key, value in expected.items() if key != "method"}
    signature_parameters = tuple(inspect.signature(_optimize._minimize_bfgs).parameters)
    required_parameters = tuple(
        runtime_amendment["corrected_runtime_contract"][
            "bfgs_signature_parameters_required"
        ]
    )
    signature_support = all(value in signature_parameters for value in required_parameters)
    passed = (
        settings.method == expected["method"]
        and serializable_actual == expected_options
        and signature_support
    )
    return {
        "call_path": "solve_static_seed_to_scipy_optimize_minimize",
        "options_mapping_function": "bfgs_minimize_options",
        "method": settings.method,
        "actual_options": serializable_actual,
        "expected_options": expected_options,
        "runtime_bfgs_signature_parameters": list(signature_parameters),
        "required_signature_parameters": list(required_parameters),
        "runtime_signature_supports_frozen_options": signature_support,
        "fallback_solver_allowed": False,
        "status": "PASS" if passed else "FAIL",
    }


def _runtime_amendment_metrics(amendment: dict[str, Any]) -> dict[str, Any]:
    expected = amendment["corrected_runtime_contract"]["first_valid_target_runtime"]
    actual = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
    }
    exact_runtime = actual == expected
    return {
        "schema": amendment["schema"],
        "frozen_before_first_valid_g2r_target_execution": amendment[
            "frozen_before_first_valid_g2r_target_execution"
        ],
        "invalidated_trial": amendment["invalidated_trial"],
        "expected_first_valid_target_runtime": expected,
        "actual_runtime": actual,
        "exact_runtime_match": exact_runtime,
        "unknown_solver_options_warning_treatment": amendment[
            "corrected_runtime_contract"
        ]["unknown_solver_options_warning_treatment"],
        "status": "PASS" if exact_runtime else "FAIL",
    }


def _resample_polyline(
    material_coordinates: np.ndarray,
    positions: np.ndarray,
    sample_count: int,
) -> np.ndarray:
    coordinates = np.asarray(material_coordinates, dtype=float)
    points = np.asarray(positions, dtype=float)
    if coordinates.ndim != 1 or points.shape != (coordinates.size, 3):
        raise ValueError("Branch polyline coordinate and position shapes are inconsistent.")
    if np.any(np.diff(coordinates) <= 0.0):
        raise ValueError("Branch material coordinates must be strictly increasing.")
    samples = np.linspace(coordinates[0], coordinates[-1], sample_count)
    return np.column_stack(
        [np.interp(samples, coordinates, points[:, axis]) for axis in range(3)]
    )


def _centerline_metrics(
    observables: list[dict[str, Any]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    centerline_contract = contract["material_centerline_trend"]
    branch_ids = tuple(centerline_contract["branch_ids"])
    sample_count = int(centerline_contract["sample_count_per_branch"])
    sampled: list[dict[str, np.ndarray]] = []
    for level in observables:
        branch_documents: dict[str, np.ndarray] = {}
        for branch_id in branch_ids:
            polyline = level["branch_polylines"][branch_id]
            branch_documents[branch_id] = _resample_polyline(
                polyline["material_coordinates_m"],
                polyline["node_positions_m"],
                sample_count,
            )
        sampled.append(branch_documents)

    threshold = float(centerline_contract["successive_difference_ratio_max"])
    branches: dict[str, dict[str, Any]] = {}
    for branch_id in branch_ids:
        coarse = float(
            np.max(
                np.linalg.norm(
                    sampled[1][branch_id] - sampled[0][branch_id], axis=1
                )
            )
        )
        fine = float(
            np.max(
                np.linalg.norm(
                    sampled[2][branch_id] - sampled[1][branch_id], axis=1
                )
            )
        )
        ratio = fine / coarse if coarse > 0.0 else (0.0 if fine == 0.0 else float("inf"))
        passed = fine < coarse and ratio <= threshold
        branches[branch_id] = {
            "maximum_pointwise_difference_m": [coarse, fine],
            "fine_to_coarse_difference_ratio": ratio,
            "strictly_decreased": fine < coarse,
            "status": "PASS" if passed else "FAIL",
        }
    system_coarse = max(
        document["maximum_pointwise_difference_m"][0] for document in branches.values()
    )
    system_fine = max(
        document["maximum_pointwise_difference_m"][1] for document in branches.values()
    )
    system_ratio = system_fine / system_coarse
    system_pass = system_fine < system_coarse and system_ratio <= threshold
    passed = system_pass and all(
        document["status"] == "PASS" for document in branches.values()
    )
    return {
        "levels": centerline_contract["levels"],
        "normalized_material_coordinate_rule": centerline_contract[
            "normalized_material_coordinate_rule"
        ],
        "sample_count_per_branch": sample_count,
        "interpolation": centerline_contract["interpolation"],
        "difference_norm": centerline_contract["difference_norm"],
        "successive_difference_ratio_max": threshold,
        "branches": branches,
        "all_branches": {
            "maximum_pointwise_difference_m": [system_coarse, system_fine],
            "fine_to_coarse_difference_ratio": system_ratio,
            "strictly_decreased": system_fine < system_coarse,
            "status": "PASS" if system_pass else "FAIL",
        },
        "audit_only_not_in_solver_or_selection": True,
        "status": "PASS" if passed else "FAIL",
    }


def _selected_candidate(mesh_document: dict[str, Any]) -> dict[str, Any]:
    selected_seed = mesh_document["selected_seed_id"]
    matches = [
        candidate
        for candidate in mesh_document["candidates"]
        if candidate["seed_id"] == selected_seed
    ]
    if len(matches) != 1:
        raise ValueError("A mesh must identify exactly one selected candidate.")
    return matches[0]


def _dimensionless_metrics(
    mesh_documents: list[dict[str, Any]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    tolerance = float(
        contract["dimensionless_segment_diagnostics"][
            "algebraic_identity_absolute_tolerance"
        ]
    )
    levels: list[dict[str, Any]] = []
    for mesh in mesh_documents:
        candidate = _selected_candidate(mesh)
        diagnostics = candidate["dimensionless_segment_diagnostics"]
        arrays = [
            np.asarray(diagnostics["engineering_strain"], dtype=float),
            np.asarray(
                diagnostics["extension_fraction_of_current_length"], dtype=float
            ),
            np.asarray(diagnostics["current_to_rest_length_ratio"], dtype=float),
        ]
        finite = all(np.all(np.isfinite(values)) for values in arrays)
        identity_error = max(
            float(diagnostics["extension_fraction_identity_max_absolute_error"]),
            float(diagnostics["stretch_identity_max_absolute_error"]),
        )
        passed = finite and identity_error <= tolerance
        levels.append(
            {
                "mesh_segments_per_branch": mesh["mesh_segments_per_branch"],
                "selected_seed_id": mesh["selected_seed_id"],
                "engineering_strain_minimum": diagnostics[
                    "engineering_strain_minimum"
                ],
                "engineering_strain_maximum": diagnostics[
                    "engineering_strain_maximum"
                ],
                "extension_fraction_of_current_length_minimum": diagnostics[
                    "extension_fraction_of_current_length_minimum"
                ],
                "extension_fraction_of_current_length_maximum": diagnostics[
                    "extension_fraction_of_current_length_maximum"
                ],
                "current_to_rest_length_ratio_minimum": diagnostics[
                    "current_to_rest_length_ratio_minimum"
                ],
                "current_to_rest_length_ratio_maximum": diagnostics[
                    "current_to_rest_length_ratio_maximum"
                ],
                "maximum_algebraic_identity_error": identity_error,
                "all_arrays_finite": finite,
                "status": "PASS" if passed else "FAIL",
            }
        )
    passed = all(level["status"] == "PASS" for level in levels)
    return {
        "definitions": contract["dimensionless_segment_diagnostics"],
        "selected_mesh_levels": levels,
        "arrays_location": "y_anchor_meshes.candidates.dimensionless_segment_diagnostics",
        "status": "PASS" if passed else "FAIL",
    }


def _equivalence_metrics(
    historical: dict[str, Any],
    current_meshes: list[dict[str, Any]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    thresholds = contract["historical_equivalence"]
    historical_by_level = {
        int(mesh["mesh_segments_per_branch"]): mesh
        for mesh in historical["y_anchor_meshes"]
    }
    levels: list[dict[str, Any]] = []
    for current_mesh in current_meshes:
        level = int(current_mesh["mesh_segments_per_branch"])
        old_mesh = historical_by_level[level]
        old = _selected_candidate(old_mesh)
        new = _selected_candidate(current_mesh)
        seed_same = old_mesh["selected_seed_id"] == current_mesh["selected_seed_id"]
        differences = {
            "total_potential_absolute_difference_J": abs(
                float(new["total_potential_J"]) - float(old["total_potential_J"])
            ),
            "macro_shape_l2_difference_m": float(
                np.linalg.norm(
                    np.asarray(new["junction_attachment_bob_shape_m"], dtype=float)
                    - np.asarray(old["junction_attachment_bob_shape_m"], dtype=float)
                )
            ),
            "segment_tension_max_absolute_difference_N": float(
                np.max(
                    np.abs(
                        np.asarray(new["segment_tensions_N"], dtype=float)
                        - np.asarray(old["segment_tensions_N"], dtype=float)
                    ),
                    initial=0.0,
                )
            ),
            "support_reaction_l2_difference_N": float(
                np.linalg.norm(
                    np.asarray(new["two_support_reactions_N"], dtype=float)
                    - np.asarray(old["two_support_reactions_N"], dtype=float)
                )
            ),
            "minimum_nongauge_hessian_eigenvalue_absolute_difference": abs(
                float(
                    new["second_order"][
                        "minimum_nongauge_normalized_eigenvalue"
                    ]
                )
                - float(
                    old["second_order"][
                        "minimum_nongauge_normalized_eigenvalue"
                    ]
                )
            ),
        }
        checks = {
            "same_selected_seed_id": seed_same,
            "total_potential": differences[
                "total_potential_absolute_difference_J"
            ]
            <= float(thresholds["total_potential_absolute_difference_max_J"]),
            "macro_shape": differences["macro_shape_l2_difference_m"]
            <= float(thresholds["macro_shape_l2_difference_max_m"]),
            "segment_tension": differences[
                "segment_tension_max_absolute_difference_N"
            ]
            <= float(
                thresholds["segment_tension_max_absolute_difference_max_N"]
            ),
            "support_reaction": differences[
                "support_reaction_l2_difference_N"
            ]
            <= float(thresholds["support_reaction_l2_difference_max_N"]),
            "stability": differences[
                "minimum_nongauge_hessian_eigenvalue_absolute_difference"
            ]
            <= float(
                thresholds[
                    "minimum_nongauge_hessian_eigenvalue_absolute_difference_max"
                ]
            ),
        }
        levels.append(
            {
                "mesh_segments_per_branch": level,
                "historical_selected_seed_id": old_mesh["selected_seed_id"],
                "g2r_selected_seed_id": current_mesh["selected_seed_id"],
                "differences": differences,
                "gate_checks": checks,
                "status": "PASS" if all(checks.values()) else "FAIL",
            }
        )
    passed = all(level["status"] == "PASS" for level in levels)
    return {
        "historical_schema": historical["schema"],
        "thresholds": thresholds,
        "mesh_levels": levels,
        "status": "PASS" if passed else "FAIL",
    }


def _evidence_binding(root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    paths = {
        "g2r_acceptance_manifest": "contracts/g2r_acceptance_manifest.json",
        "g2r_module_manifest": str(contract["module_manifest"]),
        "g2r_protocol": str(contract["protocol"]),
        "g2r_deviation_record": str(contract["deviation_record"]),
        "g2r_runtime_amendment": "contracts/g2r_runtime_amendment.json",
        "g2r_runtime_amendment_report": "contracts/G2R_RUNTIME_AMENDMENT.md",
        "base_g2_acceptance_manifest": str(contract["base_g2_acceptance_manifest"]),
        "model_identity": "contracts/model_identity_0_2.json",
        "evidence_generator": "tools/generate_g2r_evidence.py",
        "pyproject": "pyproject.toml",
        "readme": "README.md",
    }
    source_hashes = {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted((root / "src" / "ypendulum_hfv2").rglob("*.py"))
    }
    test_hashes = {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted((root / "tests").rglob("*.py"))
    }
    return {
        "paths": {
            name: {"path": relative, "sha256": _sha256(root / relative)}
            for name, relative in paths.items()
        },
        "source_sha256": source_hashes,
        "test_sha256": test_hashes,
    }


def build_g2r_evidence(candidate_root: str | Path) -> dict[str, Any]:
    root = Path(candidate_root)
    contract = _load_json(root / "contracts" / "g2r_acceptance_manifest.json")
    runtime_amendment = _load_json(
        root / "contracts" / "g2r_runtime_amendment.json"
    )
    base_path = root / contract["base_g2_acceptance_manifest"]
    if _sha256(base_path) != contract["base_g2_acceptance_manifest_sha256"]:
        raise ValueError("The frozen base G2 acceptance manifest changed.")
    base_manifest = _load_json(base_path)
    if contract["model_id"] != MODEL_ID or base_manifest["model_id"] != MODEL_ID:
        raise ValueError("G2R or base G2 model identity differs from the package.")
    if runtime_amendment["model_id"] != MODEL_ID:
        raise ValueError("G2R runtime amendment model identity differs from the package.")
    runtime_manifest = copy.deepcopy(base_manifest)
    runtime_manifest["module_manifest"] = contract["module_manifest"]
    settings = _solver_settings(base_manifest)

    historical_immutability = _historical_immutability(root, contract)
    runtime_amendment_metrics = _runtime_amendment_metrics(runtime_amendment)
    historical_metrics = _load_json(root / contract["historical_g2"]["metrics_path"])
    architecture = _architecture_metrics(root, runtime_manifest)
    levels = tuple(int(value) for value in base_manifest["mesh_trend"]["levels"])
    cases = [build_y_anchor_case(base_manifest, level) for level in levels]
    energy_force = _energy_force_metrics(cases[0], base_manifest)
    vertical = _vertical_metrics(root, base_manifest, settings)
    mesh_documents: list[dict[str, Any]] = []
    observables: list[dict[str, Any]] = []
    mesh_passes: list[bool] = []
    for case in cases:
        document, selected_observables, passed = _mesh_metrics(
            case, base_manifest, settings
        )
        mesh_documents.append(document)
        observables.append(selected_observables)
        mesh_passes.append(passed)
    trend = (
        _mesh_trend_metrics(observables, base_manifest)
        if all(observables)
        else {"status": "FAIL", "reason": "one_or_more_meshes_have_no_qualified_solution"}
    )
    identity = _identity_metrics(base_manifest, contract)
    bfgs = _bfgs_metrics(base_manifest, contract, runtime_amendment)
    centerline = (
        _centerline_metrics(observables, contract)
        if all(observables)
        else {"status": "FAIL", "reason": "missing_selected_mesh_observables"}
    )
    dimensionless = _dimensionless_metrics(mesh_documents, contract)
    equivalence = _equivalence_metrics(
        historical_metrics, mesh_documents, contract
    )
    gates = {
        "historical_g2_immutability": historical_immutability["status"] == "PASS",
        "architecture": architecture["status"] == "PASS",
        "corrected_runtime_contract": runtime_amendment_metrics["status"] == "PASS",
        "complete_assembly_identity": identity["status"] == "PASS",
        "bfgs_frozen_options_forwarded": bfgs["status"] == "PASS",
        "assembly_energy_force": energy_force["status"] == "PASS",
        "analytic_vertical_system": vertical["status"] == "PASS",
        "all_y_meshes": all(mesh_passes),
        "legacy_macro_mesh_trend": trend["status"] == "PASS",
        "full_material_centerline_trend": centerline["status"] == "PASS",
        "dimensionless_segment_diagnostics": dimensionless["status"] == "PASS",
        "historical_g2_equivalence": equivalence["status"] == "PASS",
    }
    passed = all(gates.values())
    return {
        "schema": "YPS-HFV2-G2R-EVIDENCE-1.0",
        "model_id": MODEL_ID,
        "phase": contract["phase"],
        "stop_gate": contract["stop_gate"],
        "status": contract["pass_status"] if passed else contract["fail_status"],
        "allowed_claim": contract["allowed_claim_on_pass"] if passed else "NO_GO",
        "claim_ceiling": contract["claim_ceiling"],
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
        "historical_g2_immutability": historical_immutability,
        "protocol_deviation_treatment": {
            "record": contract["deviation_record"],
            "target_results_were_observed_before_original_g2_corrections": True,
            "g2r_is_separately_preregistered": True,
            "original_g2_recast_as_unbiased_preregistration": False,
            "runtime_amendment": "contracts/G2R_RUNTIME_AMENDMENT.md",
            "first_unknown_options_trial_rejected": True,
        },
        "corrected_runtime_contract": runtime_amendment_metrics,
        "architecture": architecture,
        "complete_assembly_identity": identity,
        "bfgs_frozen_options": bfgs,
        "assembly_energy_force": energy_force,
        "analytic_vertical_system": vertical,
        "y_anchor_meshes": mesh_documents,
        "legacy_macro_mesh_trend": trend,
        "full_material_centerline_trend": centerline,
        "dimensionless_segment_diagnostics": dimensionless,
        "historical_g2_equivalence": equivalence,
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
        "evidence_binding": _evidence_binding(root, contract),
    }


def canonical_g2r_evidence_text(evidence: dict[str, Any]) -> str:
    return json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n"
