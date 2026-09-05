"""One-shot P3R3 reference discovery, target admissibility and seed freeze."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
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
from ypendulum_hfv2_p3r.kkt import matrix_rank
from ypendulum_hfv2_p3r2.solver import (
    settings_from_manifest as predecessor_settings_from_manifest,
)
from ypendulum_hfv2_p3r2.solver import solve_contact_seed as solve_predecessor_seed

from . import (
    P3R3_CONTACT_MODEL_ID,
    P3R3_LOCAL_BASIN_ID,
    P3R3_REFERENCE_DISCOVERY_ID,
    P3R3_TARGET_ADMISSIBILITY_ID,
)
from .cases import P3R3DesignCase, build_design_cases, build_target_freeze
from .certification import (
    characteristic_scales,
    deterministic_tangent_basis,
)
from .dual_certification import (
    audit_contact_kkt,
    certify_centered_dual,
    component_allowed_raw,
    thresholds_from_manifest,
)
from .evidence_support import (
    contract_binding,
    git_head,
    jsonable,
    load_json,
    sha256,
)
from .restoration import audit_full_composite_jacobian
from .solver import settings_from_manifest

Checkpoint = Callable[[list[dict[str, Any]]], None]


def _identity_subset(
    identities: tuple[str, ...],
    indices: np.ndarray,
) -> tuple[str, ...]:
    return tuple(identities[int(index)] for index in indices)


def _jacobian_document(samples: tuple[object, ...]) -> list[dict[str, float]]:
    return [
        {
            "difference_step": float(sample.difference_step),
            "maximum_row_relative_error": float(sample.maximum_row_relative_error),
            "matrix_relative_error": float(sample.matrix_relative_error),
        }
        for sample in samples
    ]


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


def _critical_document(audit: object) -> dict[str, Any]:
    return jsonable(
        {
            "passed": audit.passed,
            "unsymmetrized_relative_asymmetry": (audit.unsymmetrized_relative_asymmetry),
            "gauge_dimension": audit.gauge_dimension,
            "critical_equality_rank": audit.critical_equality_rank,
            "near_active_count": audit.near_active_count,
            "near_active_rank": audit.near_active_rank,
            "supported_tangent_dimension": audit.supported_tangent_dimension,
            "supported_tangent_eigenvalues": audit.supported_tangent_eigenvalues,
            "minimum_supported_tangent_curvature": (audit.minimum_supported_tangent_curvature),
            "critical_direction_count": audit.critical_direction_count,
            "critical_directions": audit.critical_directions,
            "critical_direction_minimum_linearized_gap": (
                audit.critical_direction_minimum_linearized_gap
            ),
            "matrix_directional_curvatures": audit.matrix_directional_curvatures,
            "independent_directional_curvatures": (audit.independent_directional_curvatures),
            "maximum_curvature_crosscheck_error": (audit.maximum_curvature_crosscheck_error),
            "minimum_critical_cone_curvature": (audit.minimum_critical_cone_curvature),
        }
    )


def _dual_document(certificate: object) -> dict[str, Any]:
    return jsonable(asdict(certificate))


def _tangent_directions(basis: np.ndarray) -> tuple[tuple[str, np.ndarray], ...]:
    if basis.shape != (6, 3):
        raise ValueError("P3R3 freezes a three-dimensional tangent basis.")
    directions: list[tuple[str, np.ndarray]] = [
        (f"basis_{index}", np.array(basis[:, index], copy=True)) for index in range(3)
    ]
    for first in range(3):
        for second in range(first + 1, 3):
            for operation, sign in (("sum", 1.0), ("difference", -1.0)):
                vector = basis[:, first] + sign * basis[:, second]
                vector /= np.linalg.norm(vector)
                directions.append((f"basis_{first}_{operation}_{second}", vector))
    return tuple(directions)


def _branch_correlations(
    reference_rows: np.ndarray,
    current_rows: np.ndarray,
    coordinate_scales: np.ndarray,
) -> np.ndarray:
    reference = reference_rows * coordinate_scales[None, :]
    current = current_rows * coordinate_scales[None, :]
    numerator = np.sum(reference * current, axis=1)
    denominator = np.linalg.norm(reference, axis=1) * np.linalg.norm(current, axis=1)
    return numerator / denominator


def _basin_certificate(
    case: P3R3DesignCase,
    coordinates: object,
    evaluation: object,
    supported_indices: np.ndarray,
    multipliers_N: np.ndarray,
    scales: object,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    local = manifest["local_basin"]
    rank_tolerance = float(manifest["kkt"]["rank_relative_tolerance"])
    basis = deterministic_tangent_basis(
        case.assembly,
        evaluation,
        supported_indices,
        scales,
        rank_relative_tolerance=rank_tolerance,
    )
    directions = _tangent_directions(basis)
    radius = float(local["coordinate_radius_dimensionless"])
    fractions = tuple(float(item) for item in local["probe_radius_fractions"])
    all_indices = np.arange(evaluation.contact.gaps_m.size)
    nonactive = np.setdiff1d(all_indices, supported_indices, assume_unique=True)
    reference_rows = evaluation.contact.gap_jacobian[supported_indices]
    reference_value = float(
        evaluation.total_potential - multipliers_N @ evaluation.contact.gaps_m[supported_indices]
    )
    records = []
    curvature_by_direction: dict[str, list[float]] = {identity: [] for identity, _ in directions}
    for identity, direction in directions:
        for fraction in fractions:
            layer_radius = fraction * radius
            endpoint_records = []
            lagrangian_values = []
            for sign in (-1.0, 1.0):
                values = coordinates.values + (
                    sign * layer_radius * scales.coordinate_scales * direction
                )
                current = case.assembly.evaluate(case.assembly.coordinates_from_values(values))
                current_rows = current.contact.gap_jacobian[supported_indices]
                correlations = _branch_correlations(
                    reference_rows,
                    current_rows,
                    scales.coordinate_scales,
                )
                active_rank = matrix_rank(current_rows, rank_tolerance)
                nonactive_minimum = (
                    float(np.min(current.contact.gaps_m[nonactive]))
                    if nonactive.size
                    else float("inf")
                )
                validity_minimum = float(np.min(current.validity.normalized_residuals))
                finite = bool(
                    np.all(np.isfinite(values))
                    and np.all(np.isfinite(current.contact.gaps_m))
                    and np.all(np.isfinite(current.validity.normalized_residuals))
                    and np.all(np.isfinite(correlations))
                )
                endpoint_records.append(
                    {
                        "sign": sign,
                        "finite": finite,
                        "minimum_nonactive_gap_m": nonactive_minimum,
                        "minimum_validity_normalized_residual": validity_minimum,
                        "supported_rank": active_rank,
                        "branch_orientation_correlations": correlations,
                        "passed": bool(
                            finite
                            and nonactive_minimum
                            > float(local["probe_nonactive_contact_gap_strict_min_m"])
                            and validity_minimum
                            >= float(local["probe_validity_normalized_margin_min"])
                            and active_rank == supported_indices.size
                            and float(np.min(correlations)) > 0.0
                        ),
                    }
                )
                lagrangian_values.append(
                    float(
                        current.total_potential
                        - multipliers_N @ current.contact.gaps_m[supported_indices]
                    )
                )
            curvature = (lagrangian_values[1] - 2.0 * reference_value + lagrangian_values[0]) / (
                layer_radius**2 * scales.energy_N_m
            )
            curvature_by_direction[identity].append(float(curvature))
            records.append(
                {
                    "direction_id": identity,
                    "radius_fraction": fraction,
                    "dimensionless_radius": layer_radius,
                    "normalized_curvature": float(curvature),
                    "endpoints": endpoint_records,
                    "passed": bool(
                        all(item["passed"] for item in endpoint_records)
                        and curvature >= float(local["probe_minimum_normalized_curvature"])
                    ),
                }
            )
    layer_differences = {
        identity: abs(values[1] - values[0]) for identity, values in curvature_by_direction.items()
    }
    same_sign = {
        identity: bool(values[0] * values[1] > 0.0)
        for identity, values in curvature_by_direction.items()
    }
    passed = bool(
        all(item["passed"] for item in records)
        and all(same_sign.values())
        and max(layer_differences.values())
        <= float(local["two_radius_curvature_absolute_difference_max"])
    )
    return jsonable(
        {
            "identity": P3R3_LOCAL_BASIN_ID,
            "passed": passed,
            "dimensionless_radius": radius,
            "tangent_basis": basis,
            "direction_count_unoriented": len(directions),
            "endpoint_probe_count": 2 * len(directions) * len(fractions),
            "records": records,
            "same_sign_by_direction": same_sign,
            "two_radius_curvature_difference_by_direction": layer_differences,
            "maximum_two_radius_curvature_difference": max(layer_differences.values()),
        }
    )


def _admissibility_audits(
    case: P3R3DesignCase,
    coordinates: object,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    evaluation = case.assembly.evaluate(coordinates)
    scales = characteristic_scales(case.assembly)
    thresholds = thresholds_from_manifest(manifest)
    kkt = audit_contact_kkt(case.assembly, evaluation, thresholds, scales)
    allowed = component_allowed_raw(scales, thresholds)
    dual = None
    if kkt.near_active_indices.size == 2:
        dual = certify_centered_dual(
            evaluation,
            kkt.near_active_indices,
            kkt.canonical_multipliers_N,
            scales,
            allowed,
            manifest,
        )
    physical_samples = physical_gap_jacobian_samples(
        case.assembly,
        coordinates,
        tuple(manifest["jacobian_audits"]["physical_gap_steps"]),
    )
    validity_samples = validity_jacobian_samples(
        case.assembly,
        coordinates,
        tuple(manifest["jacobian_audits"]["validity_five_point_steps"]),
    )
    critical = audit_critical_cone(
        case.assembly,
        coordinates,
        kkt,
        **_critical_kwargs(manifest),
    )
    action = contact_action_reaction_audit(
        evaluation.contact,
        kkt.canonical_multipliers_N,
    )
    base_coordinates = case.assembly.base_assembly.coordinates_from_values(coordinates.values)
    base = case.assembly.base_assembly.evaluate(base_coordinates)
    p2_unchanged = bool(
        evaluation.total_potential == base.total_potential
        and np.array_equal(evaluation.generalized_force, base.generalized_force)
    )
    basin = None
    jacobian_audit = None
    if kkt.supported_indices.size == 2:
        active_multipliers = kkt.canonical_multipliers_N[kkt.supported_indices]
        basin = _basin_certificate(
            case,
            coordinates,
            evaluation,
            kkt.supported_indices,
            active_multipliers,
            scales,
            manifest,
        )
        jacobian_audit = audit_full_composite_jacobian(
            case.assembly,
            coordinates,
            kkt.supported_indices,
            active_multipliers,
            scales,
            settings_from_manifest(manifest).restoration,
        )
    return {
        "evaluation": evaluation,
        "scales": scales,
        "kkt": kkt,
        "dual": dual,
        "physical_samples": physical_samples,
        "validity_samples": validity_samples,
        "critical": critical,
        "action": action,
        "p2_unchanged": p2_unchanged,
        "basin": basin,
        "jacobian_audit": jacobian_audit,
    }


def _invalid_discovery_record(
    case: P3R3DesignCase,
    reason: str,
    *,
    failure_type: str | None = None,
) -> dict[str, Any]:
    return {
        "design_id": case.design_id,
        "category": case.category,
        "reference_discovery_identity": P3R3_REFERENCE_DISCOVERY_ID,
        "reference_discovery_execution_count": 1,
        "admissibility_execution_count": 0,
        "status": "TARGET_INVALID",
        "failure_stage": "REFERENCE_DISCOVERY",
        "failure_reason": reason,
        "failure_type": failure_type,
        "qualification_seed_execution_count": 0,
    }


def _run_design(
    case: P3R3DesignCase,
    manifest: dict[str, Any],
    predecessor_manifest: dict[str, Any],
) -> dict[str, Any]:
    try:
        discovery = solve_predecessor_seed(
            case.predecessor_assembly,
            case.discovery_seed,
            predecessor_settings_from_manifest(predecessor_manifest),
        )
    except (ContactGeometryError, ValueError, np.linalg.LinAlgError) as error:
        return _invalid_discovery_record(
            case,
            str(error),
            failure_type=type(error).__name__,
        )
    if not discovery.restoration.converged:
        return _invalid_discovery_record(
            case,
            f"predecessor restoration status {discovery.restoration.status}",
        )
    coordinates = case.assembly.coordinates_from_values(discovery.coordinates.values)
    try:
        audits = _admissibility_audits(case, coordinates, manifest)
    except (ContactGeometryError, ValueError, np.linalg.LinAlgError) as error:
        record = _invalid_discovery_record(
            case,
            str(error),
            failure_type=type(error).__name__,
        )
        record["admissibility_execution_count"] = 1
        record["failure_stage"] = "TARGET_ADMISSIBILITY"
        return record
    evaluation = audits["evaluation"]
    scales = audits["scales"]
    kkt = audits["kkt"]
    dual = audits["dual"]
    critical = audits["critical"]
    action = audits["action"]
    basin = audits["basin"]
    jacobian_audit = audits["jacobian_audit"]
    ids = evaluation.contact.constraint_ids
    near_ids = _identity_subset(ids, kkt.near_active_indices)
    supported_ids = _identity_subset(ids, kkt.supported_indices)
    all_indices = np.arange(evaluation.contact.gaps_m.size)
    nonactive = np.setdiff1d(all_indices, kkt.near_active_indices, assume_unique=True)
    nonactive_minimum = (
        float(np.min(evaluation.contact.gaps_m[nonactive])) if nonactive.size else float("inf")
    )
    supported_multipliers = kkt.canonical_multipliers_N[kkt.supported_indices]
    multiplier_minimum = (
        float(np.min(supported_multipliers)) if supported_multipliers.size else float("-inf")
    )
    multiplier_difference = (
        float(abs(supported_multipliers[0] - supported_multipliers[1]))
        if supported_multipliers.size == 2
        else 0.0
    )
    witness_margin = (
        min(
            evaluation.contact.witnesses[int(index)].unit_interval_parameter_margin
            for index in kkt.supported_indices
        )
        if kkt.supported_indices.size
        else float("-inf")
    )
    target = manifest["target_admissibility"]
    action_contract = manifest["action_reaction"]
    component_kkt = bool(
        kkt.finite
        and kkt.primal_violation_m <= thresholds_from_manifest(manifest).primal_penetration_max_m
        and kkt.dual_violation_N <= thresholds_from_manifest(manifest).dual_negative_max_N
        and kkt.legacy_stationarity_passed
        and kkt.translation_stationarity_passed
        and kkt.rotation_stationarity_passed
        and kkt.dimensionless_stationarity_passed
        and kkt.complementarity_residual_N_m <= kkt.complementarity_limit_N_m
        and kkt.supported_rank == kkt.supported_indices.size
    )
    checks = {
        "identity_binding": bool(
            case.assembly.identity_binding["contact_model_id"] == P3R3_CONTACT_MODEL_ID
            and case.assembly.identity_binding["target_admissibility_identity"]
            == P3R3_TARGET_ADMISSIBILITY_ID
            and case.contract["design_id"] == case.design_id
            and case.contract["category"] == case.category
        ),
        "finite": bool(
            np.all(np.isfinite(coordinates.values))
            and np.all(np.isfinite(evaluation.contact.gaps_m))
            and np.all(np.isfinite(evaluation.validity.normalized_residuals))
        ),
        "strict_validity": float(np.min(evaluation.validity.normalized_residuals))
        >= float(target["strict_validity_normalized_margin_min"]),
        "exactly_two_near_active_bob_contacts": bool(
            kkt.near_active_indices.size == int(target["required_near_active_count"])
            and all(identity.startswith("bob:") for identity in near_ids)
        ),
        "exactly_two_supported_bob_contacts": bool(
            kkt.supported_indices.size == int(target["required_supported_count"])
            and all(identity.startswith("bob:") for identity in supported_ids)
        ),
        "supported_rank_two": kkt.supported_rank == int(target["required_supported_rank"]),
        "strict_nonactive_gap": nonactive_minimum
        > float(target["nonactive_contact_gap_strict_min_m"]),
        "strict_positive_multipliers": multiplier_minimum
        > float(target["positive_supported_multiplier_strict_min_N"]),
        "asymmetric_multiplier_difference": bool(
            case.category != "asymmetric_unequal_positive_multipliers"
            or multiplier_difference
            > float(target["asymmetric_multiplier_difference_strict_min_N"])
        ),
        "scale_design_not_historical_1p0_or_1p4": bool(
            case.category != "changed_geometry_and_load_scale"
            or (
                "geometry_scale_from_P3R_35_degree" in case.contract
                and not np.isclose(
                    float(case.contract["geometry_scale_from_P3R_35_degree"]),
                    1.0,
                )
                and not np.isclose(
                    float(case.contract["geometry_scale_from_P3R_35_degree"]),
                    1.4,
                )
            )
        ),
        "component_scaled_kkt": component_kkt,
        "centered_dual_certificate": bool(dual is not None and dual.passed),
        "interior_witnesses": witness_margin
        >= float(target["supported_witness_parameter_margin_min"]),
        "action_reaction_force": float(action.maximum_individual_force_residual_N)
        <= float(action_contract["force_residual_max_N"]),
        "action_reaction_moment": float(action.maximum_individual_moment_residual_N_m)
        <= float(action_contract["moment_residual_max_N_m"]),
        "p2_bitwise_unchanged": bool(audits["p2_unchanged"]),
        "critical_cone_strict_curvature": bool(
            critical.minimum_critical_cone_curvature
            > float(manifest["critical_cone_second_order"]["minimum_normalized_curvature"])
            and critical.minimum_supported_tangent_curvature
            > float(manifest["critical_cone_second_order"]["minimum_normalized_curvature"])
        ),
        "critical_cone_crosscheck": bool(critical.passed),
        "physical_gap_jacobian": audits["physical_samples"][-1].maximum_row_relative_error
        <= float(manifest["jacobian_audits"]["physical_final_error_max"]),
        "validity_jacobian": audits["validity_samples"][-1].maximum_row_relative_error
        <= float(manifest["jacobian_audits"]["validity_final_error_max"]),
        "local_basin": bool(basin is not None and basin["passed"]),
        "full_composite_jacobian": bool(jacobian_audit is not None and jacobian_audit.passed),
    }
    internal = bool(dual is not None and dual.status == "CERTIFIER_INTERNAL_INCONSISTENCY")
    status = (
        "CERTIFIER_INTERNAL_INCONSISTENCY"
        if internal
        else "ADMISSIBLE"
        if all(checks.values())
        else "TARGET_INVALID"
    )
    return jsonable(
        {
            "design_id": case.design_id,
            "category": case.category,
            "reference_discovery_identity": P3R3_REFERENCE_DISCOVERY_ID,
            "target_admissibility_identity": P3R3_TARGET_ADMISSIBILITY_ID,
            "reference_discovery_execution_count": 1,
            "admissibility_execution_count": 1,
            "qualification_seed_execution_count": 0,
            "predecessor_optimizer": {
                "success": discovery.optimizer_success,
                "success_used_as_admissibility_gate": False,
                "status": discovery.optimizer_status,
                "message": discovery.optimizer_message,
                "iterations": discovery.optimizer_iterations,
            },
            "predecessor_restoration": {
                "executed": discovery.restoration.executed,
                "converged": discovery.restoration.converged,
                "status": discovery.restoration.status,
                "iterations": discovery.restoration.iterations,
            },
            "contact_assembly_token": case.assembly.contact_assembly_token,
            "reference_coordinates": coordinates.values,
            "reference_total_potential_J": evaluation.total_potential,
            "characteristic_scales": {
                "length_m": scales.length_m,
                "force_N": scales.force_N,
                "energy_N_m": scales.energy_N_m,
                "coordinate_scales": scales.coordinate_scales,
                "stationarity_scales": scales.stationarity_scales,
            },
            "near_active_ids": near_ids,
            "supported_ids": supported_ids,
            "canonical_multipliers_N": kkt.canonical_multipliers_N,
            "supported_multiplier_difference_N": multiplier_difference,
            "minimum_nonactive_gap_m": nonactive_minimum,
            "minimum_validity_normalized_residual": float(
                np.min(evaluation.validity.normalized_residuals)
            ),
            "supported_witness_parameter_margin": witness_margin,
            "near_active_rank": kkt.near_active_rank,
            "supported_rank": kkt.supported_rank,
            "stationarity": {
                "raw": kkt.stationarity_vector_N,
                "dimensionless": kkt.dimensionless_stationarity,
                "component_allowed_raw": kkt.component_allowed_raw,
                "complementarity_residual_N_m": kkt.complementarity_residual_N_m,
                "complementarity_limit_N_m": kkt.complementarity_limit_N_m,
            },
            "dual_certificate": _dual_document(dual) if dual is not None else None,
            "critical_cone": _critical_document(critical),
            "physical_gap_jacobian": _jacobian_document(audits["physical_samples"]),
            "validity_jacobian": _jacobian_document(audits["validity_samples"]),
            "action_reaction": {
                "maximum_individual_force_residual_N": (action.maximum_individual_force_residual_N),
                "maximum_individual_moment_residual_N_m": (
                    action.maximum_individual_moment_residual_N_m
                ),
                "global_force_residual_N": action.global_force_residual_N,
                "global_moment_residual_N_m": action.global_moment_residual_N_m,
            },
            "p2_potential_and_force_bitwise_unchanged": audits["p2_unchanged"],
            "local_basin": basin,
            "full_composite_jacobian": (
                asdict(jacobian_audit) if jacobian_audit is not None else None
            ),
            "checks": checks,
            "status": status,
        }
    )


def run_admissibility_campaign(
    root: Path,
    *,
    checkpoint: Checkpoint | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    manifest = load_json(root / "contracts/p3r3_acceptance_manifest.json")
    predecessor = load_json(root / "contracts/p3r2_acceptance_manifest.json")
    design_cards = load_json(root / "contracts/p3r3_design_cards.json")
    binding = contract_binding(root, manifest, require_target_freeze=False)
    if binding["status"] != "PASS":
        raise RuntimeError("P3R3 implementation binding is not committed and closed.")
    repository_root = root.parents[2]
    implementation_commit = git_head(repository_root)
    cases = build_design_cases(
        manifest,
        predecessor,
        design_cards,
        adapter_contract_sha256=sha256(root / "contracts" / manifest["adapter_contract"]),
        frozen_protocol_sha256=sha256(root / "contracts" / manifest["frozen_protocol"]),
        predecessor_adapter_sha256=sha256(root / "contracts/p3r2_contact_adapter_contract.json"),
        predecessor_protocol_sha256=sha256(root / "contracts/P3R2_FROZEN_PROTOCOL.md"),
    )
    outcomes: list[dict[str, Any]] = []
    for case in cases:
        outcomes.append(_run_design(case, manifest, predecessor))
        if checkpoint is not None:
            checkpoint(outcomes)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    target_freeze = build_target_freeze(
        manifest,
        design_cards,
        outcomes,
        implementation_commit=implementation_commit,
        generated_at=generated_at,
    )
    internal = any(item["status"] == "CERTIFIER_INTERNAL_INCONSISTENCY" for item in outcomes)
    if internal:
        status = "CERTIFIER_INTERNAL_INCONSISTENCY"
    else:
        status = target_freeze["status"]
    metrics = {
        "schema": "YPS-HFV2-P3R3-ADMISSIBILITY-EVIDENCE-1.0",
        "generated_at": generated_at,
        "implementation_commit": implementation_commit,
        "design_card_sha256": sha256(root / "contracts/p3r3_design_cards.json"),
        "reference_discovery_run_count": len(outcomes),
        "target_admissibility_run_count": sum(
            int(item["admissibility_execution_count"]) for item in outcomes
        ),
        "qualification_seed_run_count": 0,
        "selection_rule": manifest["target_design_and_selection"]["selection_rule"],
        "outcomes": outcomes,
        "selected_design_ids": target_freeze["selected_design_ids"],
        "target_freeze_status": target_freeze["status"],
        "status": status,
        "formal_numerical_qualification": manifest["formal_numerical_qualification"],
        "mandatory_stop_after_evidence": manifest["mandatory_stop_after_evidence"],
    }
    report = render_admissibility_report(metrics)
    return jsonable(metrics), jsonable(target_freeze), report


def render_admissibility_report(metrics: dict[str, Any]) -> str:
    lines = [
        "# P3R3 目标准入报告",
        "",
        f"生成时间：{metrics['generated_at']}",
        "",
        f"实现提交：`{metrics['implementation_commit']}`",
        "",
        f"分类状态：`{metrics['status']}`",
        "",
        "本报告仅覆盖静态接触参考发现、目标准入、局部盆地和种子冻结；不构成正式数值资格、物理验证或实验验证。",
        "",
        "| 设计卡 | 类别 | 参考运行 | 准入运行 | 状态 |",
        "|---|---|---:|---:|---|",
    ]
    for item in metrics["outcomes"]:
        lines.append(
            f"| {item['design_id']} | {item['category']} | "
            f"{item['reference_discovery_execution_count']} | "
            f"{item['admissibility_execution_count']} | {item['status']} |"
        )
    lines.extend(
        [
            "",
            "## 选择结果",
            "",
        ]
    )
    if metrics["selected_design_ids"]:
        for category, design_id in metrics["selected_design_ids"].items():
            lines.append(f"- `{category}`：`{design_id}`")
    else:
        lines.append("- 未冻结资格目标。")
    lines.extend(
        [
            "",
            f"资格种子结果运行数：`{metrics['qualification_seed_run_count']}`。",
            "",
            f"正式高保真数值资格保持：`{metrics['formal_numerical_qualification']}`。",
            "",
            f"完成后停止门：`{metrics['mandatory_stop_after_evidence']}`。",
            "",
        ]
    )
    return "\n".join(lines)
