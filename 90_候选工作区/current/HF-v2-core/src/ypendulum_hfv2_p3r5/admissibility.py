"""One-shot P3R5 holdout reference, admissibility and manifold campaign."""

from __future__ import annotations

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
from ypendulum_hfv2_p3r4.restoration import audit_full_composite_jacobian

from . import (
    P3R5_CONTACT_MODEL_ID,
    P3R5_MANIFOLD_RETRACTION_ID,
    P3R5_REFERENCE_CONSTRUCTOR_ID,
    P3R5_SECOND_ORDER_ID,
    P3R5_TARGET_ADMISSIBILITY_ID,
)
from .attempt_ledger import AttemptLedger
from .cases import P3R5DesignCase, build_admissibility_selection, build_design_case
from .certification import characteristic_scales, deterministic_tangent_basis
from .dual_certification import (
    audit_contact_kkt,
    certify_centered_dual,
    component_allowed_raw,
    component_kkt_finite,
    component_kkt_passed,
    thresholds_from_manifest,
)
from .evidence_support import jsonable, sha256
from .manifold import audit_manifold_neighborhood
from .reference import construct_reference
from .reference import settings_from_manifest as reference_settings
from .second_order import audit_reference_second_order
from .solver import settings_from_manifest as qualification_settings


def _core_audits(
    case: P3R5DesignCase,
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
    qualification_jacobian = None
    if kkt.supported_indices.size == 2:
        tangent_basis = deterministic_tangent_basis(
            case.assembly,
            evaluation,
            kkt.supported_indices,
            scales,
            rank_relative_tolerance=float(manifest["kkt"]["rank_relative_tolerance"]),
        )
        qualification_jacobian = audit_full_composite_jacobian(
            case.assembly,
            coordinates,
            kkt.supported_indices,
            kkt.canonical_multipliers_N[kkt.supported_indices],
            scales,
            qualification_settings(manifest).restoration,
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
        "qualification_jacobian": qualification_jacobian,
    }


def _protocol_failure_record(
    contract: dict[str, Any],
    reason: str,
    failure_type: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    return {
        "holdout_id": str(contract["holdout_id"]),
        "category": str(contract["category"]),
        "reference_constructor_identity": P3R5_REFERENCE_CONSTRUCTOR_ID,
        "target_admissibility_identity": P3R5_TARGET_ADMISSIBILITY_ID,
        "second_order_identity": P3R5_SECOND_ORDER_ID,
        "manifold_retraction_identity": P3R5_MANIFOLD_RETRACTION_ID,
        "input_assembly_execution_count": 1,
        "reference_construction_execution_count": 0,
        "target_admissibility_execution_count": 0,
        "second_order_execution_count": 0,
        "manifold_neighborhood_execution_count": 0,
        "qualification_seed_execution_count": 0,
        "status": manifest["protocol_construction_fail_status"],
        "failure_stage": "INPUT_ASSEMBLY_VALIDATION",
        "failure_reason": reason,
        "failure_type": failure_type,
    }


def _reference_failure_record(
    case: P3R5DesignCase,
    reference: object,
) -> dict[str, Any]:
    return jsonable(
        {
            "holdout_id": case.design_id,
            "category": case.category,
            "reference_constructor_identity": P3R5_REFERENCE_CONSTRUCTOR_ID,
            "target_admissibility_identity": P3R5_TARGET_ADMISSIBILITY_ID,
            "second_order_identity": P3R5_SECOND_ORDER_ID,
            "manifold_retraction_identity": P3R5_MANIFOLD_RETRACTION_ID,
            "input_assembly_execution_count": 1,
            "reference_construction_execution_count": 1,
            "target_admissibility_execution_count": 0,
            "second_order_execution_count": 0,
            "manifold_neighborhood_execution_count": 0,
            "qualification_seed_execution_count": 0,
            "reference_constructor": {
                "converged": reference.converged,
                "status": reference.status,
                "iterations": reference.iterations,
                "total_backtracks": reference.total_backtracks,
                "initial_composite_residual": reference.initial_composite_residual,
                "final_composite_residual": reference.final_composite_residual,
                "accepted_step_lengths": reference.accepted_step_lengths,
                "linear_system_relative_singular_values": (
                    reference.linear_system_relative_singular_values
                ),
            },
            "status": "TARGET_INVALID",
            "failure_stage": "REFERENCE_CONSTRUCTION",
            "failure_reason": f"reference constructor status {reference.status}",
        }
    )


def _complete_record(
    case: P3R5DesignCase,
    reference: object,
    audits: dict[str, Any],
    second_order: object | None,
    manifold: object | None,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    coordinates = reference.coordinates
    evaluation = audits["evaluation"]
    scales = audits["scales"]
    thresholds = audits["thresholds"]
    kkt = audits["kkt"]
    dual = audits["dual"]
    critical = audits["critical"]
    action = audits["action"]
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
    declared = tuple(case.declared_active_constraint_ids)
    reference_jacobian_passed = bool(
        reference.jacobian_audit is not None and reference.jacobian_audit.passed
    )
    checks = {
        "identity_binding": bool(
            case.assembly.identity_binding["contact_model_id"] == P3R5_CONTACT_MODEL_ID
            and case.assembly.identity_binding["reference_constructor_identity"]
            == P3R5_REFERENCE_CONSTRUCTOR_ID
            and case.assembly.identity_binding["target_admissibility_identity"]
            == P3R5_TARGET_ADMISSIBILITY_ID
            and case.assembly.identity_binding["second_order_identity"] == P3R5_SECOND_ORDER_ID
            and case.assembly.identity_binding["manifold_retraction_identity"]
            == P3R5_MANIFOLD_RETRACTION_ID
        ),
        "finite": bool(
            np.all(np.isfinite(coordinates.values))
            and np.all(np.isfinite(evaluation.contact.gaps_m))
            and np.all(np.isfinite(evaluation.validity.normalized_residuals))
        ),
        "reference_full_jacobian": reference_jacobian_passed,
        "strict_validity": float(np.min(evaluation.validity.normalized_residuals))
        >= float(target["strict_validity_normalized_margin_min"]),
        "exactly_two_declared_near_active_bob_contacts": bool(
            kkt.near_active_indices.size == int(target["required_near_active_count"])
            and tuple(near_ids) == declared
            and all(identity.startswith("bob:") for identity in near_ids)
        ),
        "exactly_two_declared_supported_bob_contacts": bool(
            kkt.supported_indices.size == int(target["required_supported_count"])
            and tuple(supported_ids) == declared
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
        "pure_holdout_signature": bool(case.contract["pure_constructibility"]["passed"]),
        "component_kkt_finite_separated": component_kkt_finite(kkt, evaluation),
        "component_scaled_kkt": component_kkt_passed(kkt, thresholds, evaluation),
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
        "qualification_composite_jacobian": bool(
            audits["qualification_jacobian"] is not None and audits["qualification_jacobian"].passed
        ),
    }
    internal = bool(
        not reference_jacobian_passed
        or (dual is not None and dual.status == "CERTIFIER_INTERNAL_INCONSISTENCY")
    )
    status = (
        manifest["certifier_internal_status"]
        if internal
        else "ADMISSIBLE"
        if all(checks.values())
        else "TARGET_INVALID"
    )
    return jsonable(
        {
            "holdout_id": case.design_id,
            "category": case.category,
            "reference_constructor_identity": P3R5_REFERENCE_CONSTRUCTOR_ID,
            "target_admissibility_identity": P3R5_TARGET_ADMISSIBILITY_ID,
            "second_order_identity": P3R5_SECOND_ORDER_ID,
            "manifold_retraction_identity": P3R5_MANIFOLD_RETRACTION_ID,
            "input_assembly_execution_count": 1,
            "reference_construction_execution_count": 1,
            "target_admissibility_execution_count": 1,
            "second_order_execution_count": int(second_order is not None),
            "manifold_neighborhood_execution_count": int(manifold is not None),
            "qualification_seed_execution_count": 0,
            "reference_constructor": {
                "converged": reference.converged,
                "status": reference.status,
                "iterations": reference.iterations,
                "total_backtracks": reference.total_backtracks,
                "declared_active_constraint_ids": reference.declared_active_constraint_ids,
                "initial_active_multipliers_N": reference.initial_active_multipliers_N,
                "active_multipliers_N": reference.active_multipliers_N,
                "initial_composite_residual": reference.initial_composite_residual,
                "final_composite_residual": reference.final_composite_residual,
                "accepted_step_lengths": reference.accepted_step_lengths,
                "linear_system_relative_singular_values": (
                    reference.linear_system_relative_singular_values
                ),
                "full_jacobian_audit": asdict(reference.jacobian_audit),
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
                "legacy_dual_interval_endpoints_excluded_from_component_finiteness": True,
            },
            "dual_certificate": _dual_document(dual) if dual is not None else None,
            "critical_cone": _critical_document(critical),
            "physical_gap_jacobian": _jacobian_document(audits["physical_samples"]),
            "validity_jacobian": _jacobian_document(audits["validity_samples"]),
            "action_reaction": {
                "maximum_individual_force_residual_N": action.maximum_individual_force_residual_N,
                "maximum_individual_moment_residual_N_m": (
                    action.maximum_individual_moment_residual_N_m
                ),
                "global_force_residual_N": action.global_force_residual_N,
                "global_moment_residual_N_m": action.global_moment_residual_N_m,
            },
            "p2_potential_and_force_bitwise_unchanged": audits["p2_unchanged"],
            "second_order_numerics": asdict(second_order) if second_order is not None else None,
            "manifold_neighborhood": asdict(manifold) if manifold is not None else None,
            "qualification_composite_jacobian": (
                asdict(audits["qualification_jacobian"])
                if audits["qualification_jacobian"] is not None
                else None
            ),
            "checks": checks,
            "status": status,
        }
    )


def _run_design(
    case: P3R5DesignCase,
    manifest: dict[str, Any],
    ledger: AttemptLedger,
    cumulative_counts: dict[str, int],
) -> dict[str, Any]:
    ledger.checkpoint(
        "REFERENCE_CONSTRUCTION_STARTED",
        holdout_id=case.design_id,
        cumulative_run_counts=dict(cumulative_counts),
    )
    reference = construct_reference(
        case.assembly,
        case.initial_coordinates,
        case.declared_active_constraint_ids,
        reference_settings(manifest),
        manifest,
    )
    cumulative_counts["reference_construction"] += 1
    ledger.checkpoint(
        "REFERENCE_CONSTRUCTION_COMPLETED",
        holdout_id=case.design_id,
        status=reference.status,
        converged=reference.converged,
        cumulative_run_counts=dict(cumulative_counts),
    )
    if not reference.converged:
        return _reference_failure_record(case, reference)
    ledger.checkpoint(
        "TARGET_ADMISSIBILITY_STARTED",
        holdout_id=case.design_id,
        cumulative_run_counts=dict(cumulative_counts),
    )
    try:
        audits = _core_audits(case, reference.coordinates, manifest)
    except (ContactGeometryError, ValueError, np.linalg.LinAlgError) as error:
        cumulative_counts["target_admissibility"] += 1
        ledger.checkpoint(
            "TARGET_ADMISSIBILITY_FAILED",
            holdout_id=case.design_id,
            failure_type=type(error).__name__,
            failure_reason=str(error),
            cumulative_run_counts=dict(cumulative_counts),
        )
        record = _reference_failure_record(case, reference)
        record["target_admissibility_execution_count"] = 1
        record["failure_stage"] = "TARGET_ADMISSIBILITY"
        record["failure_type"] = type(error).__name__
        record["failure_reason"] = str(error)
        return record
    cumulative_counts["target_admissibility"] += 1
    ledger.checkpoint(
        "TARGET_ADMISSIBILITY_CORE_COMPLETED",
        holdout_id=case.design_id,
        cumulative_run_counts=dict(cumulative_counts),
    )
    second_order = None
    manifold = None
    if audits["tangent_basis"] is not None:
        active = audits["kkt"].supported_indices
        active_multipliers = audits["kkt"].canonical_multipliers_N[active]
        ledger.checkpoint(
            "SECOND_ORDER_AUDIT_STARTED",
            holdout_id=case.design_id,
            cumulative_run_counts=dict(cumulative_counts),
        )
        second_order = audit_reference_second_order(
            case.assembly,
            reference.coordinates,
            audits["evaluation"],
            active,
            active_multipliers,
            audits["scales"],
            audits["tangent_basis"],
            manifest,
        )
        cumulative_counts["second_order"] += 1
        ledger.checkpoint(
            "SECOND_ORDER_AUDIT_COMPLETED",
            holdout_id=case.design_id,
            passed=second_order.passed,
            cumulative_run_counts=dict(cumulative_counts),
        )
        ledger.checkpoint(
            "MANIFOLD_AUDIT_STARTED",
            holdout_id=case.design_id,
            cumulative_run_counts=dict(cumulative_counts),
        )
        manifold = audit_manifold_neighborhood(
            case.assembly,
            reference.coordinates,
            audits["evaluation"],
            active,
            audits["scales"],
            audits["tangent_basis"],
            manifest,
        )
        cumulative_counts["manifold_neighborhood"] += 1
        ledger.checkpoint(
            "MANIFOLD_AUDIT_COMPLETED",
            holdout_id=case.design_id,
            passed=manifold.passed,
            cumulative_run_counts=dict(cumulative_counts),
        )
    return _complete_record(
        case,
        reference,
        audits,
        second_order,
        manifold,
        manifest,
    )


def run_admissibility_campaign(
    root: Path,
    manifest: dict[str, Any],
    predecessor_manifest: dict[str, Any],
    holdout_freeze: dict[str, Any],
    ledger: AttemptLedger,
    *,
    implementation_commit: str,
    holdout_freeze_commit: str,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    adapter_sha = sha256(root / "contracts" / manifest["adapter_contract"])
    protocol_sha = sha256(root / "contracts" / manifest["frozen_protocol"])
    outcomes: list[dict[str, Any]] = []
    counts = {
        "input_assembly": 0,
        "reference_construction": 0,
        "target_admissibility": 0,
        "second_order": 0,
        "manifold_neighborhood": 0,
        "qualification_seed": 0,
    }
    stop_early = False
    for contract in holdout_freeze["holdout_cards"]:
        holdout_id = str(contract["holdout_id"])
        ledger.checkpoint(
            "INPUT_ASSEMBLY_STARTED",
            holdout_id=holdout_id,
            cumulative_run_counts=dict(counts),
        )
        try:
            case = build_design_case(
                manifest,
                predecessor_manifest,
                contract,
                adapter_contract_sha256=adapter_sha,
                frozen_protocol_sha256=protocol_sha,
            )
        except (ContactGeometryError, ValueError, np.linalg.LinAlgError) as error:
            counts["input_assembly"] += 1
            outcome = _protocol_failure_record(
                contract,
                str(error),
                type(error).__name__,
                manifest,
            )
            ledger.checkpoint(
                "INPUT_ASSEMBLY_PROTOCOL_CONSTRUCTION_FAILURE",
                holdout_id=holdout_id,
                failure_type=type(error).__name__,
                failure_reason=str(error),
                cumulative_run_counts=dict(counts),
            )
            outcomes.append(outcome)
            stop_early = True
        else:
            counts["input_assembly"] += 1
            ledger.checkpoint(
                "INPUT_ASSEMBLY_COMPLETED",
                holdout_id=holdout_id,
                contact_assembly_token=case.assembly.contact_assembly_token,
                cumulative_run_counts=dict(counts),
            )
            outcome = _run_design(case, manifest, ledger, counts)
            outcomes.append(outcome)
            ledger.checkpoint(
                "HOLDOUT_CLASSIFIED",
                holdout_id=holdout_id,
                status=outcome["status"],
                cumulative_run_counts=dict(counts),
            )
            stop_early = outcome["status"] == manifest["certifier_internal_status"]
        if stop_early:
            break
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    provisional = build_admissibility_selection(
        manifest,
        holdout_freeze,
        outcomes,
        implementation_commit=implementation_commit,
        holdout_freeze_commit=holdout_freeze_commit,
        attempt_ledger_sha256="PENDING_LEDGER_CLOSE",
        generated_at=generated_at,
    )
    ledger.checkpoint(
        "ADMISSIBILITY_CAMPAIGN_CLOSED",
        status=provisional["status"],
        attempted_holdout_count=len(outcomes),
        cumulative_run_counts=dict(counts),
        self_rerun_forbidden=True,
    )
    ledger_sha = sha256(ledger.path)
    selection = build_admissibility_selection(
        manifest,
        holdout_freeze,
        outcomes,
        implementation_commit=implementation_commit,
        holdout_freeze_commit=holdout_freeze_commit,
        attempt_ledger_sha256=ledger_sha,
        generated_at=generated_at,
    )
    metrics = {
        "schema": "YPS-HFV2-P3R5-ADMISSIBILITY-EVIDENCE-1.0",
        "generated_at": generated_at,
        "implementation_commit": implementation_commit,
        "holdout_freeze_commit": holdout_freeze_commit,
        "holdout_cards_sha256": sha256(root / "contracts" / manifest["holdout_cards"]),
        "attempt_ledger_sha256": ledger_sha,
        "attempted_holdout_count": len(outcomes),
        "input_assembly_run_count": counts["input_assembly"],
        "reference_construction_run_count": counts["reference_construction"],
        "target_admissibility_run_count": counts["target_admissibility"],
        "second_order_run_count": counts["second_order"],
        "manifold_neighborhood_run_count": counts["manifold_neighborhood"],
        "target_freeze_run_count": 0,
        "qualification_seed_run_count": 0,
        "selection_rule": manifest["holdout_design_and_selection"]["target_selection_rule"],
        "outcomes": outcomes,
        "selected_holdout_ids": selection["selected_holdout_ids"],
        "selection_status": selection["status"],
        "status": selection["status"],
        "formal_numerical_qualification": manifest["formal_numerical_qualification"],
        "mandatory_stop_after_evidence": manifest["mandatory_stop_after_evidence"],
    }
    report = render_admissibility_report(metrics)
    return jsonable(metrics), jsonable(selection), report


def render_admissibility_report(metrics: dict[str, Any]) -> str:
    lines = [
        "# P3R5 未观察留出目标准入报告",
        "",
        f"生成时间：{metrics['generated_at']}",
        "",
        f"实现提交：`{metrics['implementation_commit']}`",
        "",
        f"留出冻结提交：`{metrics['holdout_freeze_commit']}`",
        "",
        f"分类状态：`{metrics['status']}`",
        "",
        "本报告覆盖固定双活动 KKT 参考、参考稳定性、二阶数值一致性和约束流形有限邻域；不含资格种子运行，不构成正式数值资格、物理验证或实验验证。",
        "",
        "| 留出卡 | 类别 | 输入装配 | 参考构造 | 准入 | 二阶 | 流形 | 失败阶段 | 状态 |",
        "|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for item in metrics["outcomes"]:
        lines.append(
            f"| {item['holdout_id']} | {item['category']} | "
            f"{item['input_assembly_execution_count']} | "
            f"{item['reference_construction_execution_count']} | "
            f"{item['target_admissibility_execution_count']} | "
            f"{item['second_order_execution_count']} | "
            f"{item['manifold_neighborhood_execution_count']} | "
            f"{item.get('failure_stage', '-')} | {item['status']} |"
        )
    lines.extend(["", "## 选择结果", ""])
    if metrics["selected_holdout_ids"]:
        for category, holdout_id in metrics["selected_holdout_ids"].items():
            lines.append(f"- `{category}`：`{holdout_id}`")
        lines.extend(["", "目标与算法初值尚未冻结；必须先提交本准入结果。"])
    else:
        lines.append("- 未形成完整目标套件，不得冻结或运行资格种子。")
    lines.extend(
        [
            "",
            f"一次性账本 SHA-256：`{metrics['attempt_ledger_sha256']}`。",
            "",
            f"资格种子结果运行数：`{metrics['qualification_seed_run_count']}`。",
            "",
            f"正式高保真数值资格保持：`{metrics['formal_numerical_qualification']}`。",
            "",
            f"最终停止门：`{metrics['mandatory_stop_after_evidence']}`。",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = ["render_admissibility_report", "run_admissibility_campaign"]
