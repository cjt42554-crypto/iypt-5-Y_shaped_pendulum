"""Deterministic G3R3 historical and local-basin qualification evidence."""

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

from .admissibility import (
    _critical_document,
    _critical_kwargs,
    _dual_document,
    _identity_subset,
    _jacobian_document,
)
from .cases import (
    P3R3StaticContactCase,
    build_historical_cases,
    build_qualification_targets,
)
from .certification import characteristic_scales
from .dual_certification import (
    audit_contact_kkt,
    certify_centered_dual,
    component_allowed_raw,
    thresholds_from_manifest,
)
from .evidence_support import (
    architecture_metrics,
    contract_binding,
    evidence_hash_binding,
    git_head,
    jsonable,
    load_json,
    runtime_metrics,
    sha256,
)
from .restoration import audit_full_composite_jacobian
from .solver import settings_from_manifest, solve_contact_seed


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


def _final_audits(
    case: P3R3StaticContactCase,
    evaluation: object,
    scales: object,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    thresholds = thresholds_from_manifest(manifest)
    kkt = audit_contact_kkt(case.assembly, evaluation, thresholds, scales)
    dual = None
    if kkt.supported_indices.size == 2:
        dual = certify_centered_dual(
            evaluation,
            kkt.supported_indices,
            kkt.canonical_multipliers_N,
            scales,
            component_allowed_raw(scales, thresholds),
            manifest,
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
    jacobian_audit = None
    if kkt.supported_indices.size == 2:
        jacobian_audit = audit_full_composite_jacobian(
            case.assembly,
            evaluation.coordinates,
            kkt.supported_indices,
            kkt.canonical_multipliers_N[kkt.supported_indices],
            scales,
            settings_from_manifest(manifest).restoration,
        )
    return {
        "thresholds": thresholds,
        "kkt": kkt,
        "dual": dual,
        "physical_samples": physical_samples,
        "validity_samples": validity_samples,
        "critical": critical,
        "action": action,
        "p2_unchanged": p2_unchanged,
        "jacobian_audit": jacobian_audit,
    }


def _audit_document(audits: dict[str, Any]) -> dict[str, Any]:
    kkt = audits["kkt"]
    action = audits["action"]
    return jsonable(
        {
            "component_scaled_kkt_passed": _component_kkt_passed(
                kkt,
                audits["thresholds"],
            ),
            "near_active_indices": kkt.near_active_indices,
            "supported_indices": kkt.supported_indices,
            "near_active_rank": kkt.near_active_rank,
            "supported_rank": kkt.supported_rank,
            "canonical_multipliers_N": kkt.canonical_multipliers_N,
            "stationarity_vector": kkt.stationarity_vector_N,
            "dimensionless_stationarity": kkt.dimensionless_stationarity,
            "complementarity_residual_N_m": kkt.complementarity_residual_N_m,
            "complementarity_limit_N_m": kkt.complementarity_limit_N_m,
            "dual_certificate": (
                _dual_document(audits["dual"]) if audits["dual"] is not None else None
            ),
            "critical_cone": _critical_document(audits["critical"]),
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
            "full_composite_jacobian": (
                asdict(audits["jacobian_audit"]) if audits["jacobian_audit"] is not None else None
            ),
        }
    )


def _target_seed_record(
    case: P3R3StaticContactCase,
    seed: object,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    try:
        result = solve_contact_seed(
            case.assembly,
            seed,
            settings_from_manifest(manifest),
        )
        audits = _final_audits(case, result.evaluation, result.scales, manifest)
    except (ContactGeometryError, ValueError, np.linalg.LinAlgError) as error:
        return {
            "seed_id": seed.seed_id,
            "execution_status": "FAIL_CLOSED_UNDEFINED_GEOMETRY_COORDINATE_OR_LINEAR_SYSTEM",
            "failure_type": type(error).__name__,
            "failure_message": str(error),
            "status": "ALGORITHM_SEED_FAIL",
        }
    kkt = audits["kkt"]
    dual = audits["dual"]
    critical = audits["critical"]
    jacobian_audit = audits["jacobian_audit"]
    ids = result.evaluation.contact.constraint_ids
    expected = case.expectation
    near_ids = _identity_subset(ids, kkt.near_active_indices)
    supported_ids = _identity_subset(ids, kkt.supported_indices)
    coordinate_error = float(
        np.linalg.norm(
            (result.coordinates.values - expected.reference_coordinates)
            / result.scales.coordinate_scales,
            ord=np.inf,
        )
    )
    multiplier_errors = []
    for identity, expected_value in zip(
        expected.supported_constraint_ids,
        expected.supported_multipliers_N,
        strict=True,
    ):
        multiplier_errors.append(
            abs(kkt.canonical_multipliers_N[ids.index(identity)] - expected_value)
        )
    multiplier_error_fraction = (
        max(multiplier_errors) / result.scales.force_N if multiplier_errors else float("inf")
    )
    all_indices = np.arange(result.evaluation.contact.gaps_m.size)
    nonactive = np.setdiff1d(all_indices, kkt.near_active_indices, assume_unique=True)
    nonactive_minimum = (
        float(np.min(result.evaluation.contact.gaps_m[nonactive]))
        if nonactive.size
        else float("inf")
    )
    action = audits["action"]
    checks = {
        "restoration_executed": result.restoration.executed,
        "restoration_converged": result.restoration.converged,
        "active_multipliers_nonnegative": bool(
            result.restoration.final_restore_multipliers_N.size == 0
            or float(np.min(result.restoration.final_restore_multipliers_N)) >= 0.0
        ),
        "component_scaled_kkt": _component_kkt_passed(
            kkt,
            audits["thresholds"],
        ),
        "near_active_identity": near_ids == expected.near_active_constraint_ids,
        "supported_identity": supported_ids == expected.supported_constraint_ids,
        "near_active_rank": kkt.near_active_rank == expected.near_active_rank,
        "supported_rank": kkt.supported_rank == expected.supported_rank,
        "centered_dual_certificate": bool(dual is not None and dual.passed),
        "reference_error": coordinate_error
        <= float(manifest["local_basin"]["reference_error_dimensionless_max"]),
        "multiplier_error": multiplier_error_fraction
        <= float(manifest["local_basin"]["multiplier_error_force_scale_fraction_max"]),
        "strict_validity": float(np.min(result.evaluation.validity.normalized_residuals))
        >= float(manifest["target_admissibility"]["strict_validity_normalized_margin_min"]),
        "strict_nonactive_gap": nonactive_minimum
        > float(manifest["target_admissibility"]["nonactive_contact_gap_strict_min_m"]),
        "critical_cone": bool(
            critical.passed
            and critical.minimum_critical_cone_curvature
            > float(manifest["critical_cone_second_order"]["minimum_normalized_curvature"])
            and critical.minimum_supported_tangent_curvature
            > float(manifest["critical_cone_second_order"]["minimum_normalized_curvature"])
        ),
        "physical_gap_jacobian": audits["physical_samples"][-1].maximum_row_relative_error
        <= float(manifest["jacobian_audits"]["physical_final_error_max"]),
        "validity_jacobian": audits["validity_samples"][-1].maximum_row_relative_error
        <= float(manifest["jacobian_audits"]["validity_final_error_max"]),
        "action_reaction_force": float(action.maximum_individual_force_residual_N)
        <= float(manifest["action_reaction"]["force_residual_max_N"]),
        "action_reaction_moment": float(action.maximum_individual_moment_residual_N_m)
        <= float(manifest["action_reaction"]["moment_residual_max_N_m"]),
        "p2_bitwise_unchanged": bool(audits["p2_unchanged"]),
        "full_composite_jacobian": bool(jacobian_audit is not None and jacobian_audit.passed),
    }
    status = (
        "CERTIFIER_INTERNAL_INCONSISTENCY"
        if dual is not None and dual.status == "CERTIFIER_INTERNAL_INCONSISTENCY"
        else "PASS"
        if all(checks.values())
        else "ALGORITHM_SEED_FAIL"
    )
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
            "restoration": {
                "executed": result.restoration.executed,
                "converged": result.restoration.converged,
                "status": result.restoration.status,
                "iterations": result.restoration.iterations,
                "total_backtracks": result.restoration.total_backtracks,
                "accepted_step_lengths": result.restoration.accepted_step_lengths,
                "initial_composite_residual": (result.restoration.initial_composite_residual),
                "final_composite_residual": result.restoration.final_composite_residual,
                "final_restore_multipliers_N": (result.restoration.final_restore_multipliers_N),
            },
            "coordinates": result.coordinates.values,
            "total_potential_J": result.evaluation.total_potential,
            "coordinate_reference_error_dimensionless": coordinate_error,
            "multiplier_error_force_scale_fraction": multiplier_error_fraction,
            "minimum_contact_gap_m": float(np.min(result.evaluation.contact.gaps_m)),
            "minimum_nonactive_gap_m": nonactive_minimum,
            "minimum_validity_normalized_residual": float(
                np.min(result.evaluation.validity.normalized_residuals)
            ),
            "checks": checks,
            "audits": _audit_document(audits),
            "status": status,
        }
    )


def _target_record(
    case: P3R3StaticContactCase,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    records = [_target_seed_record(case, seed, manifest) for seed in case.seeds]
    completed = [item for item in records if item["execution_status"] == "COMPLETED"]
    scales = characteristic_scales(case.assembly)
    if len(completed) == len(case.seeds):
        coordinates = np.asarray([item["coordinates"] for item in completed], dtype=float)
        energies = np.asarray(
            [item["total_potential_J"] for item in completed],
            dtype=float,
        )
        spread = max(
            float(
                np.linalg.norm(
                    (first - second) / scales.coordinate_scales,
                    ord=np.inf,
                )
            )
            for first in coordinates
            for second in coordinates
        )
        energy_spread = float(np.max(energies) - np.min(energies)) / scales.energy_N_m
    else:
        spread = float("inf")
        energy_spread = float("inf")
    checks = {
        "exactly_three_frozen_seeds": len(case.seeds)
        == int(manifest["local_basin"]["qualification_seed_count_per_target"]),
        "all_seed_executions_completed": len(completed) == len(case.seeds),
        "all_seed_checks_passed": all(item["status"] == "PASS" for item in records),
        "multiseed_spread": spread
        <= float(manifest["local_basin"]["multiseed_spread_dimensionless_max"]),
        "multiseed_energy_spread": energy_spread
        <= float(manifest["local_basin"]["multiseed_energy_spread_scale_fraction_max"]),
    }
    internal = any(item["status"] == "CERTIFIER_INTERNAL_INCONSISTENCY" for item in records)
    status = (
        "CERTIFIER_INTERNAL_INCONSISTENCY"
        if internal
        else "PASS"
        if all(checks.values())
        else "ALGORITHM_SEED_FAIL"
    )
    return jsonable(
        {
            "case_id": case.case_id,
            "role": case.role,
            "seed_execution_count": len(records),
            "seed_records": records,
            "multiseed_spread_dimensionless": spread,
            "multiseed_energy_spread_scale_fraction": energy_spread,
            "checks": checks,
            "status": status,
        }
    )


def _historical_seed_record(
    case: P3R3StaticContactCase,
    seed: object,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    try:
        result = solve_contact_seed(
            case.assembly,
            seed,
            settings_from_manifest(manifest),
        )
        audits = _final_audits(case, result.evaluation, result.scales, manifest)
    except (ContactGeometryError, ValueError, np.linalg.LinAlgError) as error:
        return {
            "seed_id": seed.seed_id,
            "failure_type": type(error).__name__,
            "failure_message": str(error),
            "status": "FAIL",
        }
    kkt = audits["kkt"]
    ids = result.evaluation.contact.constraint_ids
    expected = case.expectation
    position_error = float(
        np.linalg.norm(result.coordinates.values[:3] - expected.reference_coordinates[:3])
    )
    rotation_error = float(
        np.linalg.norm(result.coordinates.values[3:] - expected.reference_coordinates[3:])
    )
    multiplier_errors = [
        abs(kkt.canonical_multipliers_N[ids.index(identity)] - expected_value)
        for identity, expected_value in zip(
            expected.supported_constraint_ids,
            expected.supported_multipliers_N,
            strict=True,
        )
    ]
    contract = case.contract
    checks = {
        "restoration_executed": result.restoration.executed,
        "restoration_converged": result.restoration.converged,
        "near_active_identity": _identity_subset(ids, kkt.near_active_indices)
        == expected.near_active_constraint_ids,
        "supported_identity": _identity_subset(ids, kkt.supported_indices)
        == expected.supported_constraint_ids,
        "near_active_rank": kkt.near_active_rank == expected.near_active_rank,
        "supported_rank": kkt.supported_rank == expected.supported_rank,
        "legacy_mixed_stationarity": kkt.stationarity_residual_N
        <= float(manifest["component_scale_contract"]["legacy_mixed_infinity_max"]),
        "position": position_error <= float(contract.get("position_absolute_error_max_m", 2.0e-7)),
        "rotation": rotation_error
        <= float(contract.get("rotation_vector_absolute_error_max_rad", 2.0e-7)),
        "multipliers": max(multiplier_errors, default=float("inf"))
        <= float(contract.get("multiplier_absolute_error_max_N", 2.0e-6)),
        "critical_cone": bool(audits["critical"].passed),
        "p2_bitwise_unchanged": bool(audits["p2_unchanged"]),
    }
    return jsonable(
        {
            "seed_id": result.seed_id,
            "position_error_m": position_error,
            "rotation_error_rad": rotation_error,
            "multiplier_max_error_N": max(multiplier_errors, default=float("inf")),
            "checks": checks,
            "status": "PASS" if all(checks.values()) else "FAIL",
        }
    )


def _historical_record(
    case: P3R3StaticContactCase,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    records = [_historical_seed_record(case, seed, manifest) for seed in case.seeds]
    required = 3 if "35_DEG" in case.case_id else 1
    passed = len(records) == required and all(item["status"] == "PASS" for item in records)
    return {
        "case_id": case.case_id,
        "required_seed_count": required,
        "seed_execution_count": len(records),
        "seed_records": records,
        "status": "PASS" if passed else "HISTORICAL_REGRESSION_FAIL",
    }


def generate_g3r3_evidence(root: Path) -> dict[str, Any]:
    manifest = load_json(root / "contracts/p3r3_acceptance_manifest.json")
    predecessor = load_json(root / "contracts/p3r2_acceptance_manifest.json")
    target_freeze = load_json(root / "contracts" / manifest["target_freeze"])
    if target_freeze["status"] != "TARGETS_FROZEN":
        raise RuntimeError("P3R3 qualification cannot run without two frozen targets.")
    repository_root = root.parents[2]
    binding = contract_binding(root, manifest, require_target_freeze=True)
    if binding["status"] != "PASS":
        raise RuntimeError("P3R3 target-freeze commit order or hash binding failed.")
    adapter_hash = sha256(root / "contracts" / manifest["adapter_contract"])
    protocol_hash = sha256(root / "contracts" / manifest["frozen_protocol"])
    historical_cases = build_historical_cases(
        manifest,
        predecessor,
        adapter_contract_sha256=adapter_hash,
        frozen_protocol_sha256=protocol_hash,
    )
    targets = build_qualification_targets(
        manifest,
        target_freeze,
        adapter_contract_sha256=adapter_hash,
        frozen_protocol_sha256=protocol_hash,
    )
    historical = [_historical_record(case, manifest) for case in historical_cases]
    target_records = [_target_record(case, manifest) for case in targets]
    architecture = architecture_metrics(root, manifest)
    runtime = runtime_metrics(manifest)
    historical_passed = all(item["status"] == "PASS" for item in historical)
    internal = any(item["status"] == "CERTIFIER_INTERNAL_INCONSISTENCY" for item in target_records)
    targets_passed = bool(target_records) and all(
        item["status"] == "PASS" for item in target_records
    )
    infrastructure_passed = all(
        item["status"] == "PASS" for item in (binding, architecture, runtime)
    )
    if internal:
        classification = manifest["certifier_internal_status"]
    elif not historical_passed:
        classification = "HISTORICAL_REGRESSION_FAIL"
    elif not targets_passed or not infrastructure_passed:
        classification = manifest["fail_status"]
    else:
        classification = manifest["pass_status"]
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    return jsonable(
        {
            "schema": "YPS-HFV2-G3R3-EVIDENCE-1.0",
            "generated_at": generated_at,
            "evidence_parent_commit": git_head(repository_root),
            "model_id": manifest["contact_model_id"],
            "classification": classification,
            "classification_components": {
                "contract_binding": binding["status"],
                "architecture": architecture["status"],
                "runtime": runtime["status"],
                "historical_regressions": (
                    "PASS" if historical_passed else "HISTORICAL_REGRESSION_FAIL"
                ),
                "target_qualification": (
                    "CERTIFIER_INTERNAL_INCONSISTENCY"
                    if internal
                    else "PASS"
                    if targets_passed
                    else "ALGORITHM_SEED_FAIL"
                ),
            },
            "qualification_seed_execution_counts": {
                item["case_id"]: item["seed_execution_count"] for item in target_records
            },
            "contract_binding": binding,
            "architecture": architecture,
            "runtime": runtime,
            "historical_regressions": historical,
            "qualification_targets": target_records,
            "evidence_hash_binding": evidence_hash_binding(root, manifest),
            "historical_g3_status_preserved": manifest["historical_g3_status_preserved"],
            "historical_g3r_status_preserved": manifest["historical_g3r_status_preserved"],
            "historical_g3r2_status_preserved": manifest["historical_g3r2_status_preserved"],
            "formal_numerical_qualification": manifest["formal_numerical_qualification"],
            "not_executed": manifest["not_executed"],
            "mandatory_stop": manifest["mandatory_stop_after_evidence"],
        }
    )


def render_raw_report(metrics: dict[str, Any]) -> str:
    lines = [
        "# G3R3 原始门禁报告",
        "",
        f"生成时间：{metrics['generated_at']}",
        "",
        f"模型身份：`{metrics['model_id']}`",
        "",
        f"分类：`{metrics['classification']}`",
        "",
        "## 分类分量",
        "",
    ]
    for name, status in metrics["classification_components"].items():
        lines.append(f"- `{name}`：`{status}`")
    lines.extend(["", "## 历史回归", ""])
    for item in metrics["historical_regressions"]:
        lines.append(
            f"- `{item['case_id']}`：`{item['status']}`，"
            f"运行 {item['seed_execution_count']} 个种子。"
        )
    lines.extend(["", "## 新目标资格", ""])
    for target in metrics["qualification_targets"]:
        lines.append(
            f"- `{target['case_id']}`：`{target['status']}`，"
            f"运行 {target['seed_execution_count']} 个种子，"
            f"坐标无量纲散布 `{target['multiseed_spread_dimensionless']}`，"
            f"能量尺度散布 `{target['multiseed_energy_spread_scale_fraction']}`。"
        )
        for seed in target["seed_records"]:
            lines.append(f"  - `{seed['seed_id']}`：`{seed['status']}`")
    lines.extend(
        [
            "",
            f"正式数值资格：`{metrics['formal_numerical_qualification']}`。",
            "",
            f"停止门：`{metrics['mandatory_stop']}`。",
            "",
        ]
    )
    return "\n".join(lines)


def render_human_report(metrics: dict[str, Any]) -> str:
    passed = metrics["classification"].startswith("G3R3_CANDIDATE_PASS")
    conclusion = (
        "两个新目标的固定三种子局部静态接触资格全部通过。"
        if passed
        else "G3R3 未通过全部静态接触局部资格门。"
    )
    return "\n".join(
        [
            "# HF-v2 G3R3 候选裁决报告",
            "",
            f"结论：{conclusion}",
            "",
            f"机器分类：`{metrics['classification']}`",
            "",
            "本轮只验证新的双接触目标、显式对偶证书、局部盆地内三种子恢复和历史静态回归。优化器成功标志不作为资格门。",
            "",
            "未执行动力学接触、摩擦、恢复系数、罚接触、装置物理验证或实验验证；也未修改正式理论或正式程序。",
            "",
            f"正式高保真数值资格仍为：`{metrics['formal_numerical_qualification']}`。",
            "",
            f"必须停止于：`{metrics['mandatory_stop']}`，等待 Pro 复审。",
            "",
        ]
    )
