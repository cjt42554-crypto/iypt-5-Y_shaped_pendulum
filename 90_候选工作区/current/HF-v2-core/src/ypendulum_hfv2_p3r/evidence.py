"""Deterministic G3R evidence for the frozen P3R static-contact candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from ypendulum_hfv2.audit.contact import contact_action_reaction_audit
from ypendulum_hfv2.contact import ContactGeometryError

from . import P3R_CONTACT_MODEL_ID
from .cases import (
    P3RStaticContactCase,
    build_observed_symmetric_regression,
    build_unobserved_qualification_target,
)
from .critical_cone import audit_critical_cone
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
from .jacobian_audit import (
    physical_gap_jacobian_samples,
    validity_jacobian_samples,
)
from .kkt import P3RKKTAudit, P3RKKTThresholds, audit_contact_kkt
from .solver import P3RSolverSettings, solve_contact_seed


def _kkt_thresholds(manifest: dict[str, Any]) -> P3RKKTThresholds:
    source = manifest["kkt"]
    return P3RKKTThresholds(
        **{name: source[name] for name in P3RKKTThresholds.__dataclass_fields__}
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


def _jacobian_document(samples: tuple[object, ...]) -> list[dict[str, float]]:
    return [
        {
            "difference_step": float(sample.difference_step),
            "maximum_row_relative_error": float(sample.maximum_row_relative_error),
            "matrix_relative_error": float(sample.matrix_relative_error),
        }
        for sample in samples
    ]


def _identity_subset(
    constraint_ids: tuple[str, ...],
    indices: np.ndarray,
) -> tuple[str, ...]:
    return tuple(constraint_ids[int(index)] for index in indices)


def _kkt_document(kkt: P3RKKTAudit, constraint_ids: tuple[str, ...]) -> dict[str, Any]:
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
    return jsonable(
        {
            "passed": kkt.passed,
            "near_active_ids": _identity_subset(constraint_ids, kkt.near_active_indices),
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
            "force_scale_N": kkt.force_scale_N,
            "energy_scale_N_m": kkt.energy_scale_N_m,
            "primal_violation_m": kkt.primal_violation_m,
            "dual_violation_N": kkt.dual_violation_N,
            "stationarity_residual_N": kkt.stationarity_residual_N,
            "stationarity_limit_N": kkt.stationarity_limit_N,
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


def _dual_width(kkt: P3RKKTAudit) -> float:
    if kkt.near_active_indices.size == 0:
        return 0.0
    widths = (
        kkt.dual_interval_upper_N[kkt.near_active_indices]
        - kkt.dual_interval_lower_N[kkt.near_active_indices]
    )
    return float(np.max(widths))


def _seed_audits(
    case: P3RStaticContactCase,
    evaluation: object,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    kkt = audit_contact_kkt(case.assembly, evaluation, _kkt_thresholds(manifest))
    physical_steps = tuple(manifest["jacobian_audits"]["physical_gap_steps"])
    validity_steps = tuple(manifest["jacobian_audits"]["validity_five_point_steps"])
    physical_samples = physical_gap_jacobian_samples(
        case.assembly,
        evaluation.coordinates,
        physical_steps,
    )
    validity_samples = validity_jacobian_samples(
        case.assembly,
        evaluation.coordinates,
        validity_steps,
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


def _observed_regression(
    root: Path,
    manifest: dict[str, Any],
    adapter_hash: str,
    protocol_hash: str,
) -> dict[str, Any]:
    del root
    case = build_observed_symmetric_regression(
        manifest,
        adapter_contract_sha256=adapter_hash,
        frozen_protocol_sha256=protocol_hash,
    )
    seed = case.seeds[0]
    evaluation = case.assembly.evaluate(case.assembly.coordinates_from_seed(seed))
    audits = _seed_audits(case, evaluation, manifest)
    kkt = audits.pop("kkt_object")
    near_ids = _identity_subset(evaluation.contact.constraint_ids, kkt.near_active_indices)
    supported_ids = _identity_subset(
        evaluation.contact.constraint_ids,
        kkt.supported_indices,
    )
    expected = case.expectation
    checks = {
        "four_near_active_identities": near_ids == expected.near_active_constraint_ids,
        "two_supported_identities": supported_ids == expected.supported_constraint_ids,
        "near_active_rank_three": kkt.near_active_rank == expected.near_active_rank,
        "supported_rank_two": kkt.supported_rank == expected.supported_rank,
        "dual_nonuniqueness_reported": kkt.dual_nonunique,
        "mandatory_support_is_the_bob_pair": _identity_subset(
            evaluation.contact.constraint_ids,
            kkt.mandatory_supported_indices,
        )
        == expected.supported_constraint_ids,
        "critical_cone": bool(audits["critical_passed"]),
        "p2_unchanged": bool(audits["p2_potential_and_force_bitwise_unchanged"]),
    }
    return jsonable(
        {
            "case_id": case.case_id,
            "role": "observed_regression_not_qualification_target",
            "checks": checks,
            "audits": audits,
            "status": "PASS" if all(checks.values()) else "FAIL",
        }
    )


def _qualification_seed(
    case: P3RStaticContactCase,
    seed: object,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    settings_contract = manifest["primary_solver"]
    settings = P3RSolverSettings(
        method=settings_contract["method"],
        function_tolerance=settings_contract["ftol"],
        maximum_iterations=settings_contract["maximum_iterations"],
    )
    result = solve_contact_seed(case.assembly, seed, settings)
    evaluation = result.evaluation
    audits = _seed_audits(case, evaluation, manifest)
    kkt = audits.pop("kkt_object")
    ids = evaluation.contact.constraint_ids
    near_ids = _identity_subset(ids, kkt.near_active_indices)
    supported_ids = _identity_subset(ids, kkt.supported_indices)
    possible_ids = _identity_subset(ids, kkt.possible_supported_indices)
    mandatory_ids = _identity_subset(ids, kkt.mandatory_supported_indices)
    expected = case.expectation
    target = manifest["qualification_target"]
    supported_multipliers = kkt.canonical_multipliers_N[kkt.supported_indices]
    multiplier_error = (
        float(
            np.max(
                np.abs(
                    supported_multipliers - expected.each_supported_multiplier_N
                )
            )
        )
        if supported_multipliers.size
        else float("inf")
    )
    position_error = float(
        np.linalg.norm(
            evaluation.contact.base_evaluation.bob_position - expected.bob_position_m
        )
    )
    supported_witnesses = [
        evaluation.contact.witnesses[int(index)] for index in kkt.supported_indices
    ]
    witness_margin = (
        min(item.unit_interval_parameter_margin for item in supported_witnesses)
        if supported_witnesses
        else float("-inf")
    )
    action = audits["action_reaction"]
    validity_minimum = float(
        np.min(evaluation.validity.normalized_residuals)
    )
    checks = {
        "finite": bool(
            np.all(np.isfinite(result.coordinates.values))
            and np.all(np.isfinite(evaluation.contact.gaps_m))
            and np.all(np.isfinite(evaluation.validity.signed_residuals))
        ),
        "kkt": kkt.passed,
        "near_active_identity": near_ids == expected.near_active_constraint_ids,
        "supported_identity": supported_ids == expected.supported_constraint_ids,
        "possible_support_identity": possible_ids == expected.supported_constraint_ids,
        "mandatory_support_identity": mandatory_ids == expected.supported_constraint_ids,
        "near_active_rank": kkt.near_active_rank == expected.near_active_rank,
        "supported_rank": kkt.supported_rank == expected.supported_rank,
        "dual_interval_width": audits["dual_interval_maximum_width_N"]
        <= float(manifest["kkt"]["qualification_dual_interval_width_max_N"]),
        "position": position_error <= float(target["position_absolute_error_max_m"]),
        "multipliers": multiplier_error
        <= float(target["multiplier_absolute_error_max_N"]),
        "interior_witnesses": witness_margin
        >= float(target["interior_witness_parameter_margin_min"]),
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
                "iterations": result.iterations,
                "function_evaluations": result.function_evaluations,
                "gradient_evaluations": result.gradient_evaluations,
            },
            "coordinates": result.coordinates.values,
            "bob_position_m": evaluation.contact.base_evaluation.bob_position,
            "total_potential_J": evaluation.total_potential,
            "minimum_contact_gap_m": float(np.min(evaluation.contact.gaps_m)),
            "minimum_validity_normalized_residual": validity_minimum,
            "position_error_m": position_error,
            "supported_multiplier_max_error_N": multiplier_error,
            "supported_witness_parameter_margin": witness_margin,
            "checks": checks,
            "audits": audits,
            "qualified": qualified,
        }
    )


def _qualification_target(
    manifest: dict[str, Any],
    adapter_hash: str,
    protocol_hash: str,
) -> dict[str, Any]:
    case = build_unobserved_qualification_target(
        manifest,
        adapter_contract_sha256=adapter_hash,
        frozen_protocol_sha256=protocol_hash,
    )
    records = []
    for seed in case.seeds:
        try:
            records.append(_qualification_seed(case, seed, manifest))
        except (ContactGeometryError, ValueError) as error:
            records.append(
                {
                    "seed_id": seed.seed_id,
                    "execution_status": "FAIL_CLOSED_UNDEFINED_GEOMETRY_OR_COORDINATE",
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
    target = manifest["qualification_target"]
    multiseed_checks = {
        "required_passing_seed_count": len(qualified)
        == int(target["required_passing_seed_count"]),
        "position_spread": position_spread
        <= float(target["multiseed_position_spread_max_m"]),
        "energy_spread": energy_spread
        <= float(target["multiseed_energy_spread_max_J"]),
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
            "role": "prefrozen_unobserved_static_contact_algorithm_qualification_target",
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


def build_g3r_evidence(root: str | Path) -> dict[str, Any]:
    candidate_root = Path(root)
    manifest = load_json(candidate_root / "contracts" / "p3r_acceptance_manifest.json")
    binding = contract_binding(candidate_root, manifest)
    runtime = runtime_metrics(manifest)
    architecture = architecture_metrics(candidate_root, manifest)
    benchmarks = run_bound_benchmarks(candidate_root, manifest)
    adapter_hash = sha256(candidate_root / "contracts" / manifest["adapter_contract"])
    protocol_hash = sha256(candidate_root / "contracts" / manifest["frozen_protocol"])
    regression = _observed_regression(
        candidate_root,
        manifest,
        adapter_hash,
        protocol_hash,
    )
    preconditions = bool(
        binding["status"] == "PASS"
        and runtime["status"] == "PASS"
        and architecture["status"] == "PASS"
        and benchmarks["status"] == "PASS"
        and regression["status"] == "PASS"
    )
    target = (
        _qualification_target(manifest, adapter_hash, protocol_hash)
        if preconditions
        else {
            "status": "NOT_RUN_PRECONDITION_FAILURE",
            "qualification_target_evaluations": 0,
        }
    )
    gate_summary = {
        "contract_and_frozen_source_binding": binding["status"] == "PASS",
        "exact_runtime": runtime["status"] == "PASS",
        "architecture": architecture["status"] == "PASS",
        "benchmark_identity_binding_before_target": benchmarks["status"] == "PASS",
        "observed_symmetric_regression_before_target": regression["status"] == "PASS",
        "unobserved_qualification_target": target["status"] == "PASS",
    }
    status = manifest["pass_status"] if all(gate_summary.values()) else manifest["fail_status"]
    return jsonable(
        {
            "schema": "YPS-HFV2-G3R-EVIDENCE-1.0",
            "status": status,
            "contact_model_id": P3R_CONTACT_MODEL_ID,
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
            "observed_symmetric_regression": regression,
            "qualification_target": target,
            "historical_g3_status_preserved": "NO_GO_G3_STATIC_CONTACT_ALGORITHM",
            "forbidden_scope_not_executed": manifest["forbidden"],
            "not_executed": manifest["not_executed"],
            "evidence_binding": evidence_hash_binding(candidate_root, manifest),
        }
    )


def render_g3r_report(evidence: dict[str, Any], metrics_sha256: str) -> str:
    gates = evidence["gate_summary"]
    target = evidence["qualification_target"]
    lines = [
        "# HF-v2 G3R 静态接触算法证据报告",
        "",
        f"状态：`{evidence['status']}`",
        "",
        f"指标 SHA-256：`{metrics_sha256}`",
        "",
        "## 1. 结论边界",
        "",
        "本报告只评价候选静态、无摩擦、刚性、单边法向接触算法。",
        "它不是装置预测、物理验证或实验验证。正式高保真总状态仍为",
        f"`{evidence['formal_numerical_qualification']}`。",
        "",
        "历史 `0.3-CONTACT-CANDIDATE` 的 G3 NO-GO、旧报告与旧指标保持不变。",
        "P3R 使用 `0.4-CONTACT-CANDIDATE` 和新的接触组装身份。",
        "",
        "## 2. 门禁结果",
        "",
    ]
    for identity, passed in gates.items():
        lines.append(f"- `{identity}`：{'PASS' if passed else 'FAIL'}")
    lines.extend(
        [
            "",
            "## 3. Pro 指定的结构回归",
            "",
            "旧对称目标只作已观察回归。报告分别保留近活动集合、正乘子支撑集合、",
            "弱活动集合、对偶反力区间和真实临界锥；不删除零乘子接触。",
            "",
            f"回归状态：`{evidence['observed_symmetric_regression']['status']}`。",
            "",
            "## 4. 新资格目标",
            "",
            f"目标状态：`{target['status']}`。",
        ]
    )
    if target.get("seeds"):
        for seed in target["seeds"]:
            lines.append(
                f"- `{seed['seed_id']}`：执行 `{seed['execution_status']}`，"
                f"资格 `{'PASS' if seed.get('qualified') else 'FAIL'}`"
            )
        lines.extend(
            [
                "",
                f"多种子位置展宽：`{target['multiseed_position_spread_m']}` m。",
                "",
                f"多种子势能展宽：`{target['multiseed_energy_spread_J']}` J。",
                "",
                f"冻结选择规则得到：`{target['selected_seed_id']}`。",
            ]
        )
    lines.extend(
        [
            "",
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
    return metrics, render_g3r_report(evidence, digest)
