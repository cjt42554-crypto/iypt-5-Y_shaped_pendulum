"""Deterministic G3R2 evidence for the frozen P3R2 certification candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from ypendulum_hfv2.audit.contact import contact_action_reaction_audit
from ypendulum_hfv2.contact import ContactGeometryError
from ypendulum_hfv2_p3r.critical_cone import audit_critical_cone
from ypendulum_hfv2_p3r.jacobian_audit import (
    physical_gap_jacobian_samples,
    validity_jacobian_samples,
)

from . import P3R2_CONTACT_MODEL_ID
from .cases import (
    P3R2StaticContactCase,
    build_observed_p3r_35_degree_regression,
    build_observed_symmetric_regression,
    build_qualification_targets,
)
from .evidence_support import (
    architecture_metrics,
    contract_binding,
    evidence_hash_binding,
    jsonable,
    load_json,
    run_bound_benchmarks,
    runtime_metrics,
    sha256,
)
from .kkt import P3R2KKTAudit, audit_contact_kkt, thresholds_from_manifest
from .solver import settings_from_manifest, solve_contact_seed


def _identity_subset(
    constraint_ids: tuple[str, ...],
    indices: np.ndarray,
) -> tuple[str, ...]:
    return tuple(constraint_ids[int(index)] for index in indices)


def _jacobian_document(samples: tuple[object, ...]) -> list[dict[str, float]]:
    return [
        {
            "difference_step": float(sample.difference_step),
            "maximum_row_relative_error": float(sample.maximum_row_relative_error),
            "matrix_relative_error": float(sample.matrix_relative_error),
        }
        for sample in samples
    ]


def _kkt_document(kkt: P3R2KKTAudit, constraint_ids: tuple[str, ...]) -> dict[str, Any]:
    intervals = []
    for index in kkt.near_active_indices:
        integer = int(index)
        intervals.append(
            {
                "constraint_id": constraint_ids[integer],
                "canonical_multiplier_N": kkt.canonical_multipliers_N[integer],
                "lower_N": kkt.dual_interval_lower_N[integer],
                "upper_N": kkt.dual_interval_upper_N[integer],
            }
        )
    components = []
    for index, coordinate_id in enumerate(kkt.coordinate_ids):
        components.append(
            {
                "coordinate_id": coordinate_id,
                "unit": kkt.stationarity_units[index],
                "raw_value": kkt.stationarity_vector_N[index],
                "raw_allowed_absolute": kkt.component_allowed_raw[index],
                "component_scale": kkt.scales.stationarity_scales[index],
                "dimensionless_value": kkt.dimensionless_stationarity[index],
            }
        )
    translation_index = int(np.argmax(np.abs(kkt.translation_force_residual_N)))
    rotation_index = int(np.argmax(np.abs(kkt.rotation_torque_residual_N_m))) + 3
    dimensionless_index = int(np.argmax(np.abs(kkt.dimensionless_stationarity)))
    legacy_index = int(np.argmax(np.abs(kkt.stationarity_vector_N)))
    return jsonable(
        {
            "passed": kkt.passed,
            "coordinate_ids": kkt.coordinate_ids,
            "stationarity_units": kkt.stationarity_units,
            "characteristic_scales": {
                "length_m": kkt.scales.length_m,
                "force_N": kkt.scales.force_N,
                "energy_N_m": kkt.scales.energy_N_m,
                "coordinate_scales": kkt.scales.coordinate_scales,
                "stationarity_scales": kkt.scales.stationarity_scales,
            },
            "stationarity_components": components,
            "translation_force_residual_N": kkt.translation_force_residual_N,
            "rotation_torque_residual_N_m": kkt.rotation_torque_residual_N_m,
            "dimensionless_stationarity": kkt.dimensionless_stationarity,
            "maximum_components": {
                "translation": {
                    "coordinate_id": kkt.coordinate_ids[translation_index],
                    "raw_value_N": kkt.stationarity_vector_N[translation_index],
                    "absolute_value_N": kkt.translation_force_infinity_N,
                },
                "rotation": {
                    "coordinate_id": kkt.coordinate_ids[rotation_index],
                    "raw_value_N_m": kkt.stationarity_vector_N[rotation_index],
                    "absolute_value_N_m": kkt.rotation_torque_infinity_N_m,
                },
                "dimensionless": {
                    "coordinate_id": kkt.coordinate_ids[dimensionless_index],
                    "value": kkt.dimensionless_stationarity[dimensionless_index],
                    "absolute_value": kkt.dimensionless_stationarity_infinity,
                },
                "legacy_mixed": {
                    "coordinate_id": kkt.coordinate_ids[legacy_index],
                    "unit": kkt.stationarity_units[legacy_index],
                    "raw_value": kkt.stationarity_vector_N[legacy_index],
                    "absolute_value": kkt.stationarity_residual_N,
                },
            },
            "stationarity_checks": {
                "legacy_mixed_infinity": kkt.legacy_stationarity_passed,
                "translation_force_components": kkt.translation_stationarity_passed,
                "rotation_torque_components": kkt.rotation_stationarity_passed,
                "dimensionless_components": kkt.dimensionless_stationarity_passed,
            },
            "near_active_ids": _identity_subset(
                constraint_ids,
                kkt.near_active_indices,
            ),
            "supported_ids": _identity_subset(constraint_ids, kkt.supported_indices),
            "weak_active_ids": _identity_subset(
                constraint_ids,
                kkt.weak_active_indices,
            ),
            "possible_supported_ids": _identity_subset(
                constraint_ids,
                kkt.possible_supported_indices,
            ),
            "mandatory_supported_ids": _identity_subset(
                constraint_ids,
                kkt.mandatory_supported_indices,
            ),
            "near_active_rank": kkt.near_active_rank,
            "supported_rank": kkt.supported_rank,
            "dual_interval_feasible": kkt.dual_interval_feasible,
            "dual_nonunique": kkt.dual_nonunique,
            "dual_intervals": intervals,
            "primal_violation_m": kkt.primal_violation_m,
            "dual_violation_N": kkt.dual_violation_N,
            "legacy_stationarity_residual_mixed_units": kkt.stationarity_residual_N,
            "legacy_stationarity_limit_mixed_units": kkt.stationarity_limit_N,
            "complementarity_residual_N_m": kkt.complementarity_residual_N_m,
            "complementarity_limit_N_m": kkt.complementarity_limit_N_m,
        }
    )


def _critical_document(audit: object) -> dict[str, Any]:
    return jsonable(
        {
            "passed": audit.passed,
            "definition": "J_near_active*d>=0_and_gradient_Pi_dot_d=0_with_registered_gauge_removed",
            "unsymmetrized_relative_asymmetry": audit.unsymmetrized_relative_asymmetry,
            "gauge_dimension": audit.gauge_dimension,
            "critical_equality_rank": audit.critical_equality_rank,
            "near_active_count": audit.near_active_count,
            "near_active_rank": audit.near_active_rank,
            "supported_tangent_dimension": audit.supported_tangent_dimension,
            "supported_tangent_eigenvalues": audit.supported_tangent_eigenvalues,
            "minimum_supported_tangent_curvature": (
                audit.minimum_supported_tangent_curvature
            ),
            "critical_direction_count": audit.critical_direction_count,
            "critical_direction_minimum_linearized_gap": (
                audit.critical_direction_minimum_linearized_gap
            ),
            "matrix_directional_curvatures": audit.matrix_directional_curvatures,
            "independent_directional_curvatures": (
                audit.independent_directional_curvatures
            ),
            "maximum_curvature_crosscheck_error": (
                audit.maximum_curvature_crosscheck_error
            ),
            "minimum_critical_cone_curvature": (
                audit.minimum_critical_cone_curvature
            ),
        }
    )


def _critical_kwargs(manifest: dict[str, Any]) -> dict[str, Any]:
    source = manifest["critical_cone_second_order"]
    names = (
        "hessian_difference_step",
        "directional_difference_step",
        "rank_relative_tolerance",
        "cone_feasibility_tolerance",
        "duplicate_direction_tolerance",
        "maximum_enumerated_inequalities",
        "asymmetry_max",
        "minimum_normalized_curvature",
        "curvature_crosscheck_absolute_max",
    )
    return {name: source[name] for name in names}


def _validity_document(evaluation: object) -> dict[str, Any]:
    validity = evaluation.validity
    return jsonable(
        {
            "constraint_ids": validity.constraint_ids,
            "units": validity.units,
            "scales": validity.scales,
            "signed_residuals": validity.signed_residuals,
            "normalized_residuals": validity.normalized_residuals,
            "minimum_normalized_residual": float(
                np.min(validity.normalized_residuals)
            ),
        }
    )


def _dual_width(kkt: P3R2KKTAudit) -> float:
    if kkt.near_active_indices.size == 0:
        return 0.0
    widths = (
        kkt.dual_interval_upper_N[kkt.near_active_indices]
        - kkt.dual_interval_lower_N[kkt.near_active_indices]
    )
    return float(np.max(widths))


def _final_audits(
    case: P3R2StaticContactCase,
    evaluation: object,
    scales: object,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    kkt = audit_contact_kkt(
        case.assembly,
        evaluation,
        thresholds_from_manifest(manifest),
        scales,
    )
    physical_samples = physical_gap_jacobian_samples(
        case.assembly,
        evaluation.coordinates,
        tuple(manifest["jacobian_audits"]["physical_gap_steps"]),
    )
    validity_samples = validity_jacobian_samples(
        case.assembly,
        evaluation.coordinates,
        tuple(manifest["jacobian_audits"]["validity_five_point_steps"]),
    )
    critical = audit_critical_cone(
        case.assembly,
        evaluation.coordinates,
        kkt,
        **_critical_kwargs(manifest),
    )
    action = contact_action_reaction_audit(
        evaluation.contact,
        kkt.canonical_multipliers_N,
    )
    base_coordinates = case.assembly.base_assembly.coordinates_from_values(
        evaluation.coordinates.values
    )
    base = case.assembly.base_assembly.evaluate(base_coordinates)
    p2_unchanged = bool(
        evaluation.total_potential == base.total_potential
        and np.array_equal(evaluation.generalized_force, base.generalized_force)
    )
    return {
        "kkt_object": kkt,
        "kkt": _kkt_document(kkt, evaluation.contact.constraint_ids),
        "physical_gap_jacobian": _jacobian_document(physical_samples),
        "validity_jacobian": _jacobian_document(validity_samples),
        "critical_cone": _critical_document(critical),
        "critical_passed": critical.passed,
        "action_reaction": jsonable(
            {
                "maximum_individual_force_residual_N": (
                    action.maximum_individual_force_residual_N
                ),
                "maximum_individual_moment_residual_N_m": (
                    action.maximum_individual_moment_residual_N_m
                ),
                "global_force_residual_N": action.global_force_residual_N,
                "global_moment_residual_N_m": action.global_moment_residual_N_m,
            }
        ),
        "p2_potential_and_force_bitwise_unchanged": p2_unchanged,
        "validity": _validity_document(evaluation),
        "physical_final_error": physical_samples[-1].maximum_row_relative_error,
        "validity_final_error": validity_samples[-1].maximum_row_relative_error,
        "dual_interval_maximum_width_N": _dual_width(kkt),
    }


def _restoration_document(result: object) -> dict[str, Any]:
    restore = result.restoration
    return jsonable(
        {
            "executed": restore.executed,
            "converged": restore.converged,
            "status": restore.status,
            "iterations": restore.iterations,
            "total_backtracks": restore.total_backtracks,
            "restore_constraint_ids": restore.restore_constraint_ids,
            "weak_constraint_ids_preserved": restore.weak_constraint_ids,
            "initial_restore_multipliers_N": (
                restore.initial_restore_multipliers_N
            ),
            "final_restore_multipliers_N": restore.final_restore_multipliers_N,
            "initial_composite_residual": restore.initial_composite_residual,
            "final_composite_residual": restore.final_composite_residual,
            "initial_composite_infinity": float(
                np.linalg.norm(restore.initial_composite_residual, ord=np.inf)
            ),
            "final_composite_infinity": float(
                np.linalg.norm(restore.final_composite_residual, ord=np.inf)
            ),
            "accepted_step_lengths": restore.accepted_step_lengths,
            "linear_system_relative_singular_values": (
                restore.linear_system_relative_singular_values
            ),
        }
    )


def _seed_record(
    case: P3R2StaticContactCase,
    seed: object,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    result = solve_contact_seed(
        case.assembly,
        seed,
        settings_from_manifest(manifest),
    )
    thresholds = thresholds_from_manifest(manifest)
    before_kkt = audit_contact_kkt(
        case.assembly,
        result.slsqp_evaluation,
        thresholds,
        result.scales,
    )
    audits = _final_audits(case, result.evaluation, result.scales, manifest)
    after_kkt = audits.pop("kkt_object")
    ids = result.evaluation.contact.constraint_ids
    near_ids = _identity_subset(ids, after_kkt.near_active_indices)
    supported_ids = _identity_subset(ids, after_kkt.supported_indices)
    possible_ids = _identity_subset(ids, after_kkt.possible_supported_indices)
    mandatory_ids = _identity_subset(ids, after_kkt.mandatory_supported_indices)
    expected = case.expectation
    multiplier_errors = []
    for identity, expected_value in zip(
        expected.supported_constraint_ids,
        expected.supported_multipliers_N,
        strict=True,
    ):
        index = ids.index(identity)
        multiplier_errors.append(
            abs(after_kkt.canonical_multipliers_N[index] - expected_value)
        )
    multiplier_error = max(multiplier_errors) if multiplier_errors else float("inf")
    position = result.evaluation.contact.base_evaluation.bob_position
    position_error = float(np.linalg.norm(position - expected.bob_position_m))
    rotation_slice = case.assembly.base_assembly.layout.bob_rotation_slice.slice
    rotation = result.coordinates.values[rotation_slice]
    rotation_error = float(
        np.linalg.norm(rotation - expected.bob_rotation_vector_rad)
    )
    supported_witnesses = [
        result.evaluation.contact.witnesses[ids.index(identity)]
        for identity in expected.supported_constraint_ids
    ]
    witness_margin = min(
        item.unit_interval_parameter_margin for item in supported_witnesses
    )
    validity_minimum = float(
        np.min(result.evaluation.validity.normalized_residuals)
    )
    action = audits["action_reaction"]
    contract = case.contract
    checks = {
        "finite": bool(
            np.all(np.isfinite(result.coordinates.values))
            and np.all(np.isfinite(result.evaluation.contact.gaps_m))
            and np.all(np.isfinite(result.evaluation.validity.signed_residuals))
        ),
        "restoration_executed": result.restoration.executed,
        "restoration_converged": result.restoration.converged,
        "kkt": after_kkt.passed,
        "legacy_stationarity_gate": after_kkt.legacy_stationarity_passed,
        "translation_force_components": after_kkt.translation_stationarity_passed,
        "rotation_torque_components": after_kkt.rotation_stationarity_passed,
        "dimensionless_stationarity_components": (
            after_kkt.dimensionless_stationarity_passed
        ),
        "near_active_identity": near_ids == expected.near_active_constraint_ids,
        "supported_identity": supported_ids == expected.supported_constraint_ids,
        "possible_support_identity": possible_ids == expected.supported_constraint_ids,
        "mandatory_support_identity": mandatory_ids
        == expected.supported_constraint_ids,
        "near_active_rank": after_kkt.near_active_rank == expected.near_active_rank,
        "supported_rank": after_kkt.supported_rank == expected.supported_rank,
        "dual_interval_width": audits["dual_interval_maximum_width_N"]
        <= float(manifest["kkt"]["qualification_dual_interval_width_max_N"]),
        "position": position_error <= float(contract["position_absolute_error_max_m"]),
        "rotation_gauge_representative": rotation_error
        <= float(contract["rotation_vector_absolute_error_max_rad"]),
        "multipliers": multiplier_error
        <= float(contract["multiplier_absolute_error_max_N"]),
        "interior_witnesses": witness_margin
        >= float(contract["interior_witness_parameter_margin_min"]),
        "validity_strict_interior": validity_minimum
        >= float(manifest["validity_final_normalized_margin_min"]),
        "physical_gap_jacobian": audits["physical_final_error"]
        <= float(manifest["jacobian_audits"]["physical_final_error_max"]),
        "validity_jacobian": audits["validity_final_error"]
        <= float(manifest["jacobian_audits"]["validity_final_error_max"]),
        "critical_cone": bool(audits["critical_passed"]),
        "action_reaction_force": float(action["maximum_individual_force_residual_N"])
        <= float(manifest["action_reaction"]["force_residual_max_N"]),
        "action_reaction_moment": float(
            action["maximum_individual_moment_residual_N_m"]
        )
        <= float(manifest["action_reaction"]["moment_residual_max_N_m"]),
        "p2_unchanged": bool(audits["p2_potential_and_force_bitwise_unchanged"]),
    }
    qualified = all(checks.values())
    return jsonable(
        {
            "seed_id": result.seed_id,
            "execution_status": "COMPLETED",
            "optimizer": {
                "success": result.optimizer_success,
                "success_used_as_acceptance_gate": False,
                "status": result.optimizer_status,
                "message": result.optimizer_message,
                "iterations": result.optimizer_iterations,
                "function_evaluations": result.function_evaluations,
                "gradient_evaluations": result.gradient_evaluations,
            },
            "restoration": _restoration_document(result),
            "slsqp_stationarity": _kkt_document(
                before_kkt,
                result.slsqp_evaluation.contact.constraint_ids,
            ),
            "restored_stationarity": audits["kkt"],
            "coordinates": result.coordinates.values,
            "bob_position_m": position,
            "bob_rotation_vector_rad": rotation,
            "total_potential_J": result.evaluation.total_potential,
            "minimum_contact_gap_m": float(
                np.min(result.evaluation.contact.gaps_m)
            ),
            "minimum_validity_normalized_residual": validity_minimum,
            "position_error_m": position_error,
            "rotation_vector_error_rad": rotation_error,
            "supported_multiplier_max_error_N": multiplier_error,
            "supported_witness_parameter_margin": witness_margin,
            "checks": checks,
            "audits": audits,
            "qualified": qualified,
        }
    )


def _structure_regression(
    case: P3R2StaticContactCase,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    result = solve_contact_seed(
        case.assembly,
        case.seeds[0],
        settings_from_manifest(manifest),
    )
    audits = _final_audits(case, result.evaluation, result.scales, manifest)
    kkt = audits.pop("kkt_object")
    ids = result.evaluation.contact.constraint_ids
    expected = case.expectation
    checks = {
        "restoration_executed": result.restoration.executed,
        "restoration_converged": result.restoration.converged,
        "four_near_active_identities": _identity_subset(ids, kkt.near_active_indices)
        == expected.near_active_constraint_ids,
        "two_supported_identities": _identity_subset(ids, kkt.supported_indices)
        == expected.supported_constraint_ids,
        "two_weak_active_identities": kkt.weak_active_indices.size == 2,
        "near_active_rank_three": kkt.near_active_rank == expected.near_active_rank,
        "supported_rank_two": kkt.supported_rank == expected.supported_rank,
        "dual_nonuniqueness_reported": kkt.dual_nonunique,
        "mandatory_support_is_the_bob_pair": _identity_subset(
            ids,
            kkt.mandatory_supported_indices,
        )
        == expected.supported_constraint_ids,
        "kkt": kkt.passed,
        "critical_cone": bool(audits["critical_passed"]),
        "p2_unchanged": bool(audits["p2_potential_and_force_bitwise_unchanged"]),
    }
    return jsonable(
        {
            "case_id": case.case_id,
            "role": case.role,
            "restoration": _restoration_document(result),
            "checks": checks,
            "audits": audits,
            "status": "PASS" if all(checks.values()) else "FAIL",
        }
    )


def _target(
    case: P3R2StaticContactCase,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    records = []
    for seed in case.seeds:
        try:
            records.append(_seed_record(case, seed, manifest))
        except (ContactGeometryError, ValueError, np.linalg.LinAlgError) as error:
            records.append(
                {
                    "seed_id": seed.seed_id,
                    "execution_status": "FAIL_CLOSED_UNDEFINED_GEOMETRY_COORDINATE_OR_LINEAR_SYSTEM",
                    "failure_type": type(error).__name__,
                    "failure_message": str(error),
                    "qualified": False,
                }
            )
    completed = [item for item in records if item["execution_status"] == "COMPLETED"]
    qualified = [item for item in completed if item["qualified"]]
    if len(qualified) >= 2:
        positions = np.asarray([item["bob_position_m"] for item in qualified], dtype=float)
        energies = np.asarray([item["total_potential_J"] for item in qualified], dtype=float)
        position_spread = float(
            max(
                np.linalg.norm(first - second)
                for first in positions
                for second in positions
            )
        )
        energy_spread = float(np.max(energies) - np.min(energies))
    else:
        position_spread = float("inf")
        energy_spread = float("inf")
    contract = case.contract
    multiseed_checks = {
        "required_passing_seed_count": len(qualified)
        == int(contract["required_passing_seed_count"]),
        "position_spread": position_spread
        <= float(contract["multiseed_position_spread_max_m"]),
        "energy_spread": energy_spread
        <= float(contract["multiseed_energy_spread_max_J"]),
    }
    selected = None
    if qualified:
        selected = min(
            qualified,
            key=lambda item: (float(item["total_potential_J"]), str(item["seed_id"])),
        )["seed_id"]
    passed = len(qualified) == len(records) and all(multiseed_checks.values())
    return jsonable(
        {
            "case_id": case.case_id,
            "role": case.role,
            "seed_count": len(records),
            "completed_seed_count": len(completed),
            "qualified_seed_count": len(qualified),
            "seeds": records,
            "multiseed_position_spread_m": position_spread,
            "multiseed_energy_spread_J": energy_spread,
            "multiseed_checks": multiseed_checks,
            "selected_seed_id": selected,
            "status": "PASS" if passed else "FAIL",
        }
    )


def build_g3r2_evidence(root: str | Path) -> dict[str, Any]:
    candidate_root = Path(root)
    manifest = load_json(
        candidate_root / "contracts" / "p3r2_acceptance_manifest.json"
    )
    binding = contract_binding(candidate_root, manifest)
    runtime = runtime_metrics(manifest)
    architecture = architecture_metrics(candidate_root, manifest)
    benchmarks = run_bound_benchmarks(candidate_root, manifest)
    adapter_hash = sha256(candidate_root / "contracts" / manifest["adapter_contract"])
    protocol_hash = sha256(candidate_root / "contracts" / manifest["frozen_protocol"])
    preconditions = bool(
        binding["status"] == "PASS"
        and runtime["status"] == "PASS"
        and architecture["status"] == "PASS"
        and benchmarks["status"] == "PASS"
    )
    if preconditions:
        structure_case = build_observed_symmetric_regression(
            manifest,
            adapter_contract_sha256=adapter_hash,
            frozen_protocol_sha256=protocol_hash,
        )
        structure = _structure_regression(structure_case, manifest)
    else:
        structure = {"status": "NOT_RUN_PRECONDITION_FAILURE", "seed_evaluations": 0}
    if structure["status"] == "PASS":
        p3r_case = build_observed_p3r_35_degree_regression(
            manifest,
            adapter_contract_sha256=adapter_hash,
            frozen_protocol_sha256=protocol_hash,
        )
        p3r_regression = _target(p3r_case, manifest)
    else:
        p3r_regression = {
            "status": "NOT_RUN_STRUCTURE_REGRESSION_FAILURE",
            "seed_evaluations": 0,
        }
    if p3r_regression["status"] == "PASS":
        qualification_cases = build_qualification_targets(
            manifest,
            adapter_contract_sha256=adapter_hash,
            frozen_protocol_sha256=protocol_hash,
        )
        qualification_targets = [
            _target(case, manifest) for case in qualification_cases
        ]
    else:
        qualification_targets = [
            {
                "case_id": contract["case_id"],
                "status": "NOT_RUN_P3R_35_DEGREE_REGRESSION_FAILURE",
                "seed_evaluations": 0,
            }
            for contract in manifest["qualification_targets"]
        ]
    gate_summary = {
        "contract_commits_and_frozen_source_binding": binding["status"] == "PASS",
        "exact_runtime": runtime["status"] == "PASS",
        "architecture": architecture["status"] == "PASS",
        "benchmark_identity_binding_before_targets": benchmarks["status"] == "PASS",
        "observed_symmetric_structure_regression": structure["status"] == "PASS",
        "observed_P3R_35_degree_three_seed_regression": (
            p3r_regression["status"] == "PASS"
        ),
        "two_prefrozen_unobserved_qualification_targets": bool(
            qualification_targets
            and all(target["status"] == "PASS" for target in qualification_targets)
        ),
    }
    status = manifest["pass_status"] if all(gate_summary.values()) else manifest["fail_status"]
    return jsonable(
        {
            "schema": "YPS-HFV2-G3R2-EVIDENCE-1.0",
            "status": status,
            "contact_model_id": P3R2_CONTACT_MODEL_ID,
            "composite_algorithm_identity": manifest["composite_algorithm_identity"],
            "component_scale_identity": manifest["component_scale_identity"],
            "formal_numerical_qualification": manifest[
                "formal_numerical_qualification"
            ],
            "mandatory_stop": manifest["mandatory_stop_after_evidence"],
            "optimizer_success_used_as_acceptance_gate": False,
            "gate_summary": gate_summary,
            "contract_binding": binding,
            "runtime": runtime,
            "architecture": architecture,
            "small_benchmarks": benchmarks,
            "observed_symmetric_structure_regression": structure,
            "observed_p3r_35_degree_regression": p3r_regression,
            "qualification_targets": qualification_targets,
            "historical_g3_status_preserved": manifest[
                "historical_g3_status_preserved"
            ],
            "historical_g3r_status_preserved": manifest[
                "historical_g3r_status_preserved"
            ],
            "forbidden_scope_not_executed": manifest["forbidden"],
            "not_executed": manifest["not_executed"],
            "evidence_binding": evidence_hash_binding(candidate_root, manifest),
        }
    )


def render_g3r2_report(evidence: dict[str, Any], metrics_sha256: str) -> str:
    lines = [
        "# HF-v2 G3R2 静态接触数值认证证据报告",
        "",
        f"状态：`{evidence['status']}`",
        "",
        f"指标 SHA-256：`{metrics_sha256}`",
        "",
        "## 1. 结论边界",
        "",
        "本报告只评价候选静态、无摩擦、刚性、单边法向接触算法的数值认证闭合。",
        "它不是装置预测、物理验证或实验验证。正式高保真总状态仍为",
        f"`{evidence['formal_numerical_qualification']}`。",
        "",
        "历史 G3 和 G3R 的冻结 NO-GO、报告、指标与哈希均保持不变。",
        "",
        "## 2. 门禁结果",
        "",
    ]
    for identity, passed in evidence["gate_summary"].items():
        lines.append(f"- `{identity}`：{'PASS' if passed else 'FAIL'}")
    lines.extend(
        [
            "",
            "## 3. 历史结构与 35 度回归",
            "",
            "旧对称结构回归状态：",
            f"`{evidence['observed_symmetric_structure_regression']['status']}`。",
            "",
            "P3R 35 度三种子回归状态：",
            f"`{evidence['observed_p3r_35_degree_regression']['status']}`。",
        ]
    )
    p3r = evidence["observed_p3r_35_degree_regression"]
    if p3r.get("seeds"):
        lines.append("")
        for seed in p3r["seeds"]:
            lines.append(
                f"- `{seed['seed_id']}`：执行 `{seed['execution_status']}`，"
                f"资格 `{'PASS' if seed.get('qualified') else 'FAIL'}`"
            )
    lines.extend(["", "## 4. 两个新资格目标", ""])
    for target in evidence["qualification_targets"]:
        lines.append(f"### {target['case_id']}")
        lines.append("")
        lines.append(f"状态：`{target['status']}`。")
        if target.get("seeds"):
            lines.append("")
            for seed in target["seeds"]:
                lines.append(
                    f"- `{seed['seed_id']}`：执行 `{seed['execution_status']}`，"
                    f"资格 `{'PASS' if seed.get('qualified') else 'FAIL'}`"
                )
            lines.extend(
                [
                    "",
                    f"合格种子数：`{target['qualified_seed_count']}/{target['seed_count']}`。",
                    "",
                    f"位置展宽：`{target['multiseed_position_spread_m']}` m。",
                    "",
                    f"势能展宽：`{target['multiseed_energy_spread_J']}` J。",
                ]
            )
        lines.append("")
    lines.extend(
        [
            "## 5. 停止门",
            "",
            f"本轮强制停在 `{evidence['mandatory_stop']}`。不进入 P4、P5 或 P6。",
            "",
            "未修改正式理论、正式程序、公共 API、HDF5 或 UI。",
            "",
        ]
    )
    return "\n".join(lines)


def canonical_json_bytes(evidence: dict[str, Any]) -> bytes:
    return (
        json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def report_for_metrics(evidence: dict[str, Any]) -> tuple[bytes, str]:
    metrics = canonical_json_bytes(evidence)
    digest = hashlib.sha256(metrics).hexdigest()
    return metrics, render_g3r2_report(evidence, digest)
