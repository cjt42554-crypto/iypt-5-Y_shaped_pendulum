"""One-shot P3R4 reference, second-order and manifold admissibility campaign."""

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
from ypendulum_hfv2_p3r3.admissibility import (
    _critical_document,
    _critical_kwargs,
    _dual_document,
    _identity_subset,
    _jacobian_document,
)
from ypendulum_hfv2_p3r3.solver import (
    settings_from_manifest as predecessor_settings_from_manifest,
)
from ypendulum_hfv2_p3r3.solver import (
    solve_contact_seed as solve_predecessor_seed,
)

from . import (
    P3R4_CONTACT_MODEL_ID,
    P3R4_MANIFOLD_RETRACTION_ID,
    P3R4_REFERENCE_DISCOVERY_ID,
    P3R4_SECOND_ORDER_ID,
    P3R4_TARGET_ADMISSIBILITY_ID,
)
from .cases import P3R4DesignCase, build_admissibility_selection, build_design_case
from .certification import characteristic_scales, deterministic_tangent_basis
from .dual_certification import (
    audit_contact_kkt,
    certify_centered_dual,
    component_allowed_raw,
    thresholds_from_manifest,
)
from .evidence_support import contract_binding, git_head, jsonable, load_json, sha256
from .manifold import audit_manifold_neighborhood
from .restoration import audit_full_composite_jacobian
from .second_order import audit_reference_second_order
from .solver import settings_from_manifest

Checkpoint = Callable[[list[dict[str, Any]]], None]


def _component_kkt_passed(kkt: object, thresholds: object) -> bool:
    return bool(
        kkt.finite
        and kkt.primal_violation_m <= thresholds.primal_penetration_max_m
        and kkt.dual_violation_N <= thresholds.dual_negative_max_N
        and kkt.legacy_stationarity_passed
        and kkt.translation_stationarity_passed
        and kkt.rotation_stationarity_passed
        and kkt.dimensionless_stationarity_passed
        and kkt.complementarity_residual_N_m <= kkt.complementarity_limit_N_m
        and kkt.supported_rank == kkt.supported_indices.size
    )


def _admissibility_audits(
    case: P3R4DesignCase,
    coordinates: object,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    evaluation = case.assembly.evaluate(coordinates)
    scales = characteristic_scales(case.assembly)
    thresholds = thresholds_from_manifest(manifest)
    kkt = audit_contact_kkt(case.assembly, evaluation, thresholds, scales)
    dual = None
    if kkt.near_active_indices.size == 2:
        dual = certify_centered_dual(
            evaluation,
            kkt.near_active_indices,
            kkt.canonical_multipliers_N,
            scales,
            component_allowed_raw(scales, thresholds),
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
    tangent_basis = None
    second_order = None
    manifold = None
    jacobian_audit = None
    if kkt.supported_indices.size == 2:
        active_multipliers = kkt.canonical_multipliers_N[kkt.supported_indices]
        tangent_basis = deterministic_tangent_basis(
            case.assembly,
            evaluation,
            kkt.supported_indices,
            scales,
            rank_relative_tolerance=float(manifest["kkt"]["rank_relative_tolerance"]),
        )
        second_order = audit_reference_second_order(
            case.assembly,
            coordinates,
            evaluation,
            kkt.supported_indices,
            active_multipliers,
            scales,
            tangent_basis,
            manifest,
        )
        manifold = audit_manifold_neighborhood(
            case.assembly,
            coordinates,
            evaluation,
            kkt.supported_indices,
            scales,
            tangent_basis,
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
        "thresholds": thresholds,
        "kkt": kkt,
        "dual": dual,
        "physical_samples": physical_samples,
        "validity_samples": validity_samples,
        "critical": critical,
        "action": action,
        "p2_unchanged": p2_unchanged,
        "tangent_basis": tangent_basis,
        "second_order": second_order,
        "manifold": manifold,
        "jacobian_audit": jacobian_audit,
    }


def _invalid_discovery_record(
    case: P3R4DesignCase,
    reason: str,
    *,
    failure_type: str | None = None,
) -> dict[str, Any]:
    return {
        "design_id": case.design_id,
        "category": case.category,
        "reference_discovery_identity": P3R4_REFERENCE_DISCOVERY_ID,
        "input_assembly_validation_execution_count": 1,
        "reference_discovery_execution_count": 1,
        "admissibility_execution_count": 0,
        "second_order_execution_count": 0,
        "manifold_neighborhood_execution_count": 0,
        "status": "TARGET_INVALID",
        "failure_stage": "REFERENCE_DISCOVERY",
        "failure_reason": reason,
        "failure_type": failure_type,
        "qualification_seed_execution_count": 0,
    }


def _invalid_input_record(
    contract: dict[str, Any],
    reason: str,
    *,
    failure_type: str,
) -> dict[str, Any]:
    """Fail one frozen design closed before any numerical solver is entered."""

    return {
        "design_id": str(contract["design_id"]),
        "category": str(contract["category"]),
        "reference_discovery_identity": P3R4_REFERENCE_DISCOVERY_ID,
        "target_admissibility_identity": P3R4_TARGET_ADMISSIBILITY_ID,
        "second_order_identity": P3R4_SECOND_ORDER_ID,
        "manifold_retraction_identity": P3R4_MANIFOLD_RETRACTION_ID,
        "input_assembly_validation_execution_count": 1,
        "reference_discovery_execution_count": 0,
        "admissibility_execution_count": 0,
        "second_order_execution_count": 0,
        "manifold_neighborhood_execution_count": 0,
        "qualification_seed_execution_count": 0,
        "status": "TARGET_INVALID",
        "failure_stage": "INPUT_ASSEMBLY_VALIDATION",
        "failure_reason": reason,
        "failure_type": failure_type,
    }


def _run_design(
    case: P3R4DesignCase,
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
    thresholds = audits["thresholds"]
    kkt = audits["kkt"]
    dual = audits["dual"]
    critical = audits["critical"]
    action = audits["action"]
    second_order = audits["second_order"]
    manifold = audits["manifold"]
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
    scale_value = case.contract.get("geometry_scale_from_P3R_35_degree")
    checks = {
        "identity_binding": bool(
            case.assembly.identity_binding["contact_model_id"] == P3R4_CONTACT_MODEL_ID
            and case.assembly.identity_binding["target_admissibility_identity"]
            == P3R4_TARGET_ADMISSIBILITY_ID
            and case.assembly.identity_binding["second_order_identity"] == P3R4_SECOND_ORDER_ID
            and case.assembly.identity_binding["manifold_retraction_identity"]
            == P3R4_MANIFOLD_RETRACTION_ID
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
        "scale_design_is_new": bool(
            case.category != "changed_geometry_and_load_scale"
            or scale_value in (0.82, 1.05, 1.3, 1.75)
        ),
        "component_scaled_kkt": _component_kkt_passed(kkt, thresholds),
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
        "second_order_consistency": bool(second_order is not None and second_order.passed),
        "manifold_neighborhood": bool(manifold is not None and manifold.passed),
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
            "reference_discovery_identity": P3R4_REFERENCE_DISCOVERY_ID,
            "target_admissibility_identity": P3R4_TARGET_ADMISSIBILITY_ID,
            "second_order_identity": P3R4_SECOND_ORDER_ID,
            "manifold_retraction_identity": P3R4_MANIFOLD_RETRACTION_ID,
            "input_assembly_validation_execution_count": 1,
            "reference_discovery_execution_count": 1,
            "admissibility_execution_count": 1,
            "second_order_execution_count": 1,
            "manifold_neighborhood_execution_count": 1,
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
            "second_order_numerics": (asdict(second_order) if second_order is not None else None),
            "manifold_neighborhood": asdict(manifold) if manifold is not None else None,
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
    manifest = load_json(root / "contracts/p3r4_acceptance_manifest.json")
    predecessor = load_json(root / "contracts/p3r3_acceptance_manifest.json")
    design_cards = load_json(root / "contracts/p3r4_design_cards.json")
    binding = contract_binding(root, manifest, required_stage="implementation")
    if binding["status"] != "PASS":
        raise RuntimeError("P3R4 implementation binding is not committed and closed.")
    repository_root = root.parents[2]
    implementation_commit = git_head(repository_root)
    adapter_contract_sha256 = sha256(root / "contracts" / manifest["adapter_contract"])
    frozen_protocol_sha256 = sha256(root / "contracts" / manifest["frozen_protocol"])
    predecessor_adapter_sha256 = sha256(root / "contracts/p3r3_contact_adapter_contract.json")
    predecessor_protocol_sha256 = sha256(root / "contracts/P3R3_FROZEN_PROTOCOL.md")
    outcomes: list[dict[str, Any]] = []
    for design_contract in design_cards["design_cards"]:
        try:
            case = build_design_case(
                manifest,
                predecessor,
                design_contract,
                adapter_contract_sha256=adapter_contract_sha256,
                frozen_protocol_sha256=frozen_protocol_sha256,
                predecessor_adapter_sha256=predecessor_adapter_sha256,
                predecessor_protocol_sha256=predecessor_protocol_sha256,
            )
        except (ContactGeometryError, ValueError, np.linalg.LinAlgError) as error:
            outcome = _invalid_input_record(
                design_contract,
                str(error),
                failure_type=type(error).__name__,
            )
        else:
            outcome = _run_design(case, manifest, predecessor)
        outcomes.append(outcome)
        if checkpoint is not None:
            checkpoint(outcomes)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    selection = build_admissibility_selection(
        manifest,
        design_cards,
        outcomes,
        implementation_commit=implementation_commit,
        generated_at=generated_at,
    )
    metrics = {
        "schema": "YPS-HFV2-P3R4-ADMISSIBILITY-EVIDENCE-1.0",
        "generated_at": generated_at,
        "implementation_commit": implementation_commit,
        "design_card_sha256": sha256(root / "contracts/p3r4_design_cards.json"),
        "design_card_attempt_count": len(outcomes),
        "input_assembly_validation_run_count": sum(
            int(item["input_assembly_validation_execution_count"]) for item in outcomes
        ),
        "reference_discovery_run_count": sum(
            int(item["reference_discovery_execution_count"]) for item in outcomes
        ),
        "target_admissibility_run_count": sum(
            int(item["admissibility_execution_count"]) for item in outcomes
        ),
        "second_order_run_count": sum(
            int(item["second_order_execution_count"]) for item in outcomes
        ),
        "manifold_neighborhood_run_count": sum(
            int(item["manifold_neighborhood_execution_count"]) for item in outcomes
        ),
        "target_freeze_run_count": 0,
        "qualification_seed_run_count": 0,
        "selection_rule": manifest["target_design_and_selection"]["selection_rule"],
        "outcomes": outcomes,
        "selected_design_ids": selection["selected_design_ids"],
        "selection_status": selection["status"],
        "status": selection["status"],
        "formal_numerical_qualification": manifest["formal_numerical_qualification"],
        "mandatory_stop_after_evidence": manifest["mandatory_stop_after_evidence"],
    }
    report = render_admissibility_report(metrics)
    return jsonable(metrics), jsonable(selection), report


def render_admissibility_report(metrics: dict[str, Any]) -> str:
    lines = [
        "# P3R4 目标准入报告",
        "",
        f"生成时间：{metrics['generated_at']}",
        "",
        f"实现提交：`{metrics['implementation_commit']}`",
        "",
        f"分类状态：`{metrics['status']}`",
        "",
        "本报告只覆盖参考点约束稳定性、二阶数值一致性和约束流形有限邻域；不含资格种子运行，不构成正式数值资格、物理验证或实验验证。",
        "",
        "| 设计卡 | 类别 | 输入装配 | 参考运行 | 准入运行 | 二阶审计 | 流形审计 | 失败阶段 | 状态 |",
        "|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for item in metrics["outcomes"]:
        lines.append(
            f"| {item['design_id']} | {item['category']} | "
            f"{item['input_assembly_validation_execution_count']} | "
            f"{item['reference_discovery_execution_count']} | "
            f"{item['admissibility_execution_count']} | "
            f"{item['second_order_execution_count']} | "
            f"{item['manifold_neighborhood_execution_count']} | "
            f"{item.get('failure_stage', '-')} | {item['status']} |"
        )
    lines.extend(["", "## 选择结果", ""])
    if metrics["selected_design_ids"]:
        for category, design_id in metrics["selected_design_ids"].items():
            lines.append(f"- `{category}`：`{design_id}`")
        lines.append("")
        lines.append("目标与算法初值尚未冻结；必须先提交本准入结果。")
    else:
        lines.append("- 未形成完整目标套件，不得冻结或运行资格种子。")
    lines.extend(
        [
            "",
            f"资格种子结果运行数：`{metrics['qualification_seed_run_count']}`。",
            "",
            f"正式高保真数值资格保持：`{metrics['formal_numerical_qualification']}`。",
            "",
            f"最终停止门仍为：`{metrics['mandatory_stop_after_evidence']}`。",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "render_admissibility_report",
    "run_admissibility_campaign",
]
